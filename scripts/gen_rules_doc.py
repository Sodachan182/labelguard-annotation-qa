"""Regenerate docs/VALIDATION_RULES.md from the rule registry:  python scripts/gen_rules_doc.py"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from labelguard.config import PROFILES, ValidationConfig  # noqa: E402
from labelguard.validation.engine import all_rules  # noqa: E402

GROUP_ORDER = ["Integrity", "Bounding boxes", "Polygons", "Keypoints", "Tracking"]


def main() -> None:
    rules = all_rules()
    cfg = ValidationConfig()
    lines = [
        "# Validation rules",
        "",
        "Generated from the rule registry by `scripts/gen_rules_doc.py`. Do not edit by hand.",
        "",
        "**Structural** findings mean the data violates the format or geometry definition and",
        "can be fixed mechanically. **Heuristic** findings mean the data is valid but suspicious;",
        "a reviewer decides. Heuristic box and polygon rules skip shapes that already have a",
        "structural defect, so one mistake produces one finding instead of a cascade.",
        "",
    ]
    for group in GROUP_ORDER:
        lines += [
            f"## {group}",
            "",
            "| Id | Name | Kind | Default severity | What it detects | Suggested action |",
            "|---|---|---|---|---|---|",
        ]
        for r in rules:
            if r.group == group:
                lines.append(
                    f"| `{r.id}` | {r.name} | {r.kind.value} | {r.severity.value} | {r.description} | {r.action} |"
                )
        lines.append("")
    lines += [
        "## Default thresholds",
        "",
        "```json",
        cfg.model_dump_json(indent=2, exclude={"profile"}),
        "```",
        "",
        "## Profiles",
        "",
        "| Profile | Name | Description |",
        "|---|---|---|",
    ]
    for p in PROFILES.values():
        lines.append(f"| `{p.id}` | {p.name} | {p.description} |")
    lines += [
        "",
        "## Coordinate conventions",
        "",
        "| Source | Box encoding | Internal (continuous corners) |",
        "|---|---|---|",
        "| CVAT XML | `xtl, ytl, xbr, ybr` corners | unchanged |",
        "| COCO JSON | `[x, y, width, height]` | `[x, y, x + w, y + h]` |",
        "| BDD100K / Scalabel | `box2d` inclusive pixel corners | `[x1, y1, x2 + 1, y2 + 1]` |",
        "",
        "The BDD100K rule follows the official conversion (`width = x2 - x1 + 1`, Scalabel",
        "`box2d_to_bbox`). Reports always quote the box exactly as written in the source.",
        "",
        "## Video tracks and sparse keyframes",
        "",
        "CVAT interpolates between keyframes, so a gap between two shapes of a track is not a",
        'missing annotation. `TRK006` is therefore off unless `tracks.gap_policy = "explicit"`.',
        "Motion and scale rules normalise by the frame distance, so sparse keyframes are compared",
        'per frame. Shapes with `outside="1"` carry stale coordinates by design and are excluded',
        "from geometry checks; a visible shape after an outside shape must be a keyframe (`TRK003`).",
        "",
    ]
    (ROOT / "docs" / "VALIDATION_RULES.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(rules)} rules documented")


if __name__ == "__main__":
    main()
