"""Native BDD100K / Scalabel detection label adapter.

Accepted layouts (all are JSON):

* a single per-image record ``{"name", "attributes", "frames": [{"objects": [...]}]}``
  (the per-image files inside ``bdd100k_labels.zip``);
* a list of image records ``[{"name", "attributes", "labels": [...]}, ...]``
  (``bdd100k_labels_images_val.json`` and Detection 2020 ``det_val.json``);
* a Scalabel dataset ``{"frames": [...], "config": {...}}``.

Coordinate convention — documented by BDD100K and implemented in Scalabel's
``box2d_to_bbox``: ``box2d`` corners are **inclusive pixel indices**, so

    width  = x2 − x1 + 1
    height = y2 − y1 + 1

LabelGuard stores boxes as continuous corners, therefore
``bbox = [x1, y1, x2 + 1, y2 + 1]`` while ``bbox_source`` keeps the original
``[x1, y1, x2, y2]``. A box with ``x2 == x1`` is one pixel wide, not empty.

BDD100K label files carry no image size. The size is read from the image file
header when the image is supplied; otherwise the documented BDD100K resolution
(1280 × 720) is used and recorded as an assumption on the image record.

``poly2d`` objects (lane markings ``lane/*`` and drivable areas ``area/*``) are
outside the detection scope. They are counted and reported, never dropped
silently.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from labelguard.models import (
    Annotation,
    AttributeSpec,
    Category,
    Dataset,
    GeometryType,
    ImageRecord,
    SourceFormat,
)
from labelguard.parsers.common import (
    IdAllocator,
    ParseError,
    check_size,
    dataset_id_for,
    decode_text,
    to_float,
)

BDD_RESOLUTION = (1280.0, 720.0)

# Category lists exactly as published by BDD100K (format.rst / label release).
ONTOLOGIES: dict[str, list[str]] = {
    "bdd100k_labels_2018": [
        "person",
        "rider",
        "car",
        "truck",
        "bus",
        "train",
        "motor",
        "bike",
        "traffic light",
        "traffic sign",
    ],
    "det_20": [
        "pedestrian",
        "rider",
        "car",
        "truck",
        "bus",
        "train",
        "motorcycle",
        "bicycle",
        "traffic light",
        "traffic sign",
        "other vehicle",
        "other person",
        "trailer",
    ],
}

ATTRIBUTE_SPECS = [
    AttributeSpec(name="occluded", input_type="checkbox", values=["true", "false"]),
    AttributeSpec(name="truncated", input_type="checkbox", values=["true", "false"]),
    AttributeSpec(name="trafficLightColor", input_type="select", values=["red", "green", "yellow", "none"]),
    AttributeSpec(name="crowd", input_type="checkbox", values=["true", "false"]),
]


def looks_like_bdd(doc: Any) -> bool:
    def rec(r: Any) -> bool:
        return isinstance(r, dict) and "name" in r and ("labels" in r or "frames" in r)

    if isinstance(doc, list):
        return bool(doc) and rec(doc[0])
    if isinstance(doc, dict):
        return rec(doc) or (isinstance(doc.get("frames"), list) and "images" not in doc)
    return False


def _records(doc: Any) -> list[dict]:
    if isinstance(doc, list):
        return [r for r in doc if isinstance(r, dict)]
    if isinstance(doc, dict) and "name" in doc:
        return [doc]
    if isinstance(doc, dict) and isinstance(doc.get("frames"), list):
        return [r for r in doc["frames"] if isinstance(r, dict)]
    raise ParseError("Not a BDD100K / Scalabel label document.")


def _objects(rec: dict) -> list[dict]:
    if isinstance(rec.get("labels"), list):
        return rec["labels"]
    objs: list[dict] = []
    for fr in rec.get("frames") or []:
        if isinstance(fr, dict) and isinstance(fr.get("objects"), list):
            objs.extend(fr["objects"])
    return objs


def _attr_str(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _pick_ontology(observed: Counter) -> str:
    def overlap(name: str) -> int:
        cats = set(ONTOLOGIES[name])
        return sum(n for c, n in observed.items() if c in cats)

    return max(ONTOLOGIES, key=overlap)


def image_size(path: Path) -> tuple[float, float] | None:
    from PIL import Image

    try:
        with Image.open(path) as im:
            return float(im.width), float(im.height)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def parse_bdd100k(
    data: bytes,
    name: str = "bdd100k_labels.json",
    *,
    image_dir: str | Path | None = None,
    ontology: str | None = None,
) -> Dataset:
    check_size(data, name)
    try:
        doc = json.loads(decode_text(data))
    except json.JSONDecodeError as exc:
        raise ParseError(f"{name}: not valid JSON ({exc.msg} at line {exc.lineno}).") from exc
    return dataset_from_records(_records(doc), name, data=data, image_dir=image_dir, ontology=ontology)


def dataset_from_records(
    records: list[dict],
    name: str,
    *,
    data: bytes | None = None,
    image_dir: str | Path | None = None,
    ontology: str | None = None,
    image_lookup: Callable[[str], Path | None] | None = None,
) -> Dataset:
    ds = Dataset(
        id=dataset_id_for(name, data if data is not None else json.dumps(records).encode()),
        name=name,
        source_format=SourceFormat.BDD100K,
    )
    observed = Counter(
        str(o.get("category", "")) for r in records for o in _objects(r) if isinstance(o, dict) and "box2d" in o
    )
    onto = ontology or _pick_ontology(observed)
    ds.metadata.update({"file": name, "ontology": onto, "coordinate_convention": "inclusive pixel corners"})
    ds.categories = [
        Category(id=str(i + 1), name=c, attributes=list(ATTRIBUTE_SPECS)) for i, c in enumerate(ONTOLOGIES[onto])
    ]
    cat_ids = {c.name: c.id for c in ds.categories}

    img_dir = Path(image_dir) if image_dir else None
    image_ids = IdAllocator()
    ann_ids = IdAllocator()
    skipped = Counter()
    assumed_size = 0
    for idx, rec in enumerate(records):
        fname = str(rec.get("name", ""))
        source_id = Path(fname).stem or f"#{idx}"
        image_id = image_ids.allocate(source_id)
        errors: list[str] = [] if fname else ["missing 'name'"]
        size = None
        if fname and (img_dir is not None or image_lookup is not None):
            # The per-image label release stores 'name' without the extension.
            names = [fname] if Path(fname).suffix else [fname + ext for ext in (".jpg", ".png", ".jpeg")]
            for candidate in names:
                p = img_dir / candidate if img_dir is not None else image_lookup(candidate)
                if p is not None and p.is_file():
                    size = image_size(p)
                    ds.image_paths[image_id] = str(p)
                    break
        size_source = "image file"
        if size is None:
            size, size_source = BDD_RESOLUTION, "BDD100K documented resolution (assumed)"
            assumed_size += 1
        ds.images.append(
            ImageRecord(
                id=image_id,
                file_name=fname,
                width=size[0],
                height=size[1],
                source_location=f"[{idx}] {fname}",
                raw={
                    "source_id": source_id,
                    "parse_errors": errors,
                    "attributes": rec.get("attributes") or {},
                    "size_source": size_source,
                },
            )
        )
        for o_idx, obj in enumerate(_objects(rec)):
            if not isinstance(obj, dict):
                skipped["non-object entries"] += 1
                continue
            if "box2d" not in obj:
                kind = "poly2d" if "poly2d" in obj else "other"
                skipped[f"{kind}:{str(obj.get('category', '?')).split('/')[0]}"] += 1
                continue
            ds.annotations.append(_annotation(obj, o_idx, idx, fname, image_id, cat_ids, ann_ids))

    if img_dir is not None or image_lookup is not None:
        ds.metadata["images_supplied"] = bool(ds.image_paths) or img_dir is not None
    if skipped:
        ds.metadata["skipped_objects"] = dict(skipped)
        total = sum(skipped.values())
        detail = ", ".join(f"{n} {k}" for k, n in skipped.most_common())
        ds.parse_warnings.append(
            f"{total} non-detection objects are outside the detection scope and were not validated ({detail})."
        )
    if assumed_size:
        ds.parse_warnings.append(
            f"{assumed_size} image(s) had no readable image file; their size was assumed "
            f"to be the documented BDD100K resolution {BDD_RESOLUTION[0]:g} × {BDD_RESOLUTION[1]:g}."
        )
    return ds


def _annotation(
    obj: dict,
    o_idx: int,
    r_idx: int,
    fname: str,
    image_id: str,
    cat_ids: dict[str, str],
    ann_ids: IdAllocator,
) -> Annotation:
    errors: list[str] = []
    category = str(obj.get("category", ""))
    if "category" not in obj:
        errors.append("missing 'category'")
    # Object ids are only guaranteed unique within one image (the per-image label
    # release restarts them at 0 in every file), so ids are scoped by image.
    source_id = f"{image_id}:{obj['id']}" if "id" in obj else f"{image_id}:#{o_idx}"
    if "id" not in obj:
        errors.append("missing 'id'")
    box = obj.get("box2d")
    if isinstance(box, dict):
        src = [to_float(box.get(k), f"box2d.{k}", errors) for k in ("x1", "y1", "x2", "y2")]
    else:
        errors.append(f"'box2d' must be [x1, y1, x2, y2] object, got {str(box)[:60]}")
        src = [float("nan")] * 4
    bbox = [src[0], src[1], src[2] + 1.0, src[3] + 1.0]
    attrs = obj.get("attributes") if isinstance(obj.get("attributes"), dict) else {}
    raw: dict[str, Any] = {"source_id": source_id}
    for k in ("manualShape", "manualAttributes", "score"):
        if k in obj:
            raw[k] = obj[k]
    return Annotation(
        id=ann_ids.allocate(source_id),
        image_id=image_id,
        category=category,
        category_id=cat_ids.get(category),
        geometry_type=GeometryType.BBOX,
        bbox=bbox,
        bbox_source=src,
        attributes={str(k): _attr_str(v) for k, v in attrs.items()},
        occluded=bool(attrs.get("occluded", False)),
        source_format=SourceFormat.BDD100K,
        source_location=f"[{r_idx}] {fname} › labels[{o_idx}]",
        parse_errors=errors,
        raw=raw,
    )


def merge_per_image_files(paths: list[Path]) -> tuple[list[dict], list[str]]:
    """Read per-image BDD100K label files into one record list."""
    records, errors = [], []
    for p in sorted(paths):
        try:
            doc = json.loads(decode_text(p.read_bytes()))
            records.extend(_records(doc))
        except (json.JSONDecodeError, ParseError) as exc:
            errors.append(f"{p.name}: {exc}")
    return records, errors
