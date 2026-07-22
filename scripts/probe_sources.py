"""
Third recon pass: MoundEdge per-game field layout (base64 logos stripped so
the real content is readable) and the SportsBettingDime widget tag/attrs
that actually carries the betting-split data.

Fourth recon pass: Kalshi's MLB prediction-market data - real market JSON
so mlb_daily/fetch/kalshi.py's ticker/polarity parsing can be designed
against actual payloads instead of guessed from public docs (which is all
that was available from the dev sandbox - Kalshi's API itself was
unreachable from there, likely Cloudflare bot-protection on the edge).

Fifth recon pass: DRatings regression check - a user reported the
existing dratings.py parser (unchanged since an earlier commit) is now
only returning ~3 of 15 games instead of the full slate. This dumps the
raw table's row count/content next to what dratings.fetch_today_games()
actually parses, to tell whether DRatings' own page structure changed or
something else is going on.
"""

import json
import re
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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


def probe_moundedge_freshness_now():
    """Direct, minimal check of MoundEdge's real fetch_today_games() output
    right now - what slate_subtitle date does it show, at this exact
    UTC/ET timestamp, independent of whatever main.py's own comparison logic
    decides. Answers "is it actually stale right now" with one clean line."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from mlb_daily.fetch import moundedge

    hr("MoundEdge: live freshness check right now")
    now_utc = datetime.now(ZoneInfo("UTC"))
    now_et = datetime.now(ZoneInfo("America/New_York"))
    print(f"current time: {now_utc.isoformat()} UTC / {now_et.isoformat()} ET")
    try:
        games = moundedge.fetch_today_games()
        subtitle = games[0].slate_subtitle if games else "(no games returned)"
        print(f"games returned: {len(games)}")
        print(f"slate_subtitle: {subtitle!r}")
        today_et_display = now_et.strftime("%A, %B %-d, %Y")
        print(f"today (ET) per this exact moment: {today_et_display!r}")
        print(f"MATCHES today: {today_et_display in subtitle}")
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()


def probe_dratings():
    from mlb_daily.fetch import dratings
    from mlb_daily.teams import abbrev_from_name

    hr("DRatings: raw table structure vs what fetch_today_games() actually returns")
    r = get(dratings.URL, headers=dratings.HEADERS)
    soup = BeautifulSoup(r.text, "html.parser")

    heading = soup.find(lambda tag: tag.name in ("h2", "h3") and "Upcoming Games" in tag.get_text())
    print(f"'Upcoming Games' heading found: {heading is not None}" + (f" -> {heading.get_text(strip=True)!r}" if heading else ""))
    table = heading.find_next("table") if heading else soup.find("table")
    print(f"table found: {table is not None}")
    if table is None:
        print("No table at all - DRatings page structure likely changed significantly.")
        return

    header_cells = [re.sub(r"\s+", " ", th.get_text(' ')).strip() for th in table.select("thead th")]
    print(f"header cells: {header_cells}")

    rows = table.select("tbody.table-body > tr")
    print(f"raw <tbody.table-body> rows found: {len(rows)}")
    if not rows:
        print("Trying a looser selector: table.select('tbody tr')")
        rows = table.select("tbody tr")
        print(f"raw <tbody tr> rows found: {len(rows)}")

    for i, tr in enumerate(rows):
        cells = tr.find_all("td", recursive=False)
        teams_text = cells[0].get_text(" ", strip=True) if cells else "NO CELLS"
        print(f"row {i}: {len(cells)} <td recursive=False> cells | first cell text: {teams_text[:200]!r}")

    hr("DRatings: dratings.fetch_today_games() actual output")
    try:
        games = dratings.fetch_today_games()
        print(f"parsed games: {len(games)}")
        for g in games:
            away_ab = abbrev_from_name(g.away_team)
            home_ab = abbrev_from_name(g.home_team)
            print(
                f"  away_team={g.away_team!r} (-> {away_ab}) home_team={g.home_team!r} (-> {home_ab}) "
                f"away_win_pct={g.away_win_pct} home_win_pct={g.home_win_pct} "
                f"away_pitcher={g.away_pitcher!r} home_pitcher={g.home_pitcher!r}"
            )
    except Exception as e:
        print(f"FAILED: {e}")
        import traceback
        traceback.print_exc()


def main():
    probe_moundedge()
    try:
        probe_moundedge_freshness_now()
    except Exception as e:
        hr(f"MoundEdge freshness probe failed: {e}")
        import traceback
        traceback.print_exc()
    probe_sbd_widget()
    try:
        probe_dratings()
    except Exception as e:
        hr(f"DRatings probe failed: {e}")
        import traceback
        traceback.print_exc()
    try:
        probe_kalshi()
    except Exception as e:
        hr(f"Kalshi probe failed: {e}")
        import traceback
        traceback.print_exc()
    print("\n\nDONE.")


if __name__ == "__main__":
    sys.exit(main())
