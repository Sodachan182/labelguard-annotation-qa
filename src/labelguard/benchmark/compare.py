"""Compare a reference dataset with a converted / exported copy.

Images are matched by file name. Within an image, boxes are matched per
category by greedy highest IoU; a matched pair whose corners differ by more than
``tolerance_px`` counts as a coordinate mismatch. Everything is in LabelGuard's
continuous-corner space, so different source conventions compare directly.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from labelguard.geometry.boxes import iou, is_finite
from labelguard.models import Dataset


@dataclass
class Comparison:
    reference_images: int = 0
    candidate_images: int = 0
    missing_images: list[str] = field(default_factory=list)
    extra_images: list[str] = field(default_factory=list)
    dimension_mismatches: list[str] = field(default_factory=list)
    reference_boxes: int = 0
    candidate_boxes: int = 0
    matched: int = 0
    missing_boxes: list[dict] = field(default_factory=list)
    extra_boxes: list[dict] = field(default_factory=list)
    coordinate_mismatches: list[dict] = field(default_factory=list)
    max_abs_delta_px: float = 0.0
    category_counts_equal: bool = True

    @property
    def identical(self) -> bool:
        return not (
            self.missing_images
            or self.extra_images
            or self.dimension_mismatches
            or self.missing_boxes
            or self.extra_boxes
            or self.coordinate_mismatches
        )

    def as_dict(self) -> dict:
        return {
            "identical_within_tolerance": self.identical,
            "reference_images": self.reference_images,
            "candidate_images": self.candidate_images,
            "missing_images": self.missing_images[:20],
            "extra_images": self.extra_images[:20],
            "dimension_mismatches": self.dimension_mismatches[:20],
            "reference_boxes": self.reference_boxes,
            "candidate_boxes": self.candidate_boxes,
            "matched_boxes": self.matched,
            "missing_boxes": len(self.missing_boxes),
            "extra_boxes": len(self.extra_boxes),
            "coordinate_mismatches": len(self.coordinate_mismatches),
            "max_abs_corner_delta_px": round(self.max_abs_delta_px, 6),
            "category_counts_equal": self.category_counts_equal,
            "examples": (self.missing_boxes + self.extra_boxes + self.coordinate_mismatches)[:10],
        }


_IMAGE_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff")


def image_key(name: str) -> str:
    """Match images across formats: CVAT/COCO exports write 'x.jpg' while BDD100K
    per-image labels store 'x'. Folders and a known image extension are ignored."""
    base = name.replace("\\", "/").split("/")[-1]
    return base[: -len(ext)] if (ext := next((e for e in _IMAGE_EXT if base.lower().endswith(e)), "")) else base


def _boxes_by_image(ds: Dataset) -> dict[str, list]:
    images = ds.image_by_id()
    out: dict[str, list] = defaultdict(list)
    for a in ds.annotations:
        if a.bbox is None or not is_finite(a.bbox):
            continue
        img = images.get(a.image_id)
        out[image_key(img.file_name if img else a.image_id)].append(a)
    return out


def compare_datasets(reference: Dataset, candidate: Dataset, tolerance_px: float = 0.01) -> Comparison:
    c = Comparison(reference_images=len(reference.images), candidate_images=len(candidate.images))
    ref_imgs = {image_key(i.file_name): i for i in reference.images}
    cand_imgs = {image_key(i.file_name): i for i in candidate.images}
    c.missing_images = sorted(set(ref_imgs) - set(cand_imgs))
    c.extra_images = sorted(set(cand_imgs) - set(ref_imgs))
    for name in sorted(set(ref_imgs) & set(cand_imgs)):
        r, k = ref_imgs[name], cand_imgs[name]
        if (r.width, r.height) != (k.width, k.height):
            c.dimension_mismatches.append(f"{name}: {r.width}x{r.height} vs {k.width}x{k.height}")

    ref, cand = _boxes_by_image(reference), _boxes_by_image(candidate)
    c.reference_boxes = sum(map(len, ref.values()))
    c.candidate_boxes = sum(map(len, cand.values()))
    ref_cats: dict[str, int] = defaultdict(int)
    cand_cats: dict[str, int] = defaultdict(int)
    for name in sorted(set(ref) | set(cand)):
        for a in ref.get(name, []):
            ref_cats[a.category] += 1
        for a in cand.get(name, []):
            cand_cats[a.category] += 1
        pool = list(cand.get(name, []))
        for a in ref.get(name, []):
            best, best_iou = None, 0.0
            for b in pool:
                if b.category != a.category:
                    continue
                v = iou(a.bbox, b.bbox)
                if v > best_iou or (best is None and v == best_iou == 0 and a.bbox == b.bbox):
                    best, best_iou = b, v
            if best is None:
                c.missing_boxes.append({"image": name, "annotation": a.id, "category": a.category})
                continue
            pool.remove(best)
            c.matched += 1
            delta = max(abs(x - y) for x, y in zip(a.bbox, best.bbox, strict=True))
            c.max_abs_delta_px = max(c.max_abs_delta_px, delta)
            if delta > tolerance_px:
                c.coordinate_mismatches.append(
                    {
                        "image": name,
                        "annotation": a.id,
                        "delta_px": round(delta, 4),
                        "reference": a.bbox,
                        "candidate": best.bbox,
                    }
                )
        for b in pool:
            c.extra_boxes.append({"image": name, "annotation": b.id, "category": b.category})
    c.category_counts_equal = dict(ref_cats) == dict(cand_cats)
    return c
