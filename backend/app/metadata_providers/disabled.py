from app.metadata_providers.base import MetadataProvider, MetadataRecord
from app.services.identifier import normalize_identifier


class DisabledProvider(MetadataProvider):
    priority = 100
    timeout_seconds = 1.0
    max_retries = 0
    is_network_provider = False

    def lookup(self, identifier: str) -> MetadataRecord | None:
        normalized = normalize_identifier(identifier)
        if not normalized:
            return None
        return MetadataRecord(
            identifier=normalized,
            source=self.provider_name,
            confidence=0.0,
            status="disabled",
            error_message="Provider 第一版已禁用，不会请求外网",
        )


class JavbusProvider(DisabledProvider):
    provider_name = "javbus"
    priority = 101


class Jav321Provider(DisabledProvider):
    provider_name = "jav321"
    priority = 102


class DMMProvider(DisabledProvider):
    provider_name = "dmm"
    priority = 103


class MissAVProvider(DisabledProvider):
    provider_name = "missav"
    priority = 104


class ThePornDBProvider(DisabledProvider):
    provider_name = "theporndb"
    priority = 105
