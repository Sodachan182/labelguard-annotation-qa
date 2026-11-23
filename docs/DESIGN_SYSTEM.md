# Design system and design reviews

The binding rules live in the project skill
[`.claude/skills/labelguard-design-system/SKILL.md`](../.claude/skills/labelguard-design-system/SKILL.md);
inspector rules in [`annotation-inspector-ux`](../.claude/skills/annotation-inspector-ux/SKILL.md);
the screenshot procedure in [`visual-qa`](../.claude/skills/visual-qa/SKILL.md).

## Direction

LabelGuard is an instrument for engineers auditing labels. Chrome stays quiet so geometry
and findings carry the page. The single memorable element is the **selection-corner
mark**: four L-shaped ticks around a box. It is the logo and the Inspector's selection
treatment, and it appears nowhere else.

| | Dark (primary) | Light |
|---|---|---|
| App / panel | `#0D0F12` / `#171A20` | `#F6F5F2` / `#FFFFFF` (warm stone, not an inversion) |
| Text / secondary / muted | `#EDF0F4` / `#A1A8B3` / `#7C8592` | `#1D2229` / `#4D5562` / `#6B7280` |
| Single accent | `#8B98F9` | `#4F5BD5` |
| Critical / warning / info | `#E88080` / `#E5B567` / `#7FACE3` | `#B93A3A` / `#9A6A12` / `#2F6DB0` |

Type: Geist (bundled, SIL OFL) with Segoe UI / system fallbacks; Geist Mono only for raw
evidence and source paths; tabular numerals for metrics, tables and coordinates. Scale:
26 / 16 / 14 / 13 / 12 px. Spacing on a 4/8 px grid; radii 6 px for controls, 10 px for
panels, 14 px for the upload zone.

## How the official frontend-design guidance was applied

The official `frontend-design` skill (anthropics/claude-plugins-official) was read before
any UI code was written. Its install card was offered in the Claude desktop app; there was
no `claude` CLI on the machine to install it from the terminal. Decisions it drove:

- **Avoid template tells.** No all-caps eyebrows, no `→` appended to buttons, no gradient
  washes, no identical rounded KPI cards with drop shadows. The four metrics share **one**
  bordered strip with dividers.
- **Structure is information.** Borders appear only on the metric strip, tables, the
  details panel and the upload zone. Severity is glyph plus word (● Critical, ▲ Warning,
  ■ Info), never colour alone. Numbering is not used, because nothing here is a sequence.
- **Spend boldness once:** the selection-corner mark.
- **Copy:** sentence case, verbs that say what happens ("Run validation",
  "Open in Inspector", "Download CSV"); empty states say what is missing and what to do.
- **Self-critique with real screenshots:** see the reviews below.

The brief pinned a near-black palette and Inter/Geist. The skill flags tinted near-black as
a common default, but the brief's own words take precedence, so the pinned palette was
kept and refined for contrast. Geist was chosen over Inter as the less default option.

## Review 1: plan (before implementation)

Checked the layout sketches against the brief and the skills: one accent; severity colours
only on severity data; Streamlit-native widgets for keyboard accessibility; Inspector as
three columns (findings, canvas, details) with navigation under the canvas; light theme as
warm stone rather than an inverted dark theme.

## Review 2: working application (real BDD100K data)

| Found in a real screenshot | Fix |
|---|---|
| Dataset names rendered as `standard â€” original` (mojibake) | Repaired double-encoded source files; switched to encoding-safe edits |
| Five Inspector navigation buttons wrapped onto two rows | Image navigation moved beside the image selector as icon buttons with accessible labels; finding navigation is three buttons |
| Zoom magnified a 28 px car 20×, an unreadable blur | Zoom capped at 5× relative to the full frame |
| Zoomed view stacked edge-clamped tags of off-screen objects | Tags drawn only for objects in view; other objects dimmed with the veil |
| Coordinates table overflowed the details column | Fixed table layout, one-decimal values, full value in the tooltip |
| Fractional ticks (0.2, 0.4 …) on count charts | Integer ticks; small ranges use a step of 1 |
| Corrupted dataset silently missing after "Load sample" | Format sniffer accepts JSON arrays; import errors survive the rerun |
| Refreshing the page lost all loaded data | Last BDD100K sample is reloaded on new sessions (can be turned off in Settings) |
| Streamlit listened on all network interfaces | `server.address = "localhost"` |

## Review 3: final polish

| Found | Fix |
|---|---|
| Sidebar covered the content at 390 px | `initial_sidebar_state="auto"` collapses it on phones |
| On phones the findings list came before the canvas | CSS `order` puts the canvas first when columns stack |
| Details panel used two definition lists with misaligned labels | Merged into one list |
| "1 annotations flagged" | Pluralised |
| Issues table drew an empty trailing row | Auto height for short tables |

Final matrix: dark and light × 1920, 1440, 1366, 1024 and 390 px × six pages = 60 captures,
0 horizontal overflow, 0 exceptions (`scripts/capture_screenshots.py`, log in
`data/screenshots/visual_qa_log.json`).
