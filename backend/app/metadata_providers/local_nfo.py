from datetime import date
from pathlib import Path
import xml.etree.ElementTree as ET

from sqlalchemy import select

from app.core.database import SessionLocal
from app.metadata_providers.base import MetadataProvider, MetadataRecord
from app.models import ReferenceItem, ReferenceSource
from app.services.identifier import normalize_identifier
from app.metadata_providers.reference_metadata import split_actor_names


class LocalNFOProvider(MetadataProvider):
    provider_name = "local_nfo"
    priority = 16
    timeout_seconds = 3.0
    max_retries = 0
    is_network_provider = False

    def lookup(self, identifier: str) -> MetadataRecord | None:
        normalized = normalize_identifier(identifier)
        if not normalized:
            return None
        with SessionLocal() as db:
            item = db.scalar(
                select(ReferenceItem)
                .where(
                    ReferenceItem.identifier == normalized,
                    ReferenceItem.status == "identified",
                )
                .order_by(ReferenceItem.id.asc())
            )
            if item is None:
                return None
            source = db.get(ReferenceSource, item.source_id)
            if source is None:
                return None
            nfo_path = self._find_nfo(Path(source.root_path), item.reference_dir, normalized)
            if nfo_path is None:
                return None
            return self._parse_nfo(nfo_path, normalized)

    @staticmethod
    def _find_nfo(root: Path, reference_dir: str, identifier: str) -> Path | None:
        target_dir = root / Path(reference_dir)
        if not target_dir.is_dir():
            return None
        preferred = target_dir / f"{identifier}.nfo"
        if preferred.is_file():
            return preferred
        candidates = sorted(target_dir.glob("*.nfo"))
        return candidates[0] if candidates else None

    @staticmethod
    def _parse_nfo(path: Path, identifier: str) -> MetadataRecord | None:
        try:
            root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
        except (OSError, ET.ParseError, UnicodeDecodeError):
            return None

        title = LocalNFOProvider._text(root, "title")
        plot = LocalNFOProvider._text(root, "plot")
        studio = LocalNFOProvider._text(root, "studio")
        series = LocalNFOProvider._text(root, "set") or LocalNFOProvider._text(root, "series")
        release_date = LocalNFOProvider._parse_date(
            LocalNFOProvider._text(root, "premiered")
            or LocalNFOProvider._text(root, "release")
            or LocalNFOProvider._text(root, "releasedate")
        )
        actors = LocalNFOProvider._actors(root)
        thumb = LocalNFOProvider._text(root, "thumb")
        return MetadataRecord(
            identifier=identifier,
            title=title,
            plot=plot,
            actors=actors,
            studio=studio,
            series=series,
            release_date=release_date,
            cover_url=thumb,
            source="local_nfo",
            confidence=0.9,
            status="complete" if title else "partial",
        )

    @staticmethod
    def _text(root: ET.Element, tag: str) -> str | None:
        node = root.find(f".//{tag}")
        if node is None or node.text is None:
            return None
        text = node.text.strip()
        return text or None

    @staticmethod
    def _actors(root: ET.Element) -> list[str]:
        names = []
        for actor in root.findall(".//actor"):
            name = LocalNFOProvider._text(actor, "name")
            if name:
                names.extend(split_actor_names(name))
        if names:
            return list(dict.fromkeys(names))
        actor_text = LocalNFOProvider._text(root, "actors")
        if actor_text:
            return split_actor_names(actor_text)
        return []

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        text = value.strip()[:10]
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
