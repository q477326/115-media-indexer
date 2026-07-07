import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from app.core.config import settings
from app.providers.base import FileMetadata, FileRef, Provider


class LocalFSProvider(Provider):
    VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".avi", ".wmv", ".mov", ".ts", ".m2ts"})

    @property
    def provider_name(self) -> str:
        return "local_fs"

    def validate_root(self, root_path: str) -> Path:
        root = Path(root_path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("扫描路径不是目录")
        if settings.allowed_scan_roots and not any(
            root == allowed or allowed in root.parents for allowed in settings.allowed_scan_roots
        ):
            raise ValueError("扫描路径不在允许的挂载目录内")
        return root

    def list_files(self, root_path_or_id: str) -> Iterable[FileRef]:
        root = self.validate_root(root_path_or_id)
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            files.sort()
            for filename in files:
                if Path(filename).suffix.lower() in self.VIDEO_EXTENSIONS:
                    yield FileRef(path=str(Path(current, filename)))

    def get_file_metadata(self, file: FileRef) -> FileMetadata:
        path = Path(file.path)
        stat = path.stat(follow_symlinks=False)
        if not path.is_file() or path.is_symlink():
            raise ValueError("仅索引普通文件")
        return FileMetadata(
            filename=path.name,
            path=str(path),
            local_path=str(path),
            size=stat.st_size,
            modified_time=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )
