"""
Assigns a risk profile to each pick based on stat-type variance.
Stat names must stay in sync with STAT_MAP in models/props.py — both
platform spellings of a stat belong here (see CLAUDE.md).
"""

# Rare events: one swing decides the prop
HIGH_VARIANCE_STATS = {
    "Home Runs", "Stolen Bases", "Singles", "Doubles",
}

MEDIUM_VARIANCE_STATS = {
    "Pitcher Strikeouts", "Strikeouts",           # PP / Underdog pitcher Ks
    "Total Bases", "RBIs", "Runs",
    "Batter Strikeouts", "Hitter Strikeouts",
    "Batter Walks", "Walks",
}

LOW_VARIANCE_STATS = {
    "Hits", "Hits+Runs+RBIs", "Hits + Runs + RBIs",
}


def get_risk_profile(stat_type: str, edge: float) -> str:
    """
    LOW  — low-variance stat with a solid edge
    MEDIUM — moderate variance stat (default for unknown stats)
    HIGH — high-variance stat
    """
    if stat_type in HIGH_VARIANCE_STATS:
        return "HIGH"
    elif stat_type in LOW_VARIANCE_STATS:
        if edge >= 0.08:
            return "LOW"
        return "MEDIUM"
    else:
        return "MEDIUM"


RISK_COLORS = {
    "LOW":    "#22c55e",
    "MEDIUM": "#f97316",
    "HIGH":   "#ef4444",
}
