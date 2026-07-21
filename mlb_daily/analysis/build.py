"""
Joins the DRatings, MoundEdge, and Reddit data into one row per game and
computes the six notable-game triggers plus the alignment checks described
in the project brief. Pure analysis - no fetching, no rendering, no betting
recommendations of any kind (no stakes, no "plays").
"""

from dataclasses import dataclass, field

from mlb_daily.teams import abbrev_from_name

TOTAL_GAP_THRESHOLD = 1.0          # runs: model total vs market total (trigger a)
BPP_DISAGREEMENT_THRESHOLD = 1.0   # runs: DRatings vs BPP total disagreement (trigger b)
SPLIT_DIVERGENCE_THRESHOLD = 15.0  # percentage points: bets% vs money% (trigger c)
PITCHER_SPLIT_THRESHOLD = 1.0      # ERA: contextual (home/road) ERA vs season ERA (trigger d)
WEATHER_NET_THRESHOLD = 8.0        # percent: BPP net weather/park effect (trigger e)
SPOTLIGHT_TEAMS = {"DET", "SEA"}

SOURCE_URLS = {
    "SportsBettingDime": "https://www.sportsbettingdime.com/mlb/public-betting-trends/",
    "DRatings": "https://www.dratings.com/predictor/mlb-baseball-predictions/",
    "MoundEdge": "https://moundedge.github.io/MLB-Summaries/",
}

_CONDITION_ICONS = [
    (("clear", "sunny"), "☀️"),
    (("partly",), "⛅"),
    (("cloud", "overcast"), "☁️"),
    (("thunder", "storm"), "⛈️"),
    (("rain", "shower", "drizzle"), "🌧️"),
    (("snow", "flurr"), "❄️"),
    (("fog", "mist", "haze"), "🌫️"),
    (("wind",), "💨"),
]


def _weather_icon(conditions):
    text = (conditions or "").lower()
    for keywords, icon in _CONDITION_ICONS:
        if any(k in text for k in keywords):
            return icon
    return "🌤️"


def _weather_plain(net_pct):
    """Translate MoundEdge's 'BPP net %' into plain English, weather-app style."""
    if net_pct is None:
        return "unknown effect on scoring"
    if net_pct >= 8:
        return "makes scoring notably easier"
    if net_pct >= 3:
        return "makes scoring a bit easier"
    if net_pct <= -8:
        return "makes scoring notably harder"
    if net_pct <= -3:
        return "makes scoring a bit harder"
    return "close to a neutral effect on scoring"


@dataclass
class Flag:
    code: str
    label: str
    detail: str


@dataclass
class Matchup:
    away_abbrev: str
    home_abbrev: str
    away_name: str = ""
    home_name: str = ""
    game_time: str = ""
    venue: str = ""
    away_pitcher: str = ""
    home_pitcher: str = ""

    dratings: object = None
    moundedge: object = None
    reddit_away: object = None
    reddit_home: object = None

    # best-available projected score, for showing "the actual prediction" up front
    prediction_source: str = ""
    prediction_away: float | None = None
    prediction_home: float | None = None
    prediction_winner: str | None = None

    weather_icon: str = "🌤️"
    weather_plain: str = ""

    flags: list = field(default_factory=list)

    @property
    def flag_codes(self):
        return {f.code for f in self.flags}


def _match_dratings_to_abbrev(dr_games):
    """Returns {(away_abbrev, home_abbrev): DRatingsGame}."""
    out = {}
    for g in dr_games:
        away_ab = abbrev_from_name(g.away_team)
        home_ab = abbrev_from_name(g.home_team)
        if away_ab and home_ab:
            out[(away_ab, home_ab)] = g
    return out


def _winner(away_val, home_val):
    if away_val is None or home_val is None:
        return None
    if away_val == home_val:
        return "tie"
    return "away" if away_val > home_val else "home"


def _check_total_gap(m):
    me = m.moundedge
    model_total = (me.model_total if me else None) or (m.dratings.total_projected_runs if m.dratings else None)
    market_total = (me.market_total if me else None) or (m.dratings.market_total if m.dratings else None)
    if model_total is None or market_total is None:
        return None
    gap = abs(model_total - market_total)
    if gap > TOTAL_GAP_THRESHOLD:
        return Flag(
            "a", "Models expect a different total than the betting market",
            f"Model total {model_total:.1f} runs vs. market total {market_total:.1f} runs (off by {gap:.1f})",
        )
    return None


