"""CVAT ⇄ LabelGuard end-to-end check on the BDD100K subset (level 3 test).

Status: NOT yet executed against a real CVAT server (no Docker on the development
machine). The orchestration below is unit-tested against a mock client in
tests/test_cvat_e2e.py, and its calls were checked against the real
cvat-sdk 2.83.0 API (CVAT v2.83.0). Run it after scripts/start-cvat.ps1.

Steps
  1. check CVAT availability (/api/server/about)
  2. verify the local subset (images, labels)
  3. build COCO annotations with the official BDD100K box convention
  4. create or reuse project "LabelGuard — BDD100K QA Benchmark"
  5. create or reuse Task A (original labels) and Task B (corrupted copy)
  6. upload the real images and import annotations (COCO 1.0)
  7. read back the shape count through the API
  8. export each task as "CVAT for images 1.1" and "COCO 1.0"
  9. extract exports safely, parse with LabelGuard, compare with the reference, validate
 10. Task B: compare findings per rule with the injections COCO can carry
 11. write data/reports/cvat_e2e/<profile>/results.json

Credentials come from CVAT_USER / CVAT_PASSWORD (never printed or stored).
Requires:  pip install "cvat-sdk==2.83.0"   (match the server version)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from labelguard.benchmark.compare import compare_datasets  # noqa: E402
from labelguard.benchmark.convert import load_records, to_coco  # noqa: E402
from labelguard.benchmark.runner import PROFILE  # noqa: E402
from labelguard.config import ValidationConfig  # noqa: E402
from labelguard.parsers.archive import attach_images, load_path, safe_extract  # noqa: E402
from labelguard.parsers.bdd100k import ONTOLOGIES, dataset_from_records  # noqa: E402
from labelguard.validation.engine import validate  # noqa: E402

PROJECT_NAME = "LabelGuard — BDD100K QA Benchmark"
# Injection types that survive a COCO import (the others are dropped or flattened by
# the conversion and are reported in task_b_conversion instead).
COCO_REPRESENTABLE = {"out_of_bounds", "zero_area", "duplicate", "extreme_aspect_ratio", "suspicious_overlap"}


def check_server(host: str) -> dict:
    with urllib.request.urlopen(f"{host.rstrip('/')}/api/server/about", timeout=15) as r:
        return json.loads(r.read())


def _local_resource_type():
    try:
        from cvat_sdk.core.proxies.tasks import ResourceType

        return ResourceType.LOCAL
    except ImportError:  # mock clients in tests
        return "local"


def find_or_create_project(client, labels: list[str]):
    for p in client.projects.list():
        if p.name == PROJECT_NAME:
            return p, False
    return client.projects.create(spec={"name": PROJECT_NAME, "labels": [{"name": n} for n in labels]}), True


def find_or_create_task(client, project, name: str, images: list[Path], annotation_file: Path):
    for t in client.tasks.list():
        if t.name == name and t.project_id == project.id:
            return t, False
    task = client.tasks.create_from_data(
        spec={"name": name, "project_id": project.id},
        resources=[str(p) for p in images],
        resource_type=_local_resource_type(),
        annotation_path=str(annotation_file),
        annotation_format="COCO 1.0",
    )
    return task, True


def _coco_for_upload(records: list[dict]) -> tuple[dict, dict]:
    coco, rep = to_coco(records)
    for img in coco["images"]:  # CVAT matches annotations to uploaded files by file name
        if not Path(img["file_name"]).suffix:
            img["file_name"] += ".jpg"
    return coco, rep.as_dict()


def run_e2e(client, subset: Path, corrupted_dir: Path | None, out: Path, about: dict | None = None) -> dict:
    images = sorted((subset / "images").glob("*.jpg"))
    records = load_records(subset / "labels")
    if not images or len(images) != len(records):
        raise ValueError(f"Subset at {subset} is incomplete ({len(images)} images, {len(records)} label files).")
    work = Path(tempfile.mkdtemp(prefix="labelguard-cvat-"))
    cfg = ValidationConfig.for_profile(PROFILE)
    results: dict = {"cvat_version": (about or {}).get("version"), "subset": subset.name, "tasks": {}}

    coco_a, _ = _coco_for_upload(records)
    ann_a = work / "task_a_coco.json"
    ann_a.write_text(json.dumps(coco_a), encoding="utf-8")
    plan = {"A_original": (f"BDD100K {subset.name} — original", ann_a, records, None)}

    labels_b = corrupted_dir / "labels.json" if corrupted_dir else None
    if labels_b and labels_b.exists():
        present = {p.stem for p in images}
        bad = [r for r in json.loads(labels_b.read_text(encoding="utf-8")) if Path(r["name"]).stem in present]
        coco_b, rep_b = _coco_for_upload(bad)
        ann_b = work / "task_b_coco.json"
        ann_b.write_text(json.dumps(coco_b), encoding="utf-8")
        results["task_b_conversion"] = rep_b
        manifest = json.loads((corrupted_dir / "corruption_manifest.json").read_text(encoding="utf-8"))
        expected = Counter(m["expected_rule"] for m in manifest["injections"] if m["error_type"] in COCO_REPRESENTABLE)
        plan["B_corrupted"] = (f"BDD100K {subset.name} — QA error benchmark", ann_b, bad, expected)

    project, created = find_or_create_project(client, ONTOLOGIES["bdd100k_labels_2018"])
    results["project"] = {"id": project.id, "created": created}
    for key, (name, ann_file, recs, expected) in plan.items():
        reference = dataset_from_records(recs, f"{key} reference")
        task, created = find_or_create_task(client, project, name, images, ann_file)
        task.fetch()
        entry: dict = {"task_id": task.id, "created": created, "api_shape_count": len(task.get_annotations().shapes)}
        base_rules = Counter(i.rule_id for i in validate(reference, cfg).issues)
        for fmt, fmt_name in (("cvat_xml", "CVAT for images 1.1"), ("coco", "COCO 1.0")):
            zip_path = out / f"{key}_{fmt}.zip"
            zip_path.parent.mkdir(parents=True, exist_ok=True)
            task.export_dataset(format_name=fmt_name, filename=str(zip_path), include_images=False)
            dest = safe_extract(zip_path, work / f"{key}_{fmt}")
            loaded = load_path(dest)
            if not loaded.datasets:
                entry[fmt] = {"error": "; ".join(loaded.errors) or "export contained no annotation file"}
                continue
            ds = loaded.datasets[0]
            attach_images(ds, subset / "images")
            found = Counter(i.rule_id for i in validate(ds, cfg).issues)
            entry[fmt] = {
                "comparison": compare_datasets(reference, ds, tolerance_px=0.01).as_dict(),
                "findings_by_rule": dict(sorted(found.items())),
            }
            if expected is not None:
                entry[fmt]["injected_expected_vs_found"] = {
                    rule: {"expected": n, "found_on_export": found[rule], "found_on_reference": base_rules[rule]}
                    for rule, n in sorted(expected.items())
                }
        results["tasks"][key] = entry
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", default="smoke")
    ap.add_argument("--data", type=Path, default=ROOT / "data" / "bdd100k")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "reports" / "cvat_e2e")
    args = ap.parse_args()

    host = os.environ.get("CVAT_HOST", "http://localhost:8080")
    user, password = os.environ.get("CVAT_USER"), os.environ.get("CVAT_PASSWORD")
    if not (user and password):
        print("Set CVAT_USER and CVAT_PASSWORD in the environment.", file=sys.stderr)
        return 2
    try:
        about = check_server(host)
    except OSError as exc:
        print(f"CVAT is not reachable at {host}: {exc}", file=sys.stderr)
        return 2
    try:
        from cvat_sdk import make_client
    except ImportError:
        print('Install the SDK first: pip install "cvat-sdk==2.83.0"', file=sys.stderr)
        return 2
    with make_client(host, credentials=(user, password)) as client:
        results = run_e2e(
            client,
            args.data / args.profile,
            args.data / "derived" / args.profile / "corrupted",
            args.out / args.profile,
            about,
        )
    print(json.dumps(results, indent=2))
    a = results["tasks"]["A_original"]
    return 0 if a.get("cvat_xml", {}).get("comparison", {}).get("identical_within_tolerance") else 1


if __name__ == "__main__":
    raise SystemExit(main())
