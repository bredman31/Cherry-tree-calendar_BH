#!/usr/bin/env python3
"""
odeon.co.uk blocks automated requests (browser and plain HTTP alike) with
a Cloudflare challenge, so this scrapes flicks.co.uk's listing for ODEON
Luxe London Leicester Square instead - confirmed to accurately reflect
Odeon's real on-sale window (it goes empty past the actual cutoff date,
not just a generic recurring schedule). Records which dates have bookable
showings of "The Odyssey"; when a date shows up that wasn't there on the
previous run, posts a notification to a tracking GitHub issue.

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

SOURCE_URL = "https://www.flicks.co.uk/cinema/odeon-cinema-luxe-leicester-square/"
BOOKING_URL = "https://www.odeon.co.uk/films/the-odyssey-70mm/HO00009035/"
FILM_MARKER = "odyssey"
DAYS_AHEAD_TO_CHECK = 21
TIME_PATTERN = re.compile(r"\d{1,2}:\d{2}\s*(am|pm)", re.IGNORECASE)

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
        day.strftime("%a %-d %b").lower(),     # "fri 24 jul" - full, exact-match preferred
        day.strftime("%a %-d").lower(),        # "fri 24" - loose fallback
        day.strftime("%-d %b").lower(),        # "24 jul" - loose fallback
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


def _click_candidate(page, candidates, idx: int) -> bool:
    try:
        candidates.nth(idx).click(timeout=3000)
    except Exception:
        return False
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1500)
    return True


def find_and_click_date_tab(page, day: datetime.date) -> bool:
    """Try to find a clickable element representing `day` and click it.
    Returns True if a matching tab was found and clicked. Prefers an
    exact full-date match (e.g. "fri 24 jul") over a loose substring
    match, to avoid accidentally clicking an unrelated element whose
    text happens to contain a shorter date fragment."""
    full_pattern, *loose_patterns = date_match_patterns(day)
    candidates = page.locator("button, a, [role=tab], [role=button], li")
    texts = candidates.all_inner_texts()
    normalized = [" ".join((t or "").strip().lower().split()) for t in texts]

    exact_matches = [i for i, norm in enumerate(normalized) if norm == full_pattern]
    if len(exact_matches) == 1:
        return _click_candidate(page, candidates, exact_matches[0])

    for idx, norm in enumerate(normalized):
        if not norm or len(norm) >= 20:
            continue
        if any(pattern in norm for pattern in loose_patterns):
            if _click_candidate(page, candidates, idx):
                return True
    return False


def film_has_showtime(page) -> bool:
    """After selecting a date, check whether the film is listed with a
    real showtime on the current page."""
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False

    lower = text.lower()
    idx = lower.find(FILM_MARKER)
    if idx == -1:
        return False
    snippet = text[idx:idx + 300]
    return bool(TIME_PATTERN.search(snippet))


def scrape_available_dates() -> list[str]:
    available = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ))
        try:
            page.goto(SOURCE_URL, wait_until="domcontentloaded", timeout=30000)
            print(f"Loaded: {page.url!r} title={page.title()!r}")
            accept_cookies(page)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeoutError:
                print("networkidle wait timed out; continuing anyway")
            page.wait_for_timeout(2000)

            body_text = page.locator("body").inner_text(timeout=5000)
            print(f"Body text length: {len(body_text)} chars")
            challenge_haystack = f"{page.title()}\n{body_text}".lower()
            if any(marker in challenge_haystack for marker in
                   ["just a moment", "attention required", "checking your browser",
                    "enable javascript and cookies", "cloudflare ray id",
                    "sorry, you have been blocked"]):
                raise RuntimeError(
                    "flicks.co.uk returned a bot-protection challenge page instead of "
                    f"the listing (title={page.title()!r}). The scraper was blocked, "
                    "not just seeing an empty schedule."
                )

            DEBUG_SCREENSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(DEBUG_SCREENSHOT_PATH), full_page=True)
            DEBUG_HTML_PATH.write_text(page.content())

            today = datetime.date.today()
            for offset in range(DAYS_AHEAD_TO_CHECK):
                day = today + datetime.timedelta(days=offset)
                found_tab = find_and_click_date_tab(page, day)
                if not found_tab:
                    # No tab for this day at all -> not open for booking
                    # yet anywhere on this listing.
                    continue
                if film_has_showtime(page):
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
                f"Book here: {BOOKING_URL}\n"
                f"(Tracked via {SOURCE_URL} since odeon.co.uk blocks automated "
                "requests.)\n\n"
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
        f"Book here: {BOOKING_URL}"
    )
    post_comment(issue_number, body)


def notify_error(state: dict, message: str) -> None:
    issue_number = get_or_create_tracking_issue(state)
    state["tracking_issue_number"] = issue_number
    post_comment(
        issue_number,
        "⚠️ The Odyssey ticket checker failed to scrape flicks.co.uk "
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
