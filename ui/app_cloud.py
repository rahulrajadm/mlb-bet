"""
MLB Bet — Streamlit Community Cloud version.
Fetches all data in-memory (no SQLite). Refresh is passcode-gated.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pipeline.schedule import fetch_today_schedule
from pipeline.prizepicks import fetch_mlb_lines as pp_fetch
from pipeline.underdog import fetch_mlb_lines as ud_fetch
from pipeline.recent_form import pull_recent_batting, pull_recent_pitching
from pipeline.pitcher_stats import pull_pitcher_stats
from pipeline.handedness import fetch_and_save_pitcher_hands, load_handedness_from_db
from pipeline.lineups import fetch_lineups, get_confirmed_players
from picks.engine import build_picks, best_picks_per_player, platform_comparison, is_high_interest
from analysis.confidence import TIER_COLORS
from analysis.risk import RISK_COLORS
from analysis.ev import ev_slip

st.set_page_config(
    page_title="MLB Bet",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── In-memory data loading (cached) ───────────────────────────────────────────

@st.cache_data(ttl=1800, show_spinner=False)
def load_all_data():
    """Fetch all live data in-memory. Cached for 30 minutes."""
    games       = fetch_today_schedule()
    pp_lines    = pp_fetch()
    ud_lines    = ud_fetch()
    rec_bat     = pull_recent_batting()
    rec_pit     = pull_recent_pitching()
    pit_stats   = pull_pitcher_stats()

    # Pitcher handedness for today's starters
    try:
        pit_hands = fetch_and_save_pitcher_hands()
    except Exception:
        pit_hands = {}

    hand_db = load_handedness_from_db()

    # Confirmed lineups
    try:
        confirmed = get_confirmed_players()
    except Exception:
        confirmed = set()

    # Combine all prop lines
    all_lines = []
    for p in pp_lines:
        p.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
        all_lines.append(p)
    for p in ud_lines:
        p.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
        all_lines.append(p)

    return {
        "games":     games,
        "lines":     all_lines,
        "rec_bat":   rec_bat,
        "rec_pit":   rec_pit,
        "pit_stats": pit_stats,
        "hand_db":   hand_db,
        "confirmed": confirmed,
        "fetched_at": datetime.now(ZoneInfo("America/Chicago")).strftime("%b %d %Y, %I:%M %p"),
    }


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚾ MLB Bet")
    st.caption("AI-powered MLB betting decisions")
    st.divider()

    bankroll  = st.number_input("My Bankroll ($)", min_value=10.0, value=500.0, step=10.0)
    unit_size = st.number_input("1 Unit = ($)",    min_value=1.0,  value=10.0,  step=1.0)

    st.divider()

    # Passcode-gated refresh
    with st.expander("🔄 Refresh Data"):
        code = st.text_input("Passcode", type="password", key="refresh_code")
        if st.button("Refresh All Data", use_container_width=True):
            correct = st.secrets.get("REFRESH_CODE", "")
            if code == correct and correct != "":
                st.cache_data.clear()
                st.success("Cache cleared — reloading…")
                st.rerun()
            else:
                st.error("Invalid passcode")

    st.divider()
    min_conf = st.selectbox("Min Confidence", ["LOW", "MEDIUM", "HIGH", "STRONG"], index=1)
    platforms = st.multiselect(
        "Platforms",
        ["prizepicks", "underdog"],
        default=["prizepicks", "underdog"],
    )

# ── Load data ──────────────────────────────────────────────────────────────────

with st.spinner("Loading today's picks…"):
    data = load_all_data()

games_list   = data["games"]
lineups_up   = len(data["confirmed"]) > 0

with st.sidebar:
    st.divider()
    if lineups_up:
        st.success("✅ Lineups confirmed")
    else:
        st.warning("⏳ Lineups not posted yet")
    st.caption(f"🕐 Last updated: **{data['fetched_at']}** CT")
    st.caption("Data: PrizePicks · Underdog · MLB Stats API")

# Timestamp banner — shown at top of every tab
def timestamp_bar(fetched_at: str):
    st.markdown(
        f"<div style='background:#1a1d27;border-left:3px solid #22c55e;padding:8px 14px;"
        f"border-radius:4px;font-size:0.85rem;color:#9ca3af;margin-bottom:8px'>"
        f"🕐 Data last updated: <strong style='color:#e8eaf0'>{fetched_at} CT</strong>"
        f" &nbsp;·&nbsp; Refresh in the sidebar to update</div>",
        unsafe_allow_html=True,
    )

# Build picks from in-memory data
TIER_RANK = {"STRONG": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

@st.cache_data(ttl=1800, show_spinner=False)
def load_picks_cloud(bankroll, unit_size, min_conf, _platforms, _cache_key):
    all_picks = build_picks(
        bankroll=bankroll,
        unit_size=unit_size,
        lines_data=data["lines"],
        games_data=data["games"],
        recent_batting_data=data["rec_bat"],
        recent_pitching_data=data["rec_pit"],
        pitcher_stats_data=data["pit_stats"],
        handedness_data=data["hand_db"],
        confirmed_players_data=data["confirmed"],
    )
    filtered = [p for p in all_picks if p["platform"] in _platforms] if _platforms else all_picks
    min_rank = TIER_RANK.get(min_conf, 1)
    filtered = [p for p in filtered if TIER_RANK.get(p["confidence_tier"], 0) >= min_rank]
    return filtered

all_picks = load_picks_cloud(bankroll, unit_size, min_conf, tuple(platforms), data["fetched_at"])
best      = best_picks_per_player(all_picks)
hi        = best_picks_per_player([p for p in all_picks if is_high_interest(p)])
comp      = platform_comparison(all_picks)

# ── Shared helpers ─────────────────────────────────────────────────────────────

def picks_table(pick_list, max_rows=75, show_context=False):
    rows = []
    for p in pick_list[:max_rows]:
        row = {
            "Player":        p["player_name"],
            "Team":          p["player_team"],
            "Stat":          p["stat_type"],
            "Line":          p["line"],
            "Pick":          p["direction"],
            "Model %":       f"{p['model_prob']:.1%}",
            "Edge":          f"{p['edge']:+.1%}",
            "EV / $100":     f"${p['ev_per_100']:+.1f}",
            "Confidence":    p["confidence_tier"],
            "Risk":          p["risk_profile"],
            "Platform":      p["platform"],
            "Units":         f"{p.get('units', 0):.1f}u",
            "Stake ($)":     f"${p['stake_dollars']:.0f}",
            "Potential Win": f"${p['potential_win']:.0f}",
        }
        if show_context:
            row["Season Rate"] = f"{p.get('season_rate', 0):.2f}" if p.get("season_rate") is not None else "—"
            row["Recent Rate"] = f"{p.get('recent_rate', 0):.2f}" if p.get("recent_rate") is not None else "—"
            row["Matchup"]     = p.get("matchup", "—")
            row["Arsenal"]     = p.get("arsenal", "—")
            row["Park"]        = p.get("park", "—")
            row["Platoon"]     = p.get("platoon", "—")
        rows.append(row)

    if not rows:
        st.info("No picks match the current filters.")
        return

    df = pd.DataFrame(rows)

    def color_conf(val):
        colors = {"STRONG": "background-color:#16a34a;color:#fff;font-weight:700",
                  "HIGH":   "background-color:#22c55e;color:#000;font-weight:700",
                  "MEDIUM": "background-color:#ca8a04;color:#fff;font-weight:700",
                  "LOW":    "background-color:#374151;color:#9ca3af;font-weight:700"}
        return colors.get(val, "")

    def color_risk(val):
        colors = {"LOW":    "background-color:#16a34a;color:#fff;font-weight:700",
                  "MEDIUM": "background-color:#c2410c;color:#fff;font-weight:700",
                  "HIGH":   "background-color:#dc2626;color:#fff;font-weight:700"}
        return colors.get(val, "")

    style_fn = df.style.map if hasattr(df.style, "map") else df.style.applymap
    styled = style_fn(color_conf, subset=["Confidence"])
    style_fn2 = styled.map if hasattr(styled, "map") else styled.applymap
    styled = style_fn2(color_risk, subset=["Risk"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


# ── Tabs ───────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔥 High Interest",
    "🎯 Today's Picks",
    "⚾ Game Predictions",
    "📊 Player Props",
    "💰 Bankroll Tracker",
])

# ── Tab 1: High Interest ───────────────────────────────────────────────────────

with tab1:
    timestamp_bar(data["fetched_at"])
    st.header("🔥 High Interest Picks")
    st.caption(
        "Competitive lines only — ≥1.0 line, or More on a contested 0.5 stat. "
        "Excludes obvious Less picks on 0.5 HR/SB/Doubles."
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("High Interest Picks", len(hi))
    c2.metric("STRONG", sum(1 for p in hi if p["confidence_tier"] == "STRONG"))
    c3.metric("HIGH",   sum(1 for p in hi if p["confidence_tier"] == "HIGH"))
    c4.metric("MEDIUM", sum(1 for p in hi if p["confidence_tier"] == "MEDIUM"))

    st.divider()
    stat_types   = sorted(set(p["stat_type"] for p in hi))
    sel_stats    = st.multiselect("Filter by stat:", stat_types, default=[], key="hi_stats")
    hi_filtered  = [p for p in hi if not sel_stats or p["stat_type"] in sel_stats]
    show_ctx     = st.toggle("Show season/recent/matchup context", value=False)
    picks_table(hi_filtered, show_context=show_ctx)
    st.caption(
        "**Model %** = 55% recent 14-day form + 45% season avg, adjusted for pitcher, park & platoon.  "
        "**Edge** = Model % − 50% implied.  **Units** = quarter-Kelly stake."
    )

# ── Tab 2: Today's Picks ───────────────────────────────────────────────────────

with tab2:
    timestamp_bar(data["fetched_at"])
    st.header("Today's Picks")
    st.caption("All +EV picks. Use 🔥 High Interest for competitive lines only.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total", len(best))
    c2.metric("STRONG", sum(1 for p in best if p["confidence_tier"] == "STRONG"))
    c3.metric("HIGH",   sum(1 for p in best if p["confidence_tier"] == "HIGH"))
    c4.metric("MEDIUM", sum(1 for p in best if p["confidence_tier"] == "MEDIUM"))
    st.divider()
    picks_table(best)

# ── Tab 3: Game Predictions ────────────────────────────────────────────────────

with tab3:
    timestamp_bar(data["fetched_at"])
    st.header("Today's Games")
    if not games_list:
        st.info("No games found for today.")
    else:
        for g in games_list:
            with st.expander(
                f"**{g['away_team']}** @ **{g['home_team']}**  —  {g['away_starter']} vs {g['home_starter']}",
                expanded=False,
            ):
                c1, c2, c3 = st.columns(3)
                c1.markdown(f"**Away:** {g['away_team']}  \n**Starter:** {g['away_starter']}")
                c2.markdown(f"**Home:** {g['home_team']}  \n**Starter:** {g['home_starter']}")
                c3.markdown(f"**Venue:** {g.get('venue', 'N/A')}")
                game_picks = [p for p in hi if p.get("player_team") in [g["home_team"], g["away_team"]]]
                if game_picks:
                    st.markdown(f"**{len(game_picks)} high-interest picks:**")
                    rows = [{
                        "Player": p["player_name"], "Stat": p["stat_type"],
                        "Line": p["line"], "Pick": p["direction"],
                        "Model %": f"{p['model_prob']:.1%}", "Edge": f"{p['edge']:+.1%}",
                        "Confidence": p["confidence_tier"], "Risk": p["risk_profile"],
                        "Platform": p["platform"],
                    } for p in game_picks[:15]]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No high-interest picks for this game.")

# ── Tab 4: Player Props ────────────────────────────────────────────────────────

with tab4:
    timestamp_bar(data["fetched_at"])
    st.header("Player Props — Platform Comparison")
    search     = st.text_input("Search player name…", "")
    hi_comp    = platform_comparison(hi)
    comp_items = list(hi_comp.items())
    if search:
        comp_items = [item for item in comp_items if search.lower() in item[0][0].lower()]
    if not comp_items:
        st.info("No props match your search.")
    else:
        for (player, stat), picks_list in comp_items[:50]:
            sorted_picks = sorted(picks_list, key=lambda x: x["edge"], reverse=True)
            with st.expander(f"**{player}** — {stat}", expanded=False):
                rows = [{
                    "Platform": p["platform"], "Line": p["line"], "Pick": p["direction"],
                    "Model %": f"{p['model_prob']:.1%}", "Edge": f"{p['edge']:+.1%}",
                    "EV/$100": f"${p['ev_per_100']:+.1f}",
                    "Confidence": p["confidence_tier"], "Risk": p["risk_profile"],
                } for p in sorted_picks]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ── Tab 5: Bankroll Tracker ────────────────────────────────────────────────────

with tab5:
    st.header("Bankroll Tracker")
    c1, c2 = st.columns(2)

    with c1:
        st.metric("Bankroll", f"${bankroll:,.2f}")
        st.caption(f"1 unit = ${unit_size:.0f}")
        st.divider()
        st.subheader("Recommended Stakes")
        rows = [{
            "Player":        p["player_name"],
            "Pick":          f"{p['stat_type']} {p['direction']} {p['line']}",
            "Confidence":    p["confidence_tier"],
            "Units":         f"{p.get('units', 0):.1f}u",
            "Stake ($)":     f"${p['stake_dollars']:.2f}",
            "Potential Win": f"${p['potential_win']:.2f}",
            "R/R":           f"{p['risk_reward_ratio']:.1f}x",
        } for p in hi[:20]]
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    with c2:
        st.subheader("PrizePicks Slip Builder")
        st.caption("Select 2–6 high-interest picks to calculate slip EV.")
        slip_opts = [p["selection"] for p in hi[:30]]
        selected  = st.multiselect("Select picks:", slip_opts, max_selections=6)
        if len(selected) >= 2:
            probs  = [p["model_prob"] for sel in selected for p in hi if p["selection"] == sel]
            result = ev_slip(probs, "prizepicks", len(selected))
            if result:
                st.metric("Slip Size",         f"{len(selected)}-pick Power Play")
                st.metric("Payout Multiplier", f"{result['multiplier']}x")
                st.metric("P(all hit)",         f"{result['p_all_hit']:.1%}")
                ev_val = result["ev_per_100"]
                st.metric("EV per $100",       f"${ev_val:+.2f}",
                          delta="Positive edge" if ev_val > 0 else "Negative edge",
                          delta_color="normal" if ev_val > 0 else "inverse")
        elif len(selected) == 1:
            st.info("Select at least 2 picks.")
        else:
            st.info("Select picks above to calculate slip EV.")
