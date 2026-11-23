"""ZIP safety, reports, CLI and filters."""

import csv
import io
import json
import zipfile

import pandas as pd
import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from labelguard.analytics.statistics import issues_frame, quality_score
from labelguard.cli import app
from labelguard.parsers.archive import UnsafeArchiveError, load_path, safe_extract
from labelguard.reports import to_csv, to_json, to_xlsx
from labelguard.reports.exporters import safe_cell
from labelguard.ui.filters import filter_issues
from labelguard.validation import validate
from tests.conftest import bdd_record, box, cvat_images

IMG = '<image id="0" name="a.jpg" width="100" height="80">{}</image>'


def _zip(path, members: dict[str, bytes]):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


@pytest.mark.parametrize("name", ["../evil.txt", "/abs/evil.txt", "C:/evil.txt", "a/../../evil.txt"])
def test_zip_traversal_is_refused(tmp_path, name):
    z = _zip(tmp_path / "x.zip", {name: b"x"})
    with pytest.raises(UnsafeArchiveError):
        safe_extract(z, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()


def test_zip_bomb_ratio_is_refused(tmp_path):
    z = _zip(tmp_path / "bomb.zip", {"a.json": b"0" * 5_000_000})
    with pytest.raises(UnsafeArchiveError, match="compression ratio"):
        safe_extract(z, tmp_path / "out")


def test_zip_dataset_loads(tmp_path):
    xml = cvat_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="40" ybr="30"/>'))
    z = _zip(
        tmp_path / "ds.zip",
        {"annotations.xml": xml, "images/a.jpg": b"not really a jpeg", "__MACOSX/._annotations.xml": b"junk"},
    )
    res = load_path(z, workdir=tmp_path / "w")
    assert not res.errors and len(res.datasets) == 1
    ds = res.datasets[0]
    assert ds.metadata["archive"] == "ds.zip" and "0" in ds.image_paths


def test_bdd_per_image_folder_is_one_dataset(tmp_path):
    for i in range(3):
        (tmp_path / f"im{i}.json").write_text(json.dumps(bdd_record(f"im{i}", [box(0, "car", 1, 1, 20, 20)])))
    (tmp_path / "manifest.json").write_text(json.dumps({"images": [{"file_name": "x"}]}))
    res = load_path(tmp_path)
    assert len(res.datasets) == 1 and len(res.datasets[0].images) == 3


# ------------------------------------------------------------------ reports


@pytest.fixture
def report(parse_images):
    ds = parse_images(
        IMG.format(
            '<box label="=HYPERLINK(1)" xtl="10" ytl="10" xbr="10" ybr="30"/>'
            '<box label="car" xtl="10" ytl="10" xbr="14" ybr="14"/>'
        )
    )
    return ds, validate(ds)


def test_safe_cell():
    assert safe_cell("=1+1") == "'=1+1" and safe_cell("@x") == "'@x" and safe_cell("ok") == "ok"
    assert safe_cell(5) == 5


def test_csv_neutralises_formulas(report):
    _, rep = report
    rows = list(csv.DictReader(io.StringIO(to_csv(rep))))
    assert len(rows) == len(rep.issues)
    assert all(not r["category"].startswith("=") for r in rows)
    assert any(r["category"].startswith("'=") for r in rows)


def test_json_report(report):
    _, rep = report
    doc = json.loads(to_json(rep))
    assert doc["summary"]["findings"] == len(rep.issues)
    assert {"summary", "rules", "config", "issues"} <= set(doc)


def test_xlsx_report(report):
    ds, rep = report
    wb = load_workbook(io.BytesIO(to_xlsx(rep, ds)))
    assert wb.sheetnames == ["Summary", "Issues", "Categories", "Rules", "Configuration"]
    values = [c.value for row in wb["Issues"].iter_rows() for c in row if isinstance(c.value, str)]
    assert not any(v.startswith("=") for v in values)


def test_quality_score(report):
    _, rep = report
    score = quality_score(rep)
    assert score is not None and 0 <= score < 100


# ---------------------------------------------------------------------- CLI


def test_cli_scan_exit_codes(tmp_path):
    bad = tmp_path / "bad.xml"
    bad.write_bytes(cvat_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="10" ybr="30"/>')))
    good = tmp_path / "good" / "annotations.xml"
    good.parent.mkdir()
    good.write_bytes(cvat_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="40" ybr="30"/>')))
    runner = CliRunner()
    r = runner.invoke(app, ["scan", str(bad)])
    assert r.exit_code == 1 and "BOX001" in r.output
    assert runner.invoke(app, ["scan", str(bad), "--fail-on", "never"]).exit_code == 0
    assert runner.invoke(app, ["scan", str(good)]).exit_code == 0
    assert runner.invoke(app, ["scan", str(tmp_path / "missing.xml")]).exit_code == 2
    out = runner.invoke(app, ["scan", str(bad), "--output", "json", "--fail-on", "never"])
    assert json.loads(out.output)["summary"]["findings"] >= 1


def test_cli_report_and_rules(tmp_path):
    src = tmp_path / "a.xml"
    src.write_bytes(cvat_images(IMG.format('<box label="car" xtl="10" ytl="10" xbr="10" ybr="30"/>')))
    runner = CliRunner()
    for fmt in ("json", "csv", "xlsx"):
        dest = tmp_path / f"out.{fmt}"
        r = runner.invoke(app, ["report", str(src), "--format", fmt, "--out", str(dest)])
        assert r.exit_code == 0 and dest.stat().st_size > 0
    r = runner.invoke(app, ["rules"])
    assert "BOX001" in r.output and "TRK006" in r.output
    assert runner.invoke(app, ["bdd100k", "fetch"]).exit_code == 2  # license must be accepted


# ------------------------------------------------------------------ filters


def test_filter_issues(report):
    _, rep = report
    df = issues_frame(rep)
    assert len(filter_issues(df)) == len(df)
    assert set(filter_issues(df, severities=["Critical"])["severity"]) == {"critical"}
    assert set(filter_issues(df, kinds=["heuristic"])["rule_id"]) == {"BOX004"}
    assert len(filter_issues(df, rules=["BOX004"])) == 1
    assert len(filter_issues(df, query="ZERO AREA")) == 1
    assert filter_issues(df, query="nothing-matches").empty
    assert len(filter_issues(df, image="a.jpg")) == len(df)
    assert isinstance(filter_issues(pd.DataFrame(df), categories=["car"]), pd.DataFrame)
