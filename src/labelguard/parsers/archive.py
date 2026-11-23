"""Format detection, safe ZIP extraction and image discovery.

ZIP safety: every member name is checked before anything is written. Absolute
paths, drive letters, ``..`` segments, symlinks, excessive member counts,
excessive total size and suspicious compression ratios (zip bombs) are refused.
Extraction happens into a fresh temporary directory; user files are never
modified in place.
"""

from __future__ import annotations

import json
import stat
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from labelguard.models import Dataset, SourceFormat
from labelguard.parsers.bdd100k import _records, dataset_from_records, looks_like_bdd
from labelguard.parsers.coco_json import parse_coco_json
from labelguard.parsers.common import ParseError, check_size, decode_text
from labelguard.parsers.cvat_xml import parse_cvat_xml

MAX_ZIP_MEMBERS = 50_000
MAX_ZIP_TOTAL_BYTES = 4 * 1024**3  # 4 GB uncompressed
MAX_COMPRESSION_RATIO = 250
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}


class UnsafeArchiveError(ParseError):
    pass


def _check_member(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename.replace("\\", "/")
    path = PurePosixPath(name)
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        raise UnsafeArchiveError(f"Archive member has an absolute path: {name!r}")
    if any(part == ".." for part in path.parts):
        raise UnsafeArchiveError(f"Archive member escapes the extraction folder: {name!r}")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise UnsafeArchiveError(f"Archive member is a symbolic link: {name!r}")
    return path


def safe_extract(zip_path: str | Path, dest: str | Path) -> Path:
    """Validate every member, then extract. Raises before writing anything unsafe."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zip_path) as zf:
        infos = zf.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise UnsafeArchiveError(f"Archive has {len(infos)} members (limit {MAX_ZIP_MEMBERS}).")
        total = 0
        checked: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
        for info in infos:
            rel = _check_member(info)
            total += info.file_size
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise UnsafeArchiveError(f"Archive member {info.filename!r} has a suspicious compression ratio.")
            checked.append((info, rel))
        if total > MAX_ZIP_TOTAL_BYTES:
            raise UnsafeArchiveError(
                f"Archive expands to {total / 1e9:.1f} GB (limit {MAX_ZIP_TOTAL_BYTES / 1e9:.0f} GB)."
            )
        for info, rel in checked:
            target = (dest / Path(*rel.parts)).resolve()
            if dest not in target.parents and target != dest:
                raise UnsafeArchiveError(f"Archive member escapes the extraction folder: {rel}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                written = 0
                while chunk := src.read(1 << 20):
                    written += len(chunk)
                    if written > info.file_size:
                        raise UnsafeArchiveError(f"Archive member {rel} is larger than declared.")
                    out.write(chunk)
    return dest


def detect_format(data: bytes) -> str:
    head = data[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    if head.startswith(b"<"):
        return "cvat_xml"
    if head.startswith((b"{", b"[")):
        return "coco_json"  # any JSON; classify_json() decides COCO vs BDD100K
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = data[:4096].decode("utf-16", errors="ignore").lstrip()
        return "cvat_xml" if text.startswith("<") else "coco_json"
    raise ParseError("Unrecognised file: expected CVAT XML or COCO JSON.")


def classify_json(data: bytes) -> tuple[str, Any]:
    """Return ('coco_json' | 'bdd100k_json' | 'other', parsed document)."""
    try:
        doc = json.loads(decode_text(data))
    except json.JSONDecodeError as exc:
        raise ParseError(f"not valid JSON ({exc.msg} at line {exc.lineno}).") from exc
    if looks_like_bdd(doc):
        return "bdd100k_json", doc
    if isinstance(doc, dict) and "annotations" in doc:
        return "coco_json", doc
    if isinstance(doc, dict) and isinstance(doc.get("images"), list) and doc["images"]:
        first = doc["images"][0]
        if isinstance(first, dict) and "id" in first and "file_name" in first:
            return "coco_json", doc
    return "other", doc
    return "other", doc


def parse_bytes(data: bytes, name: str, image_lookup: Callable[[str], Path | None] | None = None) -> Dataset:
    if detect_format(data) == "cvat_xml":
        return parse_cvat_xml(data, name)
    check_size(data, name)
    kind, doc = classify_json(data)
    if kind == "bdd100k_json":
        return dataset_from_records(_records(doc), name, data=data, image_lookup=image_lookup)
    if kind == "coco_json":
        return parse_coco_json(data, name)
    raise ParseError(f"{name}: JSON is neither COCO instances nor BDD100K / Scalabel labels.")


@dataclass
class LoadResult:
    datasets: list[Dataset] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    root: Path | None = None
    image_files: int = 0


def _image_index(root: Path) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES:
            rel = p.relative_to(root).as_posix().lower()
            for key in (rel, p.name.lower(), p.stem.lower()):
                index.setdefault(key, p)
    return index


def attach_images(ds: Dataset, root: Path, index: dict[str, Path] | None = None) -> int:
    """Map image records to pixel files under ``root`` by path, name or stem."""
    index = index if index is not None else _image_index(root)
    found = 0
    for img in ds.images:
        fn = img.file_name.replace("\\", "/").lower()
        for key in (fn, PurePosixPath(fn).name, PurePosixPath(fn).stem):
            if key and key in index:
                ds.image_paths[img.id] = str(index[key])
                found += 1
                break
    ds.metadata["images_supplied"] = bool(index)
    return found


def _annotation_candidates(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in (".xml", ".json"):
            continue
        if any(part.startswith(("__MACOSX", ".")) for part in p.relative_to(root).parts):
            continue
        out.append(p)
    return out


def load_directory(root: str | Path, images_dir: str | Path | None = None) -> LoadResult:
    root = Path(root)
    result = LoadResult(root=root)
    index = _image_index(Path(images_dir) if images_dir else root)
    result.image_files = len({str(p) for p in index.values()})

    def lookup(fname: str) -> Path | None:
        fn = fname.replace("\\", "/").lower()
        for key in (fn, PurePosixPath(fn).name, PurePosixPath(fn).stem):
            if key in index:
                return index[key]
        return None

    # BDD100K ships one label file per image; group those by folder into one dataset.
    per_image: dict[Path, list[dict]] = {}
    for path in _annotation_candidates(root):
        rel = path.relative_to(root).as_posix()
        data = path.read_bytes()
        try:
            kind = detect_format(data)
            if kind == "cvat_xml":
                ds = parse_cvat_xml(data, rel)
            else:
                kind, doc = classify_json(data)
                if kind == "other":
                    continue  # unrelated JSON such as a provenance manifest
                if kind == "bdd100k_json" and isinstance(doc, dict) and "name" in doc:
                    per_image.setdefault(path.parent, []).append(doc)
                    continue
                ds = parse_bytes(data, rel, image_lookup=lookup)
        except ParseError as exc:
            result.errors.append(f"{rel}: {exc}" if rel not in str(exc) else str(exc))
            continue
        if ds.source_format != SourceFormat.BDD100K:
            attach_images(ds, root, index)
        result.datasets.append(ds)
    for folder, records in per_image.items():
        rel = folder.relative_to(root).as_posix() if folder != root else root.name
        records.sort(key=lambda r: str(r.get("name", "")))
        result.datasets.append(dataset_from_records(records, f"{rel}/ (per-image labels)", image_lookup=lookup))
    if not result.datasets and not result.errors:
        result.errors.append("No CVAT XML, COCO JSON or BDD100K JSON annotation file was found.")
    return result


def load_path(path: str | Path, workdir: str | Path | None = None, images_dir: str | Path | None = None) -> LoadResult:
    """Load a single annotation file, a directory or a ZIP archive.

    `images_dir` overrides where image files are looked up (default: next to the labels).
    """
    path = Path(path)
    if path.is_dir():
        return load_directory(path, images_dir)
    if path.suffix.lower() == ".zip":
        dest = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="labelguard-"))
        dest.mkdir(parents=True, exist_ok=True)
        try:
            safe_extract(path, dest)
        except (zipfile.BadZipFile, UnsafeArchiveError) as exc:
            return LoadResult(errors=[f"{path.name}: {exc}"])
        result = load_directory(dest)
        for ds in result.datasets:
            ds.metadata["archive"] = path.name
        return result
    result = LoadResult(root=path.parent)
    # A lone annotation file: look for an exported images/ folder next to it
    # (CVAT / BDD layout) or one level up (COCO layout) instead of crawling the disk.
    if images_dir is None:
        images_dir = next((c for c in (path.parent / "images", path.parent.parent / "images") if c.is_dir()), None)
    images_dir = Path(images_dir) if images_dir else None
    index = _image_index(images_dir) if images_dir else {}

    def lookup(fname: str) -> Path | None:
        fn = fname.replace("\\", "/").lower()
        return next((index[k] for k in (fn, PurePosixPath(fn).name) if k in index), None)

    try:
        ds = parse_bytes(path.read_bytes(), path.name, image_lookup=lookup if index else None)
    except ParseError as exc:
        result.errors.append(str(exc))
        return result
    if images_dir and ds.source_format != SourceFormat.BDD100K:
        attach_images(ds, images_dir, index)
    result.datasets.append(ds)
    return result
