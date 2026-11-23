"""Capture README screenshots and an animated walkthrough from the running app.

Only screens without dataset imagery are captured (overview, issues, reports,
settings), because BDD100K photographs are not redistributed in this repository.

    python scripts/capture_walkthrough.py            # app must run on :8517 with the BDD100K sample
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright


def ready(page: Page, ms: int = 1800) -> None:
    page.wait_for_selector('[data-testid="stMainBlockContainer"]', timeout=60_000)
    page.wait_for_timeout(400)
    for _ in range(120):
        if not page.locator('[data-testid="stStatusWidget"]').count():
            break
        page.wait_for_timeout(250)
    page.wait_for_timeout(ms)


def shot(page: Page) -> Image.Image:
    return Image.open(io.BytesIO(page.screenshot())).convert("RGB")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8517")
    ap.add_argument("--out", type=Path, default=Path("assets/screenshots"))
    ap.add_argument("--channel", default="msedge")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=True)
        for theme in ("dark", "light"):
            page = browser.new_context(viewport={"width": 1440, "height": 900}, color_scheme=theme).new_page()
            page.goto(args.url)
            ready(page)
            page.get_by_role("combobox", name="Active dataset").click()
            page.keyboard.type("corrupted")
            page.keyboard.press("Enter")
            ready(page)
            frames = [shot(page)]
            shot(page).save(args.out / f"overview_{theme}.png")
            page.get_by_role("link", name="Issues").click()
            ready(page)
            shot(page).save(args.out / f"issues_{theme}.png")
            frames.append(shot(page))
            page.get_by_role("button", name="Structural").click()
            ready(page)
            frames.append(shot(page))
            page.get_by_role("link", name="Reports").click()
            ready(page)
            shot(page).save(args.out / f"reports_{theme}.png")
            frames.append(shot(page))
            page.get_by_role("link", name="Settings").click()
            ready(page)
            page.get_by_role("tab", name="Validation").click()
            ready(page, 800)
            frames.append(shot(page))
            if theme == "dark":
                small = [f.resize((1080, 675), Image.Resampling.LANCZOS) for f in frames]
                small[0].save(
                    args.out / "walkthrough.gif",
                    save_all=True,
                    append_images=small[1:],
                    duration=2200,
                    loop=0,
                    optimize=True,
                )
            page.context.close()
        browser.close()
    print(sorted(p.name for p in args.out.iterdir()))


if __name__ == "__main__":
    main()
