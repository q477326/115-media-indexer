from pathlib import PurePosixPath

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OrganizerExecutionLog, OrganizerItem, OrganizerJob, ReferenceSource, ScanJob, Source
from app.services.cms_sync import cms_sync_configured
from app.providers.local_fs import LocalFSProvider


def _normalize_posix(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def container_to_display_path(path: str) -> str:
    normalized = _normalize_posix(path).rstrip("/")
    container_root = PurePosixPath(settings.clouddrive_container_root).as_posix().rstrip("/")
    host_root = PurePosixPath(settings.clouddrive_host_root).as_posix().rstrip("/")
    if normalized == container_root:
        return host_root
    if normalized.startswith(container_root + "/"):
        return host_root + normalized[len(container_root):]
    return normalized


def display_to_container_path(path: str) -> str:
    normalized = _normalize_posix(path).rstrip("/")
    container_root = PurePosixPath(settings.clouddrive_container_root).as_posix().rstrip("/")
    host_root = PurePosixPath(settings.clouddrive_host_root).as_posix().rstrip("/")
    if normalized == host_root:
        return container_root
    if normalized.startswith(host_root + "/"):
        return container_root + normalized[len(host_root):]
    return normalized


def ensure_local_source(db: Session, source_root: str, *, name: str | None = None) -> Source:
    normalized_root = _normalize_posix(source_root)
    LocalFSProvider().validate_root(normalized_root)
    source = db.scalar(
        select(Source).where(Source.provider_type == "local_fs", Source.root_path == normalized_root)
    )
    if source:
        if not source.enabled:
            source.enabled = True
        if name and source.name != name:
            source.name = name
        db.commit()
        db.refresh(source)
        return source
    source = Source(
        name=name or PurePosixPath(normalized_root).name or "CloudDrive2",
        provider_type="local_fs",
        root_path=normalized_root,
        enabled=True,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def resolve_reference_source(db: Session, reference_source_id: int | None) -> ReferenceSource:
    if reference_source_id is not None:
        source = db.get(ReferenceSource, reference_source_id)
        if not source:
            raise ValueError("reference source not found")
        if not source.enabled:
            raise ValueError("reference source is disabled")
        return source
    source = db.scalar(
        select(ReferenceSource).where(ReferenceSource.enabled.is_(True)).order_by(ReferenceSource.id.asc())
    )
    if not source:
        raise ValueError("no enabled reference source found")
    return source


def latest_scan_for_source(db: Session, source_id: int) -> ScanJob | None:
    return db.scalar(
        select(ScanJob).where(ScanJob.source_id == source_id).order_by(ScanJob.id.desc()).limit(1)
    )


def organizer_job_summary(db: Session, job_id: int) -> dict:
    job = db.get(OrganizerJob, job_id)
    if not job:
        raise ValueError("organizer job not found")
    if job.source_id is None or job.reference_source_id is None:
        raise ValueError("organizer task summary only supports reference_based jobs")
    source = db.get(Source, job.source_id)
    if not source or not source.root_path:
        raise ValueError("organizer source not found")

    status_counts = job.status_counts or {}
    moved_count = db.scalar(
        select(func.count()).select_from(OrganizerExecutionLog).where(
            OrganizerExecutionLog.organizer_job_id == job.id,
            OrganizerExecutionLog.status == "moved",
        )
    ) or 0
    failed_count = db.scalar(
        select(func.count()).select_from(OrganizerExecutionLog).where(
            OrganizerExecutionLog.organizer_job_id == job.id,
            OrganizerExecutionLog.status == "failed",
        )
    ) or 0
    moved_exists = exists().where(
        OrganizerExecutionLog.organizer_job_id == job.id,
        OrganizerExecutionLog.organizer_item_id == OrganizerItem.id,
        OrganizerExecutionLog.status == "moved",
    )
    remaining_ready_count = db.scalar(
        select(func.count()).select_from(OrganizerItem).where(
            OrganizerItem.job_id == job.id,
            OrganizerItem.status == "ready",
            ~moved_exists,
        )
    ) or 0
    scan_job = latest_scan_for_source(db, source.id)
    return {
        "organizer_job_id": job.id,
        "source_id": source.id,
        "source_root": source.root_path,
        "output_root": display_to_container_path(job.output_root or ""),
        "reference_source_id": job.reference_source_id,
        "reference_scope_prefix": job.reference_scope_prefix or "",
        "status": job.status,
        "scanned_count": scan_job.scanned_count if scan_job else 0,
        "identified_count": scan_job.identified_count if scan_job else 0,
        "ready_count": status_counts.get("ready", 0),
        "moved_count": moved_count,
        "remaining_ready_count": remaining_ready_count,
        "missing_reference_count": status_counts.get("missing_reference", 0),
        "unidentified_count": status_counts.get("unidentified", 0),
        "conflict_count": status_counts.get("conflict", 0),
        "failed_count": failed_count,
        "read_only_mode": settings.read_only_mode,
        "enable_remote_write": settings.enable_remote_write,
        "enable_real_move": settings.enable_real_move,
        "cms_sync_configured": cms_sync_configured(),
    }
