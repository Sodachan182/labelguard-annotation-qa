"""BDD100K real-data benchmark: validation, conversion checks, injected errors.

Inputs live under ``data/`` (git-ignored). The run writes a full private report
to ``data/reports/bdd100k/<profile>/`` and an aggregate, image-free summary to
``benchmarks/bdd100k/<profile>_results.json`` that is safe to publish.
"""

from __future__ import annotations

import json
import platform
import random
import time
import tracemalloc
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from labelguard import __version__
from labelguard.benchmark.compare import compare_datasets
from labelguard.benchmark.convert import load_records, to_coco, to_cvat_xml
from labelguard.benchmark.corrupt import ERROR_TYPES, corrupt
from labelguard.config import ValidationConfig
from labelguard.evaluation import evaluate_findings
from labelguard.models import QualityReport, Severity
from labelguard.parsers.archive import attach_images
from labelguard.parsers.bdd100k import dataset_from_records
from labelguard.parsers.coco_json import parse_coco_json
from labelguard.parsers.cvat_xml import parse_cvat_xml
from labelguard.reports import to_json
from labelguard.validation.engine import validate

PROFILE = "bdd100k_detection"


def _summary(report: QualityReport) -> dict:
    return {
        "findings": len(report.issues),
        "by_severity": {s.value: report.count(s) for s in Severity},
        "structural": sum(1 for i in report.issues if i.kind.value == "structural"),
        "heuristic": sum(1 for i in report.issues if i.kind.value == "heuristic"),
        "by_rule": dict(sorted(Counter(i.rule_id for i in report.issues).items())),
    }


def _absent_names(cache: Path, present: set[str], k: int, seed: int) -> list[str]:
    names: list[str] = []
    for f in sorted(cache.glob("val_*_metadata.jsonl")):
        with f.open(encoding="utf-8") as fh:
            names += [json.loads(line)["file_name"] for line in fh if line.strip()]
    pool = sorted(set(names) - present)
    return random.Random(seed).sample(pool, min(k, len(pool))) if pool else []


def run_benchmark(
    data_root: Path = Path("data/bdd100k"),
    profile: str = "smoke",
    reports_root: Path = Path("data/reports/bdd100k"),
    public_root: Path | None = Path("benchmarks/bdd100k"),
    seed: int = 7,
    per_type: int = 3,
) -> dict:
    subset = data_root / profile
    labels_dir, images_dir = subset / "labels", subset / "images"
    if not labels_dir.is_dir() or not images_dir.is_dir():
        raise FileNotFoundError(f"{subset} is missing; run 'labelguard bdd100k fetch --profile {profile}' first.")
    derived = data_root / "derived" / profile
    out = reports_root / profile
    derived.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    cfg = ValidationConfig.for_profile(PROFILE)

    # ---- original labels: parse + validate, timed
    tracemalloc.start()
    t0 = time.perf_counter()
    records = load_records(labels_dir)
    original = dataset_from_records(records, f"bdd100k-{profile} (original)", image_dir=images_dir)
    t_parse = time.perf_counter() - t0
    t1 = time.perf_counter()
    base_report = validate(original, cfg)
    t_validate = time.perf_counter() - t1
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    (out / "original_report.json").write_text(to_json(base_report), encoding="utf-8")

    # ---- format conversions, re-parsed and compared with the original
    coco, coco_rep = to_coco(records)
    coco_path = derived / "coco" / "instances.json"
    coco_path.parent.mkdir(parents=True, exist_ok=True)
    coco_path.write_text(json.dumps(coco), encoding="utf-8")
    coco_ds = parse_coco_json(coco_path.read_bytes(), "instances.json")
    attach_images(coco_ds, images_dir)
    xml, cvat_rep = to_cvat_xml(records)
    cvat_path = derived / "cvat" / "annotations.xml"
    cvat_path.parent.mkdir(parents=True, exist_ok=True)
    cvat_path.write_bytes(xml)
    cvat_ds = parse_cvat_xml(cvat_path.read_bytes(), "annotations.xml")
    attach_images(cvat_ds, images_dir)
    conversions = {
        "coco": {
            "conversion": coco_rep.as_dict(),
            "comparison": compare_datasets(original, coco_ds).as_dict(),
            "findings": _summary(validate(coco_ds, cfg)),
        },
        "cvat_xml": {
            "conversion": cvat_rep.as_dict(),
            "comparison": compare_datasets(original, cvat_ds).as_dict(),
            "findings": _summary(validate(cvat_ds, cfg)),
        },
    }

    # ---- injected errors on a separate copy
    present = {r.get("name") for r in records}
    absent = _absent_names(data_root / "cache", present, per_type, seed)
    bad_records, manifest = corrupt(records, seed=seed, per_type=per_type, absent_names=absent)
    bad_dir = derived / "corrupted"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "labels.json").write_text(json.dumps(bad_records), encoding="utf-8")
    (bad_dir / "corruption_manifest.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "per_type": per_type,
                "error_types": [e[0] for e in ERROR_TYPES],
                "source_subset": str(subset),
                "injections": manifest,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    t2 = time.perf_counter()
    bad = dataset_from_records(bad_records, f"bdd100k-{profile} (corrupted copy)", image_dir=images_dir)
    bad_report = validate(bad, cfg)
    t_bad = time.perf_counter() - t2
    (out / "corrupted_report.json").write_text(to_json(bad_report), encoding="utf-8")
    evaluation = evaluate_findings(
        [(m["expected_rule"], m["target"]) for m in manifest], bad_report.issues, base_report.issues
    )

    slow = sorted(base_report.rule_timings_ms.items(), key=lambda kv: -kv[1])[:5]
    result = {
        "labelguard_version": __version__,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "environment": {"python": platform.python_version(), "platform": platform.platform(terse=True)},
        "dataset": {
            "name": "BDD100K val subset (original per-image labels)",
            "profile": profile,
            "images": len(original.images),
            "annotations": len(original.annotations),
            "non_detection_objects_skipped": original.metadata.get("skipped_objects", {}),
            "categories": dict(sorted(Counter(a.category for a in original.annotations).items())),
        },
        "validation_profile": PROFILE,
        "rules_run": len(base_report.rules_run),
        "original": {
            **_summary(base_report),
            "timing_ms": {
                "parse": round(t_parse * 1000, 1),
                "validate": round(t_validate * 1000, 1),
                "total": round((t_parse + t_validate) * 1000, 1),
            },
            "peak_traced_python_memory_mb": round(peak / 1e6, 2),
            "slowest_rules_ms": {k: round(v, 2) for k, v in slow},
            "findings_for_manual_review": [
                {
                    "rule_id": i.rule_id,
                    "annotation_id": i.annotation_id,
                    "image": i.image_name,
                    "title": i.title,
                    "kind": i.kind.value,
                }
                for i in base_report.issues
            ][:50],
        },
        "conversions": conversions,
        "injected_errors": {
            "seed": seed,
            "per_type": per_type,
            "injections": len(manifest),
            "corrupted_findings": _summary(bad_report),
            "parse_and_validate_ms": round(t_bad * 1000, 1),
            "evaluation": evaluation,
        },
    }
    (out / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if public_root is not None:
        public_root.mkdir(parents=True, exist_ok=True)
        public = json.loads(json.dumps(result))
        public["original"]["findings_for_manual_review"] = [
            {k: v for k, v in f.items() if k != "image"} for f in public["original"]["findings_for_manual_review"]
        ]
        (public_root / f"{profile}_results.json").write_text(json.dumps(public, indent=2), encoding="utf-8")
    return result
