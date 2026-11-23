# Validation rules

Generated from the rule registry by `scripts/gen_rules_doc.py`. Do not edit by hand.

**Structural** findings mean the data violates the format or geometry definition and
can be fixed mechanically. **Heuristic** findings mean the data is valid but suspicious;
a reviewer decides. Heuristic box and polygon rules skip shapes that already have a
structural defect, so one mistake produces one finding instead of a cascade.

## Integrity

| Id | Name | Kind | Default severity | What it detects | Suggested action |
|---|---|---|---|---|---|
| `INT001` | Missing required field | structural | critical | A field the format requires (id, image reference, label, coordinates) is absent. | Re-export the annotation from the source tool or fill the missing field. |
| `INT002` | Invalid coordinate value | structural | critical | A coordinate is not a finite number (text, NaN, infinity) or a box has the wrong arity. | Fix the coordinate in the source tool; consumers will crash or silently drop this object. |
| `INT003` | Duplicate identifier | structural | critical | Two records of the same type share an id that the format requires to be unique. | Assign a unique id; references to this id are ambiguous. |
| `INT004` | Unknown category | structural | critical | An annotation references a label or category id that the dataset does not declare. | Map the object to a declared category or add the category to the label schema. |
| `INT005` | Invalid image dimensions | structural | critical | An image declares a missing, zero, negative or non-numeric width or height. | Restore the real pixel size; bounds checks for this image are skipped until fixed. |
| `INT006` | Missing image reference | structural | critical | An annotation points to an image id that does not exist in the dataset. | Fix the image_id or restore the image record; the annotation is orphaned. |
| `INT007` | Invalid attribute value | structural | warning | An attribute is undeclared for its label, or its value is not one of the allowed values. | Choose an allowed value or update the label schema. |
| `INT008` | Geometry not validated | structural | info | A shape type (mask, ellipse, cuboid, rotation) is kept but not geometrically checked. | Review manually; LabelGuard reports it so nothing is skipped silently. |
| `INT009` | Image file not supplied | structural | info | Image files were supplied, but this record's file was not among them. | Add the image to the upload to inspect overlays on real pixels. |

## Bounding boxes

| Id | Name | Kind | Default severity | What it detects | Suggested action |
|---|---|---|---|---|---|
| `BOX001` | Zero-area box | structural | critical | Box width or height is exactly zero; it encloses no pixels. | Redraw the box around the object or delete it. |
| `BOX002` | Negative box dimensions | structural | critical | The far corner lies before the near corner (negative width or height). | Swap the corner coordinates or redraw; many loaders reject this box. |
| `BOX003` | Box outside image | structural | critical | Box coordinates extend past the image frame by more than the tolerance. | Clip the box to the image or correct the coordinates. |
| `BOX004` | Suspiciously small box | heuristic | warning | Box area or shortest side is below the configured minimum; often a stray click. | Check whether this is a real distant object or an accidental box. |
| `BOX005` | Extreme aspect ratio | heuristic | warning | Box is much longer than it is wide; typical of a drag that slipped. | Confirm the object really has this shape; otherwise redraw. |
| `BOX006` | Near-duplicate box | heuristic | warning | Two boxes with the same label overlap almost completely (IoU at or above threshold). | Keep one box; duplicates inflate the class and confuse NMS-trained models. |
| `BOX007` | Conflicting labels | heuristic | warning | Boxes with different labels cover the same region; one label may be wrong. | Decide which label is correct and remove the other, or allow the pair in settings. |

## Polygons

| Id | Name | Kind | Default severity | What it detects | Suggested action |
|---|---|---|---|---|---|
| `POL001` | Too few vertices | structural | critical | A polygon needs at least three distinct vertices to enclose an area. | Redraw the polygon or delete it. |
| `POL002` | Self-intersecting polygon | structural | critical | Edges of the polygon cross each other, so its inside is undefined. | Reorder or move the crossing vertices so the outline does not cross itself. |
| `POL003` | Zero-area polygon | structural | critical | All vertices are collinear; the polygon encloses no area. | Redraw the polygon around the object. |
| `POL004` | Repeated consecutive vertices | structural | warning | The same vertex appears twice in a row, creating a zero-length edge. | Remove the repeated vertex; some rasterizers mis-handle zero-length edges. |
| `POL005` | Polygon outside image | structural | critical | One or more vertices lie outside the image frame beyond the tolerance. | Move the vertices onto the image edge. |
| `POL006` | Suspiciously small polygon | heuristic | warning | Polygon area is below the configured minimum. | Check whether the polygon is a real small object or a stray click. |
| `POL007` | Malformed polygon | structural | critical | The polygon's coordinate list cannot be read as x,y pairs. | Re-export the polygon; the coordinate list is truncated or corrupted. |

## Keypoints

