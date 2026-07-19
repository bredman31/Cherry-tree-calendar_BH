#!/usr/bin/env python3
"""One-off diagnostic: does a plain HTTP GET (no browser) get past Odeon's
Cloudflare block, or does it hit the same wall as the Playwright-driven
checker? Prints status code and a body snippet; not used by the main
checker workflow."""
import requests

URLS = [
    "https://www.odeon.co.uk/films/the-odyssey-70mm/HO00009035/",
    "https://www.imdb.com/showtimes/cinema/UK/ci0959835/UK/SG36BN",
    "https://www.tgimovie.com/uk/cinemas/odeon/london-leicester-square",
    "https://www.flicks.co.uk/cinema/odeon-cinema-luxe-leicester-square/",
]

for url in URLS:
    print(f"\n=== {url} ===")
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        print(f"request failed: {exc!r}")
        continue
    print(f"status_code={resp.status_code}")
    print(f"final_url={resp.url}")
    print(f"content_length={len(resp.text)}")
    print(f"server_header={resp.headers.get('server')}")
    lower = resp.text.lower()
    looks_blocked = any(m in lower for m in
                         ["attention required", "cloudflare", "captcha", "access denied",
                          "just a moment", "enable javascript and cookies"])
    print(f"looks_blocked={looks_blocked}")
    contains_odyssey = "odyssey" in lower
    print(f"mentions_odyssey={contains_odyssey}")
    print("---first 800 chars---")
    print(resp.text[:800])
