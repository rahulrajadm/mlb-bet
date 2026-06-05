"""
Assigns confidence tier to each pick based on edge size and edge reliability.
For V1, tiers are edge-based. Future: calibrate against historical hit rates.
"""


def get_confidence_tier(edge: float, games_sample: int = 0) -> str:
    """
    edge: model_prob - implied_prob (0.0–1.0)
    games_sample: number of games in the player's historical sample
    """
    # Penalize small samples
    sample_penalty = 0.03 if games_sample < 50 else 0.0

    adj_edge = edge - sample_penalty

    if adj_edge >= 0.15:
        return "STRONG"
    elif adj_edge >= 0.10:
        return "HIGH"
    elif adj_edge >= 0.05:
        return "MEDIUM"
    else:
        return "LOW"


TIER_COLORS = {
    "STRONG": "#22c55e",   # green
    "HIGH":   "#86efac",   # light green
    "MEDIUM": "#fbbf24",   # yellow
    "LOW":    "#94a3b8",   # gray
}

TIER_RANK = {"STRONG": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
