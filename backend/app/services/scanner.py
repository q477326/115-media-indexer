import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MediaFile, ScanJob, Source
from app.providers import FileRef, LocalFSProvider, P115MockProvider, Provider
from app.services.identifier import extract_identifier


def _same_modified_time(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return abs(left.timestamp() - right.timestamp()) < 0.001


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _latest_successful_scan_started_at(db: Session, source_id: int, current_job_id: int) -> datetime | None:
    previous_scan = db.scalar(
        select(ScanJob)
        .where(
            ScanJob.source_id == source_id,
            ScanJob.status == "success",
            ScanJob.id != current_job_id,
        )
        .order_by(ScanJob.started_at.desc(), ScanJob.id.desc())
        .limit(1)
    )
    return previous_scan.started_at if previous_scan else None


def _directory_modified_after(path: Path, cutoff: datetime) -> bool:
    cutoff = _normalize_datetime(cutoff) or cutoff
    try:
        modified = datetime.fromtimestamp(path.stat(follow_symlinks=False).st_mtime, tz=timezone.utc)
    except OSError:
        return True
    return modified > cutoff


def _iter_incremental_local_files(
    root_path: str,
    cutoff: datetime,
    existing_files: dict[str, MediaFile],
) -> list[str]:
    cutoff = _normalize_datetime(cutoff) or cutoff
    provider = LocalFSProvider()
    root = provider.validate_root(root_path)
    results: list[str] = []

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)

        if current_path != root and not _directory_modified_after(current_path, cutoff):
            dirs[:] = []
            continue

        dirs[:] = sorted(
            directory
            for directory in dirs
            if _directory_modified_after(current_path / directory, cutoff)
        )

        for filename in sorted(files):
            candidate = current_path / filename
            if candidate.suffix.lower() not in provider.VIDEO_EXTENSIONS:
                continue
            candidate_path = str(candidate)
            existing = existing_files.get(candidate_path)
            existing_modified = _normalize_datetime(existing.modified_time if existing is not None else None)
            if existing is not None and existing_modified is not None and existing_modified <= cutoff:
                continue
            results.append(candidate_path)
    return results


def get_provider(provider_type: str) -> Provider:
    if provider_type == "local_fs":
        return LocalFSProvider()
    if provider_type == "p115":
        return P115MockProvider()
    raise ValueError(f"不支持的 provider: {provider_type}")


def scan_source(db: Session, job_id: int, stop_event: Event) -> None:
    job = db.get(ScanJob, job_id)
    if job is None:
        return

    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        source = db.get(Source, job.source_id)
        if source is None:
            raise ValueError("扫描源不存在")
        provider = get_provider(source.provider_type)
        root = source.root_path if source.provider_type == "local_fs" else source.root_file_id
        if not root:
            raise ValueError("扫描源缺少根路径或目录 ID")

        existing_files = {
            item.local_path: item
            for item in db.scalars(select(MediaFile).where(MediaFile.source_id == source.id))
            if item.local_path is not None
        }

        incremental_cutoff = None
        file_refs = None
        if source.provider_type == "local_fs":
            incremental_cutoff = _latest_successful_scan_started_at(db, source.id, job.id)
            if incremental_cutoff is not None:
                file_refs = [
                    provider.get_file_metadata(FileRef(path=path))
                    for path in _iter_incremental_local_files(root, incremental_cutoff, existing_files)
                ]

        iterable = file_refs if file_refs is not None else provider.list_files(root)

        for file_ref in iterable:
            if stop_event.is_set():
                job.status = "stopped"
                break
            try:
                metadata = file_ref if hasattr(file_ref, "filename") else provider.get_file_metadata(file_ref)
                identifier = extract_identifier(metadata.filename)
                existing = existing_files.get(metadata.local_path)
                now = datetime.now(timezone.utc)
                changed = (
                    existing is None
                    or existing.provider_file_id != metadata.provider_file_id
                    or existing.local_path != metadata.local_path
                    or existing.filename != metadata.filename
                    or existing.path != metadata.path
                    or existing.size != metadata.size
                    or not _same_modified_time(existing.modified_time, metadata.modified_time)
                    or existing.identifier != identifier
                    or existing.status != ("identified" if identifier else "unidentified")
                )
                if existing is None:
                    existing = MediaFile(source_id=source.id, provider=provider.provider_name)
                    existing_files[metadata.local_path] = existing
                    db.add(existing)
                existing.provider_file_id = metadata.provider_file_id
                existing.local_path = metadata.local_path
                existing.filename = metadata.filename
                existing.path = metadata.path
                existing.size = metadata.size
                existing.modified_time = metadata.modified_time
                existing.identifier = identifier
                existing.status = "identified" if identifier else "unidentified"
                existing.last_seen_at = now
                if changed:
                    if existing.first_seen_at is None:
                        existing.first_seen_at = now
                    existing.indexed_at = now
                    job.scanned_count += 1
                    if identifier:
                        job.identified_count += 1
                    else:
                        job.unidentified_count += 1
            except (OSError, ValueError) as exc:
                job.error_count += 1
                job.error_message = str(exc)

            if (job.scanned_count + job.error_count) % settings.scan_batch_size == 0:
                db.commit()

        if job.status != "stopped":
            db.flush()
            if incremental_cutoff is None:
                db.execute(
                    update(MediaFile)
                    .where(MediaFile.source_id == source.id, MediaFile.last_seen_at < job.started_at)
                    .values(status="missing")
                    .execution_options(synchronize_session=False)
                )
            job.status = "success"
    except Exception as exc:
        db.rollback()
        job = db.get(ScanJob, job_id)
        if job is not None:
            job.status = "failed"
            job.error_count += 1
            job.error_message = str(exc)
    finally:
        if job is not None:
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
