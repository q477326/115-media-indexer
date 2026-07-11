import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import OrganizerExecutionLog, OrganizerItem, OrganizerJob, Source


INVALID_TARGET_FRAGMENTS = ("/mnt/reference-strm", "/vol1/1000/media/小姐姐", "骑兵/骑兵")
SITE_PREFIXES = ("hhd800.com@", "4k2.me@", "489155.com@", "www.98t.la@")


def real_move_enabled() -> bool:
    return (
        settings.read_only_mode is False
        and settings.enable_remote_write is True
        and settings.enable_real_move is True
    )


def assert_real_move_enabled() -> None:
    if not real_move_enabled():
        raise PermissionError(
            "真实执行未启用：需要同时满足 READ_ONLY_MODE=false、ENABLE_REMOTE_WRITE=true、ENABLE_REAL_MOVE=true"
        )


def display_to_container_path(display_target_path: str) -> str:
    display = PurePosixPath(display_target_path).as_posix()
    host_root = PurePosixPath(settings.clouddrive_host_root).as_posix().rstrip("/")
    container_root = PurePosixPath(settings.clouddrive_container_root).as_posix().rstrip("/")
    if display == container_root or display.startswith(container_root + "/"):
        return display
    if display == host_root:
        return container_root
    if display.startswith(host_root + "/"):
        return container_root + display[len(host_root):]
    raise ValueError("target_path 不在配置的 CLOUDDRIVE_HOST_ROOT 或 CLOUDDRIVE_CONTAINER_ROOT 内")


def _normalize_posix(path: str | None) -> str:
    if not path:
        return ""
    return path.replace("\\", "/")


def _site_prefix_left(filename: str) -> bool:
    return filename.casefold().startswith(SITE_PREFIXES)


def _duplicate_suffix(filename: str) -> bool:
    lowered = filename.casefold()
    return "-c-c" in lowered or "-u-u" in lowered or "-4k-4k" in lowered


def _container_root_prefix() -> str:
    return PurePosixPath(settings.clouddrive_container_root).as_posix().rstrip("/") + "/"


def _source_root_prefix(source_root: str | None) -> str:
    if not source_root:
        return _container_root_prefix()
    return PurePosixPath(source_root).as_posix().rstrip("/") + "/"


def _container_output_root(output_root: str | None) -> str:
    if not output_root:
        return ""
    probe = display_to_container_path(output_root.rstrip("/") + "/.probe")
    return str(PurePosixPath(probe).parent).rstrip("/")


def _preflight_error(
    item: OrganizerItem,
    job: OrganizerJob,
    *,
    source_root: str | None,
    source_exists: bool,
    target_exists: bool,
) -> str | None:
    container_root_prefix = _container_root_prefix()
    source_root_prefix = _source_root_prefix(source_root)
    source_path = _normalize_posix(item.source_path)
    if item.status != "ready":
        return "item status is not ready"
    if not source_path.startswith(source_root_prefix):
        return f"source_path is outside {source_root_prefix.rstrip('/')}"
    if not source_path.startswith(container_root_prefix):
        return f"source_path is outside {container_root_prefix.rstrip('/')}"
    if not source_exists:
        return "source_path does not exist"
    if not item.target_path:
        return "target_path is empty"
    if not job.output_root or not item.target_path.startswith(job.output_root.rstrip("/") + "/"):
        return "target_path is outside organizer output_root"
    if any(fragment in item.target_path for fragment in INVALID_TARGET_FRAGMENTS):
        return "target_path contains forbidden fragment"
    filename = PurePosixPath(item.target_path).name
    if _site_prefix_left(filename):
        return "target_filename still contains site prefix"
    if _duplicate_suffix(filename):
        return "target_filename contains duplicated suffix"
    container_target_path = display_to_container_path(item.target_path)
    if not container_target_path.startswith(container_root_prefix):
        return f"container_target_path is outside {container_root_prefix.rstrip('/')}"
    if "/mnt/reference-strm" in container_target_path:
        return "container_target_path contains forbidden fragment"
    if target_exists:
        return "target_path already exists"
    return None


def _selected_items(db: Session, job_id: int, status_filter: str, limit: int) -> tuple[OrganizerJob, list[OrganizerItem]]:
    job = db.get(OrganizerJob, job_id)
    if not job:
        raise ValueError("organizer job not found")
    if job.mode != "reference_based":
        raise ValueError("第一阶段只允许执行 reference_based organizer job")
    if status_filter != "ready":
        raise ValueError("第一阶段只允许执行 status=ready")
    completed_exists = exists().where(
        OrganizerExecutionLog.organizer_job_id == job_id,
        OrganizerExecutionLog.organizer_item_id == OrganizerItem.id,
        OrganizerExecutionLog.status.in_(("moved", "skipped")),
    )
    items = db.scalars(
        select(OrganizerItem)
        .where(
            OrganizerItem.job_id == job_id,
            OrganizerItem.status == status_filter,
            ~completed_exists,
        )
        .order_by(OrganizerItem.id)
        .limit(limit)
    ).all()
    return job, items


