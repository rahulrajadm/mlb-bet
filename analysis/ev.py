"""
EV calculation for pick'em platforms (PrizePicks, Underdog, etc.)
Pick'em EV is computed per single leg, then shown for common slip sizes.
"""

# PrizePicks Power Play fixed multipliers (net payout per $1 entry)
PRIZEPICKS_POWER = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 25.0}

# Underdog multipliers (approximate)
UNDERDOG_POWER = {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0}

# Platform multiplier tables
PLATFORM_MULTIPLIERS = {
    "prizepicks": PRIZEPICKS_POWER,
    "underdog": UNDERDOG_POWER,
    "draftkings_pick6": {2: 3.0, 3: 5.5, 4: 11.0, 5: 22.0},
    "chalkboard": {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0, 6: 25.0},
    "sleeper": {2: 3.0, 3: 5.0, 4: 10.0, 5: 20.0},
    "betr": {2: 3.0, 3: 5.0, 4: 10.0},
}


def ev_per_leg(model_prob: float, implied_prob: float = 0.50) -> float:
    """
    EV per $100 wagered on a single leg at pick'em odds.
    Assumes implied probability = 0.50 (no explicit juice on individual legs).
    EV = (model_prob - implied_prob) / implied_prob * 100
    """
    return round((model_prob - implied_prob) * 100, 2)


def ev_slip(model_probs: list[float], platform: str, slip_size: int) -> dict:
    """
    EV for a full multi-leg slip where all legs must hit (Power Play style).
    Returns EV per $100 entry.
    """
    multipliers = PLATFORM_MULTIPLIERS.get(platform, PRIZEPICKS_POWER)
    multiplier = multipliers.get(slip_size)
    if multiplier is None:
        return {}

    p_all_hit = 1.0
    for p in model_probs[:slip_size]:
        p_all_hit *= p

    ev = p_all_hit * multiplier * 100 - 100
    return {
        "slip_size": slip_size,
        "p_all_hit": round(p_all_hit, 4),
        "multiplier": multiplier,
        "ev_per_100": round(ev, 2),
    }


def american_to_implied(american_odds: float) -> float:
    """Convert American odds to implied probability (with vig)."""
    if american_odds > 0:
        return 100 / (american_odds + 100)
    else:
        return abs(american_odds) / (abs(american_odds) + 100)


def ev_traditional(model_prob: float, american_odds: float) -> float:
    """
    EV per $100 for traditional sportsbook bet (Fliff, Odds API lines).
    EV = model_prob * net_win - (1 - model_prob) * 100
    """
    if american_odds > 0:
        net_win = american_odds
    else:
        net_win = 100 / abs(american_odds) * 100

    return round(model_prob * net_win - (1 - model_prob) * 100, 2)
