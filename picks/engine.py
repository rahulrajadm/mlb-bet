"""
Assembles model predictions + analysis into final structured pick objects.
Filters to meaningful +EV picks, deduplicates cross-platform, ranks by EV.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.props import predict_props
from analysis.ev import ev_per_leg, PLATFORM_MULTIPLIERS, PRIZEPICKS_POWER
from analysis.confidence import get_confidence_tier
from analysis.risk import get_risk_profile
from analysis.kelly import kelly_stake, risk_reward

# Minimum edge to surface a pick (filters out marginal/obvious picks)
MIN_EDGE = 0.04
# Filter out picks where model prob is too extreme (>90% or <10%) — likely data issues
MAX_PROB = 0.90
MIN_PROB = 0.10

# Default payout multiplier to use for Kelly (single-leg equivalent)
DEFAULT_MULTIPLIER = 3.0  # 2-pick power play baseline

# Stats where pick'em platforms almost never offer "Less" on a 0.5 line
# (the "Less" side is too obvious so platforms don't give players that option)
NO_LESS_AT_HALF = {
    "Home Runs", "Stolen Bases", "Doubles", "Triples",
    "Pitcher Strikeouts (Combo)",
}


def is_platform_realistic(pick: dict) -> bool:
    """
    Returns False for picks that pick'em platforms don't actually offer.
    Specifically: Less on 0.5 lines for rare/low-probability stats.
    """
    if pick["direction"] == "Less" and pick["line"] == 0.5 and pick["stat_type"] in NO_LESS_AT_HALF:
        return False
    return True


def is_high_interest(pick: dict) -> bool:
    """
    High-interest picks: lines where there's genuine uncertainty (not trivially obvious).
    - Excludes all 0.5 Less picks (even for stats not in NO_LESS_AT_HALF)
    - Requires line >= 1.0, OR More on a 0.5 line for a legitimately competitive stat
    - Targets stats where the platform line is genuinely contested
    """
    if pick["direction"] == "Less" and pick["line"] <= 0.5:
        return False
    if pick["line"] < 1.0 and pick["direction"] == "Less":
        return False
    return True


def build_picks(
    bankroll: float = 1000.0,
    unit_size: float = 10.0,
    # Optional in-memory data for cloud mode
    lines_data=None,
    games_data=None,
    recent_batting_data=None,
    recent_pitching_data=None,
    pitcher_stats_data=None,
    handedness_data=None,
    confirmed_players_data=None,
) -> list[dict]:
    raw = predict_props(
        lines_data=lines_data,
        games_data=games_data,
        recent_batting_data=recent_batting_data,
        recent_pitching_data=recent_pitching_data,
        pitcher_stats_data=pitcher_stats_data,
        handedness_data=handedness_data,
        confirmed_players_data=confirmed_players_data,
    )

    picks = []
    for pred in raw:
        edge = pred["edge"]
        model_prob = pred["model_prob"]

        # Filter extremes and marginal picks
        if edge < MIN_EDGE:
            continue
        if model_prob > MAX_PROB or model_prob < MIN_PROB:
            continue

        # Drop picks that platforms don't actually offer
        if not is_platform_realistic(pred):
            continue

        ev = ev_per_leg(model_prob)
        confidence = get_confidence_tier(edge, pred.get("games_sample", 100))
        risk = get_risk_profile(pred["stat_type"], edge)

        # Kelly sizing based on 2-pick power play baseline
        multiplier  = DEFAULT_MULTIPLIER
        kelly_pct   = kelly_stake(model_prob, multiplier)
        stake       = round(kelly_pct * bankroll, 2)
        units       = round(stake / unit_size, 2) if unit_size > 0 else 0
        rr          = risk_reward(stake, multiplier)

        picks.append({
            "platform":          pred["platform"],
            "player_name":       pred["player_name"],
            "player_team":       pred["player_team"],
            "stat_type":         pred["stat_type"],
            "line":              pred["line"],
            "direction":         pred["direction"],
            "selection":         f"{pred['player_name']} {pred['stat_type']} {pred['direction']} {pred['line']}",
            "model_prob":        pred["model_prob"],
            "implied_prob":      pred["implied_prob"],
            "edge":              pred["edge"],
            "expected_rate":     pred["expected_rate"],
            "ev_per_100":        ev,
            "confidence_tier":   confidence,
            "risk_profile":      risk,
            "kelly_pct":         kelly_pct,
            "stake_dollars":     stake,
            "units":             units,
            "potential_win":     rr["potential_win"],
            "risk_reward_ratio": rr["ratio"],
            "season_rate":       pred.get("season_rate"),
            "recent_rate":       pred.get("recent_rate"),
            "form_source":       pred.get("form_source", ""),
            "matchup":           pred.get("matchup", ""),
            "park":              pred.get("park", ""),
            "platoon":           pred.get("platoon", ""),
        })

    # Sort by confidence tier first, then EV
    tier_rank = {"STRONG": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    picks.sort(key=lambda x: (tier_rank.get(x["confidence_tier"], 0), x["ev_per_100"]), reverse=True)

    return picks


def best_picks_per_player(picks: list[dict]) -> list[dict]:
    """
    When the same player + stat appears on multiple platforms, keep the one
    with the best edge (deduplicating for the Today's Picks view).
    """
    seen = {}
    deduped = []
    for p in picks:
        key = (p["player_name"], p["stat_type"])
        if key not in seen:
            seen[key] = True
            deduped.append(p)
    return deduped


def platform_comparison(picks: list[dict]) -> dict:
    """
    Group picks by player+stat showing all platforms side-by-side.
    Returns dict keyed by (player_name, stat_type).
    """
    comparison = {}
    for p in picks:
        key = (p["player_name"], p["stat_type"])
        if key not in comparison:
            comparison[key] = []
        comparison[key].append(p)
    return comparison


if __name__ == "__main__":
    picks = build_picks(bankroll=1000)
    best = best_picks_per_player(picks)
    print(f"\nTotal picks: {len(picks)} | Unique player-props: {len(best)}\n")
    print(f"{'Player':<22} {'Stat':<28} {'Line':>5} {'Dir':>5} {'Model%':>7} {'Edge':>6} {'EV/100':>7} {'Conf':>7} {'Risk':>7} {'Platform'}")
    print("-" * 120)
    for p in best[:30]:
        print(
            f"{p['player_name']:<22} {p['stat_type']:<28} {p['line']:>5} "
            f"{p['direction']:>5} {p['model_prob']:>6.1%} {p['edge']:>+6.1%} "
            f"{p['ev_per_100']:>+7.1f} {p['confidence_tier']:>7} {p['risk_profile']:>7}  {p['platform']}"
        )
