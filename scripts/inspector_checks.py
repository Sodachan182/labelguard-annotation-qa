"""Targeted browser checks for Inspector edge cases (see .claude/skills/visual-qa).

Requires a running app (default http://localhost:8517) with the BDD100K standard
sample restored, and Microsoft Edge (or pass --channel chrome). Writes screenshots
and a JSON log to data/screenshots/inspector_checks/.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

LONG = (
    "front_camera_2026-11-23T10-44-51.123456Z_vehicle_0007_sequence_000042_frame_000318_"
    "very_long_descriptive_name_for_layout_testing.png"
)


def ready(page: Page, extra_ms: int = 1500) -> None:
    page.wait_for_selector('[data-testid="stMainBlockContainer"]', timeout=60_000)
    page.wait_for_timeout(500)
    for _ in range(120):
        if not page.locator('[data-testid="stStatusWidget"]').count():
            break
        page.wait_for_timeout(250)
    page.wait_for_timeout(extra_ms)


def choose(page: Page, label: str, text: str) -> None:
    page.get_by_role("combobox", name=label).first.click()
    page.keyboard.type(text)
    page.keyboard.press("Enter")
    ready(page)


def caption(page: Page) -> str:
    return page.locator(".lg-caption").first.inner_text()


def overflow(page: Page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - window.innerWidth")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8517")
    ap.add_argument("--channel", default="msedge")
    ap.add_argument("--out", type=Path, default=Path("data/screenshots/inspector_checks"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    log: dict = {}
    tmp = Path(tempfile.mkdtemp(prefix="lg-uicheck-"))
    Image.new("RGB", (640, 360), (60, 64, 70)).save(tmp / LONG)
    (tmp / "annotations.xml").write_text(
        "<annotations><version>1.1</version><meta><task><labels><label><name>car</name></label>"
        "</labels></task></meta>"
        f'<image id="0" name="{LONG}" width="640" height="360">'
        '<box label="car" xtl="40" ytl="40" xbr="40" ybr="120"/>'
        '<box label="car" xtl="300" ytl="150" xbr="420" ybr="230"/></image></annotations>',
        encoding="utf-8",
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel, headless=True)
        for theme in ("dark", "light"):
            page = browser.new_context(viewport={"width": 1366, "height": 768}, color_scheme=theme).new_page()
            page.goto(f"{args.url}/inspector")
            ready(page)
            choose(page, "Active dataset", "corrupted")

            # 1. missing image: a record whose file is absent from the subset
            choose(page, "Image", "bf245ae0-5e89fbec")
            log[f"{theme}_missing_image_caption"] = caption(page)
            page.screenshot(path=str(args.out / f"{theme}_missing_image.png"))

            # 2. class filter on a real photo
            choose(page, "Image", "ca1543ec-6ad48f6e")
            before = caption(page)
            choose(page, "Classes", "traffic light")
            page.keyboard.press("Escape")
            ready(page)
            log[f"{theme}_class_filter"] = {"before": before, "after": caption(page)}
            page.screenshot(path=str(args.out / f"{theme}_class_filter.png"))

            # 3. select a finding, then Esc clears it
            choose(page, "Image", "b41ace08-88fb022d")
            page.locator(".st-key-findings-list button").first.dispatch_event("click")
            ready(page)
            selected = page.locator(".st-key-details .lg-finding-title").first.inner_text()
            page.evaluate("document.activeElement && document.activeElement.blur()")
            page.keyboard.press("Escape")
            ready(page)
            log[f"{theme}_esc"] = {
                "selected": selected,
                "after_esc": page.locator(".st-key-details .lg-finding-title").first.inner_text(),
            }

            # 4. long file name uploaded through the UI
            page.get_by_role("link", name="Datasets").click()
            ready(page)
            page.get_by_text("Add dataset").click()
            page.locator('input[type="file"]').set_input_files([str(tmp / "annotations.xml"), str(tmp / LONG)])
            ready(page, 2500)
            page.get_by_role("button", name="Import files").click()
            ready(page, 2500)
            page.screenshot(path=str(args.out / f"{theme}_after_import.png"), full_page=True)
            log[f"{theme}_active_after_import"] = page.get_by_role("combobox", name="Active dataset").input_value()
            page.get_by_role("link", name="Inspector").click()
            ready(page)
            log[f"{theme}_long_name_overflow_px"] = overflow(page)
            page.screenshot(path=str(args.out / f"{theme}_long_filename.png"), full_page=True)
            page.context.close()
        browser.close()
    (args.out / "log.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
