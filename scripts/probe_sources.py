"""
Third recon pass: MoundEdge per-game field layout (base64 logos stripped so
the real content is readable) and the SportsBettingDime widget tag/attrs
that actually carries the betting-split data.

Fourth recon pass: Kalshi's MLB prediction-market data - real market JSON
so mlb_daily/fetch/kalshi.py's ticker/polarity parsing can be designed
against actual payloads instead of guessed from public docs (which is all
that was available from the dev sandbox - Kalshi's API itself was
unreachable from there, likely Cloudflare bot-protection on the edge).
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
}


def hr(title):
    print("\n" + "=" * 100)
    print(title)
    print("=" * 100)


def get(url, headers=BROWSER_HEADERS):
    r = requests.get(url, headers=headers, timeout=20)
    print(f"status={r.status_code}  bytes={len(r.content)}")
    return r


def strip_base64_images(html):
    return re.sub(r'src="data:image/[^"]+"', 'src="[logo]"', html)


def probe_moundedge():
    hr("MoundEdge: one full game card, base64 images stripped")
    r = get("https://moundedge.github.io/MLB-Summaries/")
    text = strip_base64_images(r.text)

    start = text.find('class="game"')
    end = text.find('class="game"', start + 10)
    if end == -1:
        end = start + 20000
    card = text[start:end]
    print(f"card length: {len(card)} chars\n")
    print(card)


def probe_sbd_widget():
    hr("SBD: locate the sas-sports-wc widget tag + surrounding markup")
    r = get("https://www.sportsbettingdime.com/mlb/public-betting-trends/")
    text = r.text

    # find any custom element tags (contain a hyphen in the tag name)
    custom_tags = sorted(set(re.findall(r"<([a-z]+-[a-z-]+)[ >]", text)))
    print(f"custom element tag names found: {custom_tags}")

    for tag in custom_tags:
        idx = text.find(f"<{tag}")
        if idx != -1:
            print(f"\n--- first <{tag} ...> occurrence ---")
            print(text[idx: idx + 1500])

    # the div with class containing "public-betting" - print it fully
    m = re.search(r'<div[^>]*class="[^"]*public-betting[^"]*"[^>]*>', text)
    if m:
        idx = m.start()
        print("\n--- div.public-betting region ---")
        print(text[idx: idx + 2000])

    # look for JSON-looking inline data near the widget (props/config)
    for kw in ["widgetId", "widget-id", "gameId", "sportsdatasolutions", "sas-sports", "matchups", "publicBetting"]:
        c = text.count(kw)
        if c:
            idx = text.find(kw)
            print(f"\nkeyword {kw!r} found {c}x, first context:")
            print(text[max(0, idx - 200): idx + 400])


KALSHI_BASE = "https://external-api.kalshi.com/trade-api/v2"


def probe_kalshi():
    hr("Kalshi: KXMLBGAME (win market) - raw market objects")
    r = get(f"{KALSHI_BASE}/markets?series_ticker=KXMLBGAME&status=open&limit=10")
    try:
        data = r.json()
    except Exception as e:
        print(f"failed to parse JSON: {e}")
        print(r.text[:2000])
        return
    markets = data.get("markets", [])
    print(f"markets returned: {len(markets)}  cursor: {data.get('cursor')!r}")
    for m in markets[:6]:
        print(json.dumps(m, indent=2, default=str))

    hr("Kalshi: KXMLBTOTAL (total runs market) - raw market objects")
    r = get(f"{KALSHI_BASE}/markets?series_ticker=KXMLBTOTAL&status=open&limit=10")
    try:
        data = r.json()
    except Exception as e:
        print(f"failed to parse JSON: {e}")
        print(r.text[:2000])
        return
    markets = data.get("markets", [])
    print(f"markets returned: {len(markets)}  cursor: {data.get('cursor')!r}")
    for m in markets[:6]:
        print(json.dumps(m, indent=2, default=str))

    # resolves whether a KXMLBGAME event has one market (need polarity
    # inference from title/subtitle) or two (one per team, no inference needed)
    hr("Kalshi: KXMLBGAME events with nested markets (1-vs-2-markets-per-game check)")
    r = get(f"{KALSHI_BASE}/events?series_ticker=KXMLBGAME&status=open&with_nested_markets=true&limit=5")
    try:
        data = r.json()
        print(json.dumps(data, indent=2, default=str)[:6000])
    except Exception as e:
        print(f"failed to parse JSON: {e}")
        print(r.text[:2000])

    hr("Kalshi: KXMLBGAME series metadata (category/tags, sanity check)")
    r = get(f"{KALSHI_BASE}/series/KXMLBGAME")
    print(r.text[:2000])


def main():
    probe_moundedge()
    probe_sbd_widget()
    try:
        probe_kalshi()
    except Exception as e:
        hr(f"Kalshi probe failed: {e}")
        import traceback
        traceback.print_exc()
    print("\n\nDONE.")


if __name__ == "__main__":
    sys.exit(main())
