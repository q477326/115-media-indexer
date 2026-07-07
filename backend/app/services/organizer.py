from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from pathlib import PurePosixPath
import re
from string import Formatter

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import MediaFile, MediaMetadata, OrganizerItem, OrganizerJob, ReferenceItem, ScanJob


ALLOWED_FIELDS = {"actor", "studio", "series", "identifier", "prefix", "title", "year", "filename", "ext"}
METADATA_FIELDS = {"actor", "studio", "series", "title", "year"}
FORBIDDEN_COMPONENT_CHARS = set('<>:"\\|?*')
DEFAULT_REFERENCE_SCOPE_PREFIX = "\u9a91\u5175/"
INVALID_REFERENCE_FRAGMENTS = ["/mnt/reference-strm", "/vol1/1000/media/\u5c0f\u59d0\u59d0"]
REFERENCE_FILENAME_STRATEGIES = {"preserve_source_filename", "match_reference_filename_with_source_suffix"}
VERSION_SUFFIXES = [
    "-uncensored",
    "-part1",
    "-part2",
    "-subtitle",
    "-cd1",
    "-cd2",
    "-cd3",
    "-cd4",
    "-sub",
    "-4k",
    "-uc",
    "-破解",
    "-字幕",
    "-c",
    "-u",
]


def template_fields(rule_template: str) -> set[str]:
    if not rule_template or not rule_template.strip():
        raise ValueError("organizer template cannot be empty")
    try:
        fields = {field for _literal, field, _format, _conversion in Formatter().parse(rule_template) if field}
    except ValueError as exc:
        raise ValueError(f"invalid organizer template: {exc}") from exc
    unknown = fields - ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported template fields: {', '.join(sorted(unknown))}")
    if not fields:
        raise ValueError("organizer template requires at least one field")
    return fields


def _safe_path_components(value: str) -> tuple[bool, str | None]:
    if not value:
        return False, "path cannot be empty"
    if len(value) > 4096:
        return False, "path is longer than 4096 characters"
    normalized = value.replace("\\", "/")
    components = [component for component in normalized.split("/") if component]
    for component in components:
        if component in (".", ".."):
            return False, "path contains traversal"
        if len(component) > 255:
            return False, "path component is longer than 255 characters"
        if component.endswith((" ", ".")):
            return False, "path component cannot end with a space or dot"
        if any(char in FORBIDDEN_COMPONENT_CHARS or ord(char) < 32 for char in component):
            return False, "path contains unsafe Windows/NAS characters"
    return True, None


def _valid_relative_path(value: str) -> tuple[bool, str | None]:
    if not value or value.startswith("/") or value.startswith("\\"):
        return False, "target path must be a non-empty relative path"
    return _safe_path_components(value)


def _strip_reference_prefix(reference_dir: str, prefix: str) -> str:
    normalized_dir = PurePosixPath(reference_dir).as_posix().strip("/")
    normalized_prefix = PurePosixPath(prefix).as_posix().strip("/")
    if normalized_prefix and normalized_dir == normalized_prefix:
        return ""
    if normalized_prefix and normalized_dir.startswith(normalized_prefix + "/"):
        return normalized_dir[len(normalized_prefix) + 1:]
    return normalized_dir


def _join_output_target(output_root: str, stripped_reference_dir: str, filename: str) -> str:
    root = output_root.replace("\\", "/").rstrip("/")
    parts = [root]
    if stripped_reference_dir:
        parts.append(PurePosixPath(stripped_reference_dir).as_posix().strip("/"))
    parts.append(filename)
    return "/".join(parts)


def _display_to_container_path(display_target_path: str) -> str:
    display = PurePosixPath(display_target_path).as_posix()
    host_root = PurePosixPath(settings.clouddrive_host_root).as_posix().rstrip("/")
    container_root = PurePosixPath(settings.clouddrive_container_root).as_posix().rstrip("/")
    if display == container_root or display.startswith(container_root + "/"):
        return display
    if display == host_root:
        return container_root
    if display.startswith(host_root + "/"):
        return container_root + display[len(host_root):]
    raise ValueError("target_path is outside configured CloudDrive roots")


def _validate_reference_target(target_path: str, filename: str) -> tuple[bool, str | None]:
    if any(fragment in target_path for fragment in INVALID_REFERENCE_FRAGMENTS):
        return False, "target path contains reference source root"
    duplicated_scope = f"{DEFAULT_REFERENCE_SCOPE_PREFIX.rstrip('/')}/{DEFAULT_REFERENCE_SCOPE_PREFIX.rstrip('/')}"
    if duplicated_scope in target_path:
        return False, "target path contains duplicated scope prefix"
    valid, error = _safe_path_components(target_path)
    if not valid:
        return False, error
    if PurePosixPath(target_path).name != filename:
        return False, "target basename does not match planned filename"
    return True, None


