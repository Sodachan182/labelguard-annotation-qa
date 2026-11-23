"""Deterministic error injection into a COPY of BDD100K labels.

Only annotation geometry and metadata are changed; image pixels and the
original label files are never modified. Each injection is recorded with the
image, the original and modified annotation identifiers (LabelGuard ids,
``<image stem>:<object id>``), the original and corrupted values, the rule
expected to detect it, and the seed.

Error types (expected rule):

1. out_of_bounds          box shifted past the right image edge      BOX003
2. zero_area              x2 = x1 − 1 (zero width, inclusive coords)  BOX001
3. duplicate              same-class copy offset by 1 px               BOX006
4. unknown_category       category outside the ontology                INT004
5. extreme_aspect_ratio   box squashed to 6 px tall                   BOX005
6. invalid_coordinate     y1 replaced by the non-finite string "NaN"   INT002
7. missing_image          record for an image absent from the subset   INT009
8. suspicious_overlap     copy relabelled to another vehicle class     BOX007
9. invalid_metadata       occluded = "maybe" (schema: boolean)         INT007
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from pathlib import Path

from labelguard.parsers.bdd100k import _objects

ERROR_TYPES = [
    ("out_of_bounds", "BOX003", "structural"),
    ("zero_area", "BOX001", "structural"),
    ("duplicate", "BOX006", "heuristic"),
    ("unknown_category", "INT004", "structural"),
    ("extreme_aspect_ratio", "BOX005", "heuristic"),
    ("invalid_coordinate", "INT002", "structural"),
    ("missing_image", "INT009", "structural"),
    ("suspicious_overlap", "BOX007", "heuristic"),
    ("invalid_metadata", "INT007", "structural"),
]
WIDTH, HEIGHT = 1280, 720


@dataclass
class Target:
    rec_idx: int
    obj: dict


def _stem(rec: dict) -> str:
    return Path(str(rec.get("name", ""))).stem


def _lg_id(rec: dict, obj_id) -> str:
    return f"{_stem(rec)}:{obj_id}"


def _box(obj: dict) -> dict:
    return obj["box2d"]


def corrupt(
    records: list[dict], seed: int = 7, per_type: int = 3, absent_names: list[str] | None = None
) -> tuple[list[dict], list[dict]]:
    """Return (corrupted copy, manifest entries)."""
    rng = random.Random(seed)
    recs = copy.deepcopy(records)
    manifest: list[dict] = []
    used_objects: set[int] = set()
    used_images: dict[str, set[int]] = {}

    def candidates(min_w: float, categories: tuple[str, ...] = ("car",)) -> list[Target]:
        out = []
        for ri, rec in enumerate(recs):
            for obj in _objects(rec):
                b = obj.get("box2d")
                if not isinstance(b, dict) or obj.get("category") not in categories:
                    continue
                if not all(isinstance(b.get(k), (int, float)) for k in ("x1", "y1", "x2", "y2")):
                    continue  # already corrupted
                w, h = b["x2"] - b["x1"] + 1, b["y2"] - b["y1"] + 1
                if w >= min_w and h >= 20 and b["x1"] > 40 and b["x2"] < WIDTH - 200 and id(obj) not in used_objects:
                    out.append(Target(ri, obj))
        return out

    def pick(kind: str, min_w: float = 40, categories: tuple[str, ...] = ("car",)) -> Target:
        pool = [t for t in candidates(min_w, categories) if t.rec_idx not in used_images.get(kind, set())]
        if not pool:
            raise RuntimeError(f"No suitable object left for '{kind}'")
        t = rng.choice(pool)
        used_objects.add(id(t.obj))
        used_images.setdefault(kind, set()).add(t.rec_idx)
        return t

    def next_id(rec: dict) -> int:
        ids = [o.get("id") for o in _objects(rec) if isinstance(o.get("id"), int)]
        return max(ids, default=0) + 1000

    def append_obj(rec: dict, obj: dict) -> None:
        if isinstance(rec.get("labels"), list):
            rec["labels"].append(obj)
        else:
            rec["frames"][0]["objects"].append(obj)

    def log(kind, rule, cls, rec, orig_id, mod_id, before, after):
        manifest.append(
            {
                "error_type": kind,
                "expected_rule": rule,
                "kind": cls,
                "image": rec.get("name"),
                "original_annotation_id": orig_id,
                "modified_annotation_id": mod_id,
                "target": mod_id,
                "original_value": before,
                "corrupted_value": after,
                "seed": seed,
            }
        )

    absent = list(absent_names or [])
    for kind, rule, cls in ERROR_TYPES:
        for n in range(per_type):
            if kind == "missing_image":
                # Copy from the untouched originals so the new record carries no other defect.
                src = rng.choice(records)
                obj = copy.deepcopy(next(o for o in _objects(src) if "box2d" in o))
                # Prefer real val image names that are not in the subset.
                name = absent[n] if n < len(absent) else f"absent-{rng.randrange(16**8):08x}.jpg"
                new = {
                    "name": name,
                    "attributes": copy.deepcopy(src.get("attributes", {})),
                    "frames": [{"objects": [obj]}],
                }
                recs.append(new)
                log(kind, rule, cls, new, None, Path(name).stem, None, {"name": name, "objects": 1})
                continue

            t = pick(kind, min_w=100 if kind == "extreme_aspect_ratio" else 40)
            rec, obj = recs[t.rec_idx], t.obj
            b = _box(obj)
            before = dict(b)
            oid = _lg_id(rec, obj["id"])
            if kind == "out_of_bounds":
                w = b["x2"] - b["x1"]
                b["x2"] = WIDTH - 1 + 40.0
                b["x1"] = b["x2"] - w
                log(kind, rule, cls, rec, oid, oid, before, dict(b))
            elif kind == "zero_area":
                b["x2"] = b["x1"] - 1.0
                log(kind, rule, cls, rec, oid, oid, before, dict(b))
            elif kind in ("duplicate", "suspicious_overlap"):
                dup = copy.deepcopy(obj)
                dup["id"] = next_id(rec)
                db = dup["box2d"]
                off = 1.0 if kind == "duplicate" else 2.0
                for k in ("x1", "x2"):
                    db[k] += off
                if kind == "suspicious_overlap":
                    dup["category"] = "truck" if obj["category"] != "truck" else "bus"
                append_obj(rec, dup)
                mid = _lg_id(rec, dup["id"])
                log(
                    kind,
                    rule,
                    cls,
                    rec,
                    oid,
                    mid,
                    {"category": obj["category"], **before},
                    {"category": dup["category"], **db},
                )
            elif kind == "unknown_category":
                obj["category"] = "ambulance"
                log(kind, rule, cls, rec, oid, oid, {"category": "car"}, {"category": "ambulance"})
            elif kind == "extreme_aspect_ratio":
                b["y2"] = b["y1"] + 5.0
                log(kind, rule, cls, rec, oid, oid, before, dict(b))
            elif kind == "invalid_coordinate":
                b["y1"] = "NaN"
                log(kind, rule, cls, rec, oid, oid, before, dict(b))
            elif kind == "invalid_metadata":
                attrs = obj.setdefault("attributes", {})
                old = attrs.get("occluded")
                attrs["occluded"] = "maybe"
                log(kind, rule, cls, rec, oid, oid, {"occluded": old}, {"occluded": "maybe"})
    return recs, manifest
