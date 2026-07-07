from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class MetadataRecord:
    identifier: str
    title: str | None = None
    plot: str | None = None
    actors: list[str] = field(default_factory=list)
    studio: str | None = None
    series: str | None = None
    release_date: date | None = None
    cover_url: str | None = None
    title_locked: bool = False
    plot_locked: bool = False
    actors_locked: bool = False
    studio_locked: bool = False
    series_locked: bool = False
    release_date_locked: bool = False
    source: str = "unknown"
    confidence: float = 0.0
    status: str = "partial"
    error_message: str | None = None


class MetadataProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def priority(self) -> int: ...

    @property
    @abstractmethod
    def timeout_seconds(self) -> float: ...

    @property
    @abstractmethod
    def max_retries(self) -> int: ...

    @property
    @abstractmethod
    def is_network_provider(self) -> bool: ...

    @abstractmethod
    def lookup(self, identifier: str) -> MetadataRecord | None: ...
