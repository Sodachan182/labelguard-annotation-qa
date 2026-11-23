---
name: labelguard-design-system
description: LabelGuard visual design system — tokens, type scale, spacing, component standards and rejection criteria for the Streamlit UI. Use before creating or changing any LabelGuard screen, chart, table, CSS or copy, and when reviewing UI screenshots.
---

# LabelGuard design system

LabelGuard is a precision tool for computer-vision engineers who audit annotation
datasets. The interface should read like an instrument: quiet chrome, dense but
legible data, and one memorable element — the annotation canvas in the Inspector.
Everything else stays disciplined so the geometry and the findings carry the page.

## Principles

1. **Data over decoration.** Every border, color and label must encode information.
   If removing an element loses no information, remove it.
2. **One accent.** Indigo (`--accent`) marks interaction and selection only.
   Severity colors appear only where they encode severity.
3. **Never color alone.** Severity is always color + text label (and a shape glyph
   in dense lists).
4. **Structural vs heuristic is always visible.** A confirmed structural error and a
   heuristic warning must never look identical. Use the words "Structural" and
   "Heuristic", not icons alone.
5. **Spend boldness once.** The selection-corner motif (four L-shaped corners
   around a box) is the brand mark and the Inspector's selection treatment. Do not
   repeat it as decoration elsewhere.

## Tokens

Colors are defined once in `src/labelguard/ui/theme.py` and emitted as CSS custom
properties. Never hard-code a hex value in a page module.

| Token | Dark | Light | Use |
|---|---|---|---|
| `--bg-app` | `#0D0F12` | `#F6F5F2` | App canvas |
| `--bg-sidebar` | `#121519` | `#EFEDE8` | Sidebar |
| `--bg-panel` | `#171A20` | `#FFFFFF` | Panels, tables, inputs |
| `--bg-hover` | `#20242B` | `#ECEAE5` | Row hover, list hover |
| `--border` | `#272C34` | `#DEDAD2` | 1px dividers only |
| `--text-primary` | `#EDF0F4` | `#1D2229` | Titles, values |
| `--text-secondary` | `#A1A8B3` | `#4D5562` | Body, table text |
| `--text-muted` | `#7C8592` | `#6B7280` | Captions, axis labels (AA on bg) |
| `--accent` | `#8B98F9` | `#4F5BD5` | Selection, focus, primary action |
| `--critical` | `#E88080` | `#B93A3A` | Critical severity |
| `--warning` | `#E5B567` | `#9A6A12` | Warning severity |
| `--info` | `#7FACE3` | `#2F6DB0` | Info severity |
| `--success` | `#6CC3A9` | `#23795F` | Passed / clean |

The light palette is a warm neutral, not an inversion: the hue of the neutrals is
shifted toward stone, and severity colors are darkened to pass AA on white.

Radii: `--radius-sm: 6px` (chips, inputs), `--radius-md: 10px` (panels, tables),
`--radius-lg: 14px` (upload drop zone only). Nothing else.

Shadows: none, except focus rings. Elevation is expressed with `--bg-panel` vs
`--bg-app` and a 1px border.

## Typography

- Family: **Geist** (SIL OFL, loaded from Google Fonts) with fallbacks
  `"Segoe UI", system-ui, -apple-system, sans-serif`. Offline, the system fallback
  is used and must still look correct.
- Monospace (**Geist Mono**) is reserved for raw evidence: JSON, XML source paths,
  coordinate tuples. Never for labels or metrics.
- Numbers: `font-variant-numeric: tabular-nums` on metrics, tables, coordinates.
- Scale (px): page title 26 / 600, section title 16 / 600, body 14 / 400,
  supporting 13 / 400, caption 12 / 500, metric value 26 / 500.
- Line height: 1.25 for titles, 1.5 for body.
- Sentence case everywhere. No all-caps labels, no tracked-out eyebrows.

## Spacing and layout

- 4px base, 8px rhythm: 4, 8, 12, 16, 24, 32, 48.
- Page gutter 32px desktop, 16px under 768px.
- Control height 36px. Buttons, selects and text inputs share it.
- Sidebar: native `st.navigation`, 240px, Material Symbols (rounded, 20px) icons.
- Page header: title + one-line description left, actions right, 1px divider below.
- Use dividers and whitespace for grouping. A panel (`--bg-panel` + border +
  `--radius-md`) is allowed only for: metric strip, tables, inspector panels, upload
  zone. **No nested panels.**

## Components

- **Metric strip:** four metrics in one bordered strip separated by vertical
  dividers, not four floating cards. Label 12px muted above, value 26px.
- **Severity chip:** glyph + word (`● Critical`, `▲ Warning`, `■ Info`), 12px,
  colored text on transparent background. Never a filled pill.
- **Kind tag:** "Structural" / "Heuristic" in muted text with a 1px outline.
- **Tables:** native `st.dataframe`, compact row height, single-row selection,
  column config for severity and ids. Selection opens a detail strip below.
- **Charts:** Plotly, transparent background, no gridlines on the category axis,
  light gridlines on the value axis, 12px muted tick labels, horizontal bars for
  categories, severity colors only on severity charts, `--accent` otherwise.
  No pies, no donuts, no 3D, no legends when the axis already labels the series.
- **Empty states:** one sentence about what is missing, one action. No illustrations.

## Copy

- Name things as users know them: "dataset", "finding", "annotation", "frame".
- Buttons are verbs that say what happens: "Run validation", "Open in Inspector",
  "Download CSV". The resulting toast reuses the verb: "Validation finished".
- Errors state what failed and how to fix it. No apologies.
- Do not claim semantic understanding. Heuristic findings say "may", "suspicious",
  "review"; structural findings state the defect plainly.

## Rejection criteria

Reject a screen (and fix before shipping) if it has any of:

- gradient backgrounds, glow, drop shadows on cards, glassmorphism
- emoji in navigation, headings or buttons
- more than one accent color, or severity colors used for decoration
- a hero banner or oversized intro copy
- cards inside cards, or identical rounded cards for everything
- all-caps labels, eyebrows above headings, `→` appended to buttons
- metrics that are not computed from the loaded data
- text clipping, horizontal page scroll, or controls of mismatched heights
- a control that does nothing (decorative zoom buttons, fake links)
- default Streamlit chrome left unstyled (deploy button, hamburger toolbar spacing)
