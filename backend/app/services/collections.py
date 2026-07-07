from collections import defaultdict
from datetime import date
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import MediaFile, MediaMetadata

CollectionKind = Literal["actor", "studio", "series"]


def _names(item: MediaMetadata, kind: CollectionKind) -> list[str]:
    if kind == "actor":
        return [name.strip() for name in (item.actors or []) if name.strip()]
    value = getattr(item, kind)
    return [value.strip()] if value and value.strip() else []


def list_collections(
    db: Session,
    kind: CollectionKind,
    q: str | None,
    sort_by: Literal["file_count", "latest_release_date"],
    sort_order: Literal["asc", "desc"],
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    file_counts = dict(db.execute(
        select(MediaFile.identifier, func.count(MediaFile.id))
        .where(MediaFile.identifier.is_not(None))
        .group_by(MediaFile.identifier)
    ).all())

    grouped: dict[str, dict] = defaultdict(lambda: {
        "file_count": 0,
        "identifiers": set(),
        "latest_release_date": None,
        "cover_url": None,
        "cover_date": None,
    })
    for item in db.scalars(select(MediaMetadata)):
        count = file_counts.get(item.identifier, 0)
        if count == 0:
            continue
        for name in dict.fromkeys(_names(item, kind)):
            state = grouped[name]
            state["file_count"] += count
            state["identifiers"].add(item.identifier)
            if item.release_date and (
                state["latest_release_date"] is None or item.release_date > state["latest_release_date"]
            ):
                state["latest_release_date"] = item.release_date
            if item.cover_url and (
                state["cover_url"] is None
                or (item.release_date is not None and (state["cover_date"] is None or item.release_date > state["cover_date"]))
            ):
                state["cover_url"] = item.cover_url
                state["cover_date"] = item.release_date

    key_name = kind
    items = [{
        key_name: name,
        "file_count": state["file_count"],
        "identifier_count": len(state["identifiers"]),
        "latest_release_date": state["latest_release_date"],
        "cover_url": state["cover_url"],
    } for name, state in grouped.items() if not q or q.casefold() in name.casefold()]

    items.sort(key=lambda item: item[key_name].casefold())
    reverse = sort_order == "desc"
    if sort_by == "file_count":
        items.sort(key=lambda item: item["file_count"], reverse=reverse)
    else:
        none_value = date.min if reverse else date.max
        items.sort(key=lambda item: item["latest_release_date"] or none_value, reverse=reverse)

    total = len(items)
    start = (page - 1) * page_size
    return items[start:start + page_size], total


def collection_files(
    db: Session,
    kind: CollectionKind,
    name: str,
    q: str | None,
    page: int,
    page_size: int,
) -> tuple[list[dict], int]:
    metadata_items = [item for item in db.scalars(select(MediaMetadata)) if name in _names(item, kind)]
    identifiers = [item.identifier for item in metadata_items]
    if not identifiers:
        return [], 0

    filters = [MediaFile.identifier.in_(identifiers)]
    if q:
        term = f"%{q}%"
        filters.append(or_(
            MediaFile.filename.ilike(term),
            MediaFile.path.ilike(term),
            MediaFile.identifier.ilike(term),
            MediaMetadata.title.ilike(term),
        ))
    base = (
        select(MediaFile, MediaMetadata)
        .join(MediaMetadata, MediaMetadata.identifier == MediaFile.identifier)
        .where(*filters)
    )
    total = db.scalar(
        select(func.count())
        .select_from(MediaFile)
        .join(MediaMetadata, MediaMetadata.identifier == MediaFile.identifier)
        .where(*filters)
    ) or 0
    rows = db.execute(
        base.order_by(MediaMetadata.release_date.desc(), MediaFile.filename.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    items = [{
        "id": file.id,
        "filename": file.filename,
        "path": file.path,
        "identifier": file.identifier,
        "title": metadata.title,
        "actors": metadata.actors or [],
        "studio": metadata.studio,
        "series": metadata.series,
        "size": file.size,
    } for file, metadata in rows]
    return items, total
