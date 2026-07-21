"""
Fetches today's MLB game predictions from DRatings.

The predictor page (https://www.dratings.com/predictor/mlb-baseball-predictions/)
is plain server-rendered HTML - no JS execution needed. Each row of the
"Upcoming Games for <date>" table holds: game time, both teams (with
records), both starting pitchers, DRatings' win probabilities, best market
moneyline/spread/total across tracked books, and DRatings' own projected
score per team ("Runs" column).
"""

import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

URL = "https://www.dratings.com/predictor/mlb-baseball-predictions/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass
class DRatingsGame:
    away_team: str
    home_team: str
    away_pitcher: str
    home_pitcher: str
    away_win_pct: float | None
    home_win_pct: float | None
    away_projected_runs: float | None
    home_projected_runs: float | None
    total_projected_runs: float | None
    market_total: float | None
    detail_url: str | None = None
    raw: dict = field(default_factory=dict)


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_two_stacked_spans(cell):
    """Cells like <span>Team A</span><br/><span>Team B</span> -> [textA, textB]."""
    spans = cell.find_all("span", recursive=False) if cell else []
    if len(spans) >= 2:
        return [_clean(s.get_text()) for s in spans[:2]]
    # fallback: split on <br>
    if cell is None:
        return [None, None]
    parts = [p for p in cell.stripped_strings]
    if len(parts) >= 2:
        return parts[:2]
    return [parts[0] if parts else None, None]


def _first_number(text):
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def _market_total_from_ou_cell(cell):
    """Cell holds things like 'o9-102' / 'u9-110' across offshore/vegas divs; the
    number right after o/u is the total line."""
    if cell is None:
        return None
    text = cell.get_text(" ", strip=True)
    m = re.search(r"[ou](\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def fetch_today_games(timeout=20):
    """Returns a list of DRatingsGame for today's upcoming slate. Raises on
    network/parsing failure at the top level so callers can decide how to
    degrade (this source is optional in the final report)."""
    r = requests.get(URL, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    heading = soup.find(lambda tag: tag.name in ("h2", "h3") and "Upcoming Games" in tag.get_text())
    table = heading.find_next("table") if heading else soup.find("table")
    if table is None:
        raise ValueError("DRatings: could not locate the upcoming-games table")

    header_cells = [_clean(th.get_text()) for th in table.select("thead th")]
    col_index = {name.lower(): i for i, name in enumerate(header_cells)}

    def col(cells, name, default=None):
        i = col_index.get(name)
        if i is None or i >= len(cells):
            return default
        return cells[i]

    games = []
    for tr in table.select("tbody.table-body > tr"):
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        try:
            teams_cell = col(cells, "teams")
            away_team, home_team = _parse_two_stacked_spans(teams_cell)

            pitchers_cell = col(cells, "pitchers")
            away_pitcher, home_pitcher = _parse_two_stacked_spans(pitchers_cell)

            win_cell = col(cells, "win")
            win_spans = win_cell.find_all("span", recursive=False) if win_cell else []
            away_win = _first_number(win_spans[0].get_text()) if len(win_spans) > 0 else None
            home_win = _first_number(win_spans[1].get_text()) if len(win_spans) > 1 else None

            runs_cell = col(cells, "runs")
            away_runs = home_runs = None
            if runs_cell is not None:
                parts = list(runs_cell.stripped_strings)
                if len(parts) >= 2:
                    away_runs, home_runs = _first_number(parts[0]), _first_number(parts[1])

            total_cell = col(cells, "total runs")
            total_runs = _first_number(total_cell.get_text()) if total_cell is not None else None

            ou_cell = col(cells, "best o/u")
            market_total = _market_total_from_ou_cell(ou_cell)

            link = tr.find("a", href=True)
            detail_url = ("https://www.dratings.com" + link["href"]) if link else None

            games.append(
                DRatingsGame(
                    away_team=away_team,
                    home_team=home_team,
                    away_pitcher=away_pitcher,
                    home_pitcher=home_pitcher,
                    away_win_pct=away_win,
                    home_win_pct=home_win,
                    away_projected_runs=away_runs,
                    home_projected_runs=home_runs,
                    total_projected_runs=total_runs,
                    market_total=market_total,
                    detail_url=detail_url,
                )
            )
        except Exception:
            # skip malformed rows rather than failing the whole source
            continue

    return games
