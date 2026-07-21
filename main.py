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
from mlb_daily.report import fonts
from mlb_daily.report.render import render_artifact_fragment, render_report

ET = ZoneInfo("America/New_York")  # MLB slates are organized by US Eastern date
PT = ZoneInfo("America/Los_Angeles")  # "generated at" is shown in Pacific time
OUTPUT_DIR = Path(__file__).resolve().parent / "docs"
FONT_CACHE_PATH = Path(__file__).resolve().parent / "mlb_daily" / "report" / "inline_fonts.cache.css"


def _inline_font_css():
    """Cached so the ~150KB of embedded woff2 data isn't re-fetched every
    single day - Oswald/Inter don't change. Delete the cache file to force
    a re-fetch (e.g. if the font weights used here ever change)."""
    if FONT_CACHE_PATH.exists():
        return FONT_CACHE_PATH.read_text(encoding="utf-8")
    css = fonts.build_inline_font_css()
    FONT_CACHE_PATH.write_text(css, encoding="utf-8")
    return css


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
    generated_at = datetime.now(PT).strftime("%Y-%m-%d %H:%M %Z")

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

    inline_font_css = _fetch_safe("Google Fonts (Oswald/Inter)", _inline_font_css, "")
    if inline_font_css:
        print(f"Inline fonts: {len(inline_font_css) // 1024}KB embedded")

    html = render_report(report_data, generated_at)
    fragment_html = render_artifact_fragment(report_data, generated_at, inline_font_css)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dated_path = OUTPUT_DIR / f"{today_iso}.html"
    index_path = OUTPUT_DIR / "index.html"
    fragment_path = OUTPUT_DIR / "artifact_fragment.html"
    dated_path.write_text(html, encoding="utf-8")
    index_path.write_text(html, encoding="utf-8")
    fragment_path.write_text(fragment_html, encoding="utf-8")

    print(f"Wrote {dated_path}, {index_path}, and {fragment_path}")


if __name__ == "__main__":
    main()
