from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from app.core.config import settings
from app.services.identifier import extract_identifier


def validate_nfo_tag_root(folder_path: str) -> Path:
    candidate = Path(folder_path).resolve()
    allowed_root = Path(settings.local_media_container_root).resolve()
    if not (candidate == allowed_root or allowed_root in candidate.parents):
        raise ValueError(f"folder_path 必须位于本地媒体目录下：{allowed_root}")
    if not candidate.exists():
        raise OSError(f"目录不存在：{candidate}")
    if not candidate.is_dir():
        raise OSError(f"不是目录：{candidate}")
    return candidate


def list_nfo_files(folder_path: str) -> list[Path]:
    root = validate_nfo_tag_root(folder_path)
    return sorted(path for path in root.rglob("*.nfo") if path.is_file())


def _text(root: ET.Element, tag: str) -> str | None:
    node = root.find(f".//{tag}")
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _unique_tags(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        folded = normalized.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        output.append(normalized)
    return output


def read_nfo_tag_record(path: Path) -> dict:
    root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    title = _text(root, "title")
    original_title = _text(root, "originaltitle")
    tags = _unique_tags(
        [node.text.strip() for node in root.findall(".//tag") if node.text and node.text.strip()]
        + [node.text.strip() for node in root.findall(".//genre") if node.text and node.text.strip()]
    )
    return {
        "file_path": str(path),
        "filename": path.name,
        "identifier": extract_identifier(path.name),
        "title": title,
        "originaltitle": original_title,
        "raw_tags": tags,
    }


def search_nfo_tag_records(folder_path: str, search_type: str, q: str) -> list[dict]:
    root = validate_nfo_tag_root(folder_path)
    term = q.strip().casefold()
    if not term:
        return []
    items: list[dict] = []
    for path in list_nfo_files(str(root)):
        try:
            record = read_nfo_tag_record(path)
        except (OSError, ET.ParseError, UnicodeDecodeError):
            continue
        if search_type == "title":
            haystacks = [record["title"] or "", record["originaltitle"] or "", record["filename"]]
            matched = any(term in value.casefold() for value in haystacks if value)
        else:
            matched = any(term in value.casefold() for value in record["raw_tags"])
        if matched:
            items.append(record)
    return items


def _ensure_child(root: ET.Element, tag: str) -> ET.Element:
    node = root.find(tag)
    if node is None:
        node = ET.SubElement(root, tag)
    return node


def ensure_nfo_tag_write_enabled() -> None:
    if settings.read_only_mode or not settings.enable_remote_write:
        raise PermissionError("当前仍是只读状态：写入 NFO 标签需要 READ_ONLY_MODE=false 且 ENABLE_REMOTE_WRITE=true")


def add_extra_tag_to_nfo_files(file_paths: list[str], tag_name: str) -> dict:
    ensure_nfo_tag_write_enabled()
    normalized_tag = tag_name.strip()
    if not normalized_tag:
        raise ValueError("tag_name 不能为空")

    matched_count = 0
    added_count = 0
    skipped_count = 0
    results: list[dict] = []

    for raw_path in file_paths:
        path = Path(raw_path).resolve()
        validate_nfo_tag_root(str(path.parent))
        if not path.exists() or not path.is_file() or path.suffix.lower() != ".nfo":
            results.append({"file_path": str(path), "status": "skipped", "error_message": "NFO 文件不存在"})
            skipped_count += 1
            continue

        matched_count += 1
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            existing_tags = _unique_tags(
                [node.text.strip() for node in root.findall(".//tag") if node.text and node.text.strip()]
                + [node.text.strip() for node in root.findall(".//genre") if node.text and node.text.strip()]
            )
            if any(value.casefold() == normalized_tag.casefold() for value in existing_tags):
                skipped_count += 1
                results.append({"file_path": str(path), "status": "skipped", "error_message": "标签已存在"})
                continue

            ET.SubElement(root, "tag").text = normalized_tag
            tree.write(path, encoding="utf-8", xml_declaration=True)
            added_count += 1
            results.append({"file_path": str(path), "status": "added", "error_message": None})
        except (OSError, ET.ParseError, UnicodeDecodeError) as exc:
            skipped_count += 1
            results.append({"file_path": str(path), "status": "skipped", "error_message": str(exc)})

    return {
        "matched_count": matched_count,
        "added_count": added_count,
        "skipped_count": skipped_count,
        "items": results,
    }
