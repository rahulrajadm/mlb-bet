"""
Fractional Kelly criterion for pick'em bet sizing.
Uses 0.25x Kelly (quarter Kelly) — standard sharp practice to reduce variance.
"""

KELLY_FRACTION = 0.25


def kelly_stake(model_prob: float, payout_multiplier: float, fraction: float = KELLY_FRACTION) -> float:
    """
    Full Kelly: f* = (b*p - q) / b
    where b = net odds (multiplier - 1), p = model prob, q = 1 - p.
    Returns stake as a fraction of bankroll (0.0–1.0).
    Clamps to [0, 0.25] max for safety.
    """
    b = payout_multiplier - 1
    p = model_prob
    q = 1 - p

    if b <= 0 or p <= 0:
        return 0.0

    full_kelly = (b * p - q) / b
    if full_kelly <= 0:
        return 0.0

    fractional = full_kelly * fraction
    return round(min(fractional, 0.25), 4)


def stake_dollars(kelly_pct: float, bankroll: float) -> float:
    return round(kelly_pct * bankroll, 2)


def risk_reward(stake: float, payout_multiplier: float) -> dict:
    potential_win = round(stake * payout_multiplier - stake, 2)
    return {
        "stake": stake,
        "potential_win": potential_win,
        "potential_loss": stake,
        "ratio": round(potential_win / stake, 2) if stake > 0 else 0,
    }
