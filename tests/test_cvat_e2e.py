"""Level 3 orchestration tested against a MOCK CVAT client (no server is contacted).

The fake mimics the cvat-sdk 2.83.0 surface the script uses: projects.list/create,
tasks.list/create_from_data, Task.fetch/get_annotations/export_dataset. It stores
the uploaded COCO file and exports it back unchanged, i.e. it models an ideal
server. A real CVAT round trip may clip or drop shapes; only a real run shows that.
"""

import importlib.util
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from labelguard.benchmark.corrupt import corrupt
from tests.conftest import bdd_record, box

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cvat_e2e", ROOT / "scripts" / "cvat_bdd100k_e2e.py")
e2e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e2e)


class FakeTask:
    def __init__(self, tid, name, project_id, coco_path):
        self.id, self.name, self.project_id = tid, name, project_id
        self.coco = json.loads(Path(coco_path).read_text(encoding="utf-8"))

    def fetch(self):
        return self

    def get_annotations(self):
        return SimpleNamespace(shapes=list(self.coco["annotations"]))

    def export_dataset(self, format_name, filename, include_images=True):
        assert include_images is False
        with zipfile.ZipFile(filename, "w") as zf:
            if format_name == "COCO 1.0":
                zf.writestr("annotations/instances_default.json", json.dumps(self.coco))
                return
            assert format_name == "CVAT for images 1.1"
            cats = {c["id"]: c["name"] for c in self.coco["categories"]}
            root = ET.Element("annotations")
            labels = ET.SubElement(ET.SubElement(ET.SubElement(root, "meta"), "task"), "labels")
            for name in cats.values():
                ET.SubElement(ET.SubElement(labels, "label"), "name").text = name
            for img in self.coco["images"]:
                el = ET.SubElement(
                    root,
                    "image",
                    id=str(img["id"]),
                    name=img["file_name"],
                    width=str(img["width"]),
                    height=str(img["height"]),
                )
                for a in self.coco["annotations"]:
                    if a["image_id"] == img["id"]:
                        x, y, w, h = a["bbox"]
                        ET.SubElement(
                            el,
                            "box",
                            label=cats[a["category_id"]],
                            xtl=str(x),
                            ytl=str(y),
                            xbr=str(x + w),
                            ybr=str(y + h),
                            occluded="0",
                        )
            zf.writestr("annotations.xml", ET.tostring(root))


class FakeClient:
    def __init__(self):
        self.created_tasks = 0
        projects, tasks = [], []

        def create_project(spec):
            p = SimpleNamespace(id=len(projects) + 1, **spec)
            projects.append(p)
            return p

        def create_task(spec, resources, resource_type, annotation_path, annotation_format):
            assert annotation_format == "COCO 1.0" and resources
            self.created_tasks += 1
            t = FakeTask(len(tasks) + 1, spec["name"], spec["project_id"], annotation_path)
            tasks.append(t)
            return t

        self.projects = SimpleNamespace(list=lambda: list(projects), create=create_project)
        self.tasks = SimpleNamespace(list=lambda: list(tasks), create_from_data=create_task)


def _subset(tmp_path):
    sub = tmp_path / "smoke"
    (sub / "labels").mkdir(parents=True)
    (sub / "images").mkdir()
    recs = []
    for i in range(12):
        rec = bdd_record(f"img{i}", [box(j, "car", 100 + 150 * j, 300, 199 + 150 * j, 379) for j in range(5)])
        recs.append(rec)
        (sub / "labels" / f"img{i}.json").write_text(json.dumps(rec))
        Image.new("RGB", (1280, 720)).save(sub / "images" / f"img{i}.jpg")
    bad, manifest = corrupt(recs, seed=3, per_type=1)
    cdir = tmp_path / "corrupted"
    cdir.mkdir()
    (cdir / "labels.json").write_text(json.dumps(bad))
    (cdir / "corruption_manifest.json").write_text(json.dumps({"injections": manifest}))
    return sub, cdir


def test_e2e_round_trip_against_mock_client_is_exact_and_idempotent(tmp_path):
    sub, cdir = _subset(tmp_path)
    client = FakeClient()
    res = e2e.run_e2e(client, sub, cdir, tmp_path / "out", {"version": "mock"})
    a = res["tasks"]["A_original"]
    assert res["project"]["created"] and a["created"] and a["api_shape_count"] == 60
    for fmt in ("cvat_xml", "coco"):
        cmp = a[fmt]["comparison"]
        assert cmp["identical_within_tolerance"], cmp  # image names 'imgN' vs 'imgN.jpg' must match
        assert cmp["matched_boxes"] == 60
    b = res["tasks"]["B_corrupted"]["cvat_xml"]["injected_expected_vs_found"]
    assert set(b) == {"BOX001", "BOX003", "BOX005", "BOX006", "BOX007"}
    assert all(v["found_on_export"] >= v["expected"] for v in b.values())
    assert res["task_b_conversion"]["skipped"]  # NaN / unknown-category injections cannot be uploaded

    again = e2e.run_e2e(client, sub, cdir, tmp_path / "out2")
    assert not again["project"]["created"] and not again["tasks"]["A_original"]["created"]
    assert client.created_tasks == 2
