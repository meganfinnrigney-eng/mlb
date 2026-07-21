"""
Fetches today's MLB game previews from MoundEdge (https://moundedge.github.io/MLB-Summaries/).

This is a plain static HTML page (GitHub Pages, no JS data-loading) with one
`<div class="game" id="g-{AWAY}-{HOME}">` card per game. Each card already
contains: BPP sim projected score alongside a separate "Model" projection,
weather/park run-environment effect, starting-pitcher home/road splits
(in prose), hitting/bullpen trend arrows vs season stats, market lines, and
bets%/money% betting splits (MoundEdge's own mirror of public betting data,
used here in place of scraping SportsBettingDime's JS-rendered widget - see
README).
"""

import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

URL = "https://moundedge.github.io/MLB-Summaries/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

ARROW_COLOR_DIRECTION = {
    "#1a7d3c": "up",
    "#c0392b": "down",
    "#9aa4b1": "flat",
}


@dataclass
class TeamSide:
    abbrev: str
    record: str = ""
    pitcher_name: str = ""
    pitcher_hand: str = ""
    moneyline: str = ""


@dataclass
class TrendStat:
    l30: float | None
    szn: float | None
    trend: str | None  # 'up' / 'down' / 'flat'


@dataclass
class MoundEdgeGame:
    away: TeamSide
    home: TeamSide
    slate_subtitle: str = ""
    game_time: str = ""
    venue: str = ""
    weather_text: str = ""
    park_factor_text: str = ""
    weather_net_pct: float | None = None
    away_pitcher_home_era: float | None = None
    away_pitcher_road_era: float | None = None
    home_pitcher_home_era: float | None = None
    home_pitcher_road_era: float | None = None
    away_pitcher_era_szn: float | None = None
    home_pitcher_era_szn: float | None = None
    hitting_trend: dict = field(default_factory=dict)  # {"away": TrendStat(wRC+), "home": ...}
    bullpen_trend: dict = field(default_factory=dict)
    pitcher_trend: dict = field(default_factory=dict)
    model_away_runs: float | None = None
    model_home_runs: float | None = None
    model_total: float | None = None
    bpp_away_runs: float | None = None
    bpp_home_runs: float | None = None
    bpp_total: float | None = None
    market_total: float | None = None
    market_ml_away: str | None = None
    market_ml_home: str | None = None
    split_ml_away_bets: float | None = None
    split_ml_away_money: float | None = None
    split_ml_home_bets: float | None = None
    split_ml_home_money: float | None = None
    split_total_over_bets: float | None = None
    split_total_over_money: float | None = None
    split_total_under_bets: float | None = None
    split_total_under_money: float | None = None
    split_sharp_note: str = ""
    game_outlook: str = ""


def _clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def _first_float(text):
    if not text:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def _arrow_direction(td):
    if td is None:
        return None
    style = td.get("style", "")
    for color, direction in ARROW_COLOR_DIRECTION.items():
        if color in style:
            return direction
    return None


def _parse_side(side_div):
    tn = side_div.select_one(".tn")
    tr = side_div.select_one(".tr")
    odds_divs = side_div.select(".odds")
    pitcher_name, pitcher_hand = "", ""
    if odds_divs:
        m = re.search(r"SP:\s*(.+?)\s*\(([A-Z])\)", _clean(odds_divs[0].get_text()))
        if m:
            pitcher_name, pitcher_hand = m.group(1), m.group(2)
    ml = _clean(odds_divs[1].get_text()) if len(odds_divs) > 1 else ""
    record = _clean(tr.get_text()).split("·")[-1].strip() if tr else ""
    return TeamSide(
        abbrev=_clean(tn.get_text()) if tn else "",
        record=record,
        pitcher_name=pitcher_name,
        pitcher_hand=pitcher_hand,
        moneyline=ml,
    )


