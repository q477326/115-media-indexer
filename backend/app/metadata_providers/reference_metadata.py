import re
from pathlib import Path

from sqlalchemy import select

from app.core.database import SessionLocal
from app.metadata_providers.base import MetadataProvider, MetadataRecord
from app.models import ReferenceItem
from app.services.identifier import normalize_identifier


def split_actor_names(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[,，/&、]", value) if item.strip()]


class ReferenceMetadataProvider(MetadataProvider):
    provider_name = "reference_metadata"
    priority = 15
    timeout_seconds = 2.0
    max_retries = 0
    is_network_provider = False

    def lookup(self, identifier: str) -> MetadataRecord | None:
        normalized = normalize_identifier(identifier)
        if not normalized:
            return None
        with SessionLocal() as db:
            items = db.scalars(
                select(ReferenceItem)
                .where(
                    ReferenceItem.identifier == normalized,
                    ReferenceItem.status == "identified",
                )
                .order_by(ReferenceItem.id.asc())
            ).all()
            if len(items) != 1:
                return None

            item = items[0]
            actor_names = self._extract_actors(item.reference_dir, normalized)
            return MetadataRecord(
                identifier=normalized,
                actors=actor_names,
                source=self.provider_name,
                confidence=0.55 if actor_names else 0.4,
                status="partial",
            )

    @staticmethod
    def _extract_actors(reference_dir: str, identifier: str) -> list[str]:
        parts = [part for part in Path(reference_dir).as_posix().split("/") if part]
        if len(parts) < 2:
            return []
        tail = parts[-1].strip().upper()
        if tail != identifier.upper():
            return []
        return split_actor_names(parts[-2])
