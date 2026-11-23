"""Level 2: real BDD100K data. Skipped unless the subset was fetched locally:

labelguard bdd100k fetch --profile smoke --accept-license
"""

import hashlib
import json
from pathlib import Path

import pytest

from labelguard.benchmark.compare import compare_datasets
from labelguard.benchmark.convert import load_records, to_coco
from labelguard.benchmark.runner import run_benchmark
from labelguard.parsers.bdd100k import dataset_from_records
from labelguard.parsers.coco_json import parse_coco_json
from labelguard.visualization.overlays import OverlayOptions, render_overlay

pytestmark = pytest.mark.realdata
SUBSET = Path(__file__).resolve().parents[1] / "data" / "bdd100k" / "smoke"
needs_data = pytest.mark.skipif(not (SUBSET / "manifest.json").exists(), reason="BDD100K smoke subset not fetched")


@needs_data
def test_manifest_checksums_match_files():
    m = json.loads((SUBSET / "manifest.json").read_text(encoding="utf-8"))
    assert m["size"] == len(m["images"]) == 20
    for e in m["images"]:
        stem = Path(e["file_name"]).stem
        files = (("image", SUBSET / "images" / e["file_name"]), ("label", SUBSET / "labels" / f"{stem}.json"))
        for kind, path in files:
            algo, digest = e["checksums"][kind].split(":")
            data = path.read_bytes()
            got = (
                hashlib.sha256(data).hexdigest()
                if algo == "sha256"
                else hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()
            )
            assert got == digest, path.name


@needs_data
def test_real_images_and_labels_align():
    records = load_records(SUBSET / "labels")
    ds = dataset_from_records(records, "smoke", image_dir=SUBSET / "images")
    assert len(ds.image_paths) == len(ds.images) == 20
    assert all((i.width, i.height) == (1280, 720) for i in ds.images)
    assert len(ds.annotations) > 100
    img = ds.images[0]
    res = render_overlay(
        img,
        [a for a in ds.annotations if a.image_id == img.id],
        image_path=ds.image_paths[img.id],
        options=OverlayOptions(target_width=1280),
    )
    assert res.has_pixels and not res.size_mismatch and res.transform.scale == 1.0


@needs_data
def test_coco_conversion_is_lossless_on_real_labels():
    records = load_records(SUBSET / "labels")
    ref = dataset_from_records(records, "ref")
    coco, rep = to_coco(records)
    cmp = compare_datasets(ref, parse_coco_json(json.dumps(coco).encode()))
    assert cmp.identical and cmp.matched == rep.converted == len(ref.annotations)


@needs_data
def test_benchmark_detects_every_injected_error(tmp_path):
    res = run_benchmark(SUBSET.parent, "smoke", reports_root=tmp_path / "r", public_root=None)
    ev = res["injected_errors"]["evaluation"]
    assert ev["overall"]["fn"] == 0 and ev["overall"]["fp"] == 0
    assert res["conversions"]["cvat_xml"]["comparison"]["identical_within_tolerance"]