def _reference_stem(filename: str) -> str:
    return filename.rsplit(".", 1)[0] if "." in filename else filename


def _source_extension(filename: str) -> str:
    return PurePosixPath(filename).suffix


def _identifier_pattern(identifier: str) -> re.Pattern[str]:
    prefix, number = identifier.split("-", 1)
    return re.compile(rf"(?i)(?<![A-Za-z0-9]){re.escape(prefix)}[-_ ]?{re.escape(number)}(?!\d)")


def _extract_version_suffix(source_filename: str, identifier: str) -> str:
    stem = _reference_stem(source_filename)
    match = _identifier_pattern(identifier).search(stem)
    if not match:
        return ""
    remainder = stem[match.end():]
    suffix = ""
    while remainder:
        matched = False
        for token in VERSION_SUFFIXES:
            token_len = len(token)
            if remainder[:token_len].casefold() == token.casefold():
                suffix += remainder[:token_len]
                remainder = remainder[token_len:]
                matched = True
                break
        if not matched:
            break
    return suffix


def build_reference_target_filename(
    source_filename: str,
    identifier: str,
    reference_filename: str,
    filename_strategy: str,
) -> tuple[str | None, str | None]:
    if filename_strategy not in REFERENCE_FILENAME_STRATEGIES:
        return None, f"unsupported filename strategy: {filename_strategy}"
    if filename_strategy == "preserve_source_filename":
        return source_filename, None

    ext = _source_extension(source_filename)
    if not ext:
        return None, "source file has no extension"
    reference_stem = _reference_stem(reference_filename)
    if not reference_stem:
        return None, "reference filename has no stem"
    suffix = _extract_version_suffix(source_filename, identifier)
    return f"{identifier}{suffix}{ext}", None


def plan_item(file: MediaFile, metadata: MediaMetadata | None, rule_template: str, fields: set[str]):
    if file.status == "missing":
        return "skipped", None, "file is missing in latest scan"
    if not file.identifier:
        return "unidentified", None, "media file has no identifier"

    values = {
        "identifier": file.identifier,
        "prefix": file.identifier.split("-", 1)[0],
        "filename": file.filename,
        "ext": file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "",
        "actor": (metadata.actors[0] if metadata and metadata.actors else ""),
        "studio": metadata.studio if metadata and metadata.studio else "",
        "series": metadata.series if metadata and metadata.series else "",
        "title": metadata.title if metadata and metadata.title else "",
        "year": str(metadata.release_date.year) if metadata and metadata.release_date else "",
    }
    missing_fields = sorted(field for field in fields & METADATA_FIELDS if not values[field])
    if missing_fields:
        return "missing_metadata", None, f"missing metadata fields: {', '.join(missing_fields)}"
    if "ext" in fields and not values["ext"]:
        return "invalid_path", None, "file has no extension for {ext}"
    if any("/" in str(values[field]) or "\\" in str(values[field]) for field in fields):
        return "invalid_path", None, "template field value contains path separators"

    try:
        rendered = rule_template.format_map(values).strip()
    except (KeyError, ValueError) as exc:
        return "invalid_path", None, f"template render failed: {exc}"
    valid, error = _valid_relative_path(rendered)
    if not valid:
        return "invalid_path", None, error
    return "ready", PurePosixPath(rendered).as_posix(), None


def organizer_scope_query(scope: str):
    query = select(MediaFile, MediaMetadata).outerjoin(
        MediaMetadata, MediaMetadata.identifier == MediaFile.identifier
    )
    if scope == "identified":
        query = query.where(MediaFile.identifier.is_not(None), MediaFile.status != "missing")
    elif scope == "with_metadata":
        query = query.where(MediaMetadata.id.is_not(None), MediaFile.status != "missing")
    elif scope == "missing_metadata":
        query = query.where(
            MediaFile.identifier.is_not(None),
            MediaMetadata.id.is_(None),
            MediaFile.status != "missing",
        )
    return query.order_by(MediaFile.path)


def count_scope(db: Session, scope: str) -> int:
    return db.scalar(select(func.count()).select_from(organizer_scope_query(scope).subquery())) or 0


def count_reference_scope(db: Session, source_id: int | None, *, changed_since: datetime | None = None) -> int:
    query = select(func.count()).select_from(MediaFile)
    if source_id is not None:
        query = query.where(MediaFile.source_id == source_id)
    if changed_since is not None:
        query = query.where(MediaFile.indexed_at >= changed_since)
    return db.scalar(query) or 0


