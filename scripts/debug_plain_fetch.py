#!/usr/bin/env python3
"""One-off diagnostic: does a plain HTTP GET (no browser) get past Odeon's
Cloudflare block, or does it hit the same wall as the Playwright-driven
checker? Prints status code and a body snippet; not used by the main
checker workflow."""
import requests

import re

URL = "https://www.flicks.co.uk/cinema/odeon-cinema-luxe-leicester-square/"

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
print(f"content_length={len(resp.text)}")

# Look for JSON-LD structured data (schema.org) - the robust, machine-readable option
ld_blocks = re.findall(
    r'<script type="application/ld\+json">(.*?)</script>', resp.text, re.DOTALL
)
print(f"json_ld_blocks_found={len(ld_blocks)}")
for i, block in enumerate(ld_blocks):
    if "odyssey" in block.lower():
        print(f"\n--- JSON-LD block {i} (mentions odyssey) ---")
        print(block[:3000])

# Also show raw text context around each "odyssey" mention
lower = resp.text.lower()
idx = 0
count = 0
while True:
    idx = lower.find("odyssey", idx)
    if idx == -1 or count >= 5:
        break
    print(f"\n--- context around match {count} (char {idx}) ---")
    print(resp.text[max(0, idx - 300):idx + 300])
    idx += 7
    count += 1
