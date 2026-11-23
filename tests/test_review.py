import csv
import json

from PIL import Image

from labelguard.benchmark.review import export_review, summarize_review
from tests.conftest import bdd_record, box


def _subset(tmp_path):
    sub = tmp_path / "standard"
    (sub / "labels").mkdir(parents=True)
    (sub / "images").mkdir()
    for i in range(3):
        name = f"im{i}"
        Image.new("RGB", (1280, 720)).save(sub / "images" / f"{name}.jpg")
        objs = [box(0, "car", 100, 100, 300, 250), box(1, "traffic light", 500 + i, 50, 505 + i, 60)]
        (sub / "labels" / f"{name}.json").write_text(json.dumps(bdd_record(name, objs)))
    return sub


def test_export_leaves_decisions_empty_and_summary_counts_only_human_rows(tmp_path):
    sheet = export_review(_subset(tmp_path), tmp_path / "out", limit=10)
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert len(rows) == 3 and all(r["decision"] == "" and r["reviewer"] == "" for r in rows)
    assert all((tmp_path / "out" / r["crop"]).exists() for r in rows)
    s = summarize_review(sheet)
    assert s["reviewed_by_a_person"] == 0 and s["pending"] == 3 and s["confirmed_error_rate"] is None

    rows[0].update(decision="error", reviewer="A")
    rows[1].update(decision="acceptable", reviewer="A")
    rows[2].update(decision="maybe")
    with sheet.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    s = summarize_review(sheet)
    assert s["reviewed_by_a_person"] == 2 and s["confirmed_error_rate"] == 0.5
    assert s["invalid_decisions"] == ["R003"]
