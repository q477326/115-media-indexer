from collections import Counter

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import ReferenceItem, ReferenceSource
from app.reference_providers import LocalSTRMReferenceProvider, ReferenceProvider
from app.services.identifier import extract_identifier


def get_reference_provider(provider_type: str) -> ReferenceProvider:
    if provider_type == "local_strm":
        return LocalSTRMReferenceProvider()
    raise ValueError(f"unsupported reference provider: {provider_type}")


def _collect_snapshot(source: ReferenceSource) -> tuple[list[dict], int]:
    provider = get_reference_provider(source.provider_type)
    provider.validate_root(source.root_path)  # type: ignore[attr-defined]

    snapshot: list[dict] = []
    error_count = 0
    for file_ref in provider.list_files(source.root_path):
        try:
            metadata = provider.get_file_metadata(source.root_path, file_ref)
            identifier = extract_identifier(metadata.filename) or extract_identifier(metadata.reference_path)
            snapshot.append({
                "identifier": identifier,
                "reference_path": metadata.reference_path,
                "reference_dir": metadata.reference_dir,
                "filename": metadata.filename,
                "ext": metadata.ext,
                "size": metadata.size,
                "modified_time": metadata.modified_time,
            })
        except (OSError, ValueError):
            error_count += 1
    return snapshot, error_count


def scan_reference_source(db: Session, source: ReferenceSource) -> dict[str, int]:
    snapshot, error_count = _collect_snapshot(source)
    identifier_counts: Counter[str] = Counter(
        row["identifier"] for row in snapshot if row["identifier"]
    )
    existing_items = db.scalars(
        select(ReferenceItem).where(ReferenceItem.source_id == source.id)
    ).all()
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
        item.size = row["size"]
        item.modified_time = row["modified_time"]
        if not row["identifier"]:
            item.status = "unidentified"
        elif identifier_counts[row["identifier"]] > 1:
            item.status = "duplicate"
        else:
            item.status = "identified"

    for item in existing_items:
        if item.reference_path not in seen_paths:
            db.delete(item)

    db.commit()
    return {
        "scanned_count": len(snapshot),
        "identified_count": sum(1 for row in snapshot if row["identifier"] and identifier_counts[row["identifier"]] == 1),
        "unidentified_count": sum(1 for row in snapshot if not row["identifier"]),
        "duplicate_count": sum(1 for row in snapshot if row["identifier"] and identifier_counts[row["identifier"]] > 1),
        "error_count": error_count,
    }
