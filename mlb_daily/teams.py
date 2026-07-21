"""Canonical MLB team nickname -> abbreviation mapping, shared by the Reddit
sentiment scanner and the cross-source game matcher (DRatings uses full team
names, MoundEdge uses abbreviations - matching on nickname is more robust
than exact full-name string matching)."""


# Abbreviations match MoundEdge's convention (the richest source, and the
# one whose game-card ids anchor the cross-source join) - notably KCR, SDP,
# SFG, TBR, WSN, CHW rather than the shorter forms other sites sometimes use.
TEAMS = [
    ("Diamondbacks", "ARI", ["D-backs"]),
    ("Braves", "ATL", []),
    ("Orioles", "BAL", []),
    ("Red Sox", "BOS", []),
    ("Cubs", "CHC", []),
    ("White Sox", "CHW", ["CWS"]),
    ("Reds", "CIN", []),
    ("Guardians", "CLE", []),
    ("Rockies", "COL", []),
    ("Tigers", "DET", []),
    ("Astros", "HOU", []),
    ("Royals", "KCR", ["KC"]),
    ("Angels", "LAA", []),
    ("Dodgers", "LAD", []),
    ("Marlins", "MIA", []),
    ("Brewers", "MIL", []),
    ("Twins", "MIN", []),
    ("Mets", "NYM", []),
    ("Yankees", "NYY", []),
    ("Athletics", "ATH", ["A's"]),
    ("Phillies", "PHI", []),
    ("Pirates", "PIT", []),
    ("Padres", "SDP", ["SD"]),
    ("Mariners", "SEA", []),
    ("Giants", "SFG", ["SF"]),
    ("Cardinals", "STL", []),
    ("Rays", "TBR", ["TB"]),
    ("Rangers", "TEX", []),
    ("Blue Jays", "TOR", []),
    ("Nationals", "WSN", ["WSH"]),
]

NICKNAME_TO_ABBREV = {}
for _nickname, _abbrev, _aliases in TEAMS:
    NICKNAME_TO_ABBREV[_nickname] = _abbrev
    for _alias in _aliases:
        NICKNAME_TO_ABBREV[_alias] = _abbrev

# longest nickname first, so "Red Sox" matches before a hypothetical shorter overlap
_NICKNAMES_BY_LENGTH = sorted(NICKNAME_TO_ABBREV, key=len, reverse=True)


def abbrev_from_name(name):
    """Best-effort: find a team nickname substring in a full team name (or any
    free text) and return its abbreviation."""
    if not name:
        return None
    for nickname in _NICKNAMES_BY_LENGTH:
        if nickname.lower() in name.lower():
            return NICKNAME_TO_ABBREV[nickname]
    return None


# City/market + nickname, for readers who don't know the three-letter codes.
# The Athletics play without a home-city name as of their move away from
# Oakland, hence no city prefix there - "Athletics" is their full official name.
ABBREV_TO_FULL_NAME = {
    "ARI": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "ATH": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SFG": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSN": "Washington Nationals",
}


def full_name(abbrev):
    """City + nickname for an abbreviation (e.g. "DET" -> "Detroit Tigers"),
    falling back to the abbreviation itself for anything unrecognized."""
    return ABBREV_TO_FULL_NAME.get(abbrev, abbrev)
