"""Human review of suspicious REAL annotations.

Injected errors show that rules fire as designed; they say nothing about how
often a heuristic finding on real data is a genuine labelling mistake. This
module supports a small, honest answer to that question:

1. ``export_review`` runs the rules on the original labels with *review
   sensitivity* thresholds (stricter than the defaults, to surface borderline
   cases), and writes a review sheet plus one zoomed crop per candidate on the
   real image. Decision columns are left empty.
2. A person opens each crop (or the Inspector) and fills ``decision`` with
   ``error``, ``acceptable`` or ``unsure``, plus ``reviewer`` and ``notes``.
3. ``summarize_review`` counts only rows a reviewer filled in. Nothing is ever
   pre-filled or inferred automatically.

Everything is written under the git-ignored ``data/`` folder because crops
contain BDD100K imagery.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

from labelguard.benchmark.convert import load_records
from labelguard.config import ValidationConfig
from labelguard.models import IssueKind
from labelguard.parsers.bdd100k import dataset_from_records
from labelguard.validation.engine import validate
from labelguard.visualization.overlays import OverlayOptions, render_overlay

DECISIONS = ("error", "acceptable", "unsure")
COLUMNS = [
    "candidate_id",
    "image",
    "annotation_id",
    "category",
    "rule_id",
    "kind",
    "title",
    "box_source_x1y1x2y2",
    "crop",
    "decision",
    "reviewer",
    "notes",
]


def review_config() -> ValidationConfig:
    """Stricter heuristics than the defaults, used only to surface review candidates."""
    cfg = ValidationConfig.for_profile("bdd100k_detection")
    cfg.boxes = cfg.boxes.model_copy(
        update={
            "min_area_px": 150.0,
            "min_side_px": 8.0,
            "max_aspect_ratio": 6.0,
            "duplicate_iou": 0.7,
            "conflict_iou": 0.6,
        }
    )
    return cfg


def export_review(subset: Path, out: Path, limit: int = 40) -> Path:
    records = load_records(subset / "labels")
    ds = dataset_from_records(records, f"{subset.name} (review)", image_dir=subset / "images")
    report = validate(ds, review_config())
    candidates = [i for i in report.issues if i.kind == IssueKind.HEURISTIC and i.annotation_id]
    # Deterministic and diverse: round-robin over rules, then by image and annotation id.
    by_rule: dict[str, list] = defaultdict(list)
    for i in sorted(candidates, key=lambda i: (i.rule_id, i.image_id or "", i.annotation_id or "")):
        by_rule[i.rule_id].append(i)
    picked = []
    while len(picked) < limit and any(by_rule.values()):
        for rule in sorted(by_rule):
            if by_rule[rule] and len(picked) < limit:
                picked.append(by_rule[rule].pop(0))
    anns = {a.id: a for a in ds.annotations}
    images = ds.image_by_id()
    crops = out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, issue in enumerate(picked, start=1):
        ann = anns[issue.annotation_id]
        img = images[ann.image_id]
        same_image = [a for a in ds.annotations if a.image_id == img.id]
        res = render_overlay(
            img,
            same_image,
            image_path=ds.image_paths.get(img.id),
            selected_id=ann.id,
            options=OverlayOptions(target_width=800, zoom_to_selection=True, show_labels=True),
        )
        crop = crops / f"{n:03d}_{issue.rule_id}.jpg"
        res.image.save(crop, quality=90)
        rows.append(
            {
                "candidate_id": f"R{n:03d}",
                "image": img.file_name,
                "annotation_id": ann.id,
                "category": ann.category,
                "rule_id": issue.rule_id,
                "kind": issue.kind.value,
                "title": issue.title,
                "box_source_x1y1x2y2": " ".join(f"{v:.2f}" for v in (ann.bbox_source or [])),
                "crop": str(crop.relative_to(out)),
                "decision": "",
                "reviewer": "",
                "notes": "",
            }
        )
    sheet = out / "review_sheet.csv"
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    (out / "README.txt").write_text(
        "Open each crop (or the image in the LabelGuard Inspector) and fill 'decision' with one of: "
        f"{', '.join(DECISIONS)}. Add your name in 'reviewer' and any context in 'notes'.\n"
        "Then run: labelguard bdd100k review-summary --profile <profile>\n"
        "Crops contain BDD100K imagery (c) 2018 The Regents of the University of California; keep them private.\n",
        encoding="utf-8",
    )
    return sheet


def summarize_review(sheet: Path) -> dict:
    with sheet.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    invalid = [r["candidate_id"] for r in rows if r["decision"].strip() and r["decision"].strip() not in DECISIONS]
    reviewed = [r for r in rows if r["decision"].strip() in DECISIONS]
    per_rule: dict[str, Counter] = defaultdict(Counter)
    for r in reviewed:
        per_rule[r["rule_id"]][r["decision"].strip()] += 1

    def rate(c: Counter) -> float | None:
        decided = c["error"] + c["acceptable"]
        return round(c["error"] / decided, 4) if decided else None

    total = Counter(r["decision"].strip() for r in reviewed)
    return {
        "candidates": len(rows),
        "reviewed_by_a_person": len(reviewed),
        "pending": len(rows) - len(reviewed),
        "invalid_decisions": invalid,
        "reviewers": sorted({r["reviewer"].strip() for r in reviewed if r["reviewer"].strip()}),
        "decisions": dict(total),
        "confirmed_error_rate": rate(total),
        "by_rule": {k: {**dict(v), "confirmed_error_rate": rate(v)} for k, v in sorted(per_rule.items())},
        "note": "Only rows with a human decision are counted; unsure rows are excluded from the error rate.",
    }
