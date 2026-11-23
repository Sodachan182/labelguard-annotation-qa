"""CVAT for images 1.1 and CVAT for video 1.1 XML parsers.

XML is parsed with ``defusedxml`` so DTDs, external entities and entity
expansion ("billion laughs") are rejected.

Coordinate conventions: CVAT boxes are corner based (``xtl, ytl, xbr, ybr``),
polygons/polylines/points are ``"x,y;x,y"`` strings. Video tracks export one
shape per frame for interpolated tracks, or sparse keyframes; a shape with
``outside="1"`` marks the object leaving the frame.
"""

from __future__ import annotations

import math
from typing import Any
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from labelguard.models import (
    Annotation,
    AttributeSpec,
    Category,
    Dataset,
    GeometryType,
    ImageRecord,
    SourceFormat,
    Track,
)
from labelguard.parsers.common import (
    IdAllocator,
    ParseError,
    check_size,
    dataset_id_for,
    parse_point_string,
    to_bool,
    to_float,
)

_SHAPE_TAGS = {"box", "polygon", "polyline", "points", "skeleton", "mask", "ellipse", "cuboid"}
_MAX_VIDEO_FRAMES = 200_000


def parse_cvat_xml(data: bytes, name: str = "annotations.xml") -> Dataset:
    check_size(data, name)
    try:
        root = SafeET.fromstring(data, forbid_dtd=True)
    except DefusedXmlException as exc:
        raise ParseError(f"{name}: unsafe XML construct rejected ({type(exc).__name__}).") from exc
    except SafeET.ParseError as exc:
        raise ParseError(f"{name}: not well-formed XML ({exc}).") from exc
    if root.tag != "annotations":
        raise ParseError(f"{name}: root element is <{root.tag}>, expected CVAT <annotations>.")

    is_video = root.find("track") is not None and root.find("image") is None
    fmt = SourceFormat.CVAT_VIDEO if is_video else SourceFormat.CVAT_IMAGES
    ds = Dataset(id=dataset_id_for(name, data), name=name, source_format=fmt)
    ds.metadata["file"] = name
    ds.metadata["version"] = (root.findtext("version") or "").strip()
    meta = root.find("meta")
    ds.categories = _parse_labels(meta, ds)

    if is_video:
        _parse_video(root, meta, ds)
    else:
        _parse_images(root, ds)
    return ds


# --------------------------------------------------------------------- meta


def _parse_labels(meta: Element | None, ds: Dataset) -> list[Category]:
    if meta is None:
        ds.parse_warnings.append("No <meta> block: label schema unknown, label checks skipped.")
        return []
    labels_el = None
    for path in ("task/labels", "job/labels", "project/labels"):
        labels_el = meta.find(path)
        if labels_el is not None:
            break
    if labels_el is None:
        ds.parse_warnings.append("No <labels> in <meta>: label checks skipped.")
        return []
    cats: list[Category] = []
    for label in labels_el.findall("label"):
        lname = (label.findtext("name") or "").strip()
        if not lname:
            continue
        attrs = []
        for a in label.findall("attributes/attribute"):
            values = [v for v in (a.findtext("values") or "").split("\n") if v != ""]
            attrs.append(
                AttributeSpec(
                    name=(a.findtext("name") or "").strip(),
                    input_type=(a.findtext("input_type") or "text").strip(),
                    values=values,
                    mutable=to_bool(a.findtext("mutable")),
                )
            )
        kp_names = [(s.findtext("name") or "").strip() for s in label.findall("sublabels/label")]
        cats.append(Category(id=lname, name=lname, attributes=attrs, keypoint_names=kp_names))
    return cats


def _attrs(el: Element) -> dict[str, str]:
    return {a.get("name", ""): (a.text or "") for a in el.findall("attribute")}


# ------------------------------------------------------------------- shapes


def _shape(
    el: Element,
    *,
    ann_id: str,
    image_id: str,
    label: str,
    fmt: SourceFormat,
    location: str,
    frame: int | None = None,
    track_id: str | None = None,
) -> Annotation:
    errors: list[str] = []
    tag = el.tag
    raw: dict[str, Any] = {k: v for k, v in el.attrib.items()}
    kwargs: dict[str, Any] = {}
    if tag == "box":
        coords = [to_float(el.get(k), k, errors) for k in ("xtl", "ytl", "xbr", "ybr")]
        kwargs.update(geometry_type=GeometryType.BBOX, bbox=coords, bbox_source=list(coords))
        if el.get("rotation") not in (None, "", "0", "0.0"):
            raw["rotation_ignored"] = True
    elif tag in ("polygon", "polyline"):
        pts = parse_point_string(el.get("points"), errors)
        if tag == "polygon":
            kwargs.update(geometry_type=GeometryType.POLYGON, polygons=[pts])
        else:
            kwargs.update(geometry_type=GeometryType.POLYLINE, points=pts)
    elif tag == "points":
        pts = parse_point_string(el.get("points"), errors)
        kwargs.update(geometry_type=GeometryType.POINTS, points=pts, keypoint_visibility=[2] * len(pts))
    elif tag == "skeleton":
        pts, vis, names = [], [], []
        for p in el.findall("points"):
            sub = parse_point_string(p.get("points"), errors)
            pts.append(sub[0] if sub else [math.nan, math.nan])
            names.append(p.get("label", ""))
            vis.append(0 if to_bool(p.get("outside")) else 1 if to_bool(p.get("occluded")) else 2)
        raw["keypoint_names"] = names
        kwargs.update(geometry_type=GeometryType.KEYPOINTS, points=pts, keypoint_visibility=vis)
    else:
        raw["unsupported_shape"] = tag
        kwargs.update(geometry_type=GeometryType.UNSUPPORTED)

    return Annotation(
        id=ann_id,
        image_id=image_id,
        category=label,
        category_id=label or None,
        frame=frame,
        track_id=track_id,
        attributes=_attrs(el),
        occluded=to_bool(el.get("occluded")),
        outside=to_bool(el.get("outside")),
        keyframe=to_bool(el.get("keyframe")) if el.get("keyframe") is not None else None,
        source_format=fmt,
        source_location=location,
        parse_errors=errors,
        raw=raw,
        **kwargs,
    )


