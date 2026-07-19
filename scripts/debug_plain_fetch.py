#!/usr/bin/env python3
"""One-off diagnostic: does a plain HTTP GET (no browser) get past Odeon's
Cloudflare block, or does it hit the same wall as the Playwright-driven
checker? Prints status code and a body snippet; not used by the main
checker workflow."""
import requests

URL = "https://www.odeon.co.uk/films/the-odyssey-70mm/HO00009035/"

resp = requests.get(
    URL,
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
print(f"status_code={resp.status_code}")
print(f"final_url={resp.url}")
print(f"content_length={len(resp.text)}")
print(f"server_header={resp.headers.get('server')}")
print("---first 1500 chars---")
print(resp.text[:1500])
