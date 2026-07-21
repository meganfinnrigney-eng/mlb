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


def hr(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def get(url, headers=BROWSER_HEADERS):
    try:
        r = requests.get(url, headers=headers, timeout=20)
    except Exception as e:
        print(f"REQUEST FAILED: {e}")
        return None
    print(f"status={r.status_code}  content-type={r.headers.get('content-type')}  bytes={len(r.content)}")
    return r


def print_window(text, marker, before=200, after=3000, label=""):
    idx = text.find(marker)
    if idx == -1:
        print(f"[marker {marker!r} not found]")
        return
    lo = max(0, idx - before)
    print(f"--- window around {marker!r} {label} ---")
    print(text[lo: idx + after])


def probe_sbd():
    hr("SBD: full-page scan for wp-json refs, odds tables, data attrs")
    r = get("https://www.sportsbettingdime.com/mlb/public-betting-trends/")
    if r is None or r.status_code != 200:
        return
    text = r.text

    wp_json_refs = sorted(set(re.findall(r'https?://[^\s"\']*wp-json[^\s"\']*', text)))
    print(f"wp-json URLs referenced ({len(wp_json_refs)}):")
    for u in wp_json_refs[:15]:
        print(" ", u)

    # data- attributes often carry API endpoints / game ids for JS widgets
    data_attrs = sorted(set(re.findall(r'data-[a-z-]+="[^"]{0,120}"', text)))[:40]
    print(f"\nsample data-* attributes ({len(data_attrs)} shown):")
    for a in data_attrs:
        print(" ", a)

    print_window(text, "<table", before=100, after=4000, label="(the one <table> on the page)")

    # look for script src bundles that might be the widget doing the AJAX call
    scripts = sorted(set(re.findall(r'<script[^>]+src="([^"]+)"', text)))
    print(f"\n<script src> tags ({len(scripts)}):")
    for s in scripts[:30]:
        print(" ", s)

    # common class name guesses for betting split rows
    for cls in ["matchup", "betting", "split", "trend-row", "public-betting", "money", "handle"]:
        count = len(re.findall(rf'class="[^"]*{cls}[^"]*"', text, re.I))
        if count:
            print(f'elements with class containing "{cls}": {count}')


def probe_dratings():
    hr("DRatings: table content + JS bundle API search")
    r = get("https://www.dratings.com/predictor/mlb-baseball-predictions/")
    if r is None or r.status_code != 200:
        return
    text = r.text
    print_window(text, "<table", before=50, after=4000, label="(first table)")

    # find the main JS bundle URL and inspect it for API base / fetch calls
    m = re.search(r'<script src="(/assets/main__main\.[^"]+\.js)"', text)
    if not m:
        print("main JS bundle not found via regex")
        return
    js_url = "https://www.dratings.com" + m.group(1)
    print(f"\nfetching JS bundle: {js_url}")
    r2 = get(js_url)
    if r2 is None or r2.status_code != 200:
        return
    js = r2.text
    api_urls = sorted(set(re.findall(r'https?://(?:app\.)?dratings\.com/[a-zA-Z0-9_/.-]*api[a-zA-Z0-9_/.-]*', js)))
    print(f"api-ish URLs found in bundle ({len(api_urls)}):")
    for u in api_urls[:20]:
        print(" ", u)
    generic_urls = sorted(set(re.findall(r'https?://app\.dratings\.com/[a-zA-Z0-9_/.-]+', js)))
    print(f"\napp.dratings.com URLs found in bundle ({len(generic_urls)}):")
    for u in generic_urls[:30]:
        print(" ", u)


def probe_moundedge():
    hr("MoundEdge: section headers + first full game card")
    r = get("https://moundedge.github.io/MLB-Summaries/")
    if r is None or r.status_code != 200:
        return
    text = r.text

    titles = re.findall(r'class="ptitle">([^<]+)<', text)
    subs = re.findall(r'class="psub">(.*?)</div>', text, re.S)
    print(f"page title(s): {titles}")
    print(f"page subtitle(s) (raw): {[s[:300] for s in subs]}")

    sec_headers = re.findall(r'class="sec"[^>]*>(.*?)<', text)
    print(f"\nsection header labels found ({len(sec_headers)}): {sec_headers[:40]}")

    print_window(text, 'class="game"', before=0, after=6000, label="(first full game card)")


def probe_reddit():
    hr("Reddit: retry with slightly different endpoints / headers")
    for sub, q in [("sportsbook", "MLB daily thread"), ("baseball", "daily discussion")]:
        url = f"https://www.reddit.com/r/{sub}/search.json?q={q.replace(' ', '%20')}&restrict_sr=1&sort=new"
        print(f"\n-- r/{sub} --")
        r = get(url, headers=REDDIT_HEADERS)
        if r is None:
            continue
        print(f"status={r.status_code}")
        if r.status_code == 200:
            try:
                data = r.json()
                print(json.dumps(data, indent=2)[:2000])
            except Exception as e:
                print(f"json parse failed: {e}")
        else:
            print(r.text[:300])

    # also try the old.reddit.com host, sometimes treated differently by the WAF
    print("\n-- old.reddit.com r/sportsbook --")
    r = get(
        "https://old.reddit.com/r/sportsbook/search.json?q=MLB%20daily%20thread&restrict_sr=1&sort=new",
        headers=REDDIT_HEADERS,
    )
    if r is not None:
        print(f"status={r.status_code}")
        print(r.text[:1500])


def main():
    probe_sbd()
    probe_dratings()
    probe_moundedge()
    probe_reddit()
    print("\n\nDONE.")


if __name__ == "__main__":
    sys.exit(main())
