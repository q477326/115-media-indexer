from __future__ import annotations

import re
import shutil
from pathlib import Path, PurePosixPath

from app.core.config import settings
from app.services.cms_sync import cms_sync_configured, trigger_cms_sync
from app.services.organizer_execute import assert_real_move_enabled


VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".mov", ".wmv", ".flv"}
JUNK_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".txt", ".nfo", ".url", ".html", ".htm", ".srt", ".ass", ".ssa"}
JUNK_NAMES = {"thumbs.db", ".ds_store", "desktop.ini"}
SPLIT_PATTERNS = [r"-cd\d+$", r"-part\d+$", r"-disc\d+$", r"-\d+$"]
CODE_RE = re.compile(r"([A-Za-z]{2,10})[-_ ]?(\d{2,5})(?:\b|_)", re.IGNORECASE)
MIN_VIDEO_MB = 150


def _normalize_posix(path: str) -> str:
    return PurePosixPath(path.replace("\\", "/")).as_posix()


def validate_clouddrive_path(path: str, *, create_if_missing: bool = False) -> str:
    normalized = _normalize_posix(path).rstrip("/")
    prefix = PurePosixPath(settings.clouddrive_container_root).as_posix().rstrip("/") + "/"
    if normalized != prefix.rstrip("/") and not normalized.startswith(prefix):
        raise ValueError(f"path 必须位于 {prefix.rstrip('/')}")
    real = Path(normalized)
    if not real.exists():
        if create_if_missing:
            real.mkdir(parents=True, exist_ok=True)
        else:
            raise ValueError(f"path not found: {normalized}")
    if not real.is_dir():
        raise ValueError(f"path is not directory: {normalized}")
    return normalized


def clean_name(raw: str) -> str:
    name = raw.rsplit(".", 1)[0]
    if "@" in name:
        name = name.split("@", 1)[1]
    name = name.replace("_", "-").replace(" ", "-")
    name = re.sub(r"-{2,}", "-", name)
    return name.strip("-")


def extract_code(name: str) -> str | None:
    match = CODE_RE.search(name)
    if not match:
        return None
    prefix = match.group(1).upper()
    number = match.group(2).zfill(3)
    return f"{prefix}-{number}"


def detect_suffix_tags(name: str) -> list[str]:
    lower = name.lower()
    tags: list[str] = []
    if "4k" in lower:
        tags.append("4K")
    if "-c" in lower or lower.endswith("ch") or lower.endswith("-ch") or lower.endswith("_ch") or "字幕" in name:
        tags.append("C")
    if "uc" in lower:
        tags.append("UC")
    return tags


def detect_split_suffix(name: str) -> str:
    lower = name.lower()
    for pattern in SPLIT_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            suffix = match.group(0).lstrip("-").upper()
            code = extract_code(name)
            if code and suffix == code.split("-", 1)[1]:
                return ""
            return suffix
    return ""


def build_target_name(path: Path) -> str | None:
    cleaned = clean_name(path.name)
    code = extract_code(cleaned)
    if not code:
        return None
    tags = detect_suffix_tags(cleaned)
    split = detect_split_suffix(cleaned)
    parts = [code]
    if tags:
        parts.extend(tags)
    if split:
        parts.append(split)
    return "-".join(parts) + path.suffix.lower()


def is_junk_file(path: Path) -> bool:
    if path.name.lower() in JUNK_NAMES:
        return True
    if path.suffix.lower() in JUNK_EXTS:
        return True
    lower = path.name.lower()
    return "sample" in lower or "hhd800.com" in lower or "xhd1080" in lower


def is_small_video_junk(path: Path) -> bool:
    if path.suffix.lower() not in VIDEO_EXTS:
        return False
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except FileNotFoundError:
        return False
    return size_mb < MIN_VIDEO_MB


def scan_download_dir(root: str) -> dict:
    root_path = Path(root)
    rename_items: list[dict] = []
    move_items: list[dict] = []
    delete_items: list[str] = []
    remove_dirs: list[str] = []

    for path in root_path.rglob("*"):
        if path.is_file():
            if path.suffix.lower() in VIDEO_EXTS:
                if is_small_video_junk(path):
                    delete_items.append(str(path))
                    continue
                target_name = build_target_name(path)
                if target_name and target_name != path.name:
                    rename_items.append({
                        "path": str(path).replace("\\", "/"),
                        "target_name": target_name,
                        "target_path": str((root_path / target_name)).replace("\\", "/"),
                    })
                elif target_name and path.parent != root_path:
                    move_items.append({
                        "path": str(path).replace("\\", "/"),
                        "target_name": target_name,
                        "target_path": str((root_path / target_name)).replace("\\", "/"),
                    })
            elif is_junk_file(path):
                delete_items.append(str(path).replace("\\", "/"))

    for path in sorted(root_path.rglob("*"), reverse=True):
        if path.is_dir() and path != root_path:
            remove_dirs.append(str(path).replace("\\", "/"))

    return {
        "root": str(root_path).replace("\\", "/"),
        "rename_items": rename_items,
        "move_items": move_items,
        "delete_items": delete_items,
        "remove_dirs": remove_dirs,
    }