def count_reference_scope_for_job(
    db: Session,
    *,
    source_id: int | None,
    reference_source_id: int | None,
    reference_scope_prefix: str | None,
    changed_since: datetime | None = None,
) -> int:
    delta_ids = {
        row[0]
        for row in db.execute(
            select(MediaFile.id).where(
                *(
                    [MediaFile.source_id == source_id] if source_id is not None else []
                ),
                *(
                    [MediaFile.indexed_at >= changed_since] if changed_since is not None else []
                ),
            )
        )
    }
    retry_ids = _retry_missing_reference_media_file_ids(
        db,
        source_id=source_id,
        reference_source_id=reference_source_id,
        reference_scope_prefix=reference_scope_prefix,
    )
    return len(delta_ids | retry_ids)


def _retry_missing_reference_media_file_ids(
    db: Session,
    *,
    source_id: int | None,
    reference_source_id: int | None,
    reference_scope_prefix: str | None,
    exclude_job_id: int | None = None,
) -> set[int]:
    if source_id is None or reference_source_id is None:
        return set()
    query = (
        select(OrganizerItem.media_file_id)
        .join(OrganizerJob, OrganizerJob.id == OrganizerItem.job_id)
        .where(
            OrganizerJob.mode == "reference_based",
            OrganizerJob.source_id == source_id,
            OrganizerJob.reference_source_id == reference_source_id,
            OrganizerJob.reference_scope_prefix == reference_scope_prefix,
            OrganizerJob.status == "success",
            OrganizerItem.status == "missing_reference",
        )
        .distinct()
    )
    if exclude_job_id is not None:
        query = query.where(OrganizerJob.id != exclude_job_id)
    rows = db.scalars(query).all()
    return set(rows)


def _reference_items_by_identifier(
    db: Session,
    reference_source_id: int,
    reference_scope_prefix: str,
) -> dict[str, list[ReferenceItem]]:
    rows = db.scalars(
        select(ReferenceItem)
        .where(
            ReferenceItem.source_id == reference_source_id,
            ReferenceItem.identifier.is_not(None),
            ReferenceItem.reference_dir.startswith(reference_scope_prefix),
        )
        .order_by(ReferenceItem.reference_path)
    )
    result: dict[str, list[ReferenceItem]] = {}
    for item in rows:
        if item.identifier:
            result.setdefault(item.identifier, []).append(item)
    return result


def _reference_media_files(db: Session, source_id: int | None, *, changed_since: datetime | None = None):
    query = select(MediaFile)
    if source_id is not None:
        query = query.where(MediaFile.source_id == source_id)
    if changed_since is not None:
        query = query.where(MediaFile.indexed_at >= changed_since)
    return db.scalars(query.order_by(MediaFile.path)).yield_per(500)


def _reference_media_files_for_job(
    db: Session,
    job: OrganizerJob,
    *,
    changed_since: datetime | None = None,
):
    delta_files = list(_reference_media_files(db, job.source_id, changed_since=changed_since))
    retry_ids = _retry_missing_reference_media_file_ids(
        db,
        source_id=job.source_id,
        reference_source_id=job.reference_source_id,
        reference_scope_prefix=job.reference_scope_prefix,
        exclude_job_id=job.id,
    )
    seen_ids = {file.id for file in delta_files}
    files = list(delta_files)
    if retry_ids:
        retry_files = db.scalars(
            select(MediaFile)
            .where(MediaFile.id.in_(retry_ids))
            .order_by(MediaFile.path)
        ).all()
        for file in retry_files:
            if file.id not in seen_ids:
                files.append(file)
                seen_ids.add(file.id)
    files.sort(key=lambda item: item.path)
    return files


def _latest_successful_scan_started_at(db: Session, source_id: int | None) -> datetime | None:
    if source_id is None:
        return None
    return db.scalar(
        select(ScanJob.started_at)
        .where(
            ScanJob.source_id == source_id,
            ScanJob.status == "success",
            ScanJob.started_at.is_not(None),
        )
        .order_by(ScanJob.id.desc())
        .limit(1)
    )


def _apply_conflict_detection(
    targets: dict[str, OrganizerItem | None],
    target_path: str | None,
    status: str,
    counts: Counter,
) -> tuple[str, str | None]:
    if status != "ready" or not target_path:
        return status, None
    target_key = target_path.casefold()
    previous = targets.get(target_key)
    if previous is not None:
        if previous.status == "ready":
            previous.status = "conflict"
            previous.error_message = "multiple files generated the same target path"
            counts["ready"] -= 1
            counts["conflict"] += 1
        return "conflict", "multiple files generated the same target path"
    targets[target_key] = None
    return status, None


