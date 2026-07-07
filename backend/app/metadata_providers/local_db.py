from sqlalchemy import select

from app.core.database import SessionLocal
from app.metadata_providers.base import MetadataProvider, MetadataRecord
from app.models import MediaMetadata
from app.services.identifier import normalize_identifier


class LocalDBProvider(MetadataProvider):
    provider_name = "local_db"
    priority = 10
    timeout_seconds = 2.0
    max_retries = 0
    is_network_provider = False

    def lookup(self, identifier: str) -> MetadataRecord | None:
        normalized = normalize_identifier(identifier)
        if not normalized:
            return None
        with SessionLocal() as db:
            item = db.scalar(select(MediaMetadata).where(MediaMetadata.identifier == normalized))
            if item is None:
                return None
            return MetadataRecord(
                identifier=item.identifier,
                title=item.title,
                plot=item.plot,
                actors=list(item.actors or []),
                studio=item.studio,
                series=item.series,
                release_date=item.release_date,
                cover_url=item.cover_url,
                title_locked=item.title_locked,
                plot_locked=item.plot_locked,
                actors_locked=item.actors_locked,
                studio_locked=item.studio_locked,
                series_locked=item.series_locked,
                release_date_locked=item.release_date_locked,
                source=item.source,
                confidence=item.confidence,
                status=item.status,
            )
