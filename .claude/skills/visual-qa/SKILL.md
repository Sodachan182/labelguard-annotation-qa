---
name: visual-qa
description: Visual QA procedure for LabelGuard — run the Streamlit app, capture real browser screenshots at standard viewports and both themes, and check layout, contrast, overflow, states and interactions. Use after any UI change and before publishing screenshots or releases.
---

# Visual QA for LabelGuard

Source code is not evidence. A screen is done only after it was rendered in a real
browser and looked at.

## 1. Run

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.port 8517 --server.headless true
```

Automated captures: `.\.venv\Scripts\python.exe scripts\capture_screenshots.py`
(Playwright, Chromium). It loads the demo dataset, visits each page and writes PNGs
to `assets/screenshots/`. Interactive checks can use the Claude browser pane.

## 2. Matrix

Viewports: 1920×1080, 1440×900, 1366×768, 1024×768, 390×844.
Themes: dark (primary), light.
States to visit:

1. Empty app (no dataset)
2. Datasets page with upload zone
3. Demo loaded and validated
4. Clean dataset (no findings) — overview and issues empty states
5. Corrupted dataset with critical findings
6. Issue table filtered to zero results
7. A selected finding opened in the Inspector
8. Inspector with overlays, labels and ids on
9. Inspector with a dataset that has no images
10. Settings with changed thresholds, then re-run validation
11. Reports page, each download button

## 3. Checklist per screenshot

- [ ] Page title and description aligned with the content column
- [ ] No horizontal scroll at any viewport (`document.documentElement.scrollWidth <= innerWidth`)
- [ ] No clipped text in metrics, chips, table headers or sidebar
- [ ] Controls on a row share height (36px) and baseline
- [ ] Only one accent color visible; severity colors only on severity data
- [ ] Severity readable without color (glyph + word)
- [ ] Body text contrast ≥ 4.5:1, muted text ≥ 4.5:1 on its background
- [ ] Focus ring visible when tabbing through buttons and inputs
- [ ] Overlay boxes sit exactly on objects (compare one box's corner to its coordinates)
- [ ] Selected annotation identifiable within one second
- [ ] Charts: transparent background, readable ticks, no legend duplication
- [ ] Empty and loading states say what to do next

## 4. Regression habit

Keep the latest screenshots in `assets/screenshots/`. After a UI change, re-capture
and compare the same states side by side. Note every defect found and fixed in
`TASKS.md` under "Visual QA log".
