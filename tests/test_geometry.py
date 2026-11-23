import numpy as np
import pytest

from labelguard.geometry import boxes as B
from labelguard.geometry.polygons import diagnose


def test_coco_conversion_round_trip():
    assert B.coco_to_xyxy([10, 20, 30, 40]) == [10, 20, 40, 60]
    assert B.xyxy_to_coco([10, 20, 40, 60]) == [10, 20, 30, 40]
    # negative widths are preserved so validators can report them
    assert B.coco_to_xyxy([10, 20, -5, 4]) == [10, 20, 5, 24]


@pytest.mark.parametrize(
    "a, b, expected",
    [
        ([0, 0, 10, 10], [0, 0, 10, 10], 1.0),
        ([0, 0, 10, 10], [5, 0, 15, 10], 50 / 150),
        ([0, 0, 10, 10], [20, 20, 30, 30], 0.0),
        ([0, 0, 0, 10], [0, 0, 0, 10], 0.0),  # degenerate
    ],
)
def test_iou(a, b, expected):
    assert B.iou(a, b) == pytest.approx(expected)


def test_iou_matrix_matches_scalar():
    boxes = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [100, 100, 110, 120]], dtype=float)
    m = B.iou_matrix(boxes)
    for i in range(3):
        for j in range(3):
            assert m[i, j] == pytest.approx(B.iou(boxes[i], boxes[j]))


def test_overshoot_and_clip():
    assert B.overshoot([-3, 0, 10, 10], 100, 50) == 3
    assert B.overshoot([0, 0, 120, 10], 100, 50) == 20
    assert B.clip([-3, 0, 120, 60], 100, 50) == [0, 0, 100, 50]


def test_polygon_diagnosis():
    square = diagnose([[0, 0], [10, 0], [10, 10], [0, 10]])
    assert square.is_valid and square.area == 100
    bowtie = diagnose([[0, 0], [10, 10], [10, 0], [0, 10]])
    assert not bowtie.is_valid and "self-intersection" in bowtie.invalid_reason.lower()
    assert bowtie.self_intersection_at == pytest.approx((5.0, 5.0))
    line = diagnose([[0, 0], [5, 5], [10, 10]])
    assert line.hull_area == 0
    two = diagnose([[0, 0], [5, 5], [5, 5]])
    assert two.distinct_vertices == 2
    rep = diagnose([[0, 0], [10, 0], [10, 0], [10, 10]])
    assert rep.repeated_consecutive == 1
