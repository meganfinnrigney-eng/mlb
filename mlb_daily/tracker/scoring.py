"""
Joins predictions_log.csv and results_log.csv on game_id and scores each
source's accuracy. Pure computation - no fetching, no network calls.

A source's blank/missing pick or projection for a given game is excluded
from that source's own denominator entirely, never counted as a miss:
e.g. if DRatings had no row for a game, that game doesn't count toward
DRatings' accuracy % at all. Likewise a game with no results_log.csv row
yet (not final) is skipped for every source - it isn't scoreable yet.

Moneyline accuracy is directly comparable across all four sources
(DRatings, BPP, My model, Kalshi's win-market) - each logs a picked team,
scored against whether that team actually won.

Totals accuracy is NOT uniform across sources, and treating it as such
would be a real modeling error: DRatings/BPP/My model each log a
specific projected total (a number of runs), scored as average absolute
error against the actual total. Kalshi never projects a specific total -
it only logs a lean (over/under) relative to its own market line - so
"how accurate was Kalshi's total call" is a hit-rate percentage (did the
lean match how the actual total compared to Kalshi's line), a different
metric on a different scale from "average runs of error." Reporting them
side by side without labeling this difference would be misleading.
"""

from dataclasses import dataclass

MONEYLINE_SOURCES = ("dratings", "bpp", "mymodel", "kalshi")
NUMERIC_TOTAL_SOURCES = ("dratings", "bpp", "mymodel")


@dataclass
class MoneylineAccuracy:
    source: str
    games_scored: int
    correct_picks: int
    accuracy_pct: float | None


@dataclass
class NumericTotalAccuracy:
    source: str
    games_scored: int
    avg_abs_error_runs: float | None


@dataclass
class KalshiTotalAccuracy:
    games_scored: int
    correct_leans: int
    accuracy_pct: float | None


def _to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def score_predictions(predictions_rows, results_rows):
    """predictions_rows / results_rows: lists of dicts (e.g. from
    csv.DictReader). Returns {
        "moneyline": {source: MoneylineAccuracy, ...},
        "totals": {source: NumericTotalAccuracy, ...},   # dratings/bpp/mymodel
        "kalshi_totals": KalshiTotalAccuracy,
    }"""
    results_by_id = {r["game_id"]: r for r in results_rows if r.get("game_id")}

    ml_stats = {s: {"n": 0, "correct": 0} for s in MONEYLINE_SOURCES}
    total_stats = {s: {"n": 0, "err_sum": 0.0} for s in NUMERIC_TOTAL_SOURCES}
    kalshi_total_stats = {"n": 0, "correct": 0}

    for p in predictions_rows:
        result = results_by_id.get(p.get("game_id"))
        if not result:
            continue  # not final yet - excluded entirely, not a miss

        winner_ab = result.get("winner_abbrev")
        actual_total = _to_float(result.get("total_runs"))

        for source in MONEYLINE_SOURCES:
            pick = p.get(f"{source}_pick")
            if not pick:
                continue
            ml_stats[source]["n"] += 1
            if pick == winner_ab:
                ml_stats[source]["correct"] += 1

        for source in NUMERIC_TOTAL_SOURCES:
            proj = _to_float(p.get(f"{source}_total_proj"))
            if proj is None or actual_total is None:
                continue
            total_stats[source]["n"] += 1
            total_stats[source]["err_sum"] += abs(proj - actual_total)

        kalshi_lean = p.get("kalshi_total_pick")
        kalshi_line = _to_float(p.get("kalshi_total_line"))
        if kalshi_lean and kalshi_line is not None and actual_total is not None:
            actual_lean = "over" if actual_total > kalshi_line else ("under" if actual_total < kalshi_line else "push")
            if actual_lean != "push":
                kalshi_total_stats["n"] += 1
                if kalshi_lean == actual_lean:
                    kalshi_total_stats["correct"] += 1

    moneyline = {}
    for source, s in ml_stats.items():
        pct = round(100 * s["correct"] / s["n"], 1) if s["n"] else None
        moneyline[source] = MoneylineAccuracy(source=source, games_scored=s["n"], correct_picks=s["correct"], accuracy_pct=pct)

    totals = {}
    for source, s in total_stats.items():
        avg_err = round(s["err_sum"] / s["n"], 2) if s["n"] else None
        totals[source] = NumericTotalAccuracy(source=source, games_scored=s["n"], avg_abs_error_runs=avg_err)

    kt = kalshi_total_stats
    kalshi_pct = round(100 * kt["correct"] / kt["n"], 1) if kt["n"] else None
    kalshi_totals = KalshiTotalAccuracy(games_scored=kt["n"], correct_leans=kt["correct"], accuracy_pct=kalshi_pct)

    return {"moneyline": moneyline, "totals": totals, "kalshi_totals": kalshi_totals}