def _parse_stat_table(table, stat_names):
    """Generic parser for the Starting Pitchers / Hitting / Bullpen tables.
    Returns [{name: value_or_(l30,szn), 'trend': direction}, ...] one dict per row
    (away row first, home row second), keyed by header text (lowercased)."""
    if table is None:
        return []
    headers = [_clean(th.get_text()).lower() for th in table.select("tr")[0].find_all("th")]
    rows = table.select("tr")[1:]
    out = []
    for tr in rows:
        cells = tr.find_all("td")
        row = {}
        for name, td in zip(headers, cells):
            sv = td.select_one(".sv")
            if sv is not None:
                szn_text = sv.get_text()
                l30_text = td.get_text().replace(szn_text, "", 1)
                row[name] = (_first_float(l30_text), _first_float(szn_text))
            elif "trend" in name:
                row[name] = _arrow_direction(td)
            else:
                row[name] = _clean(td.get_text())
        out.append(row)
    return out


def _parse_home_road_era(narrative_p):
    """Pull ERA figures out of prose like 'In his road starts ... 2.47 ERA' /
    'In his home starts ... 4.11 ERA'."""
    if narrative_p is None:
        return None, None
    text = _clean(narrative_p.get_text())
    home = re.search(r"home starts.*?(\d+\.\d{2})\s*ERA", text)
    road = re.search(r"road starts.*?(\d+\.\d{2})\s*ERA", text)
    return (float(home.group(1)) if home else None, float(road.group(1)) if road else None)


def _section_div(game_div, emoji_text_fragment):
    return game_div.find("div", class_="sec", string=lambda s: s and emoji_text_fragment in s)


