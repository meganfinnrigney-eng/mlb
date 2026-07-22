"""
Fetches today's MLB prediction-market data from Kalshi's public market-data
API (https://external-api.kalshi.com/trade-api/v2) - GET /markets doesn't
require authentication. Two series matter here: KXMLBGAME (game winner) and
KXMLBTOTAL (total runs over/under).

Schema verified against real payloads via scripts/probe_sources.py's
probe_kalshi() (this dev environment can't reach Kalshi's API directly - see
that script's docstring). Notable, non-obvious things the real data showed
that generic API docs didn't:

  - KXMLBGAME has TWO markets per game (one per team, ticker suffixed
    "-{TEAM}"), not one market with an implied polarity. Each market's own
    `yes_sub_title` names its team directly - no polarity guessing needed.
  - Prices are `*_dollars` string fields (e.g. "0.1300"), not the plain int
    cents fields generic docs describe.
  - KXMLBTOTAL is a single yes/no market per game with strike_type
    "greater" and a `floor_strike` float field for the line - "yes" means
    "over", confirmed structurally, not by parsing text.
  - `yes_sub_title`/`no_sub_title` use Kalshi's own short city/market names
    ("Houston", "Chicago WS", "New York M") which do NOT reliably contain
    this project's team nicknames, so mlb_daily.teams.abbrev_from_name()
    can't resolve them - team identity here comes entirely from the
    3-letter code in the ticker/event_ticker instead.
  - GET /markets?status=open returns markets for every future game, not
    just today's slate, so results are filtered client-side against each
    market's `occurrence_datetime` (converted to US/Eastern) vs. today_iso.

Every market's parsing is wrapped in try/except: continue, same as
dratings.py's row loop - Kalshi is a best-effort optional source like every
other one here, and one game's unexpected shape shouldn't take down the
whole fetch. If a market can't be confidently placed, it's skipped.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from mlb_daily.teams import ABBREV_TO_FULL_NAME, NICKNAME_TO_ABBREV

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"

HEADERS = {
    "User-Agent": "mlb-daily-tracker/1.0 (personal project; non-commercial daily digest)",
}

GAME_SERIES = "KXMLBGAME"
TOTAL_SERIES = "KXMLBTOTAL"

ET = ZoneInfo("America/New_York")

_TRAILING_LETTERS_RE = re.compile(r"([A-Z]+)$")
_TICKER_DT_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(\d{4})[A-Z]")
_MONTH_ABBREV = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


@dataclass
class KalshiGame:
    away_abbrev: str
    home_abbrev: str
    away_win_pct: float | None = None  # 0-100, implied probability away team wins
    home_win_pct: float | None = None  # 0-100
    total_line: float | None = None  # e.g. 8.5
    over_pct: float | None = None  # 0-100, implied probability of Over
    game_ticker: str = ""
    total_ticker: str = ""
    # the event ticker's own embedded local start time - e.g.
    # "KXMLBGAME-26JUL221910BALBOS" -> 2026-07-22 19:10 ET (empirically
    # Eastern, not UTC - occurrence_datetime trails this by ~3h, which
    # looks like an estimated game-end/resolution time, not the start).
    # Only used to disambiguate doubleheader games by proximity to the
    # official schedule's start time - see build.py.
    ticker_datetime_et: object = None
    volume: float | None = None
    raw: dict = field(default_factory=dict)


def _parse_ticker_datetime_et(event_ticker):
    m = _TICKER_DT_RE.search(event_ticker or "")
    if not m:
        return None
    yy, mon, dd, hhmm = m.groups()
    month = _MONTH_ABBREV.get(mon.upper())
    if not month:
        return None
    try:
        return datetime(2000 + int(yy), month, int(dd), int(hhmm[:2]), int(hhmm[2:]), tzinfo=ET)
    except ValueError:
        return None


def _normalize_abbrev(code):
    """Resolve a ticker-derived code through the same nickname/alias table
    used for DRatings/MoundEdge reconciliation, since Kalshi's convention
    isn't guaranteed to match this project's canonical abbreviations."""
    if not code:
        return None
    code = code.upper()
    if code in ABBREV_TO_FULL_NAME:
        return code
    return NICKNAME_TO_ABBREV.get(code)


def _split_team_codes(tail):
    """tail: the trailing alphabetic run of an event ticker (e.g.
    "HOUCWS"). Try the common 3+3 split first (most MLB codes are 3
    letters); fall back to other split points - closest to 3 first - only
    accepting a split where BOTH halves resolve to a known team."""
    tail = tail.upper()
    n = len(tail)
    if n < 4:
        return None, None
    candidates = []
    if n == 6:
        candidates.append((tail[:3], tail[3:]))
    candidates += [(tail[:i], tail[i:]) for i in sorted(range(2, n - 1), key=lambda i: abs(i - 3))]
    for away_code, home_code in candidates:
        away_ab = _normalize_abbrev(away_code)
        home_ab = _normalize_abbrev(home_code)
        if away_ab and home_ab:
            return away_ab, home_ab
    return None, None


def _teams_from_event_ticker(event_ticker):
    """event_ticker looks like 'KXMLBGAME-26JUL241940HOUCWS' - date/time
    digits followed by away+home team codes; the trailing letter run is
    exactly those codes regardless of the date/time prefix's width."""
    tail_match = _TRAILING_LETTERS_RE.search(event_ticker or "")
    if not tail_match:
        return None, None
    return _split_team_codes(tail_match.group(1))


