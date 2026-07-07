import csv
import io
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ActorCollectionPage,
    AppSettingsRead,
    AppSettingsUpdate,
    CollectionFilePage,
    FilePage,
    MediaFileRead,
    MetadataDetail,
    MetadataEnrichmentJobCreate,
    MetadataEnrichmentJobRead,
    MetadataImportResult,
    MetadataPage,
    MetadataReferenceHarvestCreate,
    MetadataRead,
    MetadataTaskLogPage,
    CmsSyncResult,
    OneClickIngestRequest,
    OneClickIngestResult,
    OrganizerExecuteRequest,
    OrganizerExecutionLogPage,
    OrganizerExecutionResult,
    OrganizerPreflightResult,
    OrganizerItemPage,
    OrganizerJobCreate,
    OrganizerJobRead,
    OrganizerTaskJobCreate,
    OrganizerTaskScanRequest,
    OrganizerTaskScanResponse,
    OrganizerTaskSummaryRead,
    ReferenceItemPage,
    ReferenceScanResult,
    ReferenceSourceCreate,
    ReferenceSourceRead,
    ScanJobRead,
    SeriesCollectionPage,
    SourceCreate,
    SourceRead,
    StatsRead,
    StudioCollectionPage,
    SystemStatusRead,
    TranslationAPISettingsRead,
    TranslationAPISettingsUpdate,
    TranslationConnectionTestRead,
    TranslationConnectionTestRequest,
    TranslationFileSearchPage,
    TranslationFileSearchRead,
    TranslationItemRead,
    TranslationItemPage,
    TranslationJobCreate,
    TranslationJobRead,
    NfoTagBatchAddRequest,
    NfoTagBatchAddResult,
    NfoTagSearchPage,
    TranslationRuntimeRead,
    TranslationSingleFileRunRequest,
    TranslationWatchFolderCreate,
    TranslationWatchFolderRead,
    WesternPosterResult,
    WesternPosterRunRequest,
)
from app.core.config import settings
from app.core.database import engine, get_db
from app.metadata_providers import ManualCSVProvider, MockProvider
from app.metadata_providers.registry import provider_registry
from app.models import (
    MediaFile,
    MediaMetadata,
    MetadataEnrichmentJob,
    MetadataTaskLog,
    OrganizerExecutionLog,
    OrganizerItem,
    OrganizerJob,
    ReferenceItem,
    ReferenceSource,
    ScanJob,
    Source,
    TranslationAPISettings,
    TranslationFileState,
    TranslationItem,
    TranslationJob,
    TranslationWatchFolder,
)
from app.providers.local_fs import LocalFSProvider
from app.reference_providers import LocalSTRMReferenceProvider
from app.services.scan_manager import scan_manager
from app.services.identifier import extract_identifier, normalize_identifier
from app.services.metadata import import_provider, upsert_record
from app.services.metadata_task_manager import metadata_task_manager
from app.services.ai_translation import (
    get_or_create_translation_api_settings,
    save_translation_api_settings,
    serialize_translation_api_settings,
    test_translation_connection,
    translation_runtime,
)
from app.services.app_settings import get_app_settings, save_app_settings
from app.services.nfo_translation import create_or_update_watch_folder, list_nfo_files, retry_translation_item, validate_translation_root
from app.services.nfo_tags import add_extra_tag_to_nfo_files, search_nfo_tag_records
from app.services.cms_sync import cms_sync_configured, trigger_cms_sync
from app.services.download_ingest import one_click_ingest
from app.services.organizer import count_reference_scope, count_reference_scope_for_job, count_scope, template_fields
from app.services.organizer_execute import execute_organizer_job, preflight_organizer_job
from app.services.organizer_manager import organizer_manager
from app.services.organizer_task import (
    container_to_display_path,
    ensure_local_source,
    latest_scan_for_source,
    organizer_job_summary,
    resolve_reference_source,
)
from app.services.reference_scanner import scan_reference_source
from app.services.translation_task_manager import translation_task_manager
from app.services.translation_monitor import translation_monitor
from app.services.western_poster import run_western_poster_fix
from app.services.collections import collection_files, list_collections
from app.services.backup import actors_json, csv_stream, sqlite_backup_stream

router = APIRouter(prefix="/api/v1")


@router.get("/health")
def health():
    return {
        "status": "ok",
        "read_only_mode": settings.read_only_mode,
        "remote_write": settings.enable_remote_write,
        "external_metadata": settings.enable_external_metadata,
        "enable_real_move": settings.enable_real_move,
    }


@router.get("/system/status", response_model=SystemStatusRead)
def system_status(db: Session = Depends(get_db)):
    sqlite_status = "ok"
    sqlite_error = None
    source_count = 0
    last_scan_at = None
    try:
        db.execute(select(1)).scalar_one()
        source_count = db.scalar(select(func.count()).select_from(Source)) or 0
        last_scan_at = db.scalar(select(func.max(ScanJob.finished_at)))
    except Exception as exc:
        sqlite_status = "error"
        sqlite_error = str(exc)

    mounts = []
    for root in settings.allowed_scan_roots:
        try:
            if not root.is_dir() or not os.access(root, os.R_OK):
                raise OSError("目录不存在或没有读取权限")
            with os.scandir(root) as entries:
                next(entries, None)
            mounts.append({"path": str(root), "readable": True, "error": None})
        except OSError as exc:
            mounts.append({"path": str(root), "readable": False, "error": str(exc)})

    return {
        "backend_status": "ok",
        "sqlite_status": sqlite_status,
        "sqlite_error": sqlite_error,
        "mount_readable": bool(mounts) and all(item["readable"] for item in mounts),
        "mounts": mounts,
        "source_count": source_count,
        "last_scan_at": last_scan_at,
        "read_only_mode": settings.read_only_mode,
        "enable_remote_write": settings.enable_remote_write,
        "enable_external_metadata": settings.enable_external_metadata,
        "enable_real_move": settings.enable_real_move,
        "cms_sync_configured": cms_sync_configured(),
    }


