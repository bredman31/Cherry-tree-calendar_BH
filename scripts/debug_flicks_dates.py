#!/usr/bin/env python3
"""Does flicks.co.uk actually reflect Odeon's real on-sale cutoff, or does
it just show a generic recurring schedule regardless of what's truly
bookable? Clicks into several specific date tabs (one within the known
on-sale window, one just past it, one far in the future) and reports
whether The Odyssey has real showtimes on each."""
import datetime
import re

from playwright.sync_api import sync_playwright

URL = "https://www.flicks.co.uk/cinema/odeon-cinema-luxe-leicester-square/"
TEST_OFFSETS_DAYS = [6, 11, 12, 30]  # Jul25 (within window), Jul30 (stated cutoff), Jul31 (past it), Aug18 (far future)


def date_match_patterns(day: datetime.date) -> list[str]:
    return [
        day.strftime("%a %-d").lower(),
        day.strftime("%-d %b").lower(),
    ]


def find_and_click_date_tab(page, day: datetime.date) -> bool:
    patterns = date_match_patterns(day)
    candidates = page.locator("button, a, [role=tab], [role=button], li")
    texts = candidates.all_inner_texts()
    for idx, text in enumerate(texts):
        norm = " ".join((text or "").strip().lower().split())
        if any(p in norm for p in patterns) and len(norm) < 20:
            try:
                candidates.nth(idx).click(timeout=3000)
                page.wait_for_timeout(1500)
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
        print(f"\n=== {day.isoformat()} (+{offset}d, {day.strftime('%a')}) ===")
        found = find_and_click_date_tab(page, day)
        print(f"tab_found_and_clicked={found}")
        if not found:
            continue
        text = page.locator("body").inner_text(timeout=5000)
        lower = text.lower()
        idx = lower.find("odyssey")
        if idx == -1:
            print("odyssey NOT present on this date's listing")
        else:
            snippet = text[idx:idx + 250]
            has_time = bool(re.search(r"\d{1,2}:\d{2}\s*(am|pm)", snippet, re.IGNORECASE))
            print(f"odyssey present, has_showtime={has_time}")
            print(snippet.replace("\n", " | "))

    browser.close()
