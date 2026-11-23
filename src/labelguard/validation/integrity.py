"""Data-integrity rules (INT): schema, references, ids and coordinate values."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from labelguard.models import GeometryType, IssueKind, QualityIssue, Severity
from labelguard.validation.engine import Rule, RuleContext, classify_parse_error, register


@register
class MissingRequiredFields(Rule):
    id = "INT001"
    name = "Missing required field"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "A field the format requires (id, image reference, label, coordinates) is absent."
    action = "Re-export the annotation from the source tool or fill the missing field."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in ctx.dataset.annotations:
            missing = [e for e in ann.parse_errors if classify_parse_error(e) == "missing"]
            if not ann.category and not ann.category_id:
                missing.append("missing label / category")
            if missing:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title="Required field missing",
                    description="; ".join(sorted(set(missing))).capitalize() + ".",
                    evidence={"missing": sorted(set(missing))},
                )
        for img in ctx.dataset.images:
            errs = [
                e
                for e in img.raw.get("parse_errors", [])
                if classify_parse_error(e) == "missing" and "width" not in e and "height" not in e
            ]
            if errs or not img.file_name:
                yield self.issue(
                    ctx,
                    image=img,
                    title="Image record incomplete",
                    description="; ".join(errs or ["missing file name"]).capitalize() + ".",
                    evidence={"missing": errs or ["file_name"]},
                )


@register
class InvalidCoordinates(Rule):
    id = "INT002"
    name = "Invalid coordinate value"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "A coordinate is not a finite number (text, NaN, infinity) or a box has the wrong arity."
    action = "Fix the coordinate in the source tool; consumers will crash or silently drop this object."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in ctx.dataset.annotations:
            errs = [e for e in ann.parse_errors if classify_parse_error(e) == "value"]
            errs += [e for e in ann.parse_errors if "must be [" in e]
            if ann.geometry_type == GeometryType.POLYLINE:
                errs += [e for e in ann.parse_errors if classify_parse_error(e) == "structure"]
            if errs:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title="Coordinate is not a valid number",
                    description="; ".join(errs).capitalize() + ".",
                    evidence={"errors": errs, "raw": {k: v for k, v in ann.raw.items() if k != "source_id"}},
                )


@register
class DuplicateIds(Rule):
    id = "INT003"
    name = "Duplicate identifier"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "Two records of the same type share an id that the format requires to be unique."
    action = "Assign a unique id; references to this id are ambiguous."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        ds = ctx.dataset
        groups: dict[str, list] = defaultdict(list)
        for img in ds.images:
            groups[f"image:{img.raw.get('source_id', img.id)}"].append(("image", img))
        for ann in ds.annotations:
            groups[f"annotation:{ann.raw.get('source_id', ann.id)}"].append(("annotation", ann))
        for tr in ds.tracks:
            groups[f"track:{tr.attributes.get('source_id', tr.id)}"].append(("track", tr))
        for key, items in groups.items():
            if len(items) < 2:
                continue
            kind, source_id = key.split(":", 1)
            for _, obj in items[1:]:
                common = dict(
                    title=f"Duplicate {kind} id {source_id}",
                    description=f"{len(items)} {kind} records use id {source_id}.",
                    evidence={"id": source_id, "occurrences": len(items), "record": kind},
                    key=obj.id,
                )
                if kind == "annotation":
                    yield self.issue(ctx, annotation=obj, **common)
                elif kind == "image":
                    yield self.issue(ctx, image=obj, **common)
                else:
                    yield self.issue(ctx, track_id=obj.id, source_location=obj.source_location, **common)
        for cid in ds.metadata.get("duplicate_category_ids", []):
            yield self.issue(
                ctx,
                title=f"Duplicate category id {cid}",
                description=f"Category id {cid} is declared more than once.",
                evidence={"id": cid, "record": "category"},
                key=f"cat:{cid}",
                source_location="categories",
            )


@register
class UnknownCategory(Rule):
    id = "INT004"
    name = "Unknown category"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "An annotation references a label or category id that the dataset does not declare."
    action = "Map the object to a declared category or add the category to the label schema."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        ds = ctx.dataset
        if not ds.categories:
            return
        ids = {c.id for c in ds.categories}
        names = ds.category_names()
        for ann in ds.annotations:
            if ann.source_format.value == "coco_instances_json":
                unknown = ann.category_id is not None and ann.category_id not in ids
                ref = ann.category_id
            else:
                unknown = bool(ann.category) and ann.category not in names
                ref = ann.category
            if unknown:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Category '{ref}' is not declared",
                    description=f"'{ref}' is not in the dataset's {len(ids)} declared categories.",
                    evidence={"referenced": ref, "declared": sorted(names)[:30]},
                )


@register
class InvalidImageDimensions(Rule):
    id = "INT005"
    name = "Invalid image dimensions"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "An image declares a missing, zero, negative or non-numeric width or height."
    action = "Restore the real pixel size; bounds checks for this image are skipped until fixed."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        if ctx.dataset.is_video:
            return
        for img in ctx.dataset.images:
            if not img.has_valid_size:
                yield self.issue(
                    ctx,
                    image=img,
                    title="Image size is invalid",
                    description=f"Declared size is {img.width} × {img.height}.",
                    evidence={"width": img.width, "height": img.height},
                )


@register
class MissingImageReference(Rule):
    id = "INT006"
    name = "Missing image reference"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.CRITICAL
    description = "An annotation points to an image id that does not exist in the dataset."
    action = "Fix the image_id or restore the image record; the annotation is orphaned."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        if ctx.dataset.is_video:
            return  # frame references are checked by TRK001
        for ann in ctx.dataset.annotations:
            if ann.image_id and ctx.image_for(ann) is None:
                yield self.issue(
                    ctx,
                    annotation=ann,
                    title=f"Image {ann.image_id} does not exist",
                    description=f"Annotation {ann.id} references image id {ann.image_id}, which is not declared.",
                    evidence={"image_id": ann.image_id},
                )


@register
class InvalidAttribute(Rule):
    id = "INT007"
    name = "Invalid attribute value"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.WARNING
    description = "An attribute is undeclared for its label, or its value is not one of the allowed values."
    action = "Choose an allowed value or update the label schema."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        specs: dict[str, dict[str, list[str] | None]] = {}
        for cat in ctx.dataset.categories:
            for a in cat.attributes:
                allowed: list[str] | None = None
                if a.input_type in ("select", "radio"):
                    allowed = a.values
                elif a.input_type == "checkbox":
                    allowed = ["true", "false"]
                specs.setdefault(cat.name, {})[a.name] = allowed
        for label, attrs in ctx.config.attribute_schema.items():
            for name, values in attrs.items():
                specs.setdefault(label, {})[name] = values
        if not specs:
            return
        for ann in ctx.dataset.annotations:
            spec = specs.get(ann.category)
            if spec is None:
                continue
            for name, value in ann.attributes.items():
                if name not in spec:
                    yield self.issue(
                        ctx,
                        annotation=ann,
                        title=f"Undeclared attribute '{name}'",
                        description=f"Label '{ann.category}' does not declare attribute '{name}'.",
                        evidence={"attribute": name, "value": value, "declared": sorted(spec)},
                        key=f"undeclared:{name}",
                    )
                    continue
                allowed = spec[name]
                if allowed is not None and value not in allowed:
                    yield self.issue(
                        ctx,
                        annotation=ann,
                        title=f"'{name}' has a value outside its schema",
                        description=f"'{value}' is not one of: {', '.join(allowed)}.",
                        evidence={"attribute": name, "value": value, "allowed": allowed},
                        key=f"value:{name}",
                    )


@register
class UnsupportedGeometry(Rule):
    id = "INT008"
    name = "Geometry not validated"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.INFO
    description = "A shape type (mask, ellipse, cuboid, rotation) is kept but not geometrically checked."
    action = "Review manually; LabelGuard reports it so nothing is skipped silently."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        for ann in ctx.dataset.annotations:
            reason = None
            if ann.geometry_type == GeometryType.UNSUPPORTED:
                reason = f"'{ann.raw.get('unsupported_shape', 'unknown')}' shapes are not validated."
            elif ann.raw.get("rotation_ignored"):
                reason = f"Box rotation {ann.raw.get('rotation')}° is ignored by bounds checks."
            elif ann.raw.get("segmentation_rle"):
                reason = "RLE mask segmentation is not decoded; only the box is validated."
            if reason:
                yield self.issue(ctx, annotation=ann, title="Geometry kept but not validated", description=reason)


@register
class MissingImageFile(Rule):
    id = "INT009"
    name = "Image file not supplied"
    group = "Integrity"
    kind = IssueKind.STRUCTURAL
    severity = Severity.INFO
    description = "Image files were supplied, but this record's file was not among them."
    action = "Add the image to the upload to inspect overlays on real pixels."

    def check(self, ctx: RuleContext) -> Iterator[QualityIssue]:
        ds = ctx.dataset
        if not ds.metadata.get("images_supplied"):
            return
        missing = [img for img in ds.images if img.id not in ds.image_paths]
        if ds.is_video:
            if missing:
                yield self.issue(
                    ctx,
                    title=f"{len(missing)} frame image(s) not supplied",
                    description="Frame images were supplied but not for every frame.",
                    evidence={"missing_frames": [m.frame for m in missing][:50], "count": len(missing)},
                    source_location="frames",
                    key="frames",
                )
            return
        for img in missing:
            yield self.issue(
                ctx,
                image=img,
                title=f"{img.file_name} not found",
                description="The annotation file lists this image but no matching file was supplied.",
                evidence={"file_name": img.file_name},
            )
