"""
Fractional Kelly sizing for pick'em legs.

A leg is sized as part of the baseline 2-pick 3x slip: the slip hits with
probability ≈ p² (paired with an equally strong, independent leg), so the
Kelly input is the slip probability — not the single-leg probability against
a fictional standalone 3x payout, which sized legs at 20%+ of bankroll.
Quarter Kelly, hard-capped at 10% of bankroll per slip.
"""

KELLY_FRACTION = 0.25
MAX_STAKE_PCT = 0.10


def kelly_stake(model_prob: float, payout_multiplier: float = 3.0,
                slip_size: int = 2, fraction: float = KELLY_FRACTION) -> float:
    """
    Full Kelly on the slip: f* = (b·p − q) / b, with b = multiplier − 1 and
    p = model_prob ** slip_size. Returns a fraction of bankroll (0.0–1.0).
    """
    b = payout_multiplier - 1
    p = model_prob ** slip_size
    q = 1 - p

    if b <= 0 or p <= 0:
        return 0.0

    full_kelly = (b * p - q) / b
    if full_kelly <= 0:
        return 0.0

    return round(min(full_kelly * fraction, MAX_STAKE_PCT), 4)


def stake_dollars(kelly_pct: float, bankroll: float) -> float:
    return round(kelly_pct * bankroll, 2)


def risk_reward(stake: float, payout_multiplier: float) -> dict:
    potential_win = round(stake * payout_multiplier - stake, 2)
    return {
        "stake": stake,
        "potential_win": potential_win,
        "potential_loss": stake,
    }
