"""Fetch a small, reproducible BDD100K validation subset.

Source
------
The official download host named in the BDD100K docs (``dl.cv.ethz.ch``) no
longer resolves and ``bdd-data.berkeley.edu`` serves an expired TLS
certificate (checked 2026-11-23). This module therefore reads the Hugging Face
redistribution ``dronefreak/BDD100K``, which states that its files are
byte-identical to Berkeley's ``bdd100k_images_100k.zip`` and
``bdd100k_labels.zip`` and redistributes them under the BDD100K data license
(redistribution for educational, research and not-for-profit use, with the
copyright notice, is permitted). It is not an official release.

Reproducibility
---------------
* The repository is pinned to one commit (``REVISION``).
* Every file is verified against the checksum the Hub publishes for it (LFS
  SHA-256, or the git blob SHA-1 for small non-LFS files) before it is kept.
* Sampling is deterministic for a given seed and metadata.

Only the files that are sampled are downloaded (about 60–90 KB per image plus
its label file); the two validation metadata tables are about 17 MB in total.
"""

from __future__ import annotations

import hashlib
import json
import random
import shutil
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = "dronefreak/BDD100K"
REVISION = "fea86dd9b24ea425d66b70e0fcb6ae0023b5dca5"
HUB = "https://huggingface.co"
VAL_SHARDS = ("shard_000", "shard_001")
IMAGE_PREFIX = "data/images_100k/100k/val"
LABEL_PREFIX = "data/labels/100k/val"
SUBSET_SIZES = {"smoke": 20, "standard": 100, "extended": 500}
DEFAULT_SEED = 1729
USER_AGENT = "labelguard-dataset-fetch/1.0"

LICENSE_NOTICE = (
    "BDD100K data and labels: Copyright (c) 2018. The Regents of the University of "
    "California (Regents). All Rights Reserved. Used under the BDD100K data license for "
    "educational, research and not-for-profit purposes. "
    "License: https://github.com/bdd100k/bdd100k/blob/master/doc/source/license.rst"
)

# Categories that must be represented when the profile is large enough, rarest first.
COVERAGE_CATEGORIES = [
    "train",
    "motor",
    "rider",
    "bike",
    "bus",
    "truck",
    "person",
    "traffic light",
    "traffic sign",
    "car",
]


class FetchError(RuntimeError):
    pass


def _url(path: str) -> str:
    return f"{HUB}/datasets/{REPO}/resolve/{REVISION}/{urllib.parse.quote(path)}"


def _request(url: str, data: bytes | None = None, timeout: int = 60):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return urllib.request.urlopen(req, timeout=timeout)


def paths_info(paths: list[str]) -> dict[str, dict]:
    """Checksums the Hub publishes for each path at the pinned revision."""
    out: dict[str, dict] = {}
    for i in range(0, len(paths), 200):
        chunk = paths[i : i + 200]
        body = urllib.parse.urlencode([("paths", p) for p in chunk] + [("expand", "false")]).encode()
        with _request(f"{HUB}/api/datasets/{REPO}/paths-info/{REVISION}", data=body) as r:
            for item in json.loads(r.read()):
                out[item["path"]] = item
    missing = [p for p in paths if p not in out]
    if missing:
        raise FetchError(f"{len(missing)} path(s) not found at revision {REVISION[:10]}: {missing[:3]}")
    return out


def _verify(path: Path, info: dict) -> str:
    """Return the verified checksum string or raise."""
    data = path.read_bytes()
    lfs = info.get("lfs")
    if lfs:
        digest = hashlib.sha256(data).hexdigest()
        if digest != lfs["oid"]:
            raise FetchError(f"SHA-256 mismatch for {path.name}")
        return f"sha256:{digest}"
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
    if blob != info.get("oid"):
        raise FetchError(f"git blob SHA-1 mismatch for {path.name}")
    return f"gitsha1:{blob}"