def preflight_organizer_job(db: Session, job_id: int, *, status_filter: str, limit: int) -> dict:
    job, items = _selected_items(db, job_id, status_filter, limit)
    source = db.get(Source, job.source_id) if job.source_id else None
    source_root = source.root_path if source else None
    results = []
    passed = 0
    failed = 0
    duplicate_targets: set[str] = set()
    target_groups: dict[str, list[int]] = {}

    for item in items:
        if item.target_path:
            target_groups.setdefault(item.target_path, []).append(item.id)
    for target_path, item_ids in target_groups.items():
        if len(item_ids) > 1:
            duplicate_targets.add(target_path)

    container_output_root = _container_output_root(job.output_root)

    for item in items:
        display_target_path = item.target_path or ""
        source_path = _normalize_posix(item.source_path)
        try:
            container_target_path = display_to_container_path(display_target_path) if display_target_path else ""
        except Exception as exc:
            container_target_path = ""
            error_message = str(exc)
            source_exists = Path(item.source_path).exists() if item.source_path else False
            target_exists = False
            status = "failed"
        else:
            source_exists = Path(item.source_path).exists() if item.source_path else False
            target_exists = Path(container_target_path).exists() if container_target_path else False
            error_message = _preflight_error(
                item,
                job,
                source_root=source_root,
                source_exists=source_exists,
                target_exists=target_exists,
            )
            if error_message is None and display_target_path in duplicate_targets:
                error_message = "duplicate target_path within batch"
            if (
                error_message is None
                and container_output_root
                and source_path.startswith(container_output_root + "/")
            ):
                error_message = "source_path is already under organizer output_root"
            status = "passed" if error_message is None else "failed"

        if status == "passed":
            passed += 1
        else:
            failed += 1

        results.append({
            "organizer_item_id": item.id,
            "identifier": item.identifier,
            "source_path": source_path,
            "display_target_path": display_target_path,
            "container_target_path": container_target_path,
            "source_exists": source_exists,
            "target_exists": target_exists,
            "status": status,
            "error_message": error_message,
        })

    return {
        "organizer_job_id": job_id,
        "requested_count": len(items),
        "passed_count": passed,
        "failed_count": failed,
        "items": results,
    }


def execute_organizer_job(
    db: Session,
    job_id: int,
    *,
    status_filter: str,
    limit: int,
    mode: str,
) -> dict:
    assert_real_move_enabled()
    job, items = _selected_items(db, job_id, status_filter, limit)
    source = db.get(Source, job.source_id) if job.source_id else None
    source_root = source.root_path if source else None
    if mode != "move":
        raise ValueError("第一阶段只支持 mode=move")

    moved_logs: list[OrganizerExecutionLog] = []
    failed_logs: list[OrganizerExecutionLog] = []
    moved_count = 0
    skipped_count = 0
    failed_count = 0

    for item in items:
        source_path = _normalize_posix(item.source_path)
        container_target_path = display_to_container_path(item.target_path or "")
        log = OrganizerExecutionLog(
            organizer_job_id=job_id,
            organizer_item_id=item.id,
            identifier=item.identifier,
            source_path=source_path,
            display_target_path=item.target_path or "",
            container_target_path=container_target_path,
            action=mode,
            status="pending",
            executed_at=datetime.now(timezone.utc),
        )
        db.add(log)
        db.flush()

        source_exists = Path(item.source_path).exists() if item.source_path else False
        target_exists = Path(container_target_path).exists() if container_target_path else False
        preflight_error = _preflight_error(
            item,
            job,
            source_root=source_root,
            source_exists=source_exists,
            target_exists=target_exists,
        )
        if preflight_error:
            log.status = "skipped"
            log.error_message = preflight_error
            skipped_count += 1
            db.commit()
            continue

        try:
            Path(container_target_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(item.source_path, container_target_path)
            log.status = "moved"
            log.error_message = None
            moved_count += 1
            moved_logs.append(log)
            db.commit()
        except Exception as exc:
            log.status = "failed"
            log.error_message = str(exc)
            failed_count += 1
            failed_logs.append(log)
            db.commit()
            break

    return {
        "organizer_job_id": job_id,
        "requested_count": len(items),
        "moved_count": moved_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "moved_samples": moved_logs[:10],
        "failed_samples": failed_logs[:10],
        "rollback_hint": "如需人工回滚，可根据 execution log 将文件从 target_path 移回 source_path。",
    }
