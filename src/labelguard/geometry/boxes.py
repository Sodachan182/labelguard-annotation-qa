"""Bounding-box math. Internal boxes are corner-based ``[x1, y1, x2, y2]``."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np


def coco_to_xyxy(box: Sequence[float]) -> list[float]:
    """COCO ``[x, y, width, height]`` -> ``[x1, y1, x2, y2]``.

    Negative widths are preserved (x2 < x1) so validators can report them.
    """
    x, y, w, h = (float(v) for v in box)
    return [x, y, x + w, y + h]


def xyxy_to_coco(box: Sequence[float]) -> list[float]:
    x1, y1, x2, y2 = (float(v) for v in box)
    return [x1, y1, x2 - x1, y2 - y1]


def width_height(box: Sequence[float]) -> tuple[float, float]:
    return box[2] - box[0], box[3] - box[1]


def area(box: Sequence[float]) -> float:
    w, h = width_height(box)
    return max(w, 0.0) * max(h, 0.0)


def is_finite(box: Sequence[float]) -> bool:
    return len(box) == 4 and all(isinstance(v, (int, float)) and math.isfinite(v) for v in box)


def center(box: Sequence[float]) -> tuple[float, float]:
    return (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0


def diagonal(box: Sequence[float]) -> float:
    w, h = width_height(box)
    return math.hypot(w, h)


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """Intersection over union of two corner boxes. 0 for degenerate boxes."""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(ix2 - ix1, 0.0) * max(iy2 - iy1, 0.0)
    union = area(a) + area(b) - inter
    return inter / union if union > 0 else 0.0


def iou_matrix(boxes: np.ndarray) -> np.ndarray:
    """Pairwise IoU for an (N, 4) array of corner boxes, vectorised."""
    if len(boxes) == 0:
        return np.zeros((0, 0))
    x1 = np.maximum(boxes[:, None, 0], boxes[None, :, 0])
    y1 = np.maximum(boxes[:, None, 1], boxes[None, :, 1])
    x2 = np.minimum(boxes[:, None, 2], boxes[None, :, 2])
    y2 = np.minimum(boxes[:, None, 3], boxes[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    areas = np.clip(boxes[:, 2] - boxes[:, 0], 0, None) * np.clip(boxes[:, 3] - boxes[:, 1], 0, None)
    union = areas[:, None] + areas[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.where(union > 0, inter / union, 0.0)
    return out


def overshoot(box: Sequence[float], width: float, height: float) -> float:
    """How far (px) the box extends past the image frame; 0 if inside."""
    return max(0.0, -box[0], -box[1], box[2] - width, box[3] - height)


def clip(box: Sequence[float], width: float, height: float) -> list[float]:
    return [
        min(max(box[0], 0.0), width),
        min(max(box[1], 0.0), height),
        min(max(box[2], 0.0), width),
        min(max(box[3], 0.0), height),
    ]
