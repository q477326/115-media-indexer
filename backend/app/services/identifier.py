import re


IDENTIFIER_PATTERN = re.compile(r"(?<![A-Z0-9])([A-Z]{2,10})([\s._-]?)(\d{3,5})(?!\d)", re.IGNORECASE)
IDENTIFIER_EXACT_PATTERN = re.compile(r"^\s*([A-Z]{2,10})[\s._-]?(\d{3,5})\s*$", re.IGNORECASE)
NUMERIC_PREFIX_IDENTIFIER_PATTERN = re.compile(r"(?<![A-Z0-9])(\d{2,4}[A-Z]{2,10})([\s._-])(\d{2,5})(?!\d)", re.IGNORECASE)
NUMERIC_PREFIX_IDENTIFIER_EXACT_PATTERN = re.compile(r"^\s*(\d{2,4}[A-Z]{2,10})[\s._-](\d{2,5})\s*$", re.IGNORECASE)
DOMAIN_LIKE_PATTERN = re.compile(r"(?i)(?:^|[\\/])(?:www\.)?[a-z0-9-]+\.(?:com|net|org|me|la|tv|cc|xyz|info|jp|to|club)(?:[@._ -]|$)")


def _strip_extension(value: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,8}$", "", value)


def _domain_spans(value: str) -> list[tuple[int, int]]:
    return [match.span() for match in DOMAIN_LIKE_PATTERN.finditer(value)]


def _in_spans(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(start <= position < end for start, end in spans)


def _format_standard(match: re.Match) -> str:
    return f"{match.group(1).upper()}-{match.group(3)}"


def _format_numeric_prefix(match: re.Match) -> str:
    return f"{match.group(1).upper()}-{match.group(3)}"


def _candidates(value: str) -> list[tuple[int, int, str]]:
    domain_spans = _domain_spans(value)
    result: list[tuple[int, int, str]] = []
    for match in NUMERIC_PREFIX_IDENTIFIER_PATTERN.finditer(value):
        if not _in_spans(match.start(), domain_spans):
            separator_score = 0 if match.group(2) in {"-", "_", "."} else 1
            result.append((separator_score, match.start(), _format_numeric_prefix(match)))
    for match in IDENTIFIER_PATTERN.finditer(value):
        if not _in_spans(match.start(), domain_spans):
            separator_score = 0 if match.group(2) in {"-", "_", "."} else 1
            result.append((separator_score, match.start(), _format_standard(match)))
    result.sort(key=lambda item: (item[0], item[1]))
    return result


def extract_identifier(filename: str) -> str | None:
    basename = _strip_extension(filename)
    if "@" in basename:
        for segment in basename.split("@")[1:]:
            candidates = _candidates(segment)
            if candidates:
                return candidates[0][2]
    candidates = _candidates(basename)
    return candidates[0][2] if candidates else None


def normalize_identifier(value: str) -> str | None:
    numeric_match = NUMERIC_PREFIX_IDENTIFIER_EXACT_PATTERN.fullmatch(value)
    if numeric_match:
        return f"{numeric_match.group(1).upper()}-{numeric_match.group(2)}"
    match = IDENTIFIER_EXACT_PATTERN.fullmatch(value)
    if not match:
        return None
    return f"{match.group(1).upper()}-{match.group(2)}"
