"""
EV and break-even math for pick'em platforms (PrizePicks, Underdog).

Every leg's edge is measured against the platform break-even, NOT 0.50:
a 2-pick 3x slip returns even money only when each leg hits with
p = (1/3)^(1/2) ≈ 0.577. Measuring against a coin flip overstates every
edge by ~8 points and calls 50–57.7% legs +EV when they lose money.
"""

# Payout multipliers verified Jul 2026 (PrizePicks help center; Underdog help
# pages block scraping — table matches last verifiable published standard
# payouts and should be re-checked if slips look mispriced).
PRIZEPICKS_POWER = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0, 6: 37.5}
UNDERDOG_POWER = {2: 3.0, 3: 6.0, 4: 10.0, 5: 20.0}

PLATFORM_MULTIPLIERS = {
    "prizepicks": PRIZEPICKS_POWER,
    "underdog": UNDERDOG_POWER,
}

# Edges and Kelly stakes are priced as legs of this baseline slip.
BASELINE_SLIP_SIZE = 2
BASELINE_MULTIPLIER = 3.0


def breakeven_prob(platform: str = "prizepicks",
                   slip_size: int = BASELINE_SLIP_SIZE) -> float:
    """Per-leg probability at which a slip of equally likely, independent
    legs breaks even: (1/multiplier)^(1/slip_size)."""
    mult = PLATFORM_MULTIPLIERS.get(platform, PRIZEPICKS_POWER).get(
        slip_size, BASELINE_MULTIPLIER)
    return (1.0 / mult) ** (1.0 / slip_size)


def ev_per_leg(model_prob: float, breakeven: float) -> float:
    """Per-leg edge ×100 — the display convention for 'EV / $100'.
    This is edge over break-even, not a payout-weighted slip EV."""
    return round((model_prob - breakeven) * 100, 2)


def ev_slip(model_probs: list[float], platform: str, slip_size: int) -> dict:
    """
    EV for a full multi-leg slip where all legs must hit (Power Play style).
    Assumes independent legs — same-game legs are correlated and this
    overstates (positively correlated) or understates their combined odds.
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
