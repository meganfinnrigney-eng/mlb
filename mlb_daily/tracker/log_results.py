"""
Fetches final scores for games already logged in predictions_log.csv and
appends them to results_log.csv, keyed by game_id - a historical record
for scoring prediction accuracy later. Read-only against the official
MLB Stats API's basic schedule endpoint (no hydration needed - score and
status are already present on every game object, confirmed via
scripts/probe_sources.py's probe_final_score_schema()), the same host
mlb_daily/fetch/schedule.py already uses. No writes, no order/trade
capability anywhere - this only ever reads public schedule data and
appends historical rows to a local CSV.

results_log.csv only ever contains games whose status is "Final" - a
pending/in-progress game is simply left out until it's done, never
written as a partial/placeholder row, so join logic against
predictions_log.csv stays a plain, exact match on game_id: a game_id
present in results_log.csv is final and ready to score, absent means
not yet final.
"""

import csv
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from mlb_daily.teams import abbrev_from_name

ET = ZoneInfo("America/New_York")

HEADERS = {
    "User-Agent": "mlb-daily-tracker/1.0 (personal project; non-commercial daily digest)",
}

RESULTS_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "results_log.csv"
PREDICTIONS_LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "predictions_log.csv"

FIELDNAMES = [
    "game_id", "date", "away_abbrev", "home_abbrev", "game_number",
    "away_score", "home_score", "winner_abbrev", "total_runs", "status", "fetched_at",
]


@dataclass
class ResultRow:
    game_id: str
    date: str
    away_abbrev: str
    home_abbrev: str
    game_number: int
    away_score: int
    home_score: int
    winner_abbrev: str
    total_runs: int
    status: str
    fetched_at: str

    def as_dict(self):
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _read_csv_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _fetch_schedule_for_date(date_iso, timeout=20):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date_iso}"
    r = requests.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _find_game(schedule_data, away_ab, home_ab, game_number):
    for d in schedule_data.get("dates", []):
        for g in d.get("games", []):
            g_away = abbrev_from_name(g["teams"]["away"]["team"].get("name", ""))
            g_home = abbrev_from_name(g["teams"]["home"]["team"].get("name", ""))
            if g_away == away_ab and g_home == home_ab and g.get("gameNumber", 1) == game_number:
                return g
    return None


def fetch_and_log_results(csv_path=RESULTS_LOG_PATH, predictions_path=PREDICTIONS_LOG_PATH, now=None):
    """Checks every game_id in predictions_log.csv that isn't already
    recorded as Final in results_log.csv, and appends a row for any that
    have gone final since the last check. Returns the list of ResultRow
    objects newly written this call (empty if nothing new went final)."""
    predictions_rows = _read_csv_rows(predictions_path)
    if not predictions_rows:
        return []

    existing_results = _read_csv_rows(csv_path)
    by_id = {r["game_id"]: r for r in existing_results if r.get("game_id")}

    pending = [r for r in predictions_rows if r.get("game_id") and r["game_id"] not in by_id]
    if not pending:
        return []

    # one schedule fetch per distinct date, not per game
    dates_needed = sorted({r["date"] for r in pending if r.get("date")})
    schedule_by_date = {}
    for d in dates_needed:
        try:
            schedule_by_date[d] = _fetch_schedule_for_date(d)
        except Exception:
            continue

    fetched_at = (now or datetime.now(ET)).isoformat()
    newly_final = []
    for r in pending:
        date_iso = r.get("date")
        away_ab, home_ab = r.get("away_abbrev"), r.get("home_abbrev")
        try:
            game_number = int(r.get("game_number") or 1)
        except ValueError:
            game_number = 1

        schedule_data = schedule_by_date.get(date_iso)
        if not schedule_data:
            continue
        game = _find_game(schedule_data, away_ab, home_ab, game_number)
        if game is None:
            continue
        if game.get("status", {}).get("abstractGameState") != "Final":
            continue

        away_score = game["teams"]["away"].get("score")
        home_score = game["teams"]["home"].get("score")
        if away_score is None or home_score is None:
            continue  # marked Final but no score present - don't guess, wait for next check

        winner_ab = ""
        if game["teams"]["away"].get("isWinner"):
            winner_ab = away_ab
        elif game["teams"]["home"].get("isWinner"):
            winner_ab = home_ab

        row = ResultRow(
            game_id=r["game_id"],
            date=date_iso,
            away_abbrev=away_ab,
            home_abbrev=home_ab,
            game_number=game_number,
            away_score=away_score,
            home_score=home_score,
            winner_abbrev=winner_ab,
            total_runs=away_score + home_score,
            status="Final",
            fetched_at=fetched_at,
        )
        by_id[row.game_id] = row.as_dict()
        newly_final.append(row)

    if newly_final:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for key in sorted(by_id):
                writer.writerow(by_id[key])

    return newly_final
