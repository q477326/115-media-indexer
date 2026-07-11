import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ReferenceItem, ReferenceSource
from app.reference_providers import LocalSTRMReferenceProvider, ReferenceProvider
from app.reference_providers.base import ReferenceFileRef
from app.services.identifier import extract_identifier
from app.services.strm_reference import extract_embedded_filename, normalize_embedded_filename, read_strm_content


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _directory_modified_after(path: Path, cutoff: datetime) -> bool:
    cutoff = _normalize_datetime(cutoff) or cutoff
    try:
        modified = datetime.fromtimestamp(path.stat(follow_symlinks=False).st_mtime, tz=timezone.utc)
    except OSError:
        return True
    return modified > cutoff


def _file_modified_after(path: Path, cutoff: datetime) -> bool:
    return _directory_modified_after(path, cutoff)


def _collect_incremental_file_refs(source: ReferenceSource, cutoff: datetime) -> tuple[list[ReferenceFileRef], set[str]]:
    provider = get_reference_provider(source.provider_type)
    root = provider.validate_root(source.root_path)  # type: ignore[attr-defined]
    refs: list[ReferenceFileRef] = []
    changed_dirs: set[str] = set()

    # A parent directory's mtime does not change when a file is added several
    # levels below it. Walk the local directory tree cheaply, then only read
    # STRM files from directories or files that changed after the cutoff.
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_dir = PurePosixPath(current_path.relative_to(root).as_posix()).as_posix()
        if relative_dir == ".":
            relative_dir = ""
        directory_changed = _directory_modified_after(current_path, cutoff)
        if directory_changed:
            changed_dirs.add(relative_dir)
        dirs[:] = sorted(dirs)

        for filename in sorted(files):
            if Path(filename).suffix.lower() != ".strm":
                continue
            file_path = current_path / filename
            if directory_changed or _file_modified_after(file_path, cutoff):
                refs.append(ReferenceFileRef(path=str(file_path)))
                changed_dirs.add(relative_dir)

    return refs, changed_dirs


def get_reference_provider(provider_type: str) -> ReferenceProvider:
    if provider_type == "local_strm":
        return LocalSTRMReferenceProvider()
    raise ValueError(f"unsupported reference provider: {provider_type}")


def _collect_snapshot(source: ReferenceSource, *, incremental_cutoff: datetime | None = None) -> tuple[list[dict], int, set[str]]:
    provider = get_reference_provider(source.provider_type)
    provider.validate_root(source.root_path)  # type: ignore[attr-defined]

    snapshot: list[dict] = []
    error_count = 0
    changed_dirs: set[str] = set()
    if incremental_cutoff is not None and source.provider_type == "local_strm":
        iterable, changed_dirs = _collect_incremental_file_refs(source, incremental_cutoff)
    else:
        iterable = provider.list_files(source.root_path)
    for file_ref in iterable:
        try:
            metadata = provider.get_file_metadata(source.root_path, file_ref)
            identifier = extract_identifier(metadata.filename) or extract_identifier(metadata.reference_path)
            strm_url = None
            embedded_filename = None
            normalized_embedded_filename = None
            if metadata.ext.lower() == "strm":
                strm_url, embedded_filename = extract_embedded_filename(read_strm_content(file_ref.path))
                normalized_embedded_filename = normalize_embedded_filename(embedded_filename)
            snapshot.append({
                "identifier": identifier,
                "reference_path": metadata.reference_path,
                "reference_dir": metadata.reference_dir,
                "filename": metadata.filename,
                "ext": metadata.ext,
                "strm_url": strm_url,
                "embedded_filename": embedded_filename,
                "normalized_embedded_filename": normalized_embedded_filename,
                "size": metadata.size,
                "modified_time": metadata.modified_time,
            })
        except (OSError, ValueError):
            error_count += 1
    return snapshot, error_count, changed_dirs


def scan_reference_source(db: Session, source: ReferenceSource) -> dict[str, int]:
    incremental_cutoff = _normalize_datetime(source.last_scanned_at)
    snapshot, error_count, changed_dirs = _collect_snapshot(source, incremental_cutoff=incremental_cutoff)
    match_key_counts: Counter[str] = Counter()
    for row in snapshot:
        match_key = row["identifier"] or row["normalized_embedded_filename"]
        if match_key:
            match_key_counts[match_key] += 1
    existing_query = select(ReferenceItem).where(ReferenceItem.source_id == source.id)
    if incremental_cutoff is not None and changed_dirs:
        existing_items = db.scalars(existing_query).all()
        def _affected(item: ReferenceItem) -> bool:
            reference_dir = item.reference_dir or ""
            return reference_dir in changed_dirs
        existing_items = [item for item in existing_items if _affected(item)]
    elif incremental_cutoff is not None and not changed_dirs:
        source.last_scanned_at = datetime.now(timezone.utc)
        db.commit()
        return {
            "scanned_count": 0,
            "identified_count": 0,
            "unidentified_count": 0,
            "duplicate_count": 0,
            "error_count": error_count,
        }
    else:
        existing_items = db.scalars(existing_query).all()
    existing_by_path = {item.reference_path: item for item in existing_items}
    seen_paths: set[str] = set()

    for row in snapshot:
        seen_paths.add(row["reference_path"])
        item = existing_by_path.get(row["reference_path"])
        if item is None:
            item = ReferenceItem(
                source_id=source.id,
                reference_path=row["reference_path"],
            )
            db.add(item)
        item.identifier = row["identifier"]
        item.reference_dir = row["reference_dir"]
        item.filename = row["filename"]
        item.ext = row["ext"]
        item.strm_url = row["strm_url"]
        item.embedded_filename = row["embedded_filename"]
        item.normalized_embedded_filename = row["normalized_embedded_filename"]
        item.size = row["size"]
        item.modified_time = row["modified_time"]
        match_key = row["identifier"] or row["normalized_embedded_filename"]
        if not match_key:
            item.status = "unidentified"
        elif match_key_counts[match_key] > 1:
            item.status = "duplicate"
        else:
            item.status = "identified"

    for item in existing_items:
        if item.reference_path not in seen_paths:
            db.delete(item)

    all_items = db.scalars(
        select(ReferenceItem).where(ReferenceItem.source_id == source.id)
    ).all()
    all_match_key_counts: Counter[str] = Counter()
    for item in all_items:
        match_key = item.identifier or item.normalized_embedded_filename
        if match_key:
            all_match_key_counts[match_key] += 1
    for item in all_items:
        match_key = item.identifier or item.normalized_embedded_filename
        if not match_key:
            item.status = "unidentified"
        elif all_match_key_counts[match_key] > 1:
            item.status = "duplicate"
        else:
            item.status = "identified"

    source.last_scanned_at = datetime.now(timezone.utc)
    db.commit()
    return {
        "scanned_count": len(snapshot),
        "identified_count": sum(
            1
            for row in snapshot
            if (row["identifier"] or row["normalized_embedded_filename"])
            and match_key_counts[row["identifier"] or row["normalized_embedded_filename"]] == 1
        ),
        "unidentified_count": sum(1 for row in snapshot if not (row["identifier"] or row["normalized_embedded_filename"])),
        "duplicate_count": sum(
            1
            for row in snapshot
            if (row["identifier"] or row["normalized_embedded_filename"])
            and match_key_counts[row["identifier"] or row["normalized_embedded_filename"]] > 1
        ),
        "error_count": error_count,
    }
