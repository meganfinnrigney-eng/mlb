"""
Pulls today's MLB daily discussion thread from Reddit via the unauthenticated
.json endpoints (no OAuth app registration). Reddit blocks a lot of
datacenter/cloud traffic outright regardless of rate - if every attempt
fails, this falls back to a manually-pasted thread text file so the daily
run degrades gracefully instead of crashing.

Manual fallback: drop the thread's text into
    mlb_daily/data/reddit_manual_<YYYY-MM-DD>.txt
(one paste per day, plain text) before/after a run - the next run (or a
manual `workflow_dispatch` re-run) will pick it up automatically.
"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import requests

from mlb_daily.teams import NICKNAME_TO_ABBREV

USER_AGENT = "mlb-daily-tracker/1.0 (personal project; non-commercial daily digest)"
HEADERS = {"User-Agent": USER_AGENT}

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
    source: str  # 'api', 'manual', or 'unavailable'
    thread_title: str = ""
    thread_url: str = ""
    mentions: dict = field(default_factory=dict)  # abbrev -> RedditMention
    note: str = ""


def _get_with_retries(url, attempts=3, backoff=2):
    last_exc = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            if r.status_code == 200:
                return r
            if r.status_code in (429, 500, 502, 503, 504) and i < attempts - 1:
                time.sleep(backoff * (2**i))
                continue
            r.raise_for_status()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(backoff * (2**i))
    if last_exc:
        raise last_exc
    raise RuntimeError(f"failed to fetch {url}")


def _find_daily_thread():
    for sub, query in [("sportsbook", "MLB daily thread"), ("baseball", "daily discussion")]:
        url = (
            f"https://www.reddit.com/r/{sub}/search.json"
            f"?q={requests.utils.quote(query)}&restrict_sr=1&sort=new&limit=10"
        )
        r = _get_with_retries(url)
        data = r.json()
        candidates = [
            child["data"]
            for child in data.get("data", {}).get("children", [])
            if "daily" in child["data"].get("title", "").lower()
        ]
        if candidates:
            best = max(candidates, key=lambda c: c.get("created_utc", 0))
            return best
    return None


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
        thread = _find_daily_thread()
        if thread is None:
            raise ValueError("no daily thread found in recent search results")

        permalink = thread["permalink"].rstrip("/")
        thread_url = f"https://www.reddit.com{permalink}"
        r = _get_with_retries(f"https://www.reddit.com{permalink}.json")
        listings = r.json()

        texts = [thread.get("selftext", "")]
        if len(listings) > 1:
            for child in listings[1].get("data", {}).get("children", []):
                body = child.get("data", {}).get("body")
                if body:
                    texts.append(body)

        mentions = _extract_mentions("\n".join(texts))
        return RedditResult(
            available=True,
            source="api",
            thread_title=thread.get("title", ""),
            thread_url=thread_url,
            mentions=mentions,
            note=f"fetched {len(texts) - 1} comments from the live thread",
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
                note="live fetch failed; used manually-pasted thread text",
            )
        return RedditResult(
            available=False,
            source="unavailable",
            note=(
                f"live fetch failed ({api_exc}) and no manual paste found at "
                f"mlb_daily/data/reddit_manual_{today_iso}.txt - to include Reddit "
                f"sentiment today, paste the daily thread's text into that file and "
                f"re-run the workflow."
            ),
        )