def download(path: str, dest: Path, info: dict) -> str:
    """Download one file, verify it, skip if an identical copy exists. Returns checksum."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        try:
            return _verify(dest, info)
        except FetchError:
            dest.unlink()
    part = dest.with_suffix(dest.suffix + ".part")
    with _request(_url(path), timeout=120) as r, open(part, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 16)
    try:
        checksum = _verify(part, info)
    except FetchError:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    return checksum


def fetch_metadata(cache: Path) -> list[dict]:
    """Download (once) and read the validation metadata tables."""
    paths = [f"{IMAGE_PREFIX}/{s}/metadata.jsonl" for s in VAL_SHARDS]
    info = paths_info(paths)
    rows: list[dict] = []
    for p, shard in zip(paths, VAL_SHARDS, strict=True):
        dest = cache / f"val_{shard}_metadata.jsonl"
        download(p, dest, info[p])
        with dest.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    row = json.loads(line)
                    row["_shard"] = shard
                    rows.append(row)
    return rows


def _row_categories(row: dict) -> Counter:
    objs = row.get("objects") or {}
    cats = objs.get("category") if isinstance(objs, dict) else [o.get("category") for o in objs]
    return Counter(c for c in (cats or []) if c)


@dataclass
class Selection:
    file_name: str
    shard: str
    reason: str
    timeofday: str
    weather: str
    scene: str
    boxes: int


def sample(rows: list[dict], size: int, seed: int = DEFAULT_SEED) -> list[Selection]:
    """Deterministic, diversity-seeking sample.

    1. One image per category in ``COVERAGE_CATEGORIES`` (rarest first).
    2. One crowded scene (most boxes) and one sparse scene (fewest boxes, >= 1).
    3. One image per unseen value of time of day, weather and scene.
    4. The rest round-robin over (time of day, weather, scene) strata.
    Metadata values are used exactly as published ('undefined' stays 'undefined').
    """
    rng = random.Random(seed)
    rows = sorted(rows, key=lambda r: r["file_name"])
    chosen: dict[str, Selection] = {}

    def add(row: dict, reason: str) -> None:
        if len(chosen) >= size or row["file_name"] in chosen:
            return
        chosen[row["file_name"]] = Selection(
            file_name=row["file_name"],
            shard=row["_shard"],
            reason=reason,
            timeofday=str(row.get("timeofday", "")),
            weather=str(row.get("weather", "")),
            scene=str(row.get("scene", "")),
            boxes=sum(_row_categories(row).values()),
        )

    cats = {r["file_name"]: _row_categories(r) for r in rows}
    for cat in COVERAGE_CATEGORIES:
        pool = [r for r in rows if cats[r["file_name"]].get(cat)]
        if pool:
            add(rng.choice(pool), f"contains '{cat}'")
    by_count = sorted(rows, key=lambda r: (sum(cats[r["file_name"]].values()), r["file_name"]))
    add(by_count[-1 - rng.randrange(5)], "crowded scene")
    sparse = [r for r in by_count if sum(cats[r["file_name"]].values()) >= 1][:50]
    if sparse:
        add(rng.choice(sparse), "sparse scene")
    for key in ("timeofday", "weather", "scene"):
        for value in sorted({str(r.get(key, "")) for r in rows}):
            if any(getattr(s, key) == value for s in chosen.values()):
                continue
            pool = [r for r in rows if str(r.get(key, "")) == value]
            add(rng.choice(pool), f"{key} = {value}")
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        strata[(r.get("timeofday"), r.get("weather"), r.get("scene"))].append(r)
    keys = sorted(strata, key=lambda k: tuple(str(x) for x in k))
    for k in keys:
        rng.shuffle(strata[k])
    while len(chosen) < size and any(strata.values()):
        for k in keys:
            if strata[k] and len(chosen) < size:
                add(strata[k].pop(), "stratified fill")
    return sorted(chosen.values(), key=lambda s: s.file_name)


def build_subset(root: Path, profile: str = "smoke", seed: int = DEFAULT_SEED, size: int | None = None) -> Path:
    """Download and verify a subset into ``root/<profile>/{images,labels}``."""
    size = size or SUBSET_SIZES[profile]
    rows = fetch_metadata(root / "cache")
    picks = sample(rows, size, seed)
    out = root / profile
    files: list[tuple[str, Path, str]] = []
    for s in picks:
        stem = Path(s.file_name).stem
        files.append((f"{IMAGE_PREFIX}/{s.shard}/{s.file_name}", out / "images" / s.file_name, s.file_name))
        files.append((f"{LABEL_PREFIX}/{s.shard}/{stem}.json", out / "labels" / f"{stem}.json", s.file_name))
    info = paths_info([f[0] for f in files])
    checksums: dict[str, dict[str, str]] = defaultdict(dict)
    for hub_path, dest, fname in files:
        kind = "image" if dest.suffix == ".jpg" else "label"
        checksums[fname][kind] = download(hub_path, dest, info[hub_path])

    from labelguard.parsers.bdd100k import image_size

    entries = []
    category_counts: Counter = Counter()
    for s in picks:
        stem = Path(s.file_name).stem
        label = json.loads((out / "labels" / f"{stem}.json").read_text(encoding="utf-8"))
        if label.get("name") not in (s.file_name, stem):
            raise FetchError(f"Label file for {s.file_name} names {label.get('name')!r}")
        objs = [o for fr in label.get("frames", []) for o in fr.get("objects", [])]
        boxes = [o for o in objs if "box2d" in o]
        category_counts.update(o.get("category") for o in boxes)
        w, h = image_size(out / "images" / s.file_name) or (None, None)
        entries.append(
            {
                "file_name": s.file_name,
                "width": w,
                "height": h,
                "boxes": len(boxes),
                "non_detection_objects": len(objs) - len(boxes),
                "timeofday": s.timeofday,
                "weather": s.weather,
                "scene": s.scene,
                "selection_reason": s.reason,
                "checksums": checksums[s.file_name],
            }
        )
    manifest = {
        "dataset": "BDD100K (100K images, val split) with original per-image labels",
        "official_source": "https://github.com/bdd100k/bdd100k (docs: doc/source/download.rst)",
        "retrieved_from": f"{HUB}/datasets/{REPO} (unofficial, license-permitted redistribution)",
        "revision": REVISION,
        "label_release": "bdd100k_labels.zip per-image labels (2018 release; not Detection 2020)",
        "split": "val",
        "profile": profile,
        "size": len(entries),
        "seed": seed,
        "selection_method": sample.__doc__.strip(),
        "category_counts": dict(sorted(category_counts.items())),
        "coordinate_convention": "box2d inclusive pixel corners (width = x2 - x1 + 1)",
        "license_notice": LICENSE_NOTICE,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "images": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return out


def public_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Manifest without anything dataset-derived beyond names, sizes and checksums."""
    keep = {k: v for k, v in manifest.items() if k != "created_at"}
    return keep
