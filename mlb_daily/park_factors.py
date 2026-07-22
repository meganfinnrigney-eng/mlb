"""
Hand-maintained run-scoring park factors, keyed by the HOME team's
canonical abbreviation (see mlb_daily/teams.py).

Why hand-maintained rather than fetched: pybaseball has no dedicated
park-factor function (`park_codes()` is Retrosheet park ID/location
metadata only, not factor numbers, and is currently broken besides -
see scripts/probe_pybaseball.py's probe_park_factors()). The two sites
that do publish a park-factor page - FanGraphs' guts.aspx and Baseball
Savant's own park-factor page - are either confirmed blocked
(FanGraphs, same Cloudflare 403 documented in fetch/mymodel.py) or not
worth adding a second scrape surface for a number that barely moves
mid-season. A short table updated by hand occasionally is simpler and
just as accurate for this purpose.

Values are approximate multi-year run-scoring factors (1.00 = neutral;
above 1.00 = favors scoring, below = suppresses it), the same convention
commonly published by outlets like ESPN/FanGraphs. These should be
treated as a reasonable prior, not a precise live number - re-check and
update by hand once or twice a season, or whenever a team relocates/
renovates (e.g. the Athletics' temporary home is a genuine unknown -
flagged below with a neutral placeholder pending real data).
"""

PARK_FACTORS = {
    "ARI": 1.02,
    "ATL": 1.00,
    "BAL": 0.95,
    "BOS": 1.06,
    "CHC": 1.02,
    "CHW": 1.03,
    "CIN": 1.09,
    "CLE": 0.97,
    "COL": 1.15,  # Coors Field - the one genuine outlier in MLB
    "DET": 0.96,
    "HOU": 1.01,
    "KCR": 0.98,
    "LAA": 0.99,
    "LAD": 0.97,
    "MIA": 0.93,
    "MIL": 1.00,
    "MIN": 0.98,
    "NYM": 0.96,
    "NYY": 1.02,
    "ATH": 1.00,  # Sutter Health Park (Sacramento, temporary home) - no real multi-year data yet, neutral placeholder
    "PHI": 1.04,
    "PIT": 0.96,
    "SDP": 0.95,
    "SEA": 0.94,
    "SFG": 0.93,
    "STL": 0.97,
    "TBR": 0.97,
    "TEX": 0.98,
    "TOR": 1.01,
    "WSN": 1.00,
}

LEAGUE_NEUTRAL_FACTOR = 1.00


def park_factor(home_abbrev):
    """Run-scoring factor for the home team's park; 1.00 (neutral) if
    the team isn't recognized, so a lookup miss never breaks the formula."""
    return PARK_FACTORS.get(home_abbrev, LEAGUE_NEUTRAL_FACTOR)
