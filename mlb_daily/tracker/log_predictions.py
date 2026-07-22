"""
Paper-trading accuracy tracker - PREDICTION LOGGING ONLY.

This is a historical scoring/logging exercise, not a betting tool: it
records what each source predicted (and, for Kalshi, what its market
price was at logging time) purely so accuracy can be compared after the
fact. There is no order-placement code here, no API credentials beyond
Kalshi's public read-only market-data GET (the same endpoint
mlb_daily/fetch/kalshi.py already uses for the report itself - see that
module's docstring), and no code path that could ever submit a
transaction. Keep it that way: this module must never grow a write/POST
call to any trading endpoint.

Proof-of-concept scope (this file): log today's per-game predictions
from DRatings, BPP, My model, and Kalshi's implied price to a running
CSV, one row per (date, away, home, game_number), upserted so repeated
runs on the same day (e.g. manual test triggers) overwrite that game's
row instead of duplicating it. Every row carries a unique game_id
("{date}_{away}_{home}_G{game_number}") built from build.py's own
doubleheader-aware Matchup.game_number - never (date, away, home) alone,
which would collide Game 1 and Game 2 of a doubleheader onto the same
row. Fetching actual final scores and scoring accuracy is a separate,
not-yet-built step - see the module docstring in this package's future
results.py.
"""

import csv
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "predictions_log.csv"

FIELDNAMES = [
    "game_id", "date", "game_number", "logged_at", "away_abbrev", "home_abbrev", "game_time",
    "dratings_pick", "dratings_away_proj", "dratings_home_proj", "dratings_total_proj",
    "bpp_pick", "bpp_away_proj", "bpp_home_proj", "bpp_total_proj",
    "mymodel_pick", "mymodel_away_proj", "mymodel_home_proj", "mymodel_total_proj",
    "kalshi_pick", "kalshi_away_price", "kalshi_home_price",
    "kalshi_total_line", "kalshi_over_pct", "kalshi_total_pick",
    "market_total",
]


@dataclass
class PredictionRow:
    game_id: str
    date: str
    game_number: int
    logged_at: str
    away_abbrev: str
    home_abbrev: str
    game_time: str = ""
    dratings_pick: str = ""
    dratings_away_proj: float | None = None
    dratings_home_proj: float | None = None
    dratings_total_proj: float | None = None
    bpp_pick: str = ""
    bpp_away_proj: float | None = None
    bpp_home_proj: float | None = None
    bpp_total_proj: float | None = None
    mymodel_pick: str = ""
    mymodel_away_proj: float | None = None
    mymodel_home_proj: float | None = None
    mymodel_total_proj: float | None = None
    kalshi_pick: str = ""
    kalshi_away_price: float | None = None
    kalshi_home_price: float | None = None
    kalshi_total_line: float | None = None
    kalshi_over_pct: float | None = None
    kalshi_total_pick: str = ""
    market_total: float | None = None

    def as_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _winner(away_val, home_val, away_abbrev, home_abbrev):
    if away_val is None or home_val is None or away_val == home_val:
        return ""
    return away_abbrev if away_val > home_val else home_abbrev


def _row_from_matchup(m, today_iso, logged_at):
    dr, me, mymodel, kalshi = m.dratings, m.moundedge, m.mymodel, m.kalshi

    dratings_pick = _winner(
        dr.away_win_pct if dr else None, dr.home_win_pct if dr else None, m.away_abbrev, m.home_abbrev
    )
    bpp_pick = _winner(
        me.bpp_away_runs if me else None, me.bpp_home_runs if me else None, m.away_abbrev, m.home_abbrev
    )
    mymodel_pick = _winner(
        mymodel.away_projected_runs if mymodel else None,
        mymodel.home_projected_runs if mymodel else None,
        m.away_abbrev, m.home_abbrev,
    )
    kalshi_pick = _winner(
        kalshi.away_win_pct if kalshi else None, kalshi.home_win_pct if kalshi else None, m.away_abbrev, m.home_abbrev
    )

    mymodel_total = None
    if mymodel and mymodel.away_projected_runs is not None and mymodel.home_projected_runs is not None:
        mymodel_total = round(mymodel.away_projected_runs + mymodel.home_projected_runs, 2)

    kalshi_total_pick = ""
    if kalshi and kalshi.over_pct is not None:
        kalshi_total_pick = "over" if kalshi.over_pct > 50 else "under"

    market_total = (me.market_total if me else None) or (dr.market_total if dr else None)

    game_number = getattr(m, "game_number", 1) or 1
    game_id = f"{today_iso}_{m.away_abbrev}_{m.home_abbrev}_G{game_number}"

    return PredictionRow(
        game_id=game_id,
        date=today_iso,
        game_number=game_number,
        logged_at=logged_at,
        away_abbrev=m.away_abbrev,
        home_abbrev=m.home_abbrev,
        game_time=m.game_time or "",
        dratings_pick=dratings_pick,
        dratings_away_proj=dr.away_projected_runs if dr else None,
        dratings_home_proj=dr.home_projected_runs if dr else None,
        dratings_total_proj=dr.total_projected_runs if dr else None,
        bpp_pick=bpp_pick,
        bpp_away_proj=me.bpp_away_runs if me else None,
        bpp_home_proj=me.bpp_home_runs if me else None,
        bpp_total_proj=me.bpp_total if me else None,
        mymodel_pick=mymodel_pick,
        mymodel_away_proj=mymodel.away_projected_runs if mymodel else None,
        mymodel_home_proj=mymodel.home_projected_runs if mymodel else None,
        mymodel_total_proj=mymodel_total,
        kalshi_pick=kalshi_pick,
        kalshi_away_price=kalshi.away_win_pct if kalshi else None,
        kalshi_home_price=kalshi.home_win_pct if kalshi else None,
        kalshi_total_line=kalshi.total_line if kalshi else None,
        kalshi_over_pct=kalshi.over_pct if kalshi else None,
        kalshi_total_pick=kalshi_total_pick,
        market_total=market_total,
    )


def _read_existing_rows(csv_path):
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def log_todays_predictions(matchups, today_iso, csv_path=DEFAULT_LOG_PATH, now=None):
    """Upserts one row per game_id into the running CSV - re-running this on
    the same day (manual test triggers, retries) overwrites that game's row
    rather than piling up duplicates that would double-count in the
    accuracy stats later. Keyed by game_id (not date+away+home alone) so a
    doubleheader's two games never collide onto the same row. Returns the
    list of PredictionRow objects written for this call, so callers
    (main.py, this module's own POC runner) can show/print what was
    logged."""
    logged_at = (now or datetime.now(ET)).isoformat()
    new_rows = [_row_from_matchup(m, today_iso, logged_at) for m in matchups]

    existing = _read_existing_rows(csv_path)
    by_key = {r["game_id"]: r for r in existing if r.get("game_id")}
    for row in new_rows:
        by_key[row.game_id] = row.as_dict()

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        # keep the file in a stable, readable order: date then matchup
        for key in sorted(by_key):
            writer.writerow(by_key[key])

    return new_rows