def _parse_game(game_div):
    game_id = game_div.get("id", "")
    m = re.match(r"g-([A-Z]+)-([A-Z]+)", game_id)
    away_abbrev, home_abbrev = (m.group(1), m.group(2)) if m else (None, None)

    sides = game_div.select(".mh > .side")
    away = _parse_side(sides[0]) if len(sides) > 0 else TeamSide(abbrev=away_abbrev or "")
    home = _parse_side(sides[1]) if len(sides) > 1 else TeamSide(abbrev=home_abbrev or "")

    game = MoundEdgeGame(away=away, home=home)

    gmeta = game_div.select_one(".gmeta")
    if gmeta is not None:
        spans = [_clean(s.get_text()) for s in gmeta.find_all("span", recursive=False) if "d" not in (s.get("class") or [])]
        if spans:
            game.game_time = spans[0]
        if len(spans) > 1:
            game.venue = spans[1]

    wx_div = game_div.select_one(".wx")
    if wx_div is not None:
        game.weather_text = _clean(wx_div.get_text())
        net_m = re.search(r"BP net (-?\d+)%", game.weather_text)
        game.weather_net_pct = float(net_m.group(1)) if net_m else None
        park_m = re.search(r"Park:\s*([^·]+)", game.weather_text)
        game.park_factor_text = _clean(park_m.group(1)) if park_m else ""

    # Starting Pitchers table + narrative home/road split paragraphs
    sp_sec = _section_div(game_div, "Starting Pitchers")
    if sp_sec is not None:
        sp_table = sp_sec.find_next("table", class_="t")
        rows = _parse_stat_table(sp_table, [])
        if len(rows) >= 2:
            game.pitcher_trend["away"] = rows[0].get("trend")
            game.pitcher_trend["home"] = rows[1].get("trend")
            away_era = rows[0].get("era")
            home_era = rows[1].get("era")
            if isinstance(away_era, tuple):
                game.away_pitcher_era_szn = away_era[1]
            if isinstance(home_era, tuple):
                game.home_pitcher_era_szn = home_era[1]
        narrative_ps = []
        node = sp_table.find_next_sibling() if sp_table else None
        while node is not None and len(narrative_ps) < 2:
            if getattr(node, "name", None) == "div" and "p" in (node.get("class") or []):
                narrative_ps.append(node)
            elif getattr(node, "name", None) == "div" and "sec" in (node.get("class") or []):
                break
            node = node.find_next_sibling()
        if len(narrative_ps) >= 1:
            game.away_pitcher_home_era, game.away_pitcher_road_era = _parse_home_road_era(narrative_ps[0])
        if len(narrative_ps) >= 2:
            game.home_pitcher_home_era, game.home_pitcher_road_era = _parse_home_road_era(narrative_ps[1])

    # Hitting table (wRC+ trend)
    hit_sec = _section_div(game_div, "Hitting")
    if hit_sec is not None:
        hit_table = hit_sec.find_next("table", class_="t")
        rows = _parse_stat_table(hit_table, [])
        if len(rows) >= 2:
            for side, row in zip(("away", "home"), rows[:2]):
                l30_szn = row.get("wrc+")
                trend = row.get("trend")
                if isinstance(l30_szn, tuple):
                    game.hitting_trend[side] = TrendStat(l30=l30_szn[0], szn=l30_szn[1], trend=trend)

    # Bullpen table (ERA trend)
    pen_sec = _section_div(game_div, "Bullpen")
    if pen_sec is not None:
        pen_table = pen_sec.find_next("table", class_="t")
        rows = _parse_stat_table(pen_table, [])
        if len(rows) >= 2:
            for side, row in zip(("away", "home"), rows[:2]):
                l30_szn = row.get("era")
                trend = row.get("trend")
                if isinstance(l30_szn, tuple):
                    game.bullpen_trend[side] = TrendStat(l30=l30_szn[0], szn=l30_szn[1], trend=trend)

    # Game Summary & Prediction block
    pred_sec = _section_div(game_div, "Game Summary")
    pred_div = pred_sec.find_next("div", class_="pred") if pred_sec is not None else None
    if pred_div is not None:
        envpct = pred_div.select_one(".envpct")
        if envpct is not None:
            game.weather_net_pct = game.weather_net_pct or _first_float(envpct.get_text())

        for fx in pred_div.select(".fx"):
            text = _clean(fx.get_text())
            if text.startswith("Lines:") or "Lines:" in text:
                total_m = re.search(r"O/U\s*(\d+(?:\.\d+)?)", text)
                game.market_total = float(total_m.group(1)) if total_m else None
                ml_m = re.findall(r"([A-Z]{2,4})\s*([+-]\d+)", text)
                for abbrev, ml in ml_m:
                    if abbrev == away.abbrev:
                        game.market_ml_away = ml
                    elif abbrev == home.abbrev:
                        game.market_ml_home = ml
            elif text.startswith("Game Outlook"):
                game.game_outlook = text.replace("Game Outlook:", "").strip()

        fx2_texts = [_clean(fx2.get_text()) for fx2 in pred_div.select(".fx2")]
        for text in fx2_texts:
            floats = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
            if text.startswith("Model") and len(floats) >= 3:
                game.model_away_runs, game.model_home_runs, game.model_total = floats[:3]
            elif text.startswith("BPP") and len(floats) >= 3:
                game.bpp_away_runs, game.bpp_home_runs, game.bpp_total = floats[:3]
            elif text.startswith("ML") and len(floats) >= 4:
                game.split_ml_away_bets, game.split_ml_away_money = floats[0], floats[1]
                game.split_ml_home_bets, game.split_ml_home_money = floats[2], floats[3]
            elif text.startswith("Total") and "Over" in text and len(floats) >= 4:
                game.split_total_over_bets, game.split_total_over_money = floats[0], floats[1]
                game.split_total_under_bets, game.split_total_under_money = floats[2], floats[3]
            elif text.startswith("Sharp"):
                game.split_sharp_note = text.replace("Sharp", "", 1).strip()

    return game


def fetch_today_games(timeout=20):
    r = requests.get(URL, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    subtitle_div = soup.select_one(".psub")
    slate_subtitle = _clean(subtitle_div.get_text()) if subtitle_div else ""

    games = []
    for game_div in soup.select("div.game"):
        game_id = game_div.get("id", "")
        if not re.match(r"g-[A-Z]+-[A-Z]+$", game_id):
            continue  # not a real matchup card (malformed/placeholder id)
        try:
            game = _parse_game(game_div)
            game.slate_subtitle = slate_subtitle
            games.append(game)
        except Exception:
            continue
    return games
