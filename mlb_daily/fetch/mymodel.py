"""
"My model" - a genuinely independent prediction source built from raw
Statcast/Baseball Savant data, rather than aggregating other sites'
predictions the way DRatings/MoundEdge do.

Formula (transparent, not a black box - see _project_runs):
    expected_runs ~= league_avg_runs_per_team_game
                      * (batting_team_recent_xwoba / league_xwoba)
                      * (opposing_starter_recent_xwoba_allowed / league_xwoba)
                      * park_factor

A pitcher's "average" xwOBA-allowed and the league's average batting
xwOBA are the same underlying number (one team's batting output is by
definition the opposing pitcher's allowed output, aggregated league-wide)
- so both ratios above are legitimately divided by the same league_xwoba.

Data sources, all verified reachable via scripts/probe_pybaseball.py
(FanGraphs is deliberately NOT used - confirmed blocked with a 403 from
Cloudflare even from GitHub Actions' cloud IPs):
  - MLB Stats API (statsapi.mlb.com) - today's probable starting
    pitchers, and recent game scores for the league-average-runs figure.
    Free, unauthenticated, official; not one of this project's four core
    sources, just used here as a schedule/score lookup.
  - Baseball Savant / Statcast, via pybaseball:
      - statcast_pitcher(start, end, id) - one starter's own rolling
        pitch-level stats (velocity, whiff%, xwOBA allowed).
      - statcast(start, end) - a single league-wide pull for the same
        window, aggregated by batting team, to get every team's recent
        xwOBA plus the league average in one shot (confirmed ~2s for a
        15-day window during recon, not the many-minutes worst case
        feared going in).
  - mlb_daily/park_factors.py - hand-maintained run-scoring factors
    (pybaseball has no usable park-factor source; see that module's
    docstring for why).

Every step is defensive (skip-and-continue / None on missing data) -
this source is best-effort like every other one in this project, and a
Statcast-schema surprise for one pitcher shouldn't take down the whole
fetch. Team abbreviations are normalized through mlb_daily.teams, since
both MLB Stats API and Statcast use slightly different conventions than
this project's canonical one (e.g. Statcast's "SD"/"SF"/"AZ"/"WSH").
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import requests

from mlb_daily.park_factors import park_factor as _park_factor
from mlb_daily.teams import ABBREV_TO_FULL_NAME, NICKNAME_TO_ABBREV, abbrev_from_name

TEAM_XWOBA_WINDOW_DAYS = 15  # "recent" team-batting window
PITCHER_SEASON_START_MONTH_DAY = (3, 1)  # safely before any real MLB game

HEADERS = {
    "User-Agent": "mlb-daily-tracker/1.0 (personal project; non-commercial daily digest)",
}


def _normalize_abbrev(code):
    if not code:
        return None
    code = code.upper()
    if code in ABBREV_TO_FULL_NAME:
        return code
    return NICKNAME_TO_ABBREV.get(code)


@dataclass
class PitcherRollingStats:
    pitcher_id: int
    pitcher_name: str
    velocity_15d: float | None = None
    velocity_30d: float | None = None
    velocity_season: float | None = None
    whiff_pct_15d: float | None = None
    whiff_pct_30d: float | None = None
    whiff_pct_season: float | None = None
    xwoba_allowed_15d: float | None = None
    xwoba_allowed_30d: float | None = None
    xwoba_allowed_season: float | None = None
    pitches_30d: int = 0


@dataclass
class MyModelGame:
    away_abbrev: str
    home_abbrev: str
    away_pitcher_id: int | None = None
    away_pitcher_name: str = ""
    home_pitcher_id: int | None = None
    home_pitcher_name: str = ""
    away_pitcher_stats: object = None  # PitcherRollingStats, for the HOME lineup's opponent
    home_pitcher_stats: object = None  # PitcherRollingStats, for the AWAY lineup's opponent
    away_team_xwoba: float | None = None
    home_team_xwoba: float | None = None
    league_xwoba: float | None = None
    league_avg_runs_per_team_game: float | None = None
    park_factor: float = 1.0
    away_projected_runs: float | None = None
    home_projected_runs: float | None = None
    raw: dict = field(default_factory=dict)


def _fetch_probable_pitchers(today_iso, timeout=20):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={today_iso}&hydrate=probablePitcher,team"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    games = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            away, home = g["teams"]["away"], g["teams"]["home"]
            away_ab = abbrev_from_name(away["team"].get("name", ""))
            home_ab = abbrev_from_name(home["team"].get("name", ""))
            if not away_ab or not home_ab:
                continue
            games.append(
                {
                    "away_abbrev": away_ab,
                    "home_abbrev": home_ab,
                    "away_pitcher_id": away.get("probablePitcher", {}).get("id"),
                    "away_pitcher_name": away.get("probablePitcher", {}).get("fullName", ""),
                    "home_pitcher_id": home.get("probablePitcher", {}).get("id"),
                    "home_pitcher_name": home.get("probablePitcher", {}).get("fullName", ""),
                }
            )
    return games


def _fetch_league_avg_runs_per_team_game(today, window_days=TEAM_XWOBA_WINDOW_DAYS, timeout=20):
    start = today - timedelta(days=window_days)
    url = (
        f"https://statsapi.mlb.com/api/v1/schedule?sportId=1"
        f"&startDate={start.isoformat()}&endDate={today.isoformat()}&gameType=R"
    )
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    data = r.json()

    total_runs = 0
    team_games = 0
    for d in data.get("dates", []):
        for g in d.get("games", []):
            if g.get("status", {}).get("codedGameState") not in ("F", "O"):
                continue
            away_score = g["teams"]["away"].get("score")
            home_score = g["teams"]["home"].get("score")
            if away_score is None or home_score is None:
                continue
            total_runs += away_score + home_score
            team_games += 2
    if team_games == 0:
        return None
    return round(total_runs / team_games, 3)


def _window_stats(df):
    """(velocity, whiff_pct, xwoba_allowed) over the given pitch-level
    slice, or (None, None, None) if it's empty."""
    import pandas as pd

    if len(df) == 0:
        return None, None, None

    velocity = df["release_speed"].mean()
    velocity = round(float(velocity), 1) if pd.notna(velocity) else None

    swing_descriptions = {"swinging_strike", "swinging_strike_blocked", "foul", "foul_tip", "hit_into_play"}
    whiff_descriptions = {"swinging_strike", "swinging_strike_blocked", "foul_tip"}
    swings = df["description"].isin(swing_descriptions).sum()
    whiffs = df["description"].isin(whiff_descriptions).sum()
    whiff_pct = round(100 * whiffs / swings, 1) if swings else None

    pa_ending = df[df["woba_denom"] > 0]
    if len(pa_ending):
        component = pa_ending["estimated_woba_using_speedangle"].fillna(pa_ending["woba_value"])
        denom_sum = pa_ending["woba_denom"].sum()
        xwoba_allowed = round(float((component * pa_ending["woba_denom"]).sum() / denom_sum), 3) if denom_sum else None
    else:
        xwoba_allowed = None

    return velocity, whiff_pct, xwoba_allowed


