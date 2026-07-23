"""
Trailing-N-days "highest conviction" accuracy history - a display layer
over predictions_log.csv + results_log.csv (scoring.py's data), not new
data infrastructure. For each of the last few days, finds that day's
single highest-conviction moneyline pick and single highest-conviction
totals pick - mirroring build.py's Conviction Board vote-counting and
CONVICTION_MIN_SOURCES/CONVICTION_MAX_DISSENT thresholds exactly, just
applied to logged historical picks instead of live source objects
(a past day's Matchup objects no longer exist by the time this runs) -
then checks each against what actually happened. Scoped to one pick per
side per day, not all of that day's games, to keep the table readable.
"""

from collections import Counter
from dataclasses import dataclass

from mlb_daily.analysis.build import CONVICTION_MAX_DISSENT, CONVICTION_MIN_SOURCES
from mlb_daily.teams import full_name

_MONEYLINE_FIELDS = (("dratings_pick", "DRatings"), ("bpp_pick", "BPP"), ("mymodel_pick", "My model"), ("kalshi_pick", "Kalshi"))
_TOTALS_PROJ_FIELDS = (("dratings_total_proj", "DRatings"), ("bpp_total_proj", "BPP"), ("mymodel_total_proj", "My model"))


@dataclass
class DayRecord:
    date: str
    ml_matchup: str | None = None
    ml_pick: str | None = None
    ml_pick_name: str | None = None
    ml_agree: str | None = None
    ml_actual_winner: str | None = None
    ml_correct: bool | None = None
    totals_matchup: str | None = None
    totals_pick: str | None = None
    totals_agree: str | None = None
    totals_market_line: float | None = None
    totals_actual_total: float | None = None
    totals_correct: bool | None = None


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _moneyline_votes(row):
    return [(label, row[field]) for field, label in _MONEYLINE_FIELDS if row.get(field)]


def _totals_votes(row):
    votes = []
    market_total = _to_float(row.get("market_total"))
    if market_total is not None:
        for field, label in _TOTALS_PROJ_FIELDS:
            proj = _to_float(row.get(field))
            if proj is not None:
                votes.append((label, "over" if proj > market_total else "under"))
    kalshi_lean = row.get("kalshi_total_pick")
    if kalshi_lean:
        votes.append(("Kalshi", kalshi_lean))
    return votes


def _highest_conviction(rows, votes_fn):
    """The single game (from a day's predictions_log rows) with the most
    source agreement, same 'at least 3 of 4 sources, at most 1 dissenting'
    bar as build.py's Conviction Board - never a forced pick if nothing
    clears it. Ties broken the same way the live board is sorted: more
    agreeing sources first, then more total sources present."""
    best = None
    best_key = None
    for row in rows:
        votes = votes_fn(row)
        if len(votes) < CONVICTION_MIN_SOURCES:
            continue
        counts = Counter(choice for _, choice in votes)
        top_choice, top_count = counts.most_common(1)[0]
        total = len(votes)
        if total - top_count > CONVICTION_MAX_DISSENT:
            continue
        key = (top_count, total)
        if best is None or key > best_key:
            best = (row, top_choice, top_count, total)
            best_key = key
    return best


def build_track_record(predictions_rows, results_rows, num_days=7, exclude_date=None):
    """Returns a list of DayRecord, most recent day first, for up to the
    last `num_days` distinct dates present in predictions_rows (excluding
    exclude_date - normally today, whose games likely aren't final yet)."""
    results_by_id = {r["game_id"]: r for r in results_rows if r.get("game_id")}

    by_date = {}
    for p in predictions_rows:
        d = p.get("date")
        if d:
            by_date.setdefault(d, []).append(p)

    dates = sorted((d for d in by_date if d != exclude_date), reverse=True)[:num_days]

    records = []
    for date in dates:
        rows = by_date[date]
        rec = DayRecord(date=date)

        ml_best = _highest_conviction(rows, _moneyline_votes)
        if ml_best:
            row, pick, agree_n, total_n = ml_best
            rec.ml_matchup = f"{row['away_abbrev']} @ {row['home_abbrev']}"
            rec.ml_pick = pick
            rec.ml_pick_name = full_name(pick)
            rec.ml_agree = f"{agree_n}/{total_n}"
            result = results_by_id.get(row.get("game_id"))
            if result and result.get("winner_abbrev"):
                rec.ml_actual_winner = result["winner_abbrev"]
                rec.ml_correct = pick == result["winner_abbrev"]

        totals_best = _highest_conviction(rows, _totals_votes)
        if totals_best:
            row, lean, agree_n, total_n = totals_best
            rec.totals_matchup = f"{row['away_abbrev']} @ {row['home_abbrev']}"
            rec.totals_pick = lean
            rec.totals_agree = f"{agree_n}/{total_n}"
            rec.totals_market_line = _to_float(row.get("market_total"))
            result = results_by_id.get(row.get("game_id"))
            if result and result.get("total_runs") not in (None, ""):
                actual_total = _to_float(result["total_runs"])
                rec.totals_actual_total = actual_total
                if (
                    actual_total is not None
                    and rec.totals_market_line is not None
                    and actual_total != rec.totals_market_line
                ):
                    actual_lean = "over" if actual_total > rec.totals_market_line else "under"
                    rec.totals_correct = lean == actual_lean

        records.append(rec)

    return records
