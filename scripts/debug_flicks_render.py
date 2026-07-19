#!/usr/bin/env python3
"""One-off diagnostic: render flicks.co.uk's Leicester Square cinema page
with a real browser and dump a screenshot + visible text, so the actual
showtimes structure can be inspected (unlike odeon.co.uk, this site did
not return a bot-protection challenge to a plain HTTP GET)."""
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "https://www.flicks.co.uk/cinema/odeon-cinema-luxe-leicester-square/"
OUT_DIR = Path(__file__).resolve().parent.parent / "data"

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ))
    page.goto(URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT_DIR / "flicks_render.png"), full_page=True)
    text = page.locator("body").inner_text(timeout=5000)
    (OUT_DIR / "flicks_render.txt").write_text(text)
    print(f"title={page.title()!r}")
    print(f"visible_text_length={len(text)}")
    lower = text.lower()
    idx = lower.find("odyssey")
    if idx == -1:
        print("'odyssey' NOT found in rendered visible text")
    else:
        print("--- context around rendered 'odyssey' mention ---")
        print(text[max(0, idx - 400):idx + 400])
    browser.close()