def fetch_pitcher_rolling_stats(pitcher_id, pitcher_name, today=None, timeout=None):
    import pandas as pd
    import pybaseball as pb

    today = today or date.today()
    stats = PitcherRollingStats(pitcher_id=pitcher_id, pitcher_name=pitcher_name)

    season_start = date(today.year, *PITCHER_SEASON_START_MONTH_DAY)
    df = pb.statcast_pitcher(str(season_start), str(today), pitcher_id)
    if df is None or len(df) == 0:
        return stats

    df = df.copy()
    df["game_date"] = pd.to_datetime(df["game_date"])
    cutoff_15 = pd.Timestamp(today - timedelta(days=15))
    cutoff_30 = pd.Timestamp(today - timedelta(days=30))

    windows = {
        "15d": df[df["game_date"] >= cutoff_15],
        "30d": df[df["game_date"] >= cutoff_30],
        "season": df,
    }
    for label, sub in windows.items():
        velo, whiff, xwoba = _window_stats(sub)
        setattr(stats, f"velocity_{label}", velo)
        setattr(stats, f"whiff_pct_{label}", whiff)
        setattr(stats, f"xwoba_allowed_{label}", xwoba)
    stats.pitches_30d = len(windows["30d"])
    return stats


def fetch_team_xwoba(today=None, window_days=TEAM_XWOBA_WINDOW_DAYS):
    """Single league-wide pull, aggregated by batting team - returns
    ({abbrev: recent_xwoba}, league_avg_xwoba)."""
    import pybaseball as pb

    today = today or date.today()
    start = today - timedelta(days=window_days)
    df = pb.statcast(str(start), str(today))
    if df is None or len(df) == 0:
        return {}, None

    df = df[df["woba_denom"] > 0].copy()
    if len(df) == 0:
        return {}, None

    df["batting_team"] = df.apply(lambda r: r["away_team"] if r["inning_topbot"] == "Top" else r["home_team"], axis=1)
    df["xwoba_component"] = df["estimated_woba_using_speedangle"].fillna(df["woba_value"])

    team_xwoba = {}
    for raw_team, group in df.groupby("batting_team"):
        ab = _normalize_abbrev(raw_team)
        if not ab:
            continue
        denom_sum = group["woba_denom"].sum()
        if denom_sum:
            team_xwoba[ab] = round(float((group["xwoba_component"] * group["woba_denom"]).sum() / denom_sum), 3)

    league_denom_sum = df["woba_denom"].sum()
    league_xwoba = round(float((df["xwoba_component"] * df["woba_denom"]).sum() / league_denom_sum), 3) if league_denom_sum else None
    return team_xwoba, league_xwoba


