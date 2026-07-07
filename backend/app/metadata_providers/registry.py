from app.core.config import settings
from app.metadata_providers.disabled import DMMProvider, Jav321Provider, JavbusProvider, MissAVProvider, ThePornDBProvider
from app.metadata_providers.local_db import LocalDBProvider
from app.metadata_providers.local_nfo import LocalNFOProvider
from app.metadata_providers.manual_csv import ManualCSVProvider
from app.metadata_providers.reference_metadata import ReferenceMetadataProvider


PROVIDER_TYPES = (
    LocalDBProvider,
    ReferenceMetadataProvider,
    LocalNFOProvider,
    ManualCSVProvider,
    JavbusProvider,
    Jav321Provider,
    DMMProvider,
    MissAVProvider,
    ThePornDBProvider,
)
ALLOWED_OFFLINE_PROVIDERS = {provider.provider_name for provider in PROVIDER_TYPES}


def provider_registry() -> dict[str, type]:
    return {provider.provider_name: provider for provider in PROVIDER_TYPES}


def create_providers(names: list[str]):
    registry = provider_registry()
    unknown = set(names) - set(registry)
    if unknown:
        raise ValueError(f"未知 metadata provider: {', '.join(sorted(unknown))}")
    return sorted((registry[name]() for name in names), key=lambda provider: provider.priority)


def validate_provider_registry(provider_types=PROVIDER_TYPES) -> None:
    if settings.enable_external_metadata:
        return
    for provider in provider_types:
        if provider.provider_name not in ALLOWED_OFFLINE_PROVIDERS or provider.is_network_provider:
            raise RuntimeError(
                f"ENABLE_EXTERNAL_METADATA=false 时禁止注册网络 Provider: {provider.provider_name}"
            )
