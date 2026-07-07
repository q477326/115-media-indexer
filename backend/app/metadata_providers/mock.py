from app.metadata_providers.base import MetadataProvider, MetadataRecord
from app.services.identifier import normalize_identifier


class MockProvider(MetadataProvider):
    provider_name = "mock"
    priority = 90
    timeout_seconds = 1.0
    max_retries = 0
    is_network_provider = False

    def lookup(self, identifier: str) -> MetadataRecord | None:
        normalized = normalize_identifier(identifier)
        if not normalized:
            return None
        return MetadataRecord(
            identifier=normalized,
            title=f"Mock title for {normalized}",
            actors=["Mock Actor"],
            studio="Mock Studio",
            series="Mock Series",
            source="mock",
            confidence=0.1,
            status="mock",
        )
