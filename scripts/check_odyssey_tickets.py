#!/usr/bin/env python3
"""
Checks the ODEON film page for "The Odyssey" and records which dates have
bookable showings at ODEON Luxe London Leicester Square. When a date shows
up that wasn't there on the previous run, it means ODEON has just released
new tickets for that day, and we post a notification to a tracking GitHub
issue.

State (the last known set of available dates) is persisted to
data/odyssey_dates.json and committed back to the repo by the workflow,
since GitHub Actions runners are ephemeral.
"""
import datetime
import json
import os
import re
import sys
import traceback
from pathlib import Path

import requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

FILM_URL = "https://www.odeon.co.uk/films/the-odyssey-70mm/HO00009035/"
CINEMA_NAME = "Leicester Square"
DAYS_AHEAD_TO_CHECK = 21
TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")

REPO_ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = REPO_ROOT / "data" / "odyssey_dates.json"
SCREENSHOT_PATH = REPO_ROOT / "data" / "last_error.png"
DEBUG_SCREENSHOT_PATH = REPO_ROOT / "data" / "debug_page.png"
DEBUG_HTML_PATH = REPO_ROOT / "data" / "debug_page.html"

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.environ.get("GITHUB_REPOSITORY")  # "owner/repo"
TRACKING_LABEL = "odyssey-tracker"


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"available_dates": [], "last_checked_utc": None, "last_status": None,
            "tracking_issue_number": None}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def date_match_patterns(day: datetime.date) -> list[str]:
    return [
        day.strftime("%a %-d").lower(),        # "fri 24"
        day.strftime("%-d %b").lower(),        # "24 jul"
        day.strftime("%A %-d %B").lower(),     # "friday 24 july"
        day.strftime("%-d %B").lower(),        # "24 july"
    ]


def accept_cookies(page) -> None:
    for selector in [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accept All Cookies')",
        "button:has-text('Accept all cookies')",
        "button:has-text('Accept All')",
        "button:has-text('I Accept')",
    ]:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=2000):
                locator.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue


def find_and_click_date_tab(page, day: datetime.date) -> bool:
    """Try to find a clickable element representing `day` and click it.
    Returns True if a matching tab was found and clicked."""
    patterns = date_match_patterns(day)
    candidates = page.locator("button, a, [role=tab], [role=button]")
    count = candidates.count()
    texts = candidates.all_inner_texts()
    for idx in range(min(count, len(texts))):
        text = (texts[idx] or "").strip().lower()
        if not text:
            continue
        if any(pattern in text for pattern in patterns):
            try:
                candidates.nth(idx).click(timeout=3000)
                page.wait_for_timeout(1500)
                return True
            except Exception:
                continue
    return False


def leicester_square_has_times(page) -> bool:
    """After selecting a date, check whether Leicester Square is listed
    with any bookable times on the current page."""
    try:
        cinema_locator = page.get_by_text(re.compile(CINEMA_NAME, re.IGNORECASE)).first
        if not cinema_locator.is_visible(timeout=3000):
            return False
    except Exception:
        return False

    # Walk up to a reasonably-sized ancestor container and scan its text
    # for time-of-day patterns (e.g. "14:30"), which indicate bookable
    # performances rather than just the cinema's name being present.
    try:
        container = cinema_locator.locator(
            "xpath=ancestor::*[self::section or self::article or self::li or self::div][3]"
        )
        text = container.first.inner_text(timeout=3000)
    except Exception:
        try:
            text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            return False

    return bool(TIME_PATTERN.search(text))


