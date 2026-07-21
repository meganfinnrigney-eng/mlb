"""
SportsBettingDime's public betting trends page renders its actual split
percentages client-side via a proprietary web component
(`<srwc-public-betting-trends>`, part of the "Sports API Solutions" widget
library). The percentages are not present in the server-rendered HTML and
there is no public JSON/CSV endpoint for them (checked: no matching
wp-json route, no inline JSON props on the widget tag - only book IDs).

Fully rendering that widget would require a headless browser, which is more
machinery than a personal daily script warrants for one field that's
already available elsewhere: MoundEdge's game cards embed the same
bets%/money% splits (see fetch/moundedge.py), evidently mirroring
SportsBettingDime's numbers. This module fetches the page only to confirm
it's reachable and to describe its structure for the report's source
summary; it deliberately does not attempt to scrape the split percentages.
"""

from dataclasses import dataclass

import requests

URL = "https://www.sportsbettingdime.com/mlb/public-betting-trends/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass
class SBDStatus:
    reachable: bool
    note: str


def check_source(timeout=15):
    try:
        r = requests.get(URL, headers=HEADERS, timeout=timeout)
        r.raise_for_status()
        reachable = "srwc-public-betting-trends" in r.text
    except Exception as e:
        return SBDStatus(reachable=False, note=f"unreachable ({e})")

    if reachable:
        note = (
            "page reachable; split percentages are rendered client-side by a JS "
            "widget and are not in the static HTML, so this report uses "
            "MoundEdge's embedded bets%/money% splits instead (see below)."
        )
    else:
        note = "page reachable but the expected betting-trends widget was not found."
    return SBDStatus(reachable=reachable, note=note)
