"""
Orchestrates the daily MLB analysis report: fetches all four sources
(isolating failures so one bad source doesn't take down the report),
builds the joined/analyzed data, renders static HTML, and writes it to
docs/ (today-dated + a rolling index.html for GitHub Pages).

Usage: python main.py
"""

import sys
import traceback
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from mlb_daily.analysis.build import build_report_data
from mlb_daily.fetch import dratings, moundedge, reddit, sportsbettingdime
from mlb_daily.report.render import render_report

ET = ZoneInfo("America/New_York")
OUTPUT_DIR = Path(__file__).resolve().parent / "docs"


def _fetch_safe(label, fn, default):
    try:
        return fn()
    except Exception as e:
        print(f"[warn] {label} fetch failed: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return default


def main():
    now_et = datetime.now(ET)
    today_iso = now_et.strftime("%Y-%m-%d")
    today_display = now_et.strftime("%A, %B %-d, %Y")
    generated_at = now_et.strftime("%Y-%m-%d %H:%M %Z")

    print(f"Building MLB daily analysis for {today_display} ({today_iso})")

    dr_games = _fetch_safe("DRatings", dratings.fetch_today_games, [])
    print(f"DRatings: {len(dr_games)} games")

    me_games = _fetch_safe("MoundEdge", moundedge.fetch_today_games, [])
    print(f"MoundEdge: {len(me_games)} games")
    slate_subtitle = me_games[0].slate_subtitle if me_games else ""

    sbd_status = _fetch_safe(
        "SportsBettingDime", sportsbettingdime.check_source,
        sportsbettingdime.SBDStatus(reachable=False, note="fetch failed"),
    )
    print(f"SportsBettingDime: {sbd_status.note}")

    reddit_result = _fetch_safe(
        "Reddit", lambda: reddit.fetch_daily_sentiment(today_iso),
        reddit.RedditResult(available=False, source="unavailable", note="fetch raised an exception"),
    )
    print(f"Reddit: source={reddit_result.source} available={reddit_result.available}")

    report_data = build_report_data(dr_games, me_games, reddit_result, today_iso, today_display, slate_subtitle)
    report_data["sbd_status_note"] = sbd_status.note

    html = render_report(report_data, generated_at)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = OUTPUT_DIR / f"{today_iso}.html"
    index_path = OUTPUT_DIR / "index.html"
    dated_path.write_text(html, encoding="utf-8")
    index_path.write_text(html, encoding="utf-8")

    print(f"Wrote {dated_path} and {index_path}")


if __name__ == "__main__":
    main()