def _check_model_disagreement(m):
    if m.dratings is None or m.moundedge is None:
        return None
    dr_winner = _winner(m.dratings.away_projected_runs, m.dratings.home_projected_runs)
    bpp_winner = _winner(m.moundedge.bpp_away_runs, m.moundedge.bpp_home_runs)
    winner_disagree = dr_winner and bpp_winner and dr_winner != bpp_winner

    total_gap = None
    if m.dratings.total_projected_runs is not None and m.moundedge.bpp_total is not None:
        total_gap = abs(m.dratings.total_projected_runs - m.moundedge.bpp_total)

    if winner_disagree or (total_gap is not None and total_gap > BPP_DISAGREEMENT_THRESHOLD):
        parts = []
        if winner_disagree:
            parts.append(f"DRatings picks the {dr_winner} team, MoundEdge's BPP sim picks the {bpp_winner} team")
        if total_gap is not None and total_gap > BPP_DISAGREEMENT_THRESHOLD:
            parts.append(
                f"DRatings projects {m.dratings.total_projected_runs:.1f} total runs, BPP projects "
                f"{m.moundedge.bpp_total:.1f} (off by {total_gap:.1f})"
            )
        return Flag("b", "The two models disagree with each other", "; ".join(parts))
    return None


def _check_split_divergence(m):
    me = m.moundedge
    if me is None:
        return None
    gaps = []
    if me.split_ml_away_bets is not None and me.split_ml_away_money is not None:
        gaps.append(("ML " + m.away_abbrev, abs(me.split_ml_away_bets - me.split_ml_away_money)))
    if me.split_ml_home_bets is not None and me.split_ml_home_money is not None:
        gaps.append(("ML " + m.home_abbrev, abs(me.split_ml_home_bets - me.split_ml_home_money)))
    if me.split_total_over_bets is not None and me.split_total_over_money is not None:
        gaps.append(("Total Over", abs(me.split_total_over_bets - me.split_total_over_money)))
    if me.split_total_under_bets is not None and me.split_total_under_money is not None:
        gaps.append(("Total Under", abs(me.split_total_under_bets - me.split_total_under_money)))

    flagged = [(label, gap) for label, gap in gaps if gap > SPLIT_DIVERGENCE_THRESHOLD]
    if flagged:
        detail = "; ".join(f"{label}: {gap:.0f}-point gap between % of bets and % of money" for label, gap in flagged)
        return Flag("c", "Public bets and public money don't agree", detail)
    return None


def _check_pitcher_split(m):
    me = m.moundedge
    if me is None:
        return None
    findings = []
    if me.away_pitcher_road_era is not None and me.away_pitcher_era_szn is not None:
        gap = me.away_pitcher_road_era - me.away_pitcher_era_szn
        if abs(gap) > PITCHER_SPLIT_THRESHOLD:
            findings.append(
                f"{m.away_pitcher} road ERA {me.away_pitcher_road_era:.2f} vs season "
                f"{me.away_pitcher_era_szn:.2f} ({gap:+.2f})"
            )
    if me.home_pitcher_home_era is not None and me.home_pitcher_era_szn is not None:
        gap = me.home_pitcher_home_era - me.home_pitcher_era_szn
        if abs(gap) > PITCHER_SPLIT_THRESHOLD:
            findings.append(
                f"{m.home_pitcher} home ERA {me.home_pitcher_home_era:.2f} vs season "
                f"{me.home_pitcher_era_szn:.2f} ({gap:+.2f})"
            )
    if findings:
        return Flag("d", "Starting pitcher is far from their normal form", "; ".join(findings))
    return None


def _check_weather(m):
    me = m.moundedge
    if me is None or me.weather_net_pct is None:
        return None
    if abs(me.weather_net_pct) >= WEATHER_NET_THRESHOLD:
        return Flag(
            "e", "Weather/ballpark will change scoring a lot",
            f"{_weather_plain(me.weather_net_pct)} ({me.weather_net_pct:+.0f}% simulated effect)",
        )
    return None


def _trend_stat_contradicts(stat, higher_is_better):
    """stat: TrendStat with l30/szn/trend. Returns True if the arrow direction
    doesn't match the arithmetic L30-vs-season comparison, accounting for
    whether the stat is higher-is-better (wRC+) or lower-is-better (ERA) -
    for ERA, an L30 *below* season is the improvement and should show 'up'."""
    if stat is None or stat.l30 is None or stat.szn is None or stat.trend not in ("up", "down"):
        return False
    improved = (stat.l30 > stat.szn) if higher_is_better else (stat.l30 < stat.szn)
    return improved != (stat.trend == "up")


