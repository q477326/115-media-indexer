import csv
import io
import json
import re
from datetime import date

from sqlalchemy import select

from app.core.database import SessionLocal
from app.metadata_providers.base import MetadataProvider, MetadataRecord
from app.models import MediaMetadata, MetadataProviderCache
from app.services.identifier import normalize_identifier


class ManualCSVProvider(MetadataProvider):
    REQUIRED_COLUMNS = {"identifier", "title", "actors", "studio", "series", "release_date", "cover_url"}
    provider_name = "manual_csv"
    priority = 20
    timeout_seconds = 2.0
    max_retries = 0
    is_network_provider = False

    def __init__(self, records: dict[str, MetadataRecord] | None = None):
        self._records = records or {}

    def lookup(self, identifier: str) -> MetadataRecord | None:
        normalized = normalize_identifier(identifier)
        if not normalized:
            return None
        record = self._records.get(normalized)
        if record is not None:
            return record
        with SessionLocal() as db:
            cached = db.scalar(select(MetadataProviderCache).where(
                MetadataProviderCache.provider == self.provider_name,
                MetadataProviderCache.identifier == normalized,
                MetadataProviderCache.status == "hit",
            ))
            if cached and cached.payload:
                payload = dict(cached.payload)
                if payload.get("release_date"):
                    payload["release_date"] = date.fromisoformat(payload["release_date"])
                return MetadataRecord(**payload)
            item = db.scalar(select(MediaMetadata).where(
                MediaMetadata.identifier == normalized,
                MediaMetadata.source == self.provider_name,
            ))
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
                source=self.provider_name,
                confidence=item.confidence,
                status=item.status,
            )

    @classmethod
    def from_csv(cls, content: str) -> tuple["ManualCSVProvider", list[dict[str, str | int]]]:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")))
        columns = set(reader.fieldnames or [])
        missing = cls.REQUIRED_COLUMNS - columns
        if missing:
            raise ValueError(f"CSV 缺少字段: {', '.join(sorted(missing))}")

        records: dict[str, MetadataRecord] = {}
        errors: list[dict[str, str | int]] = []
        for line_number, row in enumerate(reader, start=2):
            try:
                identifier = normalize_identifier(row.get("identifier", ""))
                if not identifier:
                    raise ValueError("番号格式无效")
                release_date = cls._parse_date(row.get("release_date", ""))
                actors = cls._parse_actors(row.get("actors", ""))
                title = cls._clean(row.get("title"))
                records[identifier] = MetadataRecord(
                    identifier=identifier,
                    title=title,
                    plot=cls._clean(row.get("plot")),
                    actors=actors,
                    studio=cls._clean(row.get("studio")),
                    series=cls._clean(row.get("series")),
                    release_date=release_date,
                    cover_url=cls._clean(row.get("cover_url")),
                    source="manual_csv",
                    confidence=1.0,
                    status="complete" if title else "partial",
                )
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append({"line": line_number, "error": str(exc)})
        return cls(records), errors

    @staticmethod
    def _clean(value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @staticmethod
    def _parse_date(value: str) -> date | None:
        value = value.strip()
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("发行日期必须使用 YYYY-MM-DD") from exc

    @staticmethod
    def _parse_actors(value: str) -> list[str]:
        value = value.strip()
        if not value:
            return []
        if value.startswith("["):
            parsed = json.loads(value)
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                raise ValueError("actors JSON 必须是字符串数组")
            return list(dict.fromkeys(item.strip() for item in parsed if item.strip()))
        return list(dict.fromkeys(item.strip() for item in re.split(r"[|,;/、]", value) if item.strip()))