def _dollars(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mid_price_pct(market):
    """Implied probability (0-100) from a market's bid/ask midpoint
    (Kalshi's *_dollars fields, e.g. "0.1300" = 13%), falling back to
    last_price_dollars, then None if nothing usable."""
    bid, ask = _dollars(market.get("yes_bid_dollars")), _dollars(market.get("yes_ask_dollars"))
    if bid is not None and ask is not None and (bid or ask):
        return round((bid + ask) / 2 * 100, 1)
    last = _dollars(market.get("last_price_dollars"))
    return round(last * 100, 1) if last is not None else None


def _is_today(market, today_iso):
    occurrence = market.get("occurrence_datetime")
    if not occurrence or not today_iso:
        return True  # no date info to filter on - don't drop the market over it
    try:
        dt = datetime.fromisoformat(occurrence.replace("Z", "+00:00")).astimezone(ET)
    except ValueError:
        return True
    return dt.strftime("%Y-%m-%d") == today_iso


def _get_all_markets(series_ticker, timeout=20):
    """Paginates through GET /markets for one series, open status only."""
    out = []
    cursor = None
    for _ in range(10):  # hard cap - a single day's slate is a handful of pages at most
        params = {"series_ticker": series_ticker, "status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BASE_URL}/markets", headers=HEADERS, params=params, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        out.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return out


def _parse_game_market(market, today_iso, games_by_key):
    if not _is_today(market, today_iso):
        return

    event_ticker = market.get("event_ticker", "")
    ticker = market.get("ticker", "")
    away_ab, home_ab = _teams_from_event_ticker(event_ticker)
    if away_ab is None or home_ab is None:
        return

    # this specific market's own ticker suffix names the team its "yes"
    # price refers to - e.g. "KXMLBGAME-...HOUCWS-HOU" -> "HOU"
    team_suffix = ticker.rsplit("-", 1)[-1] if "-" in ticker else ""
    this_team = _normalize_abbrev(team_suffix)
    if this_team not in (away_ab, home_ab):
        return  # can't confidently tell which side this market is - skip

    pct = _mid_price_pct(market)
    if pct is None:
        return

    # keyed by (away, home, ticker_datetime) rather than just (away, home) -
    # a doubleheader has two real games for the same team pair, each with
    # its own event_ticker/start time, and collapsing them into one
    # KalshiGame would silently mix one game's win price with the other's
    # total line. See build.py's doubleheader-matching comment.
    ticker_dt = _parse_ticker_datetime_et(event_ticker)
    key = (away_ab, home_ab, ticker_dt)
    g = games_by_key.setdefault(
        key, KalshiGame(away_abbrev=away_ab, home_abbrev=home_ab, ticker_datetime_et=ticker_dt)
    )
    g.game_ticker = event_ticker
    g.volume = _dollars(market.get("volume_fp"))
    g.raw["game_market_" + this_team] = market
    if this_team == away_ab:
        g.away_win_pct = pct
    else:
        g.home_win_pct = pct


def _parse_total_market(market, today_iso, games_by_key):
    if not _is_today(market, today_iso):
        return

    event_ticker = market.get("event_ticker", "")
    away_ab, home_ab = _teams_from_event_ticker(event_ticker)
    if away_ab is None or home_ab is None:
        return

    line = market.get("floor_strike")
    if line is None:
        return
    line = float(line)

    pct = _mid_price_pct(market)
    if pct is None:
        return
    # strike_type "greater" means yes=over; be defensive about any other
    # structure by checking explicitly rather than assuming
    if market.get("strike_type") not in (None, "greater"):
        return

    ticker_dt = _parse_ticker_datetime_et(event_ticker)
    key = (away_ab, home_ab, ticker_dt)
    g = games_by_key.setdefault(
        key, KalshiGame(away_abbrev=away_ab, home_abbrev=home_ab, ticker_datetime_et=ticker_dt)
    )
    g.total_line = line
    g.total_ticker = event_ticker
    g.over_pct = pct
    g.raw["total_market"] = market


def fetch_today_games(today_iso, timeout=20):
    games_by_key = {}

    for market in _get_all_markets(GAME_SERIES, timeout=timeout):
        try:
            _parse_game_market(market, today_iso, games_by_key)
        except Exception:
            continue

    for market in _get_all_markets(TOTAL_SERIES, timeout=timeout):
        try:
            _parse_total_market(market, today_iso, games_by_key)
        except Exception:
            continue

    return list(games_by_key.values())
