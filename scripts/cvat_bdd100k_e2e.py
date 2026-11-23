"""CVAT ⇄ LabelGuard end-to-end check on the BDD100K subset.

Status: prepared but NOT yet executed against a CVAT server (no Docker on the
development machine at the time of writing). Run it after ``scripts/start-cvat.ps1``.

Steps
  1. check CVAT availability (``/api/server/about``)
  2. verify the local subset (images, labels, manifest)
  3. build COCO annotations with the official BDD100K box convention
  4. create or reuse project "LabelGuard — BDD100K QA Benchmark"
  5. create or reuse Task A (original labels) and Task B (corrupted copy)
  6. upload the real images and import annotations (COCO 1.0)
  7. verify the imported annotation counts through the API
  8. export each task as "CVAT for images 1.1" and "COCO 1.0"
  9. parse the exports with LabelGuard, compare with the reference, validate
 10. write data/reports/cvat_e2e/<profile>/results.json

Credentials come from the environment (CVAT_HOST, CVAT_USER, CVAT_PASSWORD)
and are never printed or written to disk.

Requires: ``pip install cvat-sdk`` (matching the server version).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from labelguard.benchmark.compare import compare_datasets  # noqa: E402
from labelguard.benchmark.convert import load_records, to_coco  # noqa: E402
from labelguard.benchmark.runner import PROFILE  # noqa: E402
from labelguard.config import ValidationConfig  # noqa: E402
from labelguard.parsers.archive import attach_images, load_path  # noqa: E402
from labelguard.parsers.bdd100k import ONTOLOGIES, dataset_from_records  # noqa: E402
from labelguard.validation.engine import validate  # noqa: E402

PROJECT_NAME = "LabelGuard — BDD100K QA Benchmark"


def check_server(host: str) -> dict:
    with urllib.request.urlopen(f"{host.rstrip('/')}/api/server/about", timeout=15) as r:
        return json.loads(r.read())


def find_or_create_project(client, labels: list[str]):
    for p in client.projects.list():
        if p.name == PROJECT_NAME:
            return p, False
    return client.projects.create(spec={"name": PROJECT_NAME, "labels": [{"name": n} for n in labels]}), True


def find_or_create_task(client, project, name: str, images: list[Path], annotation_file: Path):
    from cvat_sdk.core.proxies.tasks import ResourceType

    for t in client.tasks.list():
        if t.name == name and t.project_id == project.id:
            return t, False
    task = client.tasks.create_from_data(
        spec={"name": name, "project_id": project.id},
        resource_type=ResourceType.LOCAL,
        resources=[str(p) for p in images],
        annotation_path=str(annotation_file),
        annotation_format="COCO 1.0",
    )
    return task, True


def export(task, fmt: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    task.export_dataset(format_name=fmt, filename=str(dest), include_images=False)
    return dest


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
        print("Install the SDK first: pip install cvat-sdk", file=sys.stderr)
        return 2

    subset = args.data / args.profile
    images = sorted((subset / "images").glob("*.jpg"))
    records = load_records(subset / "labels")
    if not images or len(images) != len(records):
        print(f"Subset at {subset} is incomplete ({len(images)} images, {len(records)} label files).", file=sys.stderr)
        return 2
    reference = dataset_from_records(records, "reference", image_dir=subset / "images")

    work = Path(tempfile.mkdtemp(prefix="labelguard-cvat-"))
    coco, _ = to_coco(records)
    for img in coco["images"]:  # CVAT matches annotations to uploaded files by name
        if not Path(img["file_name"]).suffix:
            img["file_name"] += ".jpg"
    ann_a = work / "task_a_coco.json"
    ann_a.write_text(json.dumps(coco), encoding="utf-8")
    corrupted = args.data / "derived" / args.profile / "corrupted" / "labels.json"

    results: dict = {"cvat_version": about.get("version"), "profile": args.profile, "tasks": {}}
    cfg = ValidationConfig.for_profile(PROFILE)
    with make_client(host, credentials=(user, password)) as client:
        project, created = find_or_create_project(client, ONTOLOGIES["bdd100k_labels_2018"])
        results["project"] = {"id": project.id, "created": created}
        tasks = {"A_original": (f"BDD100K {args.profile} — original", ann_a, reference)}
        if corrupted.exists():
            bad_recs = json.loads(corrupted.read_text(encoding="utf-8"))
            bad_recs = [r for r in bad_recs if (subset / "images" / f"{r['name']}.jpg").exists()]
            bad_coco, rep = to_coco(bad_recs)
            for img in bad_coco["images"]:
                img["file_name"] += "" if Path(img["file_name"]).suffix else ".jpg"
            ann_b = work / "task_b_coco.json"
            ann_b.write_text(json.dumps(bad_coco), encoding="utf-8")
            results["task_b_conversion"] = rep.as_dict()  # injections COCO cannot carry are listed here
            bad_ref = dataset_from_records(bad_recs, "corrupted-reference", image_dir=subset / "images")
            tasks["B_corrupted"] = (f"BDD100K {args.profile} — QA error benchmark", ann_b, bad_ref)

        for key, (name, ann_file, ref) in tasks.items():
            task, created = find_or_create_task(client, project, name, images, ann_file)
            task.fetch()
            shapes = task.get_annotations().shapes
            xml_zip = export(task, "CVAT for images 1.1", args.out / args.profile / f"{key}_cvat.zip")
            coco_zip = export(task, "COCO 1.0", args.out / args.profile / f"{key}_coco.zip")
            entry = {"task_id": task.id, "created": created, "api_shape_count": len(shapes)}
            for fmt, z in (("cvat_xml", xml_zip), ("coco", coco_zip)):
                dest = work / f"{key}_{fmt}"
                with zipfile.ZipFile(z) as zf:
                    zf.extractall(dest)  # export from our own local server
                loaded = load_path(dest)
                ds = loaded.datasets[0]
                attach_images(ds, subset / "images")
                report = validate(ds, cfg)
                entry[fmt] = {
                    "comparison": compare_datasets(ref, ds, tolerance_px=0.01).as_dict(),
                    "findings": len(report.issues),
                    "by_rule": dict(__import__("collections").Counter(i.rule_id for i in report.issues)),
                }
            results["tasks"][key] = entry
    out = args.out / args.profile / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))
    ok = all(
        t["cvat_xml"]["comparison"]["identical_within_tolerance"]
        for k, t in results["tasks"].items()
        if k == "A_original"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
