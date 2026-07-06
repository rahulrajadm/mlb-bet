"""
Assembles model predictions + analysis into final structured pick objects.
Filters to meaningful +EV picks, deduplicates cross-platform, ranks by EV.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.props import predict_props
from analysis.ev import ev_per_leg, BASELINE_MULTIPLIER, BASELINE_SLIP_SIZE
from analysis.confidence import get_confidence_tier, TIER_RANK
from analysis.risk import get_risk_profile
from analysis.kelly import kelly_stake, risk_reward

# Minimum edge (vs break-even) to surface a pick
MIN_EDGE = 0.04
# Filter out picks where model prob is too extreme (>90% or <10%) — likely data issues
MAX_PROB = 0.90
MIN_PROB = 0.10

# Stats where pick'em platforms almost never offer "Less" on a 0.5 line
# (the "Less" side is too obvious so platforms don't give players that option)
NO_LESS_AT_HALF = {
    "Home Runs", "Stolen Bases", "Doubles", "Triples",
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
    High-interest picks: lines with genuine uncertainty (not trivially obvious).
    Excludes Less picks below a 1.0 line; keeps line >= 1.0 and More on 0.5.
    """
    if pick["direction"] == "Less" and pick["line"] < 1.0:
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
    arsenal_data=None,
) -> list[dict]:
    raw = predict_props(
        lines_data=lines_data,
        games_data=games_data,
        recent_batting_data=recent_batting_data,
        recent_pitching_data=recent_pitching_data,
        pitcher_stats_data=pitcher_stats_data,
        handedness_data=handedness_data,
        confirmed_players_data=confirmed_players_data,
        arsenal_data=arsenal_data,
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

        ev = ev_per_leg(model_prob, pred["implied_prob"])
        confidence = get_confidence_tier(edge, pred.get("games_sample", 0))
        risk = get_risk_profile(pred["stat_type"], edge)

        # Sized as a leg of the baseline 2-pick 3x slip
        kelly_pct = kelly_stake(model_prob, BASELINE_MULTIPLIER, BASELINE_SLIP_SIZE)
        stake     = round(kelly_pct * bankroll, 2)
        units     = round(stake / unit_size, 2) if unit_size > 0 else 0
        rr        = risk_reward(stake, BASELINE_MULTIPLIER)

        picks.append({
            "platform":        pred["platform"],
            "player_name":     pred["player_name"],
            "player_team":     pred["player_team"],
            "stat_type":       pred["stat_type"],
            "stat_key":        pred["stat_key"],
            "stat_display":    pred["stat_display"],
            "line":            pred["line"],
            "direction":       pred["direction"],
            "selection":       f"{pred['player_name']} {pred['stat_display']} {pred['direction']} {pred['line']:g}",
            "model_prob":      pred["model_prob"],
            "implied_prob":    pred["implied_prob"],
            "edge":            pred["edge"],
            "expected_rate":   pred["expected_rate"],
            "ev_per_100":      ev,
            "confidence_tier": confidence,
            "risk_profile":    risk,
            "kelly_pct":       kelly_pct,
            "stake_dollars":   stake,
            "units":           units,
            "potential_win":   rr["potential_win"],
            "season_rate":     pred.get("season_rate"),
            "recent_rate":     pred.get("recent_rate"),
            "form_source":     pred.get("form_source", ""),
            "matchup":         pred.get("matchup", ""),
            "arsenal":         pred.get("arsenal", ""),
            "park":            pred.get("park", ""),
            "platoon":         pred.get("platoon", ""),
        })

    # Sort by confidence tier first, then EV
    picks.sort(key=lambda x: (TIER_RANK.get(x["confidence_tier"], 0), x["ev_per_100"]), reverse=True)

    return picks


def _prop_key(pick: dict) -> tuple:
    """Cross-platform identity of a prop: canonical stat, not the platform's
    spelling (PP "Walks" and UD "Batter Walks" are the same prop)."""
    return (pick["player_name"], pick.get("stat_key") or pick["stat_type"])


def best_picks_per_player(picks: list[dict]) -> list[dict]:
    """
    When the same player + stat appears on multiple platforms, keep the
    highest-ranked one (input is already sorted by tier then EV).
    """
    seen = set()
    deduped = []
    for p in picks:
        key = _prop_key(p)
        if key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def platform_comparison(picks: list[dict]) -> dict:
    """
    Group picks by player + canonical stat showing all platforms side-by-side.
    Feed this the full (un-deduped) pick list — a deduped list can never
    show more than one platform per prop.
    Returns dict keyed by (player_name, stat_display).
    """
    comparison = {}
    for p in picks:
        key = (p["player_name"], p.get("stat_display") or p["stat_type"])
        comparison.setdefault(key, []).append(p)
    return comparison


if __name__ == "__main__":
    picks = build_picks(bankroll=1000)
    best = best_picks_per_player(picks)
    print(f"\nTotal picks: {len(picks)} | Unique player-props: {len(best)}\n")
    print(f"{'Player':<22} {'Stat':<22} {'Line':>5} {'Dir':>5} {'Model%':>7} {'Edge':>6} {'EV/100':>7} {'Conf':>7} {'Risk':>7} {'Platform'}")
    print("-" * 120)
    for p in best[:30]:
        print(
            f"{p['player_name']:<22} {p['stat_type']:<22} {p['line']:>5} "
            f"{p['direction']:>5} {p['model_prob']:>6.1%} {p['edge']:>+6.1%} "
            f"{p['ev_per_100']:>+7.1f} {p['confidence_tier']:>7} {p['risk_profile']:>7}  {p['platform']}"
        )
