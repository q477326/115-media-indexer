from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.translation import TranslationFileState, TranslationJob, TranslationWatchFolder
from app.services.nfo_translation import validate_translation_root
from app.services.translation_task_manager import translation_task_manager


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def file_modified_time(path: Path) -> datetime:
    return normalize_datetime(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))


def normalize_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            value = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=None)


def same_modified_time(left: datetime | str | None, right: datetime | str | None) -> bool:
    normalized_left = normalize_datetime(left)
    normalized_right = normalize_datetime(right)
    if normalized_left is None or normalized_right is None:
        return False
    return abs((normalized_left - normalized_right).total_seconds()) < 1


def iter_nfo_files(root: Path, recursive: bool) -> list[Path]:
    iterator = root.rglob("*.nfo") if recursive else root.glob("*.nfo")
    return sorted(path for path in iterator if path.is_file())


def upsert_file_state(
    db,
    *,
    folder_id: int,
    file_path: Path,
    last_status: str,
    last_job_id: int | None = None,
) -> TranslationFileState:
    stat = file_path.stat()
    normalized_path = str(file_path)
    state = db.scalar(select(TranslationFileState).where(TranslationFileState.file_path == normalized_path))
    now = utcnow()
    if state is None:
        state = TranslationFileState(
            watch_folder_id=folder_id,
            file_path=normalized_path,
            modified_time=file_modified_time(file_path),
            size=stat.st_size,
            last_status=last_status,
            last_job_id=last_job_id,
            last_seen_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(state)
        return state
    state.watch_folder_id = folder_id
    state.modified_time = file_modified_time(file_path)
    state.size = stat.st_size
    state.last_status = last_status
    state.last_job_id = last_job_id
    state.last_seen_at = now
    state.updated_at = now
    return state


def create_monitor_job(db, folder: TranslationWatchFolder, file_path: Path) -> TranslationJob:
    job = TranslationJob(
        watch_folder_id=folder.id,
        folder_path=str(file_path.parent),
        prompt_template=folder.prompt_template,
        mode="translate",
        status="pending",
        total_count=0,
        processed_count=0,
        translated_count=0,
        skipped_count=0,
        failed_count=0,
    )
    db.add(job)
    db.flush()
    upsert_file_state(db, folder_id=folder.id, file_path=file_path, last_status="queued", last_job_id=job.id)
    return job


def scan_watch_folder(db, folder: TranslationWatchFolder) -> list[int]:
    root = validate_translation_root(folder.folder_path)
    files = iter_nfo_files(root, folder.recursive)
    job_ids: list[int] = []
    now = utcnow()

    if not folder.monitor_initialized:
        for file_path in files:
            upsert_file_state(db, folder_id=folder.id, file_path=file_path, last_status="seen")
        folder.monitor_initialized = True
        folder.last_scan_at = now
        folder.last_error = None
        return []

    states = {
        state.file_path: state
        for state in db.scalars(
            select(TranslationFileState).where(TranslationFileState.watch_folder_id == folder.id)
        )
    }
    for file_path in files:
        if len(job_ids) >= settings.translation_monitor_max_jobs_per_scan:
            break
        normalized_path = str(file_path)
        stat = file_path.stat()
        modified_time = file_modified_time(file_path)
        state = states.get(normalized_path)
        changed = state is not None and (
            state.size != stat.st_size or state.modified_time is None or not same_modified_time(state.modified_time, modified_time)
        )
        if state is None or changed:
            if state is not None and state.last_status in {"queued", "running"}:
                continue
            job = create_monitor_job(db, folder, file_path)
            job_ids.append(job.id)

    folder.last_scan_at = now
    folder.last_error = None
    return job_ids


class TranslationMonitor:
    def __init__(self) -> None:
        self._stop_event = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = Thread(target=self._run, name="translation-monitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self.scan_once()
            self._stop_event.wait(settings.translation_monitor_interval_seconds)

    def scan_once(self) -> int:
        queued = 0
        with SessionLocal() as db:
            folders = db.scalars(
                select(TranslationWatchFolder).where(
                    TranslationWatchFolder.enabled.is_(True),
                    TranslationWatchFolder.auto_translate.is_(True),
                )
            ).all()
            for folder in folders:
                try:
                    job_ids = scan_watch_folder(db, folder)
                    db.commit()
                    for job_id in job_ids:
                        translation_task_manager.start(job_id)
                    queued += len(job_ids)
                except Exception as exc:
                    folder.last_error = str(exc)
                    folder.last_scan_at = utcnow()
                    db.commit()
        return queued

    def scan_folder_now(self, folder_id: int) -> int:
        with SessionLocal() as db:
            folder = db.get(TranslationWatchFolder, folder_id)
            if not folder:
                raise ValueError("translation watch folder not found")
            job_ids = scan_watch_folder(db, folder)
            db.commit()
            for job_id in job_ids:
                translation_task_manager.start(job_id)
            return len(job_ids)


translation_monitor = TranslationMonitor()
