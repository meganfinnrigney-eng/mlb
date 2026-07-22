"""
Joins the DRatings, MoundEdge, and Reddit data into one row per game and
computes the six notable-game triggers plus the alignment checks described
in the project brief. Pure analysis - no fetching, no rendering, no betting
recommendations of any kind (no stakes, no "plays").
"""

from dataclasses import dataclass, field

from mlb_daily.teams import abbrev_from_name, full_name

TOTAL_GAP_THRESHOLD = 1.0          # runs: model total vs market total (trigger a)
BPP_DISAGREEMENT_THRESHOLD = 1.0   # runs: DRatings vs BPP total disagreement (trigger b)
SPLIT_DIVERGENCE_THRESHOLD = 15.0  # percentage points: bets% vs money% (trigger c)
PITCHER_SPLIT_THRESHOLD = 1.0      # ERA: contextual (home/road) ERA vs season ERA (trigger d)
WEATHER_NET_THRESHOLD = 8.0        # percent: BPP net weather/park effect (trigger e)
SPOTLIGHT_TEAMS = {"DET", "SEA"}
TOSS_UP_THRESHOLD = 15.0           # confidence score below this reads as "not much consensus"

SOURCE_URLS = {
    "SportsBettingDime": "https://www.sportsbettingdime.com/mlb/public-betting-trends/",
    "DRatings": "https://www.dratings.com/predictor/mlb-baseball-predictions/",
    "MoundEdge": "https://moundedge.github.io/MLB-Summaries/",
    "Kalshi": "https://kalshi.com/markets/kxmlbgame/mlb-game-winner",
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


def _weather_arrow(net_pct):
    """Scannable up/down glyph + a size class for the scoring-effect
    magnitude, plus a plain-word badge label - for the prose section
    (separate from _weather_icon, which picks a sky-conditions emoji for
    the deep-dive weather tiles)."""
    if net_pct is None:
        return "", "", "Neutral"
    if net_pct >= 8:
        return "↑", "strong", "Easier"
    if net_pct >= 3:
        return "↑", "light", "Easier"
    if net_pct <= -8:
        return "↓", "strong", "Harder"
    if net_pct <= -3:
        return "↓", "light", "Harder"
    return "", "", "Neutral"


# label -> (glyph, css modifier, short badge word). No emoji here on purpose -
# these are plain Unicode symbols with reliable text-glyph fallback, unlike
# pictographic emoji (e.g. the old 🎯 target) which can render as a tofu box
# in the artifact viewer if the emoji font doesn't load.
_CONFIDENCE_ICONS = {
    "strong consensus": ("●", "strong", "Strong"),
    "fairly confident pick": ("◐", "fair", "Fairly confident"),
    "mixed signals": ("⚠", "mixed", "Mixed"),
    "not much consensus": ("–", "tossup", "Toss-up"),
}


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
    kalshi: object = None
    reddit_away: object = None
    reddit_home: object = None

    # best-available projected score, for showing "the actual prediction" up front
    prediction_source: str = ""
    prediction_away: float | None = None
    prediction_home: float | None = None
    prediction_winner: str | None = None
    prediction_winner_name: str | None = None

    weather_icon: str = "🌤️"
    weather_plain: str = ""
    weather_notable: bool = False
    weather_arrow: str = ""
    weather_arrow_class: str = ""
    weather_badge: str = "Neutral"

    # small set of totals-runs ticks for the hero-card sparkline, see
    # _totals_sparkline - None when fewer than 2 sources have a total
    totals_spark: object = None

    # set after alignment_rows is computed - {model_direction, split_direction,
    # reddit_direction, agree, confidence_score, confidence_label}, see _alignment_for_game
    alignment: object = None

    # set after alignment - prose-section-only signal agreement, consistent
    # with prediction_winner rather than the table's DRatings-priority
    # direction; see _prose_signals
    prose: object = None

    flags: list = field(default_factory=list)

    @property
    def flag_codes(self):
        return {f.code for f in self.flags}


def _totals_sparkline(m):
    """Small set of (label, value) totals-runs ticks for the hero-card
    sparkline, normalized to a 0-100 x-position within this game's own
    min/max (each game uses its own local scale, not a league-wide one).
    Returns None when fewer than 2 sources have a total to compare."""
    dr_total = m.dratings.total_projected_runs if m.dratings else None
    bpp_total = m.moundedge.bpp_total if m.moundedge else None
    model_total = m.moundedge.model_total if m.moundedge else None
    market_total = (m.moundedge.market_total if m.moundedge else None) or (
        m.dratings.market_total if m.dratings else None
    )

    candidates = [("DR", dr_total, False), ("BPP", bpp_total, False), ("Mdl", model_total, False), ("Mkt", market_total, True)]
    points = [(label, v, is_market) for label, v, is_market in candidates if v is not None]
    if len(points) < 2:
        return None

    values = [v for _, v, _ in points]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    # inset 8-92% rather than 0-100% so an extreme tick's label never gets
    # clipped by the card edge (its container is centered via translateX(-50%))
    return [
        {"label": label, "value": v, "x": round(8 + ((v - lo) / span) * 84, 1), "is_market": is_market}
        for label, v, is_market in points
    ]


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


def _build_matchups(dr_games, me_games, reddit_result, kalshi_games=None):
    dr_by_abbrev = _match_dratings_to_abbrev(dr_games)
    kalshi_by_abbrev = {(g.away_abbrev, g.home_abbrev): g for g in (kalshi_games or [])}
    matchups = []

    me_keys = {(g.away.abbrev, g.home.abbrev) for g in me_games}
    all_keys = set(dr_by_abbrev) | me_keys | set(kalshi_by_abbrev)

    for away_ab, home_ab in all_keys:
        dr = dr_by_abbrev.get((away_ab, home_ab))
        me = next((g for g in me_games if g.away.abbrev == away_ab and g.home.abbrev == home_ab), None)

        m = Matchup(away_abbrev=away_ab, home_abbrev=home_ab)
        m.dratings = dr
        m.moundedge = me
        m.kalshi = kalshi_by_abbrev.get((away_ab, home_ab))
        m.away_name = full_name(away_ab)
        m.home_name = full_name(home_ab)
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
            m.prediction_winner_name = full_name(m.prediction_winner) if m.prediction_winner != "tie" else None

        if me:
            m.weather_icon = _weather_icon(me.conditions)
            m.weather_plain = _weather_plain(me.weather_net_pct)
            m.weather_notable = me.weather_net_pct is not None and abs(me.weather_net_pct) >= 3
            m.weather_arrow, m.weather_arrow_class, m.weather_badge = _weather_arrow(me.weather_net_pct)

        m.totals_spark = _totals_sparkline(m)

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

    # Kalshi (real-money prediction market) - display-only for now: it counts
    # toward direction agreement here and in the prose section's signal
    # count, but its margin is deliberately NOT added to _confidence_score's
    # magnitude sum below, so it doesn't silently re-grade every game's
    # confidence label until its numbers have been sanity-checked over a
    # few real days (see _confidence_score's docstring).
    kalshi_dir = None
    if m.kalshi and m.kalshi.away_win_pct is not None and m.kalshi.home_win_pct is not None:
        kalshi_dir = _winner(m.kalshi.away_win_pct, m.kalshi.home_win_pct)

    directions = [d for d in (model_dir, split_dir, reddit_dir, kalshi_dir) if d]
    agree = len(set(directions)) <= 1 if directions else True

    def _team(direction):
        return {"away": m.away_abbrev, "home": m.home_abbrev, "tie": "tie"}.get(direction)

    row = {
        "matchup": m,
        "model_direction": model_dir,
        "split_direction": split_dir,
        "reddit_direction": reddit_dir,
        "kalshi_direction": kalshi_dir,
        # same directions, resolved to the actual team abbreviation for prose use
        "model_direction_team": _team(model_dir),
        "split_direction_team": _team(split_dir),
        "reddit_direction_team": _team(reddit_dir),
        "kalshi_direction_team": _team(kalshi_dir),
        "agree": agree,
    }
    row["confidence_score"] = _confidence_score(row)
    row["confidence_label"] = _confidence_label(row["confidence_score"], row["agree"])
    return row


def _confidence_score(row):
    """How strong the model/betting-money signals are, regardless of whether
    they agree - a pure magnitude, reused by both the Alignment Check table's
    existing logic and the prose section's (separate) signal-agreement logic
    below. Falls back to MoundEdge's own projected-run gap when DRatings'
    win probability isn't available for this game."""
    m = row["matchup"]
    model_margin = 0.0
    if m.dratings and m.dratings.away_win_pct is not None:
        model_margin = abs(m.dratings.away_win_pct - m.dratings.home_win_pct)
    elif m.moundedge and m.moundedge.model_away_runs is not None:
        # no win-probability number from MoundEdge, so approximate one from
        # the projected-run gap (roughly ~18 win-probability points per run
        # of edge in a typical run environment), capped at a realistic max
        model_margin = min(60.0, abs(m.moundedge.model_away_runs - m.moundedge.model_home_runs) * 18)

    split_margin = 0.0
    if m.moundedge and m.moundedge.split_ml_away_money is not None:
        split_margin = abs(m.moundedge.split_ml_away_money - m.moundedge.split_ml_home_money)

    return model_margin + split_margin


def _confidence_label(score, agree):
    if not agree:
        return "mixed signals" if score >= TOSS_UP_THRESHOLD else "not much consensus"
    if score < TOSS_UP_THRESHOLD:
        return "not much consensus"
    if score >= 40:
        return "strong consensus"
    return "fairly confident pick"


def _prose_signals(m):
    """The prose section always shows the score from m.prediction_winner
    (BPP sim > MoundEdge Model > DRatings priority - see _build_matchups),
    so "does the betting money agree" must be judged against that same
    winner, not the Alignment Check table's DRatings-priority direction
    (which is left untouched for that table). When DRatings and BPP
    disagree on the winner (trigger b), these two notions of "the model's
    pick" can differ - reusing the table's `agree` here would produce
    self-contradictory sentences ("betting money disagrees - strong
    consensus")."""
    a = m.alignment
    split_team = a["split_direction_team"] if a else None
    reddit_team = a["reddit_direction_team"] if a else None
    kalshi_team = a["kalshi_direction_team"] if a else None
    model_team = m.prediction_winner

    signals = [t for t in (model_team, split_team, reddit_team, kalshi_team) if t and t != "tie"]
    agree = len(set(signals)) <= 1 if signals else True
    score = a["confidence_score"] if a else 0.0
    label = _confidence_label(score, agree)
    icon, icon_class, badge = _CONFIDENCE_ICONS[label]

    return {
        "model_team": model_team,
        "split_team": split_team,
        "reddit_team": reddit_team,
        "kalshi_team": kalshi_team,
        "signal_count": len(signals),
        "agree": agree,
        "score": score,
        "label": label,
        "icon": icon,
        "icon_class": icon_class,
        "badge": badge,
    }


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

    # Kalshi's total-runs lean - display only, same reasoning as
    # kalshi_direction in _alignment_for_game: not folded into `agree` below
    # until its numbers have been sanity-checked over a few real days.
    kalshi_lean = None
    if m.kalshi and m.kalshi.over_pct is not None:
        kalshi_lean = "over" if m.kalshi.over_pct > 50 else "under"

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
        "kalshi_lean": kalshi_lean,
        "agree": (model_lean == split_lean) if (model_lean and split_lean) else True,
    }


def build_report_data(dr_games, me_games, reddit_result, today_iso, today_display, slate_subtitle, kalshi_games=None):
    matchups = _build_matchups(dr_games, me_games, reddit_result, kalshi_games)

    # most-flagged games first within the notable-games table itself
    notable_games = sorted((m for m in matchups if m.flags), key=lambda m: len(m.flags), reverse=True)
    most_flagged = notable_games[0] if notable_games else None

    # disagreements (NO) first in both alignment tables, stable within each group
    alignment_rows = sorted((_alignment_for_game(m) for m in matchups), key=lambda row: row["agree"])
    alignment_disagreements = [row for row in alignment_rows if not row["agree"]]

    # attach each game's alignment/confidence data directly to the Matchup so
    # templates can read m.alignment.* without a separate lookup
    for row in alignment_rows:
        row["matchup"].alignment = row

    # prose-only signal agreement, consistent with m.prediction_winner (the
    # score the prose section actually shows) - see _prose_signals for why
    # this can't just reuse the Alignment Check table's `agree`
    for m in matchups:
        m.prose = _prose_signals(m)

    # headline: the game with the strongest agreement across model/money/Reddit,
    # not the game with the most disagreement (that's the flags table below)
    aligned_matchups = [m for m in matchups if m.prose["agree"] and m.prose["signal_count"] > 0]
    highest_conviction_matchup = max(
        aligned_matchups,
        key=lambda m: m.prose["signal_count"] * 1000 + m.prose["score"],
        default=None,
    )
    highest_conviction = highest_conviction_matchup.alignment if highest_conviction_matchup else None

    totals_rows = sorted(
        (_totals_alignment_for_game(m) for m in matchups if m.flags), key=lambda row: row["agree"]
    )
    totals_disagreements = [row for row in totals_rows if not row["agree"]]

    spotlight_games = [m for m in matchups if m.away_abbrev in SPOTLIGHT_TEAMS or m.home_abbrev in SPOTLIGHT_TEAMS]
    spotlight_keys = {(m.away_abbrev, m.home_abbrev) for m in spotlight_games}
    headline_key = (
        (highest_conviction_matchup.away_abbrev, highest_conviction_matchup.home_abbrev)
        if highest_conviction_matchup else None
    )
    highest_conviction_is_spotlight = headline_key in spotlight_keys if headline_key else False

    # everything not already covered by the spotlight or the headline callout.
    # "Clear" = signals agree AND are strong enough to clear the toss-up bar;
    # everything else (weak signals, OR strong-but-conflicting "mixed
    # signals") goes in the toss-up group, per-request. Sorting by
    # (not agree, -score) puts agreeing games first, strongest first, then
    # groups every disagreeing/weak game at the end.
    def _is_clear(m):
        return m.prose["agree"] and m.prose["score"] >= TOSS_UP_THRESHOLD

    rest_of_slate = sorted(
        (m for m in matchups if (m.away_abbrev, m.home_abbrev) not in spotlight_keys and (m.away_abbrev, m.home_abbrev) != headline_key),
        key=lambda m: (not _is_clear(m), -m.prose["score"]),
    )
    rest_clear_games = [m for m in rest_of_slate if _is_clear(m)]
    rest_toss_up_games = [m for m in rest_of_slate if not _is_clear(m)]

    return {
        "date_iso": today_iso,
        "date_display": today_display,
        "slate_subtitle": slate_subtitle,
        "games": matchups,
        "notable_games": notable_games,
        "most_flagged": most_flagged,
        "highest_conviction": highest_conviction,
        "highest_conviction_is_spotlight": highest_conviction_is_spotlight,
        "rest_clear_games": rest_clear_games,
        "rest_toss_up_games": rest_toss_up_games,
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
