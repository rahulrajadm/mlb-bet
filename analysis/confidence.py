"""
Assigns confidence tier to each pick based on edge size and sample size.
Edges here are measured against the pick'em break-even (~0.577), so
thresholds follow the original design doc: STRONG >12%, HIGH 8–12%,
MEDIUM 4–8%, LOW below.
"""


def get_confidence_tier(edge: float, games_sample: int = 0) -> str:
    """
    edge: model_prob − break-even (0.0–1.0)
    games_sample: games in the player's historical sample (profiles carry
    this; pitcher props pass starts)
    """
    sample_penalty = 0.03 if games_sample < 50 else 0.0
    adj_edge = edge - sample_penalty

    if adj_edge >= 0.12:
        return "STRONG"
    elif adj_edge >= 0.08:
        return "HIGH"
    elif adj_edge >= 0.04:
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