def _project_runs(batting_team_xwoba, opposing_pitcher_stats, league_xwoba, league_avg_runs, pk_factor):
    if batting_team_xwoba is None or league_xwoba is None or league_avg_runs is None:
        return None
    if opposing_pitcher_stats is None or opposing_pitcher_stats.xwoba_allowed_30d is None:
        return None
    team_factor = batting_team_xwoba / league_xwoba
    pitcher_factor = opposing_pitcher_stats.xwoba_allowed_30d / league_xwoba
    return round(league_avg_runs * team_factor * pitcher_factor * pk_factor, 2)


def fetch_today_games(today_iso, today=None):
    today = today or date.today()
    games = _fetch_probable_pitchers(today_iso)
    if not games:
        return []

    team_xwoba, league_xwoba = fetch_team_xwoba(today)
    league_avg_runs = _fetch_league_avg_runs_per_team_game(today)

    pitcher_cache = {}

    def get_pitcher_stats(pid, name):
        if pid is None:
            return None
        if pid not in pitcher_cache:
            try:
                pitcher_cache[pid] = fetch_pitcher_rolling_stats(pid, name, today)
            except Exception:
                pitcher_cache[pid] = None
        return pitcher_cache[pid]

    out = []
    for g in games:
        try:
            away_ab, home_ab = g["away_abbrev"], g["home_abbrev"]
            away_stats = get_pitcher_stats(g["away_pitcher_id"], g["away_pitcher_name"])
            home_stats = get_pitcher_stats(g["home_pitcher_id"], g["home_pitcher_name"])

            mg = MyModelGame(
                away_abbrev=away_ab,
                home_abbrev=home_ab,
                away_pitcher_id=g["away_pitcher_id"],
                away_pitcher_name=g["away_pitcher_name"],
                home_pitcher_id=g["home_pitcher_id"],
                home_pitcher_name=g["home_pitcher_name"],
                away_pitcher_stats=away_stats,
                home_pitcher_stats=home_stats,
                away_team_xwoba=team_xwoba.get(away_ab),
                home_team_xwoba=team_xwoba.get(home_ab),
                league_xwoba=league_xwoba,
                league_avg_runs_per_team_game=league_avg_runs,
                park_factor=_park_factor(home_ab),
            )
            # away team bats against the home starter, and vice versa
            mg.away_projected_runs = _project_runs(
                mg.away_team_xwoba, home_stats, league_xwoba, league_avg_runs, mg.park_factor
            )
            mg.home_projected_runs = _project_runs(
                mg.home_team_xwoba, away_stats, league_xwoba, league_avg_runs, mg.park_factor
            )
            out.append(mg)
        except Exception:
            continue

    return out
