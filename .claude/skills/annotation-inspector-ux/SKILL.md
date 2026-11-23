---
name: annotation-inspector-ux
description: UX rules for LabelGuard's Annotation Inspector — overlay rendering, color semantics, selection, frame and issue navigation, dense scenes, missing images and responsive split panes. Use when building or changing the Inspector page, the overlay renderer, or anything that draws annotation geometry.
---

# Annotation Inspector UX

The Inspector is where an engineer decides whether a finding is real. Its job is to
answer three questions fast: *which object*, *what is wrong with it*, *what should
I do*. It is a review tool, not a gallery.

## Layout

```
┌ Inspector  image_0007.png                         Image 7 of 12 ┐
├──────────────┬──────────────────────────────┬──────────────────┤
│ Findings (n) │  toolbar: overlay mode, labels,│ Finding details  │
│ list for     │  ids, zoom to selection        │ rule, severity,  │
│ this image   │                                │ kind, geometry,  │
│              │  canvas (aspect preserved)     │ coordinates,     │
│              │                                │ explanation,     │
│              │                                │ suggested fix,   │
│              │                                │ source, JSON     │
├──────────────┴──────────────────────────────┴──────────────────┤
│ ‹ Previous finding   ‹ Previous image   Next image ›  Next finding › │
└───────────────────────────────────────────────────────────────┘
```

- Column ratio about 1 : 2.6 : 1.3 on desktop. Under ~1024px Streamlit stacks the
  columns; order must then be canvas, details, list — so the canvas is rendered in
  the middle column but the list stays short (scroll container, fixed height).
- The navigation bar sits directly under the canvas, not at the page bottom.

## Overlay rendering (Pillow, server side)

- Draw on a copy scaled to the canvas width; multiply every source coordinate by
  the same `scale = target_w / image_w`. Never round before scaling.
- Render at 2x device pixels and let the browser downscale for crisp lines.
- Default object: 2px outline in a category color from a fixed 8-hue palette at
  reduced opacity (alpha 0.85 outline, 0.10 fill for polygons).
- Flagged object: outline in its worst severity color.
- **Selected object:** accent outline at 3px plus the selection-corner motif (four
  L-shaped corner ticks offset 4px outside the box) and a dimming veil (alpha 0.35)
  over the rest of the image. The selection must be findable within one second.
- Labels: small tag above the top-left corner, flipped inside when it would leave
  the canvas. Tag shows category and, if enabled, `#id`.
- Keypoints: 4px dots, visible = filled, labeled-not-visible = hollow ring.
  Out-of-bounds points are drawn clamped to the edge with an arrow-like notch so
  they remain discoverable.
- Out-of-bounds geometry: extend the canvas with a margin when any selected
  coordinate is outside the image, so the defect is visible rather than clipped.

## Overlay modes

`All annotations` · `Flagged only` · `Selected only` · `Hidden`. Plus toggles for
labels and ids, and "Zoom to selection" which crops around the selected geometry
with 40% padding. Zoom is a real crop, not CSS scaling. No pan control unless it
works.

## Navigation

- Previous/next finding walks the filtered findings list across images.
- Previous/next image walks images (or frames) that have findings first; a toggle
  allows walking all images.
- Selecting a finding anywhere (Overview, Issues) sets `selected_issue_id` in
  session state and switches to the Inspector, which opens the right image.
- Escape-to-clear and arrow-key shortcuts only if implemented with native
  Streamlit support; never capture keys while a text input has focus.

## Missing images

If the dataset has no pixel data for the record, render an *annotation-only
canvas*: neutral background at the declared image size, a faint 10% grid, the
geometry, and a caption "Source image not available. Showing annotation geometry
on a blank canvas." Never synthesize or substitute a photo.

## Details panel

Order: severity + kind, rule id and name, plain-language explanation, suggested
action, then facts (category, geometry type, annotation id, track/frame), then
coordinates as a small two-column table in source format **and** normalized
`x1, y1, x2, y2`, then source location, then a collapsed "Raw evidence" JSON.

## Dense scenes

- More than 60 objects: labels off by default, ids off, outlines 1.5px.
- Selected object always drawn last (on top).
- Findings list groups by severity, critical first.