| Id | Name | Kind | Default severity | What it detects | Suggested action |
|---|---|---|---|---|---|
| `KPT001` | Keypoint outside image | structural | critical | A labelled point lies outside the image frame. | Move the point onto the object or mark it as not labelled (v=0). |
| `KPT002` | Malformed keypoints | structural | critical | The keypoint array is not (x, y, v) triplets, or a visibility flag is not 0, 1 or 2. | Re-export the keypoints; the array is truncated or has invalid flags. |
| `KPT003` | Keypoint count mismatch | structural | critical | The number of points differs from the category's keypoint schema. | Add the missing points (use v=0 when not visible) or fix the schema. |
| `KPT004` | Suspicious keypoint position | heuristic | warning | A keypoint lies well outside its own object box, or violates a configured left/right ordering rule (possible mirrored labels). | Check whether the point belongs to this object and whether left/right are swapped. |

## Tracking

| Id | Name | Kind | Default severity | What it detects | Suggested action |
|---|---|---|---|---|---|
| `TRK001` | Invalid frame reference | structural | critical | A track shape references a frame outside the task range, or repeats a frame. | Move the shape to a valid frame or delete the duplicate. |
| `TRK002` | Track metadata conflict | structural | warning | A track has no shapes, is never visible, or mixes geometry types. | Delete the empty track or fix its shapes. |
| `TRK003` | Invalid visibility transition | structural | warning | After an 'outside' shape the object must re-enter on a keyframe; a non-keyframe visible shape there cannot be produced by interpolation. | Mark the re-entry shape as a keyframe or correct the outside flag. |
| `TRK004` | Suspicious movement jump | heuristic | warning | The object's centre moves further per frame than a multiple of its own size; often an identity switch or a mis-placed keyframe. | Scrub the frames around this shape and check the track identity. |
| `TRK005` | Sudden scale change | heuristic | warning | Box area changes by more than the configured factor per frame. | Check whether the box was resized by mistake on this frame. |
| `TRK006` | Track continuity gap | heuristic | info | Only with the 'explicit' gap policy: a visible track has no shape for more than the allowed number of frames. Under CVAT's default interpolation this is normal. | Confirm the object is really continuously visible, or add an outside marker. |

## Default thresholds

```json
{
  "enabled_rules": null,
  "disabled_rules": [],
  "severity_overrides": {},
  "boxes": {
    "bounds_tolerance_px": 1.0,
    "min_area_px": 36.0,
    "min_side_px": 4.0,
    "max_aspect_ratio": 12.0,
    "duplicate_iou": 0.9,
    "conflict_iou": 0.85,
    "allowed_overlap_pairs": []
  },
  "polygons": {
    "bounds_tolerance_px": 1.0,
    "min_area_px": 36.0
  },
  "keypoints": {
    "bounds_tolerance_px": 1.0,
    "expected_count": null,
    "bbox_margin_ratio": 0.25,
    "order_rules": []
  },
  "tracks": {
    "max_jump_ratio": 0.6,
    "max_scale_change": 1.6,
    "gap_policy": "interpolated",
    "max_gap": 10
  },
  "attribute_schema": {}
}
```

## Profiles

| Profile | Name | Description |
|---|---|---|
| `general_detection` | General object detection | Every structural rule plus box heuristics. Sensible default. |
| `instance_segmentation` | Instance segmentation | Stricter polygon checks; box aspect-ratio heuristic relaxed. |
| `video_tracking` | Video tracking | Track continuity, motion and visibility checks with CVAT semantics. |
| `face_landmarks` | Face landmarks | Keypoint schema, bounds and left/right ordering for frontal faces. Ordering assumes a camera-facing subject and is a heuristic. |
| `bdd100k_detection` | BDD100K driving detection | General detection rules for dash-cam data. Riders legitimately overlap their bike or motorcycle, so those pairs never produce conflict findings. |
| `seat_belt` | Seat belt annotation | In-cabin profile: allows 'seat_belt' to overlap 'person'/'occupant' without conflict findings and relaxes the aspect heuristic for thin belt boxes. It does not recognise whether a belt is worn. |

## Coordinate conventions

| Source | Box encoding | Internal (continuous corners) |
|---|---|---|
| CVAT XML | `xtl, ytl, xbr, ybr` corners | unchanged |
| COCO JSON | `[x, y, width, height]` | `[x, y, x + w, y + h]` |
| BDD100K / Scalabel | `box2d` inclusive pixel corners | `[x1, y1, x2 + 1, y2 + 1]` |

The BDD100K rule follows the official conversion (`width = x2 - x1 + 1`, Scalabel
`box2d_to_bbox`). Reports always quote the box exactly as written in the source.

## Video tracks and sparse keyframes

CVAT interpolates between keyframes, so a gap between two shapes of a track is not a
missing annotation. `TRK006` is therefore off unless `tracks.gap_policy = "explicit"`.
Motion and scale rules normalise by the frame distance, so sparse keyframes are compared
per frame. Shapes with `outside="1"` carry stale coordinates by design and are excluded
from geometry checks; a visible shape after an outside shape must be a keyframe (`TRK003`).
