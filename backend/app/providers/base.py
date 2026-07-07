from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class FileRef:
    path: str


@dataclass(frozen=True)
class FileMetadata:
    filename: str
    path: str
    size: int
    modified_time: datetime | None = None
    provider_file_id: str | None = None
    local_path: str | None = None


class Provider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def list_files(self, root_path_or_id: str) -> Iterable[FileRef]: ...

    @abstractmethod
    def get_file_metadata(self, file: FileRef) -> FileMetadata: ...
