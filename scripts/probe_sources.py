"""
One-off reconnaissance script: fetches each of the four MLB data sources and
prints enough of their raw structure (status code, content-type, embedded
JSON markers, table counts, snippets) to design real parsers against.

Meant to be run once from GitHub Actions (which has normal internet access,
unlike the dev sandbox) via the "Probe Sources" workflow. Not part of the
daily pipeline.
"""

import json
import re
import sys

import requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

REDDIT_HEADERS = {
    "User-Agent": "mlb-daily-tracker/1.0 (personal project; by u/unknown)",
}

SNIPPET_CHARS = 2500


def hr(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def probe_html(label, url, headers=BROWSER_HEADERS):
    hr(f"{label}: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        print(f"REQUEST FAILED: {e}")
        return None
    print(f"status={r.status_code}  content-type={r.headers.get('content-type')}  bytes={len(r.content)}")
    if r.status_code != 200:
        print(r.text[:1000])
        return r

    text = r.text

    # Look for embedded JSON blobs (Next.js/Nuxt/Wordpress REST hints, etc.)
    markers = ["__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "application/ld+json", "window.__", "/wp-json/"]
    found = [m for m in markers if m in text]
    print(f"embedded-data markers found: {found or 'none'}")

    table_count = len(re.findall(r"<table", text, re.I))
    print(f"<table> tag count: {table_count}")

    script_json_blocks = re.findall(r'<script[^>]+type="application/(?:ld\+)?json"[^>]*>(.*?)</script>', text, re.S)
    print(f"<script type=json> blocks found: {len(script_json_blocks)}")
    for i, block in enumerate(script_json_blocks[:2]):
        print(f"--- json block {i} (first 800 chars) ---")
        print(block.strip()[:800])

    print(f"--- raw HTML snippet (first {SNIPPET_CHARS} chars) ---")
    print(text[:SNIPPET_CHARS])
    return r


def probe_json(label, url, headers=REDDIT_HEADERS):
    hr(f"{label}: {url}")
    try:
        r = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        print(f"REQUEST FAILED: {e}")
        return None
    print(f"status={r.status_code}  content-type={r.headers.get('content-type')}  bytes={len(r.content)}")
    if r.status_code != 200:
        print(r.text[:1000])
        return r
    try:
        data = r.json()
    except Exception as e:
        print(f"JSON PARSE FAILED: {e}")
        print(r.text[:SNIPPET_CHARS])
        return r
    print(f"--- json (first {SNIPPET_CHARS} chars, pretty) ---")
    print(json.dumps(data, indent=2)[:SNIPPET_CHARS])
    return r


def main():
    # 1. SportsBettingDime public betting trends
    probe_html("sportsbettingdime", "https://www.sportsbettingdime.com/mlb/public-betting-trends/")
    probe_html("sportsbettingdime robots.txt", "https://www.sportsbettingdime.com/robots.txt")

    # 2. DRatings — both the "completed" URL given and the likely upcoming/today page
    probe_html("dratings (completed/3, as given)", "https://www.dratings.com/predictor/mlb-baseball-predictions/completed/3")
    probe_html("dratings (base predictor page, likely upcoming)", "https://www.dratings.com/predictor/mlb-baseball-predictions/")

    # 3. MoundEdge summaries site
    probe_html("moundedge landing page", "https://moundedge.github.io/MLB-Summaries/")

    # 4. Reddit — search endpoint, then (if we can guess an id) the thread endpoint.
    probe_json("reddit r/sportsbook search", "https://www.reddit.com/r/sportsbook/search.json?q=MLB%20daily%20thread&restrict_sr=1&sort=new")
    probe_json("reddit r/baseball search", "https://www.reddit.com/r/baseball/search.json?q=daily%20discussion&restrict_sr=1&sort=new")

    print("\n\nDONE.")


if __name__ == "__main__":
    sys.exit(main())
