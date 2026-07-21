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