def scrape_available_dates() -> list[str]:
    available = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ))
        try:
            page.goto(FILM_URL, wait_until="domcontentloaded", timeout=30000)
            print(f"Loaded: {page.url!r} title={page.title()!r}")
            accept_cookies(page)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                print("networkidle wait timed out; continuing anyway")
            page.wait_for_timeout(2000)

            body_text = page.locator("body").inner_text(timeout=5000)
            print(f"Body text length: {len(body_text)} chars")
            if any(marker in body_text.lower() for marker in
                   ["just a moment", "attention required", "checking your browser",
                    "enable javascript and cookies"]):
                raise RuntimeError(
                    "Odeon returned a bot-protection challenge page instead of the film "
                    f"listing (title={page.title()!r}). The scraper was blocked, not "
                    "just seeing an empty schedule."
                )

            all_clickable = page.locator("button, a, [role=tab], [role=button]")
            clickable_count = all_clickable.count()
            sample_texts = [t.strip() for t in all_clickable.all_inner_texts()[:40] if t.strip()]
            print(f"Found {clickable_count} clickable elements. Sample texts: {sample_texts}")

            DEBUG_SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
            DEBUG_HTML_PATH.write_text(page.content())

            today = datetime.date.today()
            for offset in range(DAYS_AHEAD_TO_CHECK):
                day = today + datetime.timedelta(days=offset)
                found_tab = find_and_click_date_tab(page, day)
                if not found_tab:
                    # No tab for this day at all -> ODEON hasn't opened
                    # this day for booking yet anywhere.
                    continue
                if leicester_square_has_times(page):
                    available.append(day.isoformat())
        except Exception:
            try:
                SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(SCREENSHOT_PATH))
            except Exception:
                pass
            raise
        finally:
            browser.close()
    return available


def github_api(method: str, path: str, **kwargs):
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        print("Missing GITHUB_TOKEN or GITHUB_REPOSITORY; skipping GitHub API call.")
        return None
    url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}{path}"
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "odyssey-ticket-tracker",
    }
    resp = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    resp.raise_for_status()
    if resp.content:
        return resp.json()
    return None


def get_or_create_tracking_issue(state: dict) -> int | None:
    issue_number = state.get("tracking_issue_number")
    if issue_number:
        try:
            issue = github_api("GET", f"/issues/{issue_number}")
            if issue and issue.get("state") == "open":
                return issue_number
        except requests.HTTPError:
            pass

    results = github_api("GET", f"/issues?labels={TRACKING_LABEL}&state=open")
    if results:
        return results[0]["number"]

    created = github_api(
        "POST",
        "/issues",
        json={
            "title": "Odyssey ticket tracker — Odeon Leicester Square",
            "body": (
                "This issue tracks newly-released showing dates for "
                "**The Odyssey** at **ODEON Luxe London Leicester Square**.\n\n"
                f"Film page: {FILM_URL}\n\n"
                "A new comment is posted here every time new dates go on sale."
            ),
            "labels": [TRACKING_LABEL],
        },
    )
    return created["number"] if created else None


def post_comment(issue_number: int, body: str) -> None:
    if issue_number is None:
        print(f"[no GitHub issue] {body}")
        return
    github_api("POST", f"/issues/{issue_number}/comments", json={"body": body})


def notify_new_dates(state: dict, new_dates: list[str]) -> None:
    issue_number = get_or_create_tracking_issue(state)
    state["tracking_issue_number"] = issue_number
    dates_list = "\n".join(f"- {d}" for d in sorted(new_dates))
    body = (
        "\U0001F3AC **New Odyssey showings just went on sale at Odeon Leicester Square:**\n\n"
        f"{dates_list}\n\n"
        f"Book here: {FILM_URL}"
    )
    post_comment(issue_number, body)


def notify_error(state: dict, message: str) -> None:
    issue_number = get_or_create_tracking_issue(state)
    state["tracking_issue_number"] = issue_number
    post_comment(
        issue_number,
        "⚠️ The Odyssey ticket checker failed to scrape the ODEON site "
        f"(the page structure may have changed):\n\n```\n{message}\n```",
    )


def notify_recovered(state: dict) -> None:
    issue_number = state.get("tracking_issue_number")
    if issue_number:
        post_comment(issue_number, "✅ The Odyssey ticket checker is working again.")


def main() -> int:
    state = load_state()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        current_dates = scrape_available_dates()
    except Exception:
        error_text = traceback.format_exc()
        print(error_text, file=sys.stderr)
        if state.get("last_status") != "error":
            notify_error(state, error_text)
        state["last_status"] = "error"
        state["last_checked_utc"] = now
        save_state(state)
        return 1

    previous_dates = set(state.get("available_dates", []))
    new_dates = sorted(set(current_dates) - previous_dates)

    if new_dates:
        print(f"New dates released: {new_dates}")
        notify_new_dates(state, new_dates)
    else:
        print("No new dates since last check.")

    if state.get("last_status") == "error":
        notify_recovered(state)

    state["available_dates"] = sorted(set(current_dates))
    state["last_status"] = "ok"
    state["last_checked_utc"] = now
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