def _check_trend_contradiction(m):
    me = m.moundedge
    if me is None:
        return None
    findings = []
    # (section, attr, higher-is-better for this stat)
    for side_label, side_key, higher_is_better in (("hitting", "hitting_trend", True), ("bullpen", "bullpen_trend", False)):
        trend_map = getattr(me, side_key)
        for side in ("away", "home"):
            stat = trend_map.get(side)
            abbrev = m.away_abbrev if side == "away" else m.home_abbrev
            if stat and _trend_stat_contradicts(stat, higher_is_better):
                findings.append(f"{abbrev} {side_label} trend arrow vs L30/season numbers ({stat.l30} vs {stat.szn})")
    if findings:
        return Flag("f", "MoundEdge's trend arrow looks inconsistent", "; ".join(findings))
    return None


ALL_CHECKS = [
    _check_total_gap,
    _check_model_disagreement,
    _check_split_divergence,
    _check_pitcher_split,
    _check_weather,
    _check_trend_contradiction,
]


def _build_matchups(dr_games, me_games, reddit_result):
    dr_by_abbrev = _match_dratings_to_abbrev(dr_games)
    matchups = []

    me_keys = {(g.away.abbrev, g.home.abbrev) for g in me_games}
    all_keys = set(dr_by_abbrev) | me_keys

    for away_ab, home_ab in all_keys:
        dr = dr_by_abbrev.get((away_ab, home_ab))
        me = next((g for g in me_games if g.away.abbrev == away_ab and g.home.abbrev == home_ab), None)

        m = Matchup(away_abbrev=away_ab, home_abbrev=home_ab)
        m.dratings = dr
        m.moundedge = me
        m.away_name = dr.away_team if dr else (me.away.record and away_ab) or away_ab
        m.home_name = dr.home_team if dr else home_ab
        m.game_time = me.game_time if me else ""
        m.venue = me.venue if me else ""
        m.away_pitcher = (me.away.pitcher_name if me and me.away.pitcher_name else (dr.away_pitcher if dr else ""))
        m.home_pitcher = (me.home.pitcher_name if me and me.home.pitcher_name else (dr.home_pitcher if dr else ""))

        if reddit_result and reddit_result.available:
            m.reddit_away = reddit_result.mentions.get(away_ab)
            m.reddit_home = reddit_result.mentions.get(home_ab)

        # best-available projected score: prefer the BPP simulation, then MoundEdge's
        # own "Model", then DRatings - whichever is actually populated for this game
        if me and me.bpp_away_runs is not None:
            m.prediction_source, m.prediction_away, m.prediction_home = "BPP sim", me.bpp_away_runs, me.bpp_home_runs
        elif me and me.model_away_runs is not None:
            m.prediction_source, m.prediction_away, m.prediction_home = "Model", me.model_away_runs, me.model_home_runs
        elif dr and dr.away_projected_runs is not None:
            m.prediction_source, m.prediction_away, m.prediction_home = "DRatings", dr.away_projected_runs, dr.home_projected_runs
        if m.prediction_away is not None and m.prediction_home is not None:
            m.prediction_winner = away_ab if m.prediction_away > m.prediction_home else (
                home_ab if m.prediction_home > m.prediction_away else "tie"
            )

        if me:
            m.weather_icon = _weather_icon(me.conditions)
            m.weather_plain = _weather_plain(me.weather_net_pct)

        for check in ALL_CHECKS:
            flag = check(m)
            if flag:
                m.flags.append(flag)

        matchups.append(m)

    matchups.sort(key=lambda m: (m.game_time == "", m.game_time, m.away_abbrev))
    return matchups


def _alignment_for_game(m):
    """Section 8: model direction vs betting-split direction vs Reddit sentiment."""
    model_dir = None
    if m.dratings:
        model_dir = _winner(m.dratings.away_win_pct, m.dratings.home_win_pct)
    elif m.moundedge:
        model_dir = _winner(m.moundedge.model_away_runs, m.moundedge.model_home_runs)

    split_dir = None
    if m.moundedge and m.moundedge.split_ml_away_money is not None and m.moundedge.split_ml_home_money is not None:
        split_dir = _winner(m.moundedge.split_ml_away_money, m.moundedge.split_ml_home_money)

    reddit_dir = None
    if m.reddit_away or m.reddit_home:
        away_count = m.reddit_away.count if m.reddit_away else 0
        home_count = m.reddit_home.count if m.reddit_home else 0
        if away_count != home_count:
            reddit_dir = "away" if away_count > home_count else "home"

    directions = [d for d in (model_dir, split_dir, reddit_dir) if d]
    agree = len(set(directions)) <= 1 if directions else True
    return {
        "matchup": m,
        "model_direction": model_dir,
        "split_direction": split_dir,
        "reddit_direction": reddit_dir,
        "agree": agree,
    }


