"""
Canonical MLB team identity mapping.

MLB Stats API uses full names ("Philadelphia Phillies"); PrizePicks sends
abbreviations ("PHI", and "SF/CHC" for multi-player combo props); Underdog
sends opaque team UUIDs that pipeline/underdog.py resolves to abbreviations
at fetch time. Everything downstream (opponent, venue, game grouping) matches
on the full name via to_full_name().
"""

TEAM_ABBR_TO_NAME = {
    "ARI": "Arizona Diamondbacks", "AZ":  "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CWS": "Chicago White Sox",    "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC":  "Kansas City Royals",   "KCR": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "ATH": "Athletics",            "OAK": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SD":  "San Diego Padres",     "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SF":  "San Francisco Giants", "SFG": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TB":  "Tampa Bay Rays",       "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSH": "Washington Nationals", "WAS": "Washington Nationals",
}

_NAME_TO_ABBR = {}
for abbr, name in TEAM_ABBR_TO_NAME.items():
    _NAME_TO_ABBR.setdefault(name, abbr)  # first (canonical) abbr wins


def to_full_name(team: str) -> str:
    """Abbreviation or full name → full name. '' for unknown/combo teams."""
    if not team:
        return ""
    team = team.strip()
    if "/" in team:  # multi-team combo prop label like "SF/CHC"
        return ""
    if team in _NAME_TO_ABBR:  # already a full name
        return team
    return TEAM_ABBR_TO_NAME.get(team.upper(), "")


def to_abbr(team: str) -> str:
    """Full name or abbreviation → display abbreviation. Input echoed if unknown."""
    if not team:
        return ""
    team = team.strip()
    if team in _NAME_TO_ABBR:
        return _NAME_TO_ABBR[team]
    if team.upper() in TEAM_ABBR_TO_NAME:
        return team.upper()
    return team