@router.get("/settings", response_model=AppSettingsRead)
def read_app_settings(db: Session = Depends(get_db)):
    return get_app_settings(db)


@router.put("/settings", response_model=AppSettingsRead)
def update_app_settings(payload: AppSettingsUpdate, db: Session = Depends(get_db)):
    return save_app_settings(db, payload.model_dump())


@router.post("/cms/sync", response_model=CmsSyncResult)
def run_cms_sync():
    try:
        result = trigger_cms_sync()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["message"])
    return result


@router.post("/one-click-ingest", response_model=OneClickIngestResult)
def run_one_click_ingest(payload: OneClickIngestRequest):
    try:
        return one_click_ingest(payload.source_root, payload.output_root)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/western-posters/run", response_model=WesternPosterResult)
def run_western_posters(payload: WesternPosterRunRequest):
    try:
        return run_western_poster_fix(
            root=payload.root,
            state_file=payload.state_file,
            process_all=payload.process_all,
            dry_run=payload.dry_run,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backups/index.db")
def backup_database():
    if not settings.database_url.startswith("sqlite"):
        raise HTTPException(status_code=501, detail="数据库备份仅支持 SQLite")
    headers = {"Content-Disposition": 'attachment; filename="index.db"'}
    return StreamingResponse(sqlite_backup_stream(engine), media_type="application/vnd.sqlite3", headers=headers)


@router.get("/backups/metadata.csv")
def backup_metadata(db: Session = Depends(get_db)):
    items = db.scalars(select(MediaMetadata).order_by(MediaMetadata.identifier)).yield_per(500)
    rows = (
        [
            item.identifier,
            item.title or "",
            item.plot or "",
            actors_json(item.actors),
            item.studio or "",
            item.series or "",
            item.release_date or "",
            item.cover_url or "",
        ]
        for item in items
    )
    headers = {"Content-Disposition": 'attachment; filename="metadata.csv"'}
    return StreamingResponse(
        csv_stream(["identifier", "title", "plot", "actors", "studio", "series", "release_date", "cover_url"], rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/backups/files.csv")
def backup_files(db: Session = Depends(get_db)):
    items = db.scalars(select(MediaFile).order_by(MediaFile.path)).yield_per(500)
    rows = (
        [
            item.provider_file_id or item.id,
            item.filename,
            item.path,
            item.size,
            item.identifier or "",
            item.status,
            item.modified_time or "",
        ]
        for item in items
    )
    headers = {"Content-Disposition": 'attachment; filename="files.csv"'}
    return StreamingResponse(
        csv_stream(["file_id", "filename", "path", "size", "identifier", "status", "modified_time"], rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.get("/translation/runtime", response_model=TranslationRuntimeRead)
def get_translation_runtime(db: Session = Depends(get_db)):
    return translation_runtime(db)


@router.get("/translation/settings", response_model=TranslationAPISettingsRead)
def get_translation_settings(db: Session = Depends(get_db)):
    item = get_or_create_translation_api_settings(db)
    return serialize_translation_api_settings(item)


@router.put("/translation/settings", response_model=TranslationAPISettingsRead)
def update_translation_settings(payload: TranslationAPISettingsUpdate, db: Session = Depends(get_db)):
    item = save_translation_api_settings(
        db,
        enabled=payload.enabled,
        api_key=payload.api_key,
        base_url=payload.base_url,
        model_name=payload.model_name,
    )
    return serialize_translation_api_settings(item)


@router.post("/translation/settings/test", response_model=TranslationConnectionTestRead)
def translation_settings_test(payload: TranslationConnectionTestRequest):
    try:
        return test_translation_connection(
            enabled=payload.enabled,
            api_key=payload.api_key,
            base_url=payload.base_url,
            model_name=payload.model_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/translation/watch-folders", response_model=list[TranslationWatchFolderRead])
def list_translation_watch_folders(db: Session = Depends(get_db)):
    return db.scalars(
        select(TranslationWatchFolder).order_by(TranslationWatchFolder.enabled.desc(), TranslationWatchFolder.id.desc())
    ).all()


@router.post("/translation/watch-folders", response_model=TranslationWatchFolderRead, status_code=201)
def save_translation_watch_folder(payload: TranslationWatchFolderCreate, db: Session = Depends(get_db)):
    try:
        return create_or_update_watch_folder(
            db,
            name=payload.name,
            folder_path=payload.folder_path,
            prompt_template=payload.prompt_template,
            enabled=payload.enabled,
            recursive=payload.recursive,
            auto_translate=payload.auto_translate,
        )
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/translation/watch-folders/{folder_id}/monitor-scan")
def scan_translation_watch_folder(folder_id: int):
    try:
        queued_count = translation_monitor.scan_folder_now(folder_id)
        return {"folder_id": folder_id, "queued_count": queued_count}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/translation/watch-folders/{folder_id}", status_code=204)
def delete_translation_watch_folder(folder_id: int, db: Session = Depends(get_db)):
    folder = db.get(TranslationWatchFolder, folder_id)
    if not folder:
        raise HTTPException(status_code=404, detail="translation watch folder not found")
    db.query(TranslationFileState).filter(TranslationFileState.watch_folder_id == folder_id).delete()
    db.delete(folder)
    db.commit()
    return None


@router.get("/translation/jobs", response_model=list[TranslationJobRead])
def list_translation_jobs(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(TranslationJob).order_by(TranslationJob.id.desc()).limit(limit)).all()


@router.post("/translation/jobs", response_model=TranslationJobRead, status_code=202)
def create_translation_job(payload: TranslationJobCreate, db: Session = Depends(get_db)):
    watch_folder = None
    folder_path = payload.folder_path
    prompt_template = payload.prompt_template
    if payload.watch_folder_id is not None:
        watch_folder = db.get(TranslationWatchFolder, payload.watch_folder_id)
        if not watch_folder:
            raise HTTPException(status_code=404, detail="translation watch folder not found")
        folder_path = watch_folder.folder_path
        prompt_template = watch_folder.prompt_template
    if watch_folder is not None:
        watch_folder_item = watch_folder
    else:
        try:
            watch_folder_item = create_or_update_watch_folder(
                db,
                name=Path(folder_path or "").name or "AI Translation Folder",
                folder_path=folder_path or "",
                prompt_template=prompt_template or "",
                enabled=True,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    job = TranslationJob(
        watch_folder_id=watch_folder_item.id,
        folder_path=watch_folder_item.folder_path,
        prompt_template=watch_folder_item.prompt_template,
        mode=payload.mode,
        status="pending",
        total_count=0,
        processed_count=0,
        translated_count=0,
        skipped_count=0,
        failed_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    translation_task_manager.start(job.id)
    return job


@router.get("/translation/jobs/{job_id}", response_model=TranslationJobRead)
def get_translation_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(TranslationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="translation job not found")
    return job


@router.get("/translation/jobs/{job_id}/items", response_model=TranslationItemPage)
def get_translation_job_items(
    job_id: int,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if not db.get(TranslationJob, job_id):
        raise HTTPException(status_code=404, detail="translation job not found")
    filters = [TranslationItem.job_id == job_id]
    if status:
        filters.append(TranslationItem.status == status)
    total = db.scalar(select(func.count()).select_from(TranslationItem).where(*filters)) or 0
    items = db.scalars(
        select(TranslationItem)
        .where(*filters)
        .order_by(TranslationItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/translation/items", response_model=TranslationItemPage)
def list_translation_items(
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    filters = []
    if status:
        filters.append(TranslationItem.status == status)
    total = db.scalar(select(func.count()).select_from(TranslationItem).where(*filters)) or 0
    items = db.scalars(
        select(TranslationItem)
        .where(*filters)
        .order_by(TranslationItem.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/translation/files/search", response_model=TranslationFileSearchPage)
def search_translation_files(
    q: str = Query(..., min_length=1),
    folder_path: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    root = validate_translation_root(folder_path)
    term = q.strip().lower()
    matches: list[TranslationFileSearchRead] = []
    for path in list_nfo_files(str(root)):
        identifier = extract_identifier(path.name)
        haystacks = [path.name.lower(), str(path).lower(), (identifier or "").lower()]
        if not any(term in value for value in haystacks):
            continue
        latest_item = db.scalar(
            select(TranslationItem).where(TranslationItem.file_path == str(path)).order_by(TranslationItem.id.desc()).limit(1)
        )
        matches.append(
            TranslationFileSearchRead(
                file_path=str(path),
                filename=path.name,
                identifier=identifier,
                parent_path=str(path.parent),
                last_item_status=latest_item.status if latest_item else None,
                last_item_updated_at=latest_item.updated_at if latest_item else None,
            )
        )
    total = len(matches)
    start = (page - 1) * page_size
    end = start + page_size
    return {"items": matches[start:end], "total": total, "page": page, "page_size": page_size}


@router.post("/translation/files/run", response_model=TranslationJobRead, status_code=202)
def run_translation_single_file(payload: TranslationSingleFileRunRequest, db: Session = Depends(get_db)):
    target = Path(payload.file_path).resolve()
    try:
        validate_translation_root(str(target.parent))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not target.exists() or not target.is_file() or target.suffix.lower() != ".nfo":
        raise HTTPException(status_code=404, detail="translation target file not found")

    watch_folder = None
    prompt_template = payload.prompt_template or ""
    if payload.watch_folder_id is not None:
        watch_folder = db.get(TranslationWatchFolder, payload.watch_folder_id)
        if not watch_folder:
            raise HTTPException(status_code=404, detail="translation watch folder not found")
        prompt_template = watch_folder.prompt_template
    elif not prompt_template.strip():
        watch_folder = db.scalar(
            select(TranslationWatchFolder)
            .where(TranslationWatchFolder.folder_path == str(target.parent))
            .order_by(TranslationWatchFolder.id.desc())
        )
        if watch_folder:
            prompt_template = watch_folder.prompt_template
    if not prompt_template.strip():
        raise HTTPException(status_code=400, detail="prompt_template 不能为空")

    job = TranslationJob(
        watch_folder_id=watch_folder.id if watch_folder else payload.watch_folder_id,
        folder_path=str(target.parent),
        prompt_template=prompt_template,
        mode=payload.mode,
        status="pending",
        total_count=0,
        processed_count=0,
        translated_count=0,
        skipped_count=0,
        failed_count=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    translation_task_manager.start(job.id, str(target))
    return job


@router.post("/translation/jobs/{job_id}/stop", response_model=TranslationJobRead, status_code=202)
def stop_translation_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(TranslationJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="translation job not found")
    if job.status not in ("pending", "running", "stopping"):
        raise HTTPException(status_code=409, detail="translation job already finished")
    if not translation_task_manager.stop(job_id):
        raise HTTPException(status_code=409, detail="translation job is not running in current process")
    job.status = "stopping"
    db.commit()
    db.refresh(job)
    return job


@router.get("/nfo-tags/search", response_model=NfoTagSearchPage)
def search_nfo_tags(
    folder_path: str = Query(...),
    search_type: Literal["title", "raw_tag"] = Query(...),
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    items = search_nfo_tag_records(folder_path, search_type, q)
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {"items": items[start:end], "total": total, "page": page, "page_size": page_size}


@router.post("/nfo-tags/batch-add", response_model=NfoTagBatchAddResult)
def batch_add_nfo_tag(payload: NfoTagBatchAddRequest):
    try:
        return add_extra_tag_to_nfo_files(payload.file_paths, payload.tag_name)
    except (ValueError, PermissionError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/translation/items/{item_id}/retry", response_model=TranslationItemRead, status_code=200)
def retry_translation_item_api(item_id: int, db: Session = Depends(get_db)):
    try:
        return retry_translation_item(db, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/sources", response_model=list[SourceRead])
def list_sources(db: Session = Depends(get_db)):
    return db.scalars(select(Source).order_by(Source.id.desc())).all()


@router.post("/sources", response_model=SourceRead, status_code=201)
def create_source(payload: SourceCreate, db: Session = Depends(get_db)):
    if payload.provider_type == "local_fs":
        try:
            LocalFSProvider().validate_root(payload.root_path or "")
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    source = Source(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/reference-sources", response_model=list[ReferenceSourceRead])
def list_reference_sources(db: Session = Depends(get_db)):
    return db.scalars(select(ReferenceSource).order_by(ReferenceSource.id.desc())).all()


@router.post("/reference-sources", response_model=ReferenceSourceRead, status_code=201)
def create_reference_source(payload: ReferenceSourceCreate, db: Session = Depends(get_db)):
    try:
        LocalSTRMReferenceProvider().validate_root(payload.root_path)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    source = ReferenceSource(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.post("/reference-sources/{source_id}/scan", response_model=ReferenceScanResult)
def scan_reference_source_api(source_id: int, db: Session = Depends(get_db)):
    source = db.get(ReferenceSource, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="reference source not found")
    if not source.enabled:
        raise HTTPException(status_code=400, detail="reference source is disabled")
    try:
        result = scan_reference_source(db, source)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"source_id": source.id, **result}


def reference_item_filters(q: str | None, status: str | None, source_id: int | None):
    filters = []
    if q:
        term = f"%{q}%"
        filters.append(or_(
            ReferenceItem.identifier.ilike(term),
            ReferenceItem.reference_path.ilike(term),
            ReferenceItem.reference_dir.ilike(term),
            ReferenceItem.filename.ilike(term),
        ))
    if status:
        filters.append(ReferenceItem.status == status)
    if source_id:
        filters.append(ReferenceItem.source_id == source_id)
    return filters


@router.get("/reference-items", response_model=ReferenceItemPage)
def list_reference_items(
    q: str | None = None,
    status: Literal["identified", "unidentified", "duplicate"] | None = None,
    source_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    filters = reference_item_filters(q, status, source_id)
    total = db.scalar(select(func.count()).select_from(ReferenceItem).where(*filters)) or 0
    items = db.scalars(
        select(ReferenceItem)
        .where(*filters)
        .order_by(ReferenceItem.reference_path)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/sources/{source_id}/scans", response_model=ScanJobRead, status_code=202)
def start_scan(source_id: int, db: Session = Depends(get_db)):
    source = db.get(Source, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="扫描源不存在")
    if not source.enabled:
        raise HTTPException(status_code=400, detail="扫描源已禁用")
    running = db.scalar(
        select(ScanJob).where(
            ScanJob.source_id == source_id,
            ScanJob.status.in_(("pending", "running", "stopping")),
        )
    )
    if running:
        raise HTTPException(status_code=409, detail="该扫描源已有任务运行中")
    job = ScanJob(source_id=source.id, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    scan_manager.start(job.id)
    return job


@router.post("/organizer/task/scan", response_model=OrganizerTaskScanResponse, status_code=202)
def organizer_task_scan(payload: OrganizerTaskScanRequest, db: Session = Depends(get_db)):
    try:
        source = ensure_local_source(db, payload.source_root, name=payload.name or "Organizer Task Source")
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    running = db.scalar(
        select(ScanJob).where(
            ScanJob.source_id == source.id,
            ScanJob.status.in_(("pending", "running", "stopping")),
        )
    )
    if running:
        return {"source": source, "scan_job": running}

    job = ScanJob(source_id=source.id, status="pending")
    db.add(job)
    db.commit()
    db.refresh(job)
    scan_manager.start(job.id)
    return {"source": source, "scan_job": job}


@router.get("/scans", response_model=list[ScanJobRead])
def list_scans(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(ScanJob).order_by(ScanJob.id.desc()).limit(limit)).all()


@router.get("/scans/{job_id}", response_model=ScanJobRead)
def get_scan(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="扫描任务不存在")
    return job


@router.post("/scans/{job_id}/stop", response_model=ScanJobRead, status_code=202)
def stop_scan(job_id: int, db: Session = Depends(get_db)):
    job = db.get(ScanJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="扫描任务不存在")
    if job.status not in ("pending", "running", "stopping"):
        raise HTTPException(status_code=409, detail="扫描任务已经结束")
    if not scan_manager.stop(job_id):
        raise HTTPException(status_code=409, detail="扫描任务不在当前进程中运行")
    job.status = "stopping"
    db.commit()
    db.refresh(job)
    return job


def file_filters(q: str | None, status: str | None, source_id: int | None):
    filters = []
    if q:
        term = f"%{q}%"
        filters.append(or_(MediaFile.filename.ilike(term), MediaFile.path.ilike(term), MediaFile.identifier.ilike(term)))
    if status:
        filters.append(MediaFile.status == status)
    if source_id:
        filters.append(MediaFile.source_id == source_id)
    return filters


@router.get("/files", response_model=FilePage)
def list_files(
    q: str | None = None,
    status: str | None = None,
    source_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: Literal["filename", "size", "indexed_at", "identifier"] = "indexed_at",
    sort_order: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
):
    filters = file_filters(q, status, source_id)
    total = db.scalar(select(func.count()).select_from(MediaFile).where(*filters)) or 0
    sort_column = getattr(MediaFile, sort_by)
    order = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    file_items = db.scalars(
        select(MediaFile).where(*filters).order_by(order).offset((page - 1) * page_size).limit(page_size)
    ).all()
    identifiers = {item.identifier for item in file_items if item.identifier}
    metadata_by_identifier = {
        item.identifier: item
        for item in db.scalars(select(MediaMetadata).where(MediaMetadata.identifier.in_(identifiers)))
    } if identifiers else {}
    items = [MediaFileRead(
        id=item.id,
        source_id=item.source_id,
        provider=item.provider,
        provider_file_id=item.provider_file_id,
        local_path=item.local_path,
        filename=item.filename,
        path=item.path,
        size=item.size,
        modified_time=item.modified_time,
        identifier=item.identifier,
        status=item.status,
        indexed_at=item.indexed_at,
        metadata=metadata_by_identifier.get(item.identifier),
    ) for item in file_items]
    return FilePage(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=StatsRead)
def stats(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(MediaFile.status, func.count()).group_by(MediaFile.status)).all())
    last_scan_at = db.scalar(select(func.max(ScanJob.finished_at)))
    return StatsRead(
        total=sum(counts.values()),
        identified=counts.get("identified", 0),
        unidentified=counts.get("unidentified", 0),
        missing=counts.get("missing", 0),
        last_scan_at=last_scan_at,
    )


@router.get("/exports/files.csv")
def export_files(
    q: str | None = None,
    status: str | None = None,
    source_id: int | None = None,
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(MediaFile).where(*file_filters(q, status, source_id)).order_by(MediaFile.path)
    ).yield_per(500)

    def generate():
        buffer = io.StringIO()
        buffer.write("\ufeff")
        writer = csv.writer(buffer)
        writer.writerow(["file_id", "filename", "path", "size", "identifier", "status", "modified_time"])
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for row in rows:
            writer.writerow([row.provider_file_id or row.id, row.filename, row.path, row.size, row.identifier or "", row.status, row.modified_time or ""])
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    headers = {"Content-Disposition": 'attachment; filename="media-index.csv"'}
    return StreamingResponse(generate(), media_type="text/csv; charset=utf-8", headers=headers)


@router.post("/metadata/import/csv", response_model=MetadataImportResult)
async def import_metadata_csv(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="CSV 文件不能超过 10 MB")
    try:
        content = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail="CSV 必须使用 UTF-8 编码") from exc
    try:
        provider, errors = ManualCSVProvider.from_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    created, updated = import_provider(db, provider)
    return MetadataImportResult(created=created, updated=updated, skipped=len(errors), errors=errors)


@router.get("/metadata", response_model=MetadataPage)
def list_metadata(
    q: str | None = None,
    actor: str | None = None,
    studio: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    filters = []
    if q:
        term = f"%{q}%"
        filters.append(or_(MediaMetadata.identifier.ilike(term), MediaMetadata.title.ilike(term), MediaMetadata.plot.ilike(term)))
    if actor:
        filters.append(cast(MediaMetadata.actors, Text).ilike(f"%{actor}%"))
    if studio:
        filters.append(MediaMetadata.studio.ilike(f"%{studio}%"))
    total = db.scalar(select(func.count()).select_from(MediaMetadata).where(*filters)) or 0
    items = db.scalars(
        select(MediaMetadata)
        .where(*filters)
        .order_by(MediaMetadata.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return MetadataPage(items=items, total=total, page=page, page_size=page_size)


def enrichment_identifiers(db: Session, scope: str, selected: list[str]) -> list[str]:
    if scope == "selected":
        normalized = [normalize_identifier(value) for value in selected]
        return list(dict.fromkeys(value for value in normalized if value))
    if scope == "partial":
        return list(db.scalars(
            select(MediaMetadata.identifier).where(MediaMetadata.status == "partial").order_by(MediaMetadata.identifier)
        ))
    return list(db.scalars(
        select(MediaFile.identifier)
        .outerjoin(MediaMetadata, MediaMetadata.identifier == MediaFile.identifier)
        .where(MediaFile.identifier.is_not(None), MediaMetadata.id.is_(None))
        .distinct()
        .order_by(MediaFile.identifier)
    ))


def reference_identifiers(
    db: Session,
    reference_source_id: int,
    reference_scope_prefix: str | None = None,
) -> list[str]:
    filters = [
        ReferenceItem.source_id == reference_source_id,
        ReferenceItem.identifier.is_not(None),
        ReferenceItem.status == "identified",
    ]
    prefix = (reference_scope_prefix or "").strip()
    if prefix:
        filters.append(ReferenceItem.reference_dir.like(f"{prefix}%"))
    return list(dict.fromkeys(
        db.scalars(
            select(ReferenceItem.identifier)
            .where(*filters)
            .order_by(ReferenceItem.reference_dir, ReferenceItem.id)
        ).all()
    ))


def create_metadata_job(
    db: Session,
    *,
    scope: str,
    provider_names: list[str],
    identifiers: list[str],
) -> MetadataEnrichmentJob:
    job = MetadataEnrichmentJob(
        status="pending",
        scope=scope,
        provider_names=provider_names,
        identifiers=identifiers,
        total_count=len(identifiers),
    )
    if not identifiers:
        job.status = "success"
        job.started_at = datetime.now(timezone.utc)
        job.finished_at = job.started_at
    db.add(job)
    db.commit()
    db.refresh(job)
    if identifiers:
        metadata_task_manager.start(job.id)
    return job


@router.post("/metadata/enrichment/jobs", response_model=MetadataEnrichmentJobRead, status_code=202)
def create_enrichment_job(payload: MetadataEnrichmentJobCreate, db: Session = Depends(get_db)):
    registry = provider_registry()
    provider_names = payload.providers or list(registry)
    unknown = set(provider_names) - set(registry)
    if unknown:
        raise HTTPException(status_code=400, detail=f"?? Provider: {', '.join(sorted(unknown))}")
    identifiers = enrichment_identifiers(db, payload.scope, payload.identifiers)
    return create_metadata_job(
        db,
        scope=payload.scope,
        provider_names=provider_names,
        identifiers=identifiers,
    )


@router.post("/metadata/harvest/reference", response_model=MetadataEnrichmentJobRead, status_code=202)
def harvest_reference_metadata(payload: MetadataReferenceHarvestCreate, db: Session = Depends(get_db)):
    reference_source = db.get(ReferenceSource, payload.reference_source_id)
    if not reference_source:
        raise HTTPException(status_code=404, detail="reference source not found")
    registry = provider_registry()
    provider_names = payload.providers or ["reference_metadata", "local_nfo"]
    unknown = set(provider_names) - set(registry)
    if unknown:
        raise HTTPException(status_code=400, detail=f"?? Provider: {', '.join(sorted(unknown))}")
    identifiers = reference_identifiers(
        db,
        payload.reference_source_id,
        payload.reference_scope_prefix,
    )
    scope_prefix = (payload.reference_scope_prefix or "").strip()
    return create_metadata_job(
        db,
        scope=f"reference:{payload.reference_source_id}:{scope_prefix or '*'}",
        provider_names=provider_names,
        identifiers=identifiers,
    )


@router.get("/metadata/enrichment/jobs", response_model=list[MetadataEnrichmentJobRead])
def list_enrichment_jobs(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(
        select(MetadataEnrichmentJob).order_by(MetadataEnrichmentJob.id.desc()).limit(limit)
    ).all()


@router.get("/metadata/enrichment/jobs/{job_id}", response_model=MetadataEnrichmentJobRead)
def get_enrichment_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(MetadataEnrichmentJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="元数据补全任务不存在")
    return job


@router.get("/metadata/enrichment/jobs/{job_id}/logs", response_model=MetadataTaskLogPage)
def enrichment_job_logs(
    job_id: int,
    q: str | None = None,
    provider: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if not db.get(MetadataEnrichmentJob, job_id):
        raise HTTPException(status_code=404, detail="元数据补全任务不存在")
    filters = [MetadataTaskLog.job_id == job_id]
    if q:
        filters.append(MetadataTaskLog.identifier.ilike(f"%{q}%"))
    if provider:
        filters.append(MetadataTaskLog.provider == provider)
    if status:
        filters.append(MetadataTaskLog.status == status)
    total = db.scalar(select(func.count()).select_from(MetadataTaskLog).where(*filters)) or 0
    items = db.scalars(
        select(MetadataTaskLog).where(*filters).order_by(MetadataTaskLog.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/metadata/enrichment/jobs/{job_id}/stop", response_model=MetadataEnrichmentJobRead, status_code=202)
def stop_enrichment_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(MetadataEnrichmentJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="元数据补全任务不存在")
    if job.status not in ("pending", "running", "stopping"):
        raise HTTPException(status_code=409, detail="元数据补全任务已经结束")
    if not metadata_task_manager.stop(job_id):
        raise HTTPException(status_code=409, detail="任务不在当前进程中运行")
    job.status = "stopping"
    db.commit()
    db.refresh(job)
    return job


@router.get("/metadata/missing.csv")
def export_missing_metadata(db: Session = Depends(get_db)):
    identifiers = db.scalars(
        select(MediaFile.identifier)
        .outerjoin(MediaMetadata, MediaMetadata.identifier == MediaFile.identifier)
        .where(
            MediaFile.identifier.is_not(None),
            or_(MediaMetadata.id.is_(None), MediaMetadata.status == "partial"),
        )
        .distinct()
        .order_by(MediaFile.identifier)
    ).all()
    rows = ([identifier, "", "", "", "", "", "", ""] for identifier in identifiers)
    headers = {"Content-Disposition": 'attachment; filename="missing-metadata.csv"'}
    return StreamingResponse(
        csv_stream(["identifier", "title", "plot", "actors", "studio", "series", "release_date", "cover_url"], rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


@router.post("/metadata/{identifier}/lookup", response_model=MetadataRead)
def lookup_mock_metadata(identifier: str, db: Session = Depends(get_db)):
    record = MockProvider().lookup(identifier)
    if record is None:
        raise HTTPException(status_code=400, detail="番号格式无效")
    item, _created = upsert_record(db, record)
    db.commit()
    db.refresh(item)
    return item


@router.get("/metadata/{identifier}", response_model=MetadataDetail)
def get_metadata(identifier: str, db: Session = Depends(get_db)):
    normalized = normalize_identifier(identifier)
    if not normalized:
        raise HTTPException(status_code=400, detail="番号格式无效")
    item = db.scalar(select(MediaMetadata).where(MediaMetadata.identifier == normalized))
    if not item:
        raise HTTPException(status_code=404, detail="元数据不存在")
    files = db.scalars(
        select(MediaFile).where(MediaFile.identifier == normalized).order_by(MediaFile.path)
    ).all()
    data = MetadataRead.model_validate(item).model_dump()
    return MetadataDetail(**data, files=files)


@router.post("/organizer/jobs", response_model=OrganizerJobRead, status_code=202)
def create_organizer_job(payload: OrganizerJobCreate, db: Session = Depends(get_db)):
    rule_template = payload.rule_template.strip()
    total_count = count_scope(db, payload.scope)
    if payload.mode == "reference_based":
        if not db.get(Source, payload.source_id):
            raise HTTPException(status_code=404, detail="media source not found")
        if not db.get(ReferenceSource, payload.reference_source_id):
            raise HTTPException(status_code=404, detail="reference source not found")
        rule_template = "reference_based"
        total_count = count_reference_scope(db, payload.source_id)
    else:
        try:
            template_fields(payload.rule_template)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = OrganizerJob(
        rule_template=rule_template,
        scope=payload.scope,
        mode=payload.mode,
        source_id=payload.source_id,
        reference_source_id=payload.reference_source_id,
        reference_scope_prefix=payload.reference_scope_prefix.strip() if payload.reference_scope_prefix else None,
        output_root=payload.output_root.strip().rstrip("/\\") if payload.output_root else None,
        filename_strategy=payload.filename_strategy,
        status="pending",
        total_count=total_count,
        status_counts={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    organizer_manager.start(job.id)
    return job


@router.post("/organizer/task/jobs", response_model=OrganizerJobRead, status_code=202)
def create_organizer_task_job(payload: OrganizerTaskJobCreate, db: Session = Depends(get_db)):
    try:
        source = ensure_local_source(db, payload.source_root, name="Organizer Task Source")
        reference_source = resolve_reference_source(db, payload.reference_source_id)
        if reference_source.provider_type == "local_strm" and Path(reference_source.root_path).exists():
            scan_reference_source(db, reference_source)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    output_root = payload.output_root.strip().rstrip("/\\")
    allowed_prefix = settings.clouddrive_container_root.rstrip("/") + "/"
    if not output_root.startswith(allowed_prefix):
        raise HTTPException(
            status_code=400,
            detail=f"output_root 必须位于 {settings.clouddrive_container_root.rstrip('/')}",
        )

    latest_scan = latest_scan_for_source(db, source.id)
    changed_since = latest_scan.started_at if latest_scan and latest_scan.status == "success" else None

    job = OrganizerJob(
        rule_template="reference_based",
        scope="all",
        mode="reference_based",
        source_id=source.id,
        reference_source_id=reference_source.id,
        reference_scope_prefix=payload.reference_scope_prefix.strip(),
        output_root=container_to_display_path(output_root),
        filename_strategy="match_reference_filename_with_source_suffix",
        status="pending",
        total_count=count_reference_scope_for_job(
            db,
            source_id=source.id,
            reference_source_id=reference_source.id,
            reference_scope_prefix=payload.reference_scope_prefix.strip(),
            changed_since=changed_since,
        ),
        status_counts={},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    organizer_manager.start(job.id)
    return job


@router.get("/organizer/jobs", response_model=list[OrganizerJobRead])
def list_organizer_jobs(limit: int = Query(30, ge=1, le=100), db: Session = Depends(get_db)):
    return db.scalars(select(OrganizerJob).order_by(OrganizerJob.id.desc()).limit(limit)).all()


@router.get("/organizer/jobs/{job_id}", response_model=OrganizerJobRead)
def get_organizer_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(OrganizerJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="整理计划不存在")
    return job


@router.get("/organizer/task/jobs/{job_id}/summary", response_model=OrganizerTaskSummaryRead)
def get_organizer_task_summary(job_id: int, db: Session = Depends(get_db)):
    try:
        return organizer_job_summary(db, job_id)
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.post("/organizer/jobs/{job_id}/execute", response_model=OrganizerExecutionResult | OrganizerPreflightResult)
def execute_job(job_id: int, payload: OrganizerExecuteRequest, db: Session = Depends(get_db)):
    if payload.mode == "preflight":
        try:
            return preflight_organizer_job(
                db,
                job_id,
                status_filter=payload.status_filter,
                limit=payload.limit,
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if "not found" in detail else 400
            raise HTTPException(status_code=status_code, detail=detail) from exc
    try:
        return execute_organizer_job(
            db,
            job_id,
            status_filter=payload.status_filter,
            limit=payload.limit,
            mode=payload.mode,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc


@router.get("/organizer/jobs/{job_id}/items", response_model=OrganizerItemPage)
def get_organizer_items(
    job_id: int,
    q: str | None = None,
    status: Literal["ready", "missing_metadata", "missing_reference", "duplicate_reference", "unidentified", "conflict", "invalid_path", "skipped"] | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if not db.get(OrganizerJob, job_id):
        raise HTTPException(status_code=404, detail="整理计划不存在")
    filters = [OrganizerItem.job_id == job_id]
    if q:
        term = f"%{q}%"
        filters.append(or_(
            OrganizerItem.source_path.ilike(term),
            OrganizerItem.target_path.ilike(term),
            OrganizerItem.identifier.ilike(term),
        ))
    if status:
        filters.append(OrganizerItem.status == status)
    total = db.scalar(select(func.count()).select_from(OrganizerItem).where(*filters)) or 0
    items = db.scalars(
        select(OrganizerItem).where(*filters).order_by(OrganizerItem.id)
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/organizer/jobs/{job_id}/executions", response_model=OrganizerExecutionLogPage)
def get_organizer_execution_logs(
    job_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    if not db.get(OrganizerJob, job_id):
        raise HTTPException(status_code=404, detail="整理计划不存在")
    total = db.scalar(
        select(func.count()).select_from(OrganizerExecutionLog).where(OrganizerExecutionLog.organizer_job_id == job_id)
    ) or 0
    items = db.scalars(
        select(OrganizerExecutionLog)
        .where(OrganizerExecutionLog.organizer_job_id == job_id)
        .order_by(OrganizerExecutionLog.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/organizer/jobs/{job_id}/export.csv")
def export_organizer_job(job_id: int, db: Session = Depends(get_db)):
    job = db.get(OrganizerJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="整理计划不存在")
    items = db.scalars(
        select(OrganizerItem).where(OrganizerItem.job_id == job_id).order_by(OrganizerItem.id)
    ).yield_per(500)
    rows = (
        [item.source_path, item.target_path or "", item.identifier or "", item.rule_template, item.status, item.error_message or ""]
        for item in items
    )
    headers = {"Content-Disposition": f'attachment; filename="organizer-plan-{job_id}.csv"'}
    return StreamingResponse(
        csv_stream(["source_path", "target_path", "identifier", "rule_template", "status", "error_message"], rows),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )


def collection_list_response(db, kind, q, sort_by, sort_order, page, page_size):
    items, total = list_collections(db, kind, q, sort_by, sort_order, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def collection_file_response(db, kind, name, q, page, page_size):
    items, total = collection_files(db, kind, name, q, page, page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/collections/actors", response_model=ActorCollectionPage)
def actor_collections(
    q: str | None = None,
    sort_by: Literal["file_count", "latest_release_date"] = "file_count",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return collection_list_response(db, "actor", q, sort_by, sort_order, page, page_size)


@router.get("/collections/actors/{actor}/files", response_model=CollectionFilePage)
def actor_collection_files(
    actor: str,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return collection_file_response(db, "actor", actor, q, page, page_size)


@router.get("/collections/studios", response_model=StudioCollectionPage)
def studio_collections(
    q: str | None = None,
    sort_by: Literal["file_count", "latest_release_date"] = "file_count",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return collection_list_response(db, "studio", q, sort_by, sort_order, page, page_size)


@router.get("/collections/studios/{studio}/files", response_model=CollectionFilePage)
def studio_collection_files(
    studio: str,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return collection_file_response(db, "studio", studio, q, page, page_size)


@router.get("/collections/series", response_model=SeriesCollectionPage)
def series_collections(
    q: str | None = None,
    sort_by: Literal["file_count", "latest_release_date"] = "file_count",
    sort_order: Literal["asc", "desc"] = "desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return collection_list_response(db, "series", q, sort_by, sort_order, page, page_size)


@router.get("/collections/series/{series}/files", response_model=CollectionFilePage)
def series_collection_files(
    series: str,
    q: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return collection_file_response(db, "series", series, q, page, page_size)
