from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Iterable

from app.core.config import settings

DEFAULT_STATE_FILE = Path("/data/western-poster-state.json")


def validate_western_poster_root(folder_path: str) -> Path:
    candidate = Path(folder_path).resolve()
    allowed_root = Path(settings.local_media_container_root).resolve()
    if not (candidate == allowed_root or allowed_root in candidate.parents):
        raise ValueError(f"root 必须位于本地媒体目录下：{allowed_root}")
    if not candidate.exists():
        raise OSError(f"目录不存在：{candidate}")
    if not candidate.is_dir():
        raise OSError(f"不是目录：{candidate}")
    return candidate


def ensure_western_poster_write_enabled() -> None:
    if settings.read_only_mode or not settings.enable_remote_write:
        raise PermissionError("当前仍是只读状态：写入 poster/fanart 需要 READ_ONLY_MODE=false 且 ENABLE_REMOTE_WRITE=true")


def resolve_state_file(state_file: str | None) -> Path:
    if not state_file:
        return DEFAULT_STATE_FILE
    path = Path(state_file)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def iter_candidate_dirs(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir() and (path / "thumb.jpg").exists():
            yield path


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"processed": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"processed": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_once(file: Path) -> None:
    bak = file.with_name(f"{file.name}.bak")
    if file.exists() and not bak.exists():
        shutil.copy2(file, bak)


def process_dir(path: Path, *, dry_run: bool = False) -> bool:
    thumb = path / "thumb.jpg"
    if not thumb.exists():
        return False

    if dry_run:
        return True

    poster_jpg = path / "poster.jpg"
    poster_jpeg = path / "poster.jpeg"
    poster_png = path / "poster.png"
    fanart = path / "fanart.jpg"

    for item in (poster_jpg, poster_jpeg, poster_png, fanart):
        backup_once(item)

    shutil.copy2(thumb, poster_jpg)
    if poster_jpeg.exists():
        poster_jpeg.unlink()
    if poster_png.exists():
        poster_png.unlink()
    shutil.copy2(thumb, fanart)
    return True


def run_western_poster_fix(
    *,
    root: str,
    state_file: str | None = None,
    process_all: bool = False,
    dry_run: bool = True,
) -> dict[str, object]:
    root_path = validate_western_poster_root(root)
    state_path = resolve_state_file(state_file)

    if not dry_run:
        ensure_western_poster_write_enabled()

    state = load_state(state_path)
    processed_state = state.setdefault("processed", {})

    processed = 0
    skipped = 0
    dry_run_count = 0
    touched: list[str] = []

    for folder in iter_candidate_dirs(root_path):
        key = str(folder)
        thumb = folder / "thumb.jpg"
        marker = str(thumb.stat().st_mtime_ns)
        if not process_all and processed_state.get(key) == marker:
            skipped += 1
            continue

        changed = process_dir(folder, dry_run=dry_run)
        if not changed:
            skipped += 1
            continue

        touched.append(str(folder))
        if dry_run:
            dry_run_count += 1
        else:
            processed_state[key] = marker
            processed += 1

    if not dry_run:
        save_state(state_path, state)

    return {
        "root": str(root_path),
        "state_file": str(state_path),
        "processed": processed,
        "skipped": skipped,
        "dry_run": dry_run_count,
        "touched": touched[:200],
        "process_all": process_all,
        "dry_run_mode": dry_run,
    }