def _add_item(
    db: Session,
    job: OrganizerJob,
    file: MediaFile,
    target_path: str | None,
    status: str,
    error: str | None,
) -> OrganizerItem:
    item = OrganizerItem(
        job_id=job.id,
        media_file_id=file.id,
        source_path=file.path,
        target_path=target_path,
        identifier=file.identifier,
        rule_template=job.rule_template,
        status=status,
        error_message=error,
    )
    db.add(item)
    return item


def _run_reference_organizer_job(db: Session, job: OrganizerJob) -> None:
    if job.reference_source_id is None:
        raise ValueError("reference_based organizer job requires reference_source_id")
    if not job.output_root:
        raise ValueError("reference_based organizer job requires output_root")
    prefix = job.reference_scope_prefix or DEFAULT_REFERENCE_SCOPE_PREFIX
    filename_strategy = job.filename_strategy or "preserve_source_filename"
    references = _reference_items_by_identifier(db, job.reference_source_id, prefix)
    counts = Counter()
    targets: dict[str, OrganizerItem | None] = {}

    changed_since = _latest_successful_scan_started_at(db, job.source_id)
    for file in _reference_media_files_for_job(db, job, changed_since=changed_since):
        target_path = None
        error = None
        source_exists = Path(PurePosixPath(file.path).as_posix()).exists()
        if file.status == "missing" or not source_exists:
            status = "skipped"
            error = "file is missing in latest scan" if file.status == "missing" else "source_path does not exist on disk"
        elif not file.identifier:
            status = "unidentified"
            error = "media file has no identifier"
        else:
            matched = references.get(file.identifier, [])
            if not matched:
                status = "missing_reference"
                error = f"no reference item under {prefix}"
            elif len(matched) > 1 or any(item.status == "duplicate" for item in matched):
                status = "duplicate_reference"
                error = "multiple reference items matched this identifier"
            else:
                reference = matched[0]
                target_filename, filename_error = build_reference_target_filename(
                    file.filename,
                    file.identifier,
                    reference.filename,
                    filename_strategy,
                )
                if filename_error or not target_filename:
                    status = "invalid_path"
                    error = filename_error
                else:
                    stripped_reference_dir = _strip_reference_prefix(reference.reference_dir, prefix)
                    target_path = _join_output_target(job.output_root, stripped_reference_dir, target_filename)
                    valid, error = _validate_reference_target(target_path, target_filename)
                    status = "ready" if valid else "invalid_path"
                    if status == "ready":
                        try:
                            container_target_path = _display_to_container_path(target_path)
                        except ValueError as exc:
                            status = "invalid_path"
                            error = str(exc)
                        else:
                            source_path = PurePosixPath(file.path).as_posix()
                            output_root = job.output_root.rstrip("/") if job.output_root else ""
                            output_root_container = _display_to_container_path(output_root) if output_root else ""
                            if Path(container_target_path).exists():
                                status = "skipped"
                                error = "target_path already exists"
                            elif output_root_container and source_path.startswith(output_root_container + "/"):
                                status = "skipped"
                                error = "source_path is already under organizer output_root"

        status, conflict_error = _apply_conflict_detection(targets, target_path, status, counts)
        if conflict_error:
            error = conflict_error

        item = _add_item(db, job, file, target_path, status, error)
        if status == "ready" and target_path:
            targets[target_path.casefold()] = item
        counts[status] += 1
        job.processed_count += 1

    job.status_counts = dict(counts)
    job.total_count = job.processed_count
    job.status = "success"


def _run_template_organizer_job(db: Session, job: OrganizerJob) -> None:
    counts = Counter()
    targets: dict[str, OrganizerItem | None] = {}
    fields = template_fields(job.rule_template)
    rows = db.execute(organizer_scope_query(job.scope)).yield_per(500)
    for file, metadata in rows:
        status, target_path, error = plan_item(file, metadata, job.rule_template, fields)
        status, conflict_error = _apply_conflict_detection(targets, target_path, status, counts)
        if conflict_error:
            error = conflict_error

        item = _add_item(db, job, file, target_path, status, error)
        if status == "ready" and target_path:
            targets[target_path.casefold()] = item
        counts[status] += 1
        job.processed_count += 1
        if job.processed_count % 250 == 0:
            job.status_counts = dict(counts)
            db.commit()

    job.status_counts = dict(counts)
    job.status = "success"


def run_organizer_job(db: Session, job_id: int) -> None:
    job = db.get(OrganizerJob, job_id)
    if job is None:
        return
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        if job.mode == "reference_based":
            _run_reference_organizer_job(db, job)
        else:
            _run_template_organizer_job(db, job)
    except Exception as exc:
        db.rollback()
        job = db.get(OrganizerJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)
    finally:
        if job:
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
