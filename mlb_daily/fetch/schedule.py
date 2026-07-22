"""
Official MLB schedule (MLB Stats API, free/unauthenticated) - the
authoritative source of "how many real games are there today for each
team pair, and when is each one scheduled" (gamePk + gameNumber).

This exists specifically to fix a doubleheader bug: DRatings, MoundEdge,
Kalshi, and My model are each scraped/market data that doesn't reliably
self-label "Game 1" vs "Game 2" the same way (or at all), so joining them
by (away_abbrev, home_abbrev) alone silently collapses a doubleheader's
two real games into one Matchup, mixing fields from two different games.
build.py's _build_matchups uses this schedule as the spine - one Matchup
per real (away, home, game_number) - and matches each source's row(s) to
the correct game_number using each source's own best available time
signal (see build.py for the per-source matching logic).
"""

import requests

from mlb_daily.teams import abbrev_from_name

HEADERS = {
    "User-Agent": "mlb-daily-tracker/1.0 (personal project; non-commercial daily digest)",
}


def fetch_today_schedule(today_iso, timeout=20):
    """Returns a list of {game_pk, game_number, away_abbrev, home_abbrev,
    game_datetime_utc} - one entry per real scheduled game (doubleheaders
    produce two entries for the same team pair, game_number 1 and 2)."""
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today_iso}&hydrate=team"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            away_name = g["teams"]["away"]["team"].get("name", "")
            home_name = g["teams"]["home"]["team"].get("name", "")
            away_ab = abbrev_from_name(away_name)
            home_ab = abbrev_from_name(home_name)
            if not away_ab or not home_ab:
                continue
            games.append(
                {
                    "game_pk": g.get("gamePk"),
                    "game_number": g.get("gameNumber", 1),
                    "away_abbrev": away_ab,
                    "home_abbrev": home_ab,
                    "game_datetime_utc": g.get("gameDate"),
                }
            )
    return games
