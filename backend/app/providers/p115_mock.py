from typing import Iterable

from app.providers.base import FileMetadata, FileRef, Provider


class P115MockProvider(Provider):
    @property
    def provider_name(self) -> str:
        return "p115"

    def list_files(self, root_path_or_id: str) -> Iterable[FileRef]:
        raise NotImplementedError("p115 provider 第一阶段仅保留接口，不会连接 115")

    def get_file_metadata(self, file: FileRef) -> FileMetadata:
        raise NotImplementedError("p115 provider 第一阶段仅保留接口，不会连接 115")
