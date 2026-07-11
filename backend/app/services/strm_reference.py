from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote


def read_strm_content(path: str) -> str | None:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text.strip() or None


def extract_embedded_filename(strm_content: str | None) -> tuple[str | None, str | None]:
    if not strm_content:
        return None, None
    first_line = strm_content.splitlines()[0].strip().lstrip("\ufeff")
    if not first_line:
        return None, None
    embedded = None
    if "?/" in first_line:
        embedded = first_line.split("?/", 1)[1].strip()
    if embedded:
        embedded = unquote(embedded).strip()
    return first_line, embedded or None


def normalize_embedded_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    normalized = unquote(filename).strip().casefold()
    if not normalized:
        return None
    # Download clients commonly add " (1)", " (2)" … before the extension
    # when the same original file is saved twice. This is not part of the
    # CMS/STRM embedded filename and may be ignored for exact link matching.
    normalized = re.sub(r"\s*\(\d+\)(?=\.[^.]+$)", "", normalized)
    normalized = normalized.replace("[", " ").replace("]", " ")
    normalized = normalized.replace("(", " ").replace(")", " ")
    normalized = re.sub(r"[._]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip()
    return normalized or None
