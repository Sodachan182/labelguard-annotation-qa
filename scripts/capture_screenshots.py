"""Visual QA captures (see .claude/skills/visual-qa).

Drives a running LabelGuard (default http://localhost:8517) with Playwright using
the locally installed Microsoft Edge (or Chrome) — no browser download needed —
and writes PNGs plus a JSON log of layout checks (horizontal overflow).

    python scripts/capture_screenshots.py --out data/screenshots

Screenshots of BDD100K-backed screens contain BDD100K imagery; keep them in the
git-ignored data/ folder unless the BDD100K license notice accompanies them.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

VIEWPORTS = {"1920": (1920, 1080), "1440": (1440, 900), "1366": (1366, 768), "1024": (1024, 768), "390": (390, 844)}
PAGES = ["overview", "datasets", "issues", "inspector", "reports", "settings"]


def wait_ready(page: Page) -> None:
    page.wait_for_selector('[data-testid="stMainBlockContainer"]', timeout=60_000)
    page.wait_for_timeout(600)
    for _ in range(120):
        if not page.locator('[data-testid="stStatusWidget"]').count():
            break
        page.wait_for_timeout(250)
    page.wait_for_timeout(1200)


def overflow(page: Page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8517")
    ap.add_argument("--out", type=Path, default=Path("data/screenshots"))
    ap.add_argument("--channel", default="msedge")
    ap.add_argument("--viewports", default=",".join(VIEWPORTS))
    ap.add_argument("--themes", default="dark,light")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    log = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=True)
        for theme in args.themes.split(","):
            for vp in args.viewports.split(","):
                w, h = VIEWPORTS[vp]
                ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=theme, device_scale_factor=1)
                page = ctx.new_page()
                for name in PAGES:
                    page.goto(f"{args.url}/" if name == "overview" else f"{args.url}/{name}")
                    wait_ready(page)
                    if name == "inspector":
                        first = page.locator(".st-key-findings-list button").first
                        if first.count():
                            first.dispatch_event("click")
                            wait_ready(page)
                    path = args.out / f"{theme}_{vp}_{name}.png"
                    page.screenshot(path=str(path), full_page=True)
                    log.append(
                        {
                            "theme": theme,
                            "viewport": vp,
                            "page": name,
                            "horizontal_overflow_px": overflow(page),
                            "exceptions": page.locator('[data-testid="stException"]').count(),
                        }
                    )
                    print(log[-1])
                ctx.close()
        browser.close()
    (args.out / "visual_qa_log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