# ------------------------------------------------------------------- images


def _parse_images(root: Element, ds: Dataset) -> None:
    image_ids = IdAllocator()
    tag_count = 0
    for idx, img in enumerate(root.findall("image")):
        errors: list[str] = []
        source_id = img.get("id", str(idx))
        image_id = image_ids.allocate(source_id)
        rec = ImageRecord(
            id=image_id,
            file_name=img.get("name", ""),
            width=to_float(img.get("width"), "width", errors),
            height=to_float(img.get("height"), "height", errors),
            source_location=f"image[id={source_id}]",
            raw={"source_id": source_id, "parse_errors": errors},
        )
        ds.images.append(rec)
        n = 0
        for el in img:
            if el.tag == "tag":
                tag_count += 1
                continue
            if el.tag not in _SHAPE_TAGS:
                continue
            n += 1
            ann = _shape(
                el,
                ann_id=f"{image_id}:{n}",
                image_id=image_id,
                label=el.get("label", ""),
                fmt=ds.source_format,
                location=f"image[id={source_id}]/{el.tag}[{n}]",
            )
            ann.raw["source_id"] = ann.id
            ds.annotations.append(ann)
    if tag_count:
        ds.parse_warnings.append(f"{tag_count} image-level tag(s) carry no geometry and were not validated.")


# -------------------------------------------------------------------- video


def _parse_video(root: Element, meta: Element | None, ds: Dataset) -> None:
    size_el = None
    start, stop = 0, None
    width = height = math.nan
    if meta is not None:
        task = meta.find("task") if meta.find("task") is not None else meta.find("job")
        if task is not None:
            start_v = to_float(task.findtext("start_frame") or "0", "start_frame", [])
            start = int(start_v) if math.isfinite(start_v) else 0
            stop_txt = task.findtext("stop_frame")
            if stop_txt is not None:
                stop_v = to_float(stop_txt, "stop_frame", [])
                stop = int(stop_v) if math.isfinite(stop_v) else None
            if stop is None and task.findtext("size"):
                size_v = to_float(task.findtext("size"), "size", [])
                stop = start + int(size_v) - 1 if math.isfinite(size_v) else None
            size_el = task.find("original_size")
    if size_el is not None:
        width = to_float(size_el.findtext("width"), "width", [])
        height = to_float(size_el.findtext("height"), "height", [])
    else:
        ds.parse_warnings.append("No <original_size> in <meta>: frame bounds checks skipped.")

    track_ids = IdAllocator()
    referenced: set[int] = set()
    for t_idx, tr in enumerate(root.findall("track")):
        source_id = tr.get("id", str(t_idx))
        track_id = track_ids.allocate(source_id)
        label = tr.get("label", "")
        ds.tracks.append(
            Track(
                id=track_id,
                label=label,
                source=tr.get("source", ""),
                attributes={"source_id": source_id},
                source_location=f"track[id={source_id}]",
            )
        )
        for s_idx, el in enumerate(tr):
            if el.tag not in _SHAPE_TAGS:
                continue
            errs: list[str] = []
            fval = to_float(el.get("frame"), "frame", errs)
            frame = int(fval) if math.isfinite(fval) else -1
            ann = _shape(
                el,
                ann_id=f"t{track_id}:{s_idx + 1}",
                image_id=f"frame_{frame:06d}",
                label=label,
                fmt=ds.source_format,
                location=f"track[id={source_id}]/{el.tag}[frame={el.get('frame')}]",
                frame=frame,
                track_id=track_id,
            )
            ann.parse_errors = errs + ann.parse_errors
            ann.raw["source_id"] = ann.id
            ds.annotations.append(ann)
            if frame >= 0:
                referenced.add(frame)

    if stop is None:
        stop = max(referenced) if referenced else start
    ds.frame_range = (start, stop)
    if stop - start + 1 <= _MAX_VIDEO_FRAMES:
        frames = range(start, stop + 1)
    else:
        frames = sorted(f for f in referenced if start <= f <= stop)
        ds.parse_warnings.append("Very long video: only frames with shapes are listed.")
    for f in frames:
        ds.images.append(
            ImageRecord(
                id=f"frame_{f:06d}",
                file_name=f"frame_{f:06d}",
                width=width,
                height=height,
                frame=f,
                source_location=f"frame {f}",
            )
        )