def apply_download_organize(root: str, remove_empty_dirs: bool = True) -> dict:
    root_path = Path(root)
    scan = scan_download_dir(root)
    renamed: list[dict] = []
    deleted: list[str] = []
    removed_dirs: list[str] = []
    conflicts: list[dict] = []

    parsed_selected: list[tuple[str, str]] = []
    for item in [*scan["rename_items"], *scan["move_items"]]:
        parsed_selected.append((item["path"], item["target_name"]))

    for src, target_name in parsed_selected:
        src_path = Path(src)
        dst_path = root_path / target_name
        if src_path.exists() and src_path != dst_path:
            if dst_path.exists():
                conflicts.append({"from": src.replace("\\", "/"), "to": str(dst_path).replace("\\", "/")})
                continue
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src_path), str(dst_path))
            renamed.append({"from": src.replace("\\", "/"), "to": str(dst_path).replace("\\", "/")})

    for raw in scan["delete_items"]:
        path = Path(raw)
        if path.exists() and path.is_file():
            path.unlink()
            deleted.append(raw)

    if remove_empty_dirs:
        changed = True
        while changed:
            changed = False
            for path in sorted(root_path.rglob("*"), reverse=True):
                if path.is_dir() and path != root_path:
                    try:
                        next(path.iterdir())
                    except StopIteration:
                        path.rmdir()
                        removed_dirs.append(str(path).replace("\\", "/"))
                        changed = True

    return {
        "root": str(root_path).replace("\\", "/"),
        "renamed": renamed,
        "deleted": deleted,
        "removed_dirs": removed_dirs,
        "conflicts": conflicts,
        "rename_count": len(renamed),
        "delete_count": len(deleted),
        "dir_cleanup_count": len(removed_dirs),
        "conflict_count": len(conflicts),
    }


def move_all_videos(source_root: str, target_root: str) -> dict:
    source_path = Path(source_root)
    target_path = Path(target_root)
    target_path.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    moved = 0
    failed = 0

    for path in source_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        dst = target_path / path.name
        if dst.exists():
            results.append({
                "ok": False,
                "file": path.name,
                "from": str(path).replace("\\", "/"),
                "to": str(dst).replace("\\", "/"),
                "error": "target already exists",
            })
            failed += 1
            continue
        try:
            shutil.move(str(path), str(dst))
            results.append({
                "ok": True,
                "file": path.name,
                "from": str(path).replace("\\", "/"),
                "to": str(dst).replace("\\", "/"),
            })
            moved += 1
        except Exception as exc:
            results.append({
                "ok": False,
                "file": path.name,
                "from": str(path).replace("\\", "/"),
                "to": str(dst).replace("\\", "/"),
                "error": str(exc),
            })
            failed += 1

    return {
        "source_root": str(source_path).replace("\\", "/"),
        "target_root": str(target_path).replace("\\", "/"),
        "moved_count": moved,
        "failed_count": failed,
        "items": results,
    }


def one_click_ingest(source_root: str, output_root: str) -> dict:
    assert_real_move_enabled()
    source_root = validate_clouddrive_path(source_root)
    output_root = validate_clouddrive_path(output_root, create_if_missing=True)

    organize_preview = scan_download_dir(source_root)
    organize_result = apply_download_organize(source_root, remove_empty_dirs=True)
    move_result = move_all_videos(source_root, output_root)
    cms_result = None
    if cms_sync_configured():
        cms_result = trigger_cms_sync()
    return {
        "source_root": source_root,
        "output_root": output_root,
        "preview": {
            "rename_count": len(organize_preview["rename_items"]),
            "move_to_root_count": len(organize_preview["move_items"]),
            "delete_count": len(organize_preview["delete_items"]),
            "remove_dir_count": len(organize_preview["remove_dirs"]),
        },
        "organize": organize_result,
        "move": move_result,
        "cms_sync": cms_result,
    }
