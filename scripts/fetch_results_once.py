"""
One-off manual invocation of the results tracker (mlb_daily/tracker/log_results.py),
for spot-checking real completed games' data in results_log.csv.

Deliberately does NOT touch docs/, MoundEdge, DRatings, Kalshi, or My
model - only reads the official MLB Stats API schedule endpoint. Safe to
run any time, including overnight, unlike the full daily-report.yml
pipeline (which the user wants triggered manually only after mid-morning
ET, due to MoundEdge/DRatings' own staleness in the pre-dawn window -
this script has no such dependency).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mlb_daily.tracker.log_results import fetch_and_log_results


def main():
    newly_final = fetch_and_log_results()
    print(f"{len(newly_final)} game(s) newly recorded as final:")
    for r in newly_final:
        print(f"  {r.game_id}: {r.away_abbrev} {r.away_score} @ {r.home_abbrev} {r.home_score} (winner: {r.winner_abbrev}, total: {r.total_runs})")


if __name__ == "__main__":
    sys.exit(main())
