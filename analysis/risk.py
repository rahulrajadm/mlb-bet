"""
Assigns a risk profile to each pick based on stat type variance and bet structure.
"""

# Stats with naturally high game-to-game variance
HIGH_VARIANCE_STATS = {
    "Home Runs", "Stolen Bases", "Singles", "Doubles",
    "Pitcher Strikeouts (Combo)", "Earned Runs Allowed",
}

MEDIUM_VARIANCE_STATS = {
    "Pitcher Strikeouts", "Hits Allowed", "Total Bases",
    "RBIs", "Runs", "Batter Strikeouts", "Batter Walks",
    "Pitching Outs", "Pitches Thrown",
}

LOW_VARIANCE_STATS = {
    "Hits", "Hits+Runs+RBIs", "Hits + Runs + RBIs",
    "Hitter Fantasy Score", "Pitcher Fantasy Score",
    "Fantasy Points",
}


def get_risk_profile(stat_type: str, edge: float) -> str:
    """
    LOW  — low-variance stat or very high edge (model is highly certain)
    MEDIUM — moderate variance stat
    HIGH — high-variance stat or thin edge (close call)
    """
    if stat_type in HIGH_VARIANCE_STATS:
        return "HIGH"
    elif stat_type in LOW_VARIANCE_STATS:
        if edge >= 0.12:
            return "LOW"
        return "MEDIUM"
    else:
        return "MEDIUM"


RISK_COLORS = {
    "LOW":    "#22c55e",
    "MEDIUM": "#f97316",
    "HIGH":   "#ef4444",
}