def _conviction_score(row):
    """Ranks aligned games (model, betting money, and Reddit all pointing the
    same way) by how strong the agreement is - more corroborating signals
    first, then by how lopsided those signals are."""
    m = row["matchup"]
    signals = [d for d in (row["model_direction"], row["split_direction"], row["reddit_direction"]) if d]
    signal_count = len(signals)

    model_margin = 0.0
    if m.dratings and m.dratings.away_win_pct is not None:
        model_margin = abs(m.dratings.away_win_pct - m.dratings.home_win_pct)

    split_margin = 0.0
    if m.moundedge and m.moundedge.split_ml_away_money is not None:
        split_margin = abs(m.moundedge.split_ml_away_money - m.moundedge.split_ml_home_money)

    return signal_count * 1000 + model_margin + split_margin


def _totals_alignment_for_game(m):
    dr_total = m.dratings.total_projected_runs if m.dratings else None
    bpp_total = m.moundedge.bpp_total if m.moundedge else None
    model_total = m.moundedge.model_total if m.moundedge else None
    market_total = (m.moundedge.market_total if m.moundedge else None) or (
        m.dratings.market_total if m.dratings else None
    )

    split_lean = None
    if m.moundedge and m.moundedge.split_total_over_money is not None and m.moundedge.split_total_under_money is not None:
        split_lean = "over" if m.moundedge.split_total_over_money > m.moundedge.split_total_under_money else "under"

    totals = [t for t in (dr_total, bpp_total, model_total) if t is not None]
    model_lean = None
    if totals and market_total is not None:
        avg = sum(totals) / len(totals)
        model_lean = "over" if avg > market_total else "under"

    return {
        "matchup": m,
        "dratings_total": dr_total,
        "bpp_total": bpp_total,
        "model_total": model_total,
        "market_total": market_total,
        "model_lean": model_lean,
        "split_lean": split_lean,
        "agree": (model_lean == split_lean) if (model_lean and split_lean) else True,
    }


def build_report_data(dr_games, me_games, reddit_result, today_iso, today_display, slate_subtitle):
    matchups = _build_matchups(dr_games, me_games, reddit_result)

    # most-flagged games first within the notable-games table itself
    notable_games = sorted((m for m in matchups if m.flags), key=lambda m: len(m.flags), reverse=True)
    most_flagged = notable_games[0] if notable_games else None

    # disagreements (NO) first in both alignment tables, stable within each group
    alignment_rows = sorted((_alignment_for_game(m) for m in matchups), key=lambda row: row["agree"])
    alignment_disagreements = [row for row in alignment_rows if not row["agree"]]

    # headline: the game with the strongest agreement across model/money/Reddit,
    # not the game with the most disagreement (that's the flags table below)
    aligned_rows = [
        row for row in alignment_rows
        if row["agree"] and any((row["model_direction"], row["split_direction"], row["reddit_direction"]))
    ]
    highest_conviction = max(aligned_rows, key=_conviction_score, default=None)

    totals_rows = sorted(
        (_totals_alignment_for_game(m) for m in matchups if m.flags), key=lambda row: row["agree"]
    )
    totals_disagreements = [row for row in totals_rows if not row["agree"]]

    spotlight_games = [m for m in matchups if m.away_abbrev in SPOTLIGHT_TEAMS or m.home_abbrev in SPOTLIGHT_TEAMS]

    return {
        "date_iso": today_iso,
        "date_display": today_display,
        "slate_subtitle": slate_subtitle,
        "games": matchups,
        "notable_games": notable_games,
        "most_flagged": most_flagged,
        "highest_conviction": highest_conviction,
        "alignment_rows": alignment_rows,
        "alignment_disagreements": alignment_disagreements,
        "totals_rows": totals_rows,
        "totals_disagreements": totals_disagreements,
        "spotlight_games": spotlight_games,
        "reddit": reddit_result,
        "source_urls": SOURCE_URLS,
        "thresholds": {
            "total_gap": TOTAL_GAP_THRESHOLD,
            "bpp_disagreement": BPP_DISAGREEMENT_THRESHOLD,
            "split_divergence": SPLIT_DIVERGENCE_THRESHOLD,
            "pitcher_split": PITCHER_SPLIT_THRESHOLD,
            "weather_net": WEATHER_NET_THRESHOLD,
        },
    }
