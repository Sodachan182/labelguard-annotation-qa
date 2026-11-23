"""Shared parser helpers and safety limits."""

from __future__ import annotations

import hashlib
import math

MAX_ANNOTATION_BYTES = 256 * 1024 * 1024  # 256 MB per annotation file


class ParseError(ValueError):
    """Raised when a file cannot be interpreted as the declared format at all."""


def check_size(data: bytes, name: str) -> None:
    if len(data) > MAX_ANNOTATION_BYTES:
        raise ParseError(
            f"{name} is {len(data) / 1e6:.0f} MB; the limit is {MAX_ANNOTATION_BYTES / 1e6:.0f} MB per annotation file."
        )


def decode_text(data: bytes) -> str:
    """Decode annotation text tolerant of BOMs and legacy encodings."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def to_float(value: object, field: str, errors: list[str]) -> float:
    """Parse a coordinate. Invalid values become NaN and are reported, never dropped."""
    if value is None or value == "":
        errors.append(f"missing '{field}'")
        return math.nan
    if isinstance(value, bool):
        errors.append(f"'{field}' is a boolean ({value})")
        return math.nan
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        errors.append(f"'{field}' is not a number ({str(value)[:40]!r})")
        return math.nan
    if not math.isfinite(out):
        errors.append(f"'{field}' is not finite ({value})")
    return out


def to_bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def parse_point_string(text: str | None, errors: list[str]) -> list[list[float]]:
    """Parse CVAT ``"x1,y1;x2,y2"``. Malformed pairs are kept as NaN and reported."""
    if text is None or not text.strip():
        errors.append("missing 'points'")
        return []
    out: list[list[float]] = []
    for i, pair in enumerate(text.strip().split(";")):
        parts = pair.split(",")
        if len(parts) != 2:
            errors.append(f"point {i} is malformed ({pair[:40]!r})")
            out.append([math.nan, math.nan])
            continue
        out.append([to_float(parts[0], f"point {i} x", errors), to_float(parts[1], f"point {i} y", errors)])
    return out


def dataset_id_for(name: str, data: bytes) -> str:
    digest = hashlib.sha1(data, usedforsecurity=False).hexdigest()[:8]
    stem = "".join(ch if ch.isalnum() else "-" for ch in name.lower()).strip("-")[:32]
    return f"{stem or 'dataset'}-{digest}"


class IdAllocator:
    """Keep internal ids unique while remembering the id written in the source."""

    def __init__(self) -> None:
        self._seen: dict[str, int] = {}

    def allocate(self, source_id: str) -> str:
        n = self._seen.get(source_id, 0) + 1
        self._seen[source_id] = n
        return source_id if n == 1 else f"{source_id}~{n}"
