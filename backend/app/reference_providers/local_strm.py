import os
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

from app.reference_providers.base import ReferenceFileMetadata, ReferenceFileRef, ReferenceProvider


class LocalSTRMReferenceProvider(ReferenceProvider):
    EXTENSION = ".strm"

    @property
    def provider_name(self) -> str:
        return "local_strm"

    def validate_root(self, root_path: str) -> Path:
        root = Path(root_path).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("reference root is not a directory")
        return root

    def list_files(self, root_path: str) -> Iterable[ReferenceFileRef]:
        root = self.validate_root(root_path)
        for current, dirs, files in os.walk(root, followlinks=False):
            dirs.sort()
            files.sort()
            for filename in files:
                if Path(filename).suffix.lower() == self.EXTENSION:
                    yield ReferenceFileRef(path=str(Path(current, filename)))

    def get_file_metadata(self, root_path: str, file: ReferenceFileRef) -> ReferenceFileMetadata:
        root = self.validate_root(root_path)
        path = Path(file.path).resolve(strict=True)
        if not path.is_file() or path.is_symlink():
            raise ValueError("reference item must be a regular file")
        if root != path and root not in path.parents:
            raise ValueError("reference item is outside reference root")

        stat = path.stat(follow_symlinks=False)
        relative_path = PurePosixPath(path.relative_to(root).as_posix()).as_posix()
        reference_dir = PurePosixPath(path.parent.relative_to(root).as_posix()).as_posix()
        if reference_dir == ".":
            reference_dir = ""
        return ReferenceFileMetadata(
            filename=path.name,
            reference_path=relative_path,
            reference_dir=reference_dir,
            ext=path.suffix.lower().lstrip("."),
            size=stat.st_size,
            modified_time=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )
