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
            "a", "Model vs market total gap",
            f"Model total {model_total:.1f} vs market total {market_total:.1f} (gap {gap:.1f})",
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
            parts.append(f"DRatings favors {dr_winner}, BPP favors {bpp_winner}")
        if total_gap is not None and total_gap > BPP_DISAGREEMENT_THRESHOLD:
            parts.append(
                f"DRatings total {m.dratings.total_projected_runs:.1f} vs BPP total "
                f"{m.moundedge.bpp_total:.1f} (gap {total_gap:.1f})"
            )
        return Flag("b", "DRatings vs BPP disagreement", "; ".join(parts))
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
        detail = "; ".join(f"{label} bets/money gap {gap:.0f}pts" for label, gap in flagged)
        return Flag("c", "Lopsided bets% vs money% split", detail)
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
        return Flag("d", "Extreme starter home/road split", "; ".join(findings))
    return None


def _check_weather(m):
    me = m.moundedge
    if me is None or me.weather_net_pct is None:
        return None
    if abs(me.weather_net_pct) >= WEATHER_NET_THRESHOLD:
        return Flag("e", "Extreme weather/park effect", f"BPP net {me.weather_net_pct:+.0f}%")
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
        return Flag("f", "Trend arrow contradicts underlying stats", "; ".join(findings))
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

    notable_games = [m for m in matchups if m.flags]
    most_flagged = max(matchups, key=lambda m: len(m.flags), default=None)
    if most_flagged is not None and not most_flagged.flags:
        most_flagged = None

    alignment_rows = [_alignment_for_game(m) for m in matchups]
    alignment_disagreements = [row for row in alignment_rows if not row["agree"]]

    totals_rows = [_totals_alignment_for_game(m) for m in matchups if m.flags]
    totals_disagreements = [row for row in totals_rows if not row["agree"]]

    spotlight_games = [m for m in matchups if m.away_abbrev in SPOTLIGHT_TEAMS or m.home_abbrev in SPOTLIGHT_TEAMS]

    return {
        "date_iso": today_iso,
        "date_display": today_display,
        "slate_subtitle": slate_subtitle,
        "games": matchups,
        "notable_games": notable_games,
        "most_flagged": most_flagged,
        "alignment_rows": alignment_rows,
        "alignment_disagreements": alignment_disagreements,
        "totals_rows": totals_rows,
        "totals_disagreements": totals_disagreements,
        "spotlight_games": spotlight_games,
        "reddit": reddit_result,
        "thresholds": {
            "total_gap": TOTAL_GAP_THRESHOLD,
            "bpp_disagreement": BPP_DISAGREEMENT_THRESHOLD,
            "split_divergence": SPLIT_DIVERGENCE_THRESHOLD,
            "pitcher_split": PITCHER_SPLIT_THRESHOLD,
            "weather_net": WEATHER_NET_THRESHOLD,
        },
    }
