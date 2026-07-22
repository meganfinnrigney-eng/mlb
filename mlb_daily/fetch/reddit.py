"""
Confirms today's MLB daily discussion thread exists on r/sportsbook and
captures its original-post text via the subreddit's RSS feed
(/r/sportsbook/new.rss). This is intentionally NOT full sentiment
analysis: RSS is submissions-only, so no comment discussion is available
here - only the OP's own text. Comment-level "recurring picks/reasoning
across posters" requires either a manually-pasted thread (see below) or
Reddit's official OAuth API (not yet integrated into this project).

Reddit's unauthenticated .json endpoints (search.json, <permalink>.json)
started returning blocked/403 responses regardless of request rate or
User-Agent, so this module no longer uses them. RSS is also rate-limited
(observed 429s on back-to-back requests within the same minute), so this
does exactly one GET per run and does not retry - we only need the thread
once a day, and retrying risks tripping the limit further for no benefit.

Manual fallback: drop the thread's text into
    mlb_daily/data/reddit_manual_<YYYY-MM-DD>.txt
(one paste per day, plain text) before/after a run - the next run (or a
manual `workflow_dispatch` re-run) will pick it up automatically. This is
still the only way to get real comment-level sentiment into the report.
"""

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from mlb_daily.teams import NICKNAME_TO_ABBREV

USER_AGENT = "mlb-daily-tracker/1.0 (personal project; non-commercial daily digest)"
HEADERS = {"User-Agent": USER_AGENT}

REDDIT_RSS_URL = "https://www.reddit.com/r/sportsbook/new.rss"
ATOM_NS = "{http://www.w3.org/2005/Atom}"

MANUAL_FALLBACK_DIR = Path(__file__).resolve().parent.parent / "data"

TEAM_KEYWORDS = NICKNAME_TO_ABBREV

_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(TEAM_KEYWORDS, key=len, reverse=True)) + r")\b"
)


@dataclass
class RedditMention:
    team_abbrev: str
    team_keyword: str
    snippets: list = field(default_factory=list)
    count: int = 0


@dataclass
class RedditResult:
    available: bool
    source: str  # 'rss', 'manual', or 'unavailable'
    thread_title: str = ""
    thread_url: str = ""
    mentions: dict = field(default_factory=dict)  # abbrev -> RedditMention
    note: str = ""


def _fetch_rss_once():
    r = requests.get(REDDIT_RSS_URL, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.text


def _parse_rss_entries(xml_text):
    root = ET.fromstring(xml_text)
    entries = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        title_el = entry.find(f"{ATOM_NS}title")
        link_el = entry.find(f"{ATOM_NS}link")
        content_el = entry.find(f"{ATOM_NS}content")
        entries.append(
            {
                "title": title_el.text if title_el is not None else "",
                "url": link_el.get("href") if link_el is not None else "",
                "content": content_el.text if content_el is not None else "",
            }
        )
    return entries


def _find_todays_mlb_entry(entries, today_iso):
    dt = datetime.strptime(today_iso, "%Y-%m-%d")
    date_variants = {
        f"{dt.month}/{dt.day}/{dt.strftime('%y')}",
        f"{dt.month}/{dt.day}/{dt.year}",
    }
    for entry in entries:
        title = entry["title"] or ""
        if "mlb" not in title.lower():
            continue
        if any(variant in title for variant in date_variants):
            return entry
    return None


def _clean_op_text(raw_content):
    unescaped = html.unescape(raw_content or "")
    return re.sub(r"<[^>]+>", " ", unescaped)


def _extract_mentions(text):
    mentions = {}
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for m in _KEYWORD_PATTERN.finditer(sentence):
            keyword = m.group(1)
            abbrev = TEAM_KEYWORDS[keyword]
            entry = mentions.setdefault(abbrev, RedditMention(team_abbrev=abbrev, team_keyword=keyword))
            entry.count += 1
            if len(entry.snippets) < 3:
                clean = re.sub(r"\s+", " ", sentence).strip()
                if clean and clean not in entry.snippets:
                    entry.snippets.append(clean)
    return mentions


def _load_manual_fallback(today_iso):
    path = MANUAL_FALLBACK_DIR / f"reddit_manual_{today_iso}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None


def fetch_daily_sentiment(today_iso):
    try:
        xml_text = _fetch_rss_once()
        entries = _parse_rss_entries(xml_text)
        entry = _find_todays_mlb_entry(entries, today_iso)
        if entry is None:
            raise ValueError("no MLB thread dated today found in r/sportsbook's RSS feed")

        op_text = _clean_op_text(entry["content"])
        mentions = _extract_mentions(op_text)
        return RedditResult(
            available=True,
            source="rss",
            thread_title=entry["title"],
            thread_url=entry["url"],
            mentions=mentions,
            note=(
                "fetched via RSS - original post text only, no comment discussion "
                "(Reddit's .json endpoints are blocked; RSS is submissions-only, "
                "so this confirms the thread and its OP text, not recurring "
                "picks/reasoning across commenters)"
            ),
        )
    except Exception as api_exc:
        manual_text = _load_manual_fallback(today_iso)
        if manual_text:
            mentions = _extract_mentions(manual_text)
            return RedditResult(
                available=True,
                source="manual",
                thread_title=f"(manually pasted for {today_iso})",
                mentions=mentions,
                note="live fetch failed; used manually-pasted thread text (includes comments if pasted)",
            )
        return RedditResult(
            available=False,
            source="unavailable",
            note=(
                f"live RSS fetch failed ({api_exc}) and no manual paste found at "
                f"mlb_daily/data/reddit_manual_{today_iso}.txt - to include Reddit "
                f"sentiment today, paste the daily thread's text into that file and "
                f"re-run the workflow."
            ),
        )
