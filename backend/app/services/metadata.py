from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.metadata_providers import MetadataProvider, MetadataRecord
from app.models import MediaMetadata, MetadataProviderCache


def upsert_record(db: Session, record: MetadataRecord) -> tuple[MediaMetadata, bool]:
    item = db.scalar(select(MediaMetadata).where(MediaMetadata.identifier == record.identifier))
    created = item is None
    if item is None:
        item = MediaMetadata(identifier=record.identifier)
        db.add(item)
    if not item.title_locked:
        item.title = record.title
    if not item.plot_locked:
        item.plot = record.plot
    if not item.actors_locked:
        item.actors = record.actors
    if not item.studio_locked:
        item.studio = record.studio
    if not item.series_locked:
        item.series = record.series
    if not item.release_date_locked:
        item.release_date = record.release_date
    item.cover_url = record.cover_url
    item.title_locked = item.title_locked or record.title_locked
    item.plot_locked = item.plot_locked or record.plot_locked
    item.actors_locked = item.actors_locked or record.actors_locked
    item.studio_locked = item.studio_locked or record.studio_locked
    item.series_locked = item.series_locked or record.series_locked
    item.release_date_locked = item.release_date_locked or record.release_date_locked
    item.source = record.source
    item.confidence = record.confidence
    item.status = record.status
    return item, created


def import_provider(db: Session, provider: MetadataProvider) -> tuple[int, int]:
    records = getattr(provider, "_records", {})
    created_count = 0
    updated_count = 0
    for identifier in records:
        record = provider.lookup(identifier)
        if record is None:
            continue
        _, created = upsert_record(db, record)
        cached = db.scalar(select(MetadataProviderCache).where(
            MetadataProviderCache.provider == provider.provider_name,
            MetadataProviderCache.identifier == identifier,
        ))
        if cached is None:
            cached = MetadataProviderCache(provider=provider.provider_name, identifier=identifier)
            db.add(cached)
        payload = asdict(record)
        payload["release_date"] = record.release_date.isoformat() if record.release_date else None
        cached.payload = payload
        cached.confidence = record.confidence
        cached.status = "hit"
        created_count += int(created)
        updated_count += int(not created)
    db.commit()
    return created_count, updated_count
