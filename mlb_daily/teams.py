"""Canonical MLB team nickname -> abbreviation mapping, shared by the Reddit
sentiment scanner and the cross-source game matcher (DRatings uses full team
names, MoundEdge uses abbreviations - matching on nickname is more robust
than exact full-name string matching)."""


# Abbreviations match MoundEdge's convention (the richest source, and the
# one whose game-card ids anchor the cross-source join) - notably KCR, SDP,
# SFG, TBR, WSN, CHW rather than the shorter forms other sites sometimes use.
TEAMS = [
    ("Diamondbacks", "ARI", ["D-backs", "AZ"]),
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


# Each team's official primary brand color only (not the full secondary/
# tertiary palette) - for small identifying chips next to team names in the
# report, not section theming. DET/SEA match the navy values already used
# for the Tigers/Mariners spotlight accent border.
TEAM_PRIMARY_COLOR = {
    "ARI": "#A71930",
    "ATL": "#13274F",
    "BAL": "#DF4601",
    "BOS": "#BD3039",
    "CHC": "#0E3386",
    "CHW": "#27251F",
    "CIN": "#C6011F",
    "CLE": "#0C2340",
    "COL": "#33006F",
    "DET": "#0C2340",
    "HOU": "#002D62",
    "KCR": "#004687",
    "LAA": "#BA0021",
    "LAD": "#005A9C",
    "MIA": "#00A3E0",
    "MIL": "#12284B",
    "MIN": "#002B5C",
    "NYM": "#002D72",
    "NYY": "#003087",
    "ATH": "#003831",
    "PHI": "#E81828",
    "PIT": "#27251F",
    "SDP": "#2F241D",
    "SEA": "#0C2C56",
    "SFG": "#FD5A1E",
    "STL": "#C41E3A",
    "TBR": "#092C5C",
    "TEX": "#003278",
    "TOR": "#134A8E",
    "WSN": "#AB0003",
}


def team_color(abbrev):
    """Primary brand color for an abbreviation, falling back to a neutral
    gray for anything unrecognized."""
    return TEAM_PRIMARY_COLOR.get(abbrev, "#9aa39a")
