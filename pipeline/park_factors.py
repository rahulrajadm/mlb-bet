"""
MLB park factors for 2025 season (Baseball Reference multi-year avg).
Factor > 100 = hitter-friendly, < 100 = pitcher-friendly.
Applied to hit, HR, TB, and run rate predictions.
"""

# venue name (as returned by MLB Stats API) → run factor
PARK_FACTORS: dict[str, int] = {
    "Coors Field":                          127,
    "Great American Ball Park":             108,
    "Yankee Stadium":                       107,
    "Camden Yards":                         103,
    "Fenway Park":                          102,
    "American Family Field":               102,
    "Globe Life Field":                    101,
    "Chase Field":                          101,
    "Wrigley Field":                        100,
    "loanDepot park":                       100,
    "PNC Park":                             100,
    "Guaranteed Rate Field":                99,
    "Kauffman Stadium":                     99,
    "Angel Stadium":                        99,
    "Busch Stadium":                        98,
    "Nationals Park":                       98,
    "Progressive Field":                    98,
    "Citizens Bank Park":                   97,
    "Dodger Stadium":                       97,
    "Target Field":                         97,
    "Minute Maid Park":                     97,
    "Tropicana Field":                      96,
    "Truist Park":                          96,
    "Comerica Park":                        95,
    "Rogers Centre":                        95,
    "Oakland Coliseum":                     94,
    "Sutter Health Park":                   94,
    "Oracle Park":                          92,
    "T-Mobile Park":                        90,
    "Petco Park":                           91,
}

LEAGUE_AVG_FACTOR = 100

# Stats that park factor applies to
PARK_AFFECTED_STATS = {
    "hits_pg", "hr_pg", "rbi_pg", "runs_pg", "tb_pg",
    "h_r_rbi_pg", "singles_pg", "doubles_pg",
}


def get_park_factor(venue: str) -> float:
    """Returns normalized park factor (1.0 = league average)."""
    factor = PARK_FACTORS.get(venue, LEAGUE_AVG_FACTOR)
    return factor / LEAGUE_AVG_FACTOR


def apply_park_factor(rate: float, stat_col: str, venue: str) -> float:
    if stat_col not in PARK_AFFECTED_STATS:
        return rate
    pf = get_park_factor(venue)
    # Dampen: only apply 50% of park effect to avoid over-adjusting
    adj = 1.0 + 0.5 * (pf - 1.0)
    return max(rate * adj, 0.0)
