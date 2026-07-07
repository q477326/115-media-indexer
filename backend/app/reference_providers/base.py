from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class ReferenceFileRef:
    path: str


@dataclass(frozen=True)
class ReferenceFileMetadata:
    filename: str
    reference_path: str
    reference_dir: str
    ext: str
    size: int
    modified_time: datetime | None = None


class ReferenceProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def list_files(self, root_path: str) -> Iterable[ReferenceFileRef]: ...

    @abstractmethod
    def get_file_metadata(self, root_path: str, file: ReferenceFileRef) -> ReferenceFileMetadata: ...
