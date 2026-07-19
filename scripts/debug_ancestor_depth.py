#!/usr/bin/env python3
"""One-off: for a couple of specific dates, print the text captured at
each ancestor depth around the "Odyssey" title element, to figure out
the right container depth to scope film_has_showtime() to."""
import datetime
import re

from playwright.sync_api import sync_playwright

URL = "https://www.flicks.co.uk/cinema/odeon-cinema-luxe-leicester-square/"
TEST_OFFSETS_DAYS = [6, 14]  # Jul25 (real listing), Aug2 (the anomaly)


def date_match_patterns(day: datetime.date) -> list[str]:
    return [day.strftime("%a %-d %b").lower(), day.strftime("%a %-d").lower(),
            day.strftime("%-d %b").lower()]


def find_and_click_date_tab(page, day: datetime.date) -> bool:
    full_pattern, *loose = date_match_patterns(day)
    candidates = page.locator("button, a, [role=tab], [role=button], li")
    texts = candidates.all_inner_texts()
    normalized = [" ".join((t or "").strip().lower().split()) for t in texts]
    exact = [i for i, n in enumerate(normalized) if n == full_pattern]
    idxs = exact if len(exact) == 1 else [
        i for i, n in enumerate(normalized)
        if n and len(n) < 20 and any(p in n for p in loose)
    ]
    for idx in idxs:
        try:
            candidates.nth(idx).click(timeout=3000)
            page.wait_for_timeout(2000)
            return True
        except Exception:
            continue
    return False


with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page(user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ))
    page.goto(URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    today = datetime.date.today()
    for offset in TEST_OFFSETS_DAYS:
        day = today + datetime.timedelta(days=offset)
        print(f"\n\n========== {day.isoformat()} (+{offset}d) ==========")
        found = find_and_click_date_tab(page, day)
        print(f"tab_found={found}")
        if not found:
            continue

        title_locator = page.get_by_text(re.compile("odyssey", re.IGNORECASE))
        count = title_locator.count()
        print(f"matching 'odyssey' elements on page: {count}")
        for m in range(count):
            loc = title_locator.nth(m)
            try:
                own_text = loc.inner_text(timeout=2000)
            except Exception:
                own_text = "<error>"
            print(f"\n--- match {m}: own_text={own_text[:80]!r} ---")
            for depth in [1, 2, 3, 4]:
                try:
                    container = loc.locator(
                        f"xpath=ancestor::*[self::li or self::article or self::section or self::div][{depth}]"
                    )
                    text = container.first.inner_text(timeout=2000)
                    print(f"  depth {depth}: len={len(text)} text={text[:200]!r}")
                except Exception as exc:
                    print(f"  depth {depth}: error {exc!r}")

    browser.close()
