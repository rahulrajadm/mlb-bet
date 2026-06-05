"""
MLB Bet — Streamlit Dashboard
Tabs: Today's Picks | Game Predictions | Player Props | Platform Comparison | Bankroll Tracker
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from picks.engine import build_picks, best_picks_per_player, platform_comparison, is_high_interest
from pipeline.schedule import get_today_games
from pipeline.prizepicks import get_prizepicks_lines
from pipeline.underdog import get_underdog_lines
from pipeline.odds_api import get_all_odds
from pipeline.recent_form import get_recent_form
from pipeline.pitcher_stats import get_pitcher_stats
from pipeline.lineups import lineups_are_posted
from pipeline.handedness import fetch_and_save_pitcher_hands, fetch_and_save_batter_hands
from analysis.confidence import TIER_COLORS
from analysis.risk import RISK_COLORS

st.set_page_config(
    page_title="MLB Bet",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("⚾ MLB Bet")
    st.caption("AI-powered MLB betting decisions")
    st.divider()

    bankroll   = st.number_input("My Bankroll ($)",  min_value=10.0,  value=500.0, step=10.0)
    unit_size  = st.number_input("1 Unit = ($)",     min_value=1.0,   value=10.0,  step=1.0)

    st.divider()
    if st.button("🔄 Refresh All Data", use_container_width=True):
        with st.spinner("Refreshing lines, form, matchups & handedness…"):
            get_today_games()
            get_prizepicks_lines()
            get_underdog_lines()
            get_recent_form()
            get_pitcher_stats()
            fetch_and_save_pitcher_hands()
            try:
                get_all_odds()
            except Exception:
                pass
        st.success("Data refreshed!")
        st.rerun()

    # Lineup status indicator
    try:
        posted = lineups_are_posted()
        if posted:
            st.success("✅ Lineups confirmed")
        else:
            st.warning("⏳ Lineups not posted yet")
    except Exception:
        pass

    st.divider()
    min_conf = st.selectbox("Min Confidence", ["LOW", "MEDIUM", "HIGH", "STRONG"], index=1)
    platforms = st.multiselect(
        "Platforms",
        ["prizepicks", "underdog"],
        default=["prizepicks", "underdog"],
    )

    st.divider()
    st.caption("Data sources: PrizePicks · Underdog · MLB Stats API · The Odds API")

# ── Load data ──────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_picks(bankroll, unit_size):
    return build_picks(bankroll=bankroll, unit_size=unit_size)

@st.cache_data(ttl=300)
def load_games():
    return get_today_games()

TIER_RANK = {"STRONG": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

with st.spinner("Loading picks…"):
    all_picks = load_picks(bankroll, unit_size)
    games = load_games()

# Apply sidebar filters
if platforms:
    filtered = [p for p in all_picks if p["platform"] in platforms]
else:
    filtered = all_picks

min_rank = TIER_RANK[min_conf]
filtered = [p for p in filtered if TIER_RANK.get(p["confidence_tier"], 0) >= min_rank]

best = best_picks_per_player(filtered)
high_interest = best_picks_per_player([p for p in filtered if is_high_interest(p)])
comparison = platform_comparison(filtered)

# ── Helper: badge HTML ─────────────────────────────────────────────────────────

def conf_badge(tier):
    color = TIER_COLORS.get(tier, "#94a3b8")
    return f'<span style="background:{color};color:#000;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:700">{tier}</span>'

def risk_badge(risk):
    color = RISK_COLORS.get(risk, "#94a3b8")
    return f'<span style="background:{color};color:#000;padding:2px 8px;border-radius:10px;font-size:0.75rem;font-weight:700">{risk}</span>'

# ── Tabs ───────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔥 High Interest",
    "🎯 Today's Picks",
    "⚾ Game Predictions",
    "📊 Player Props",
    "💰 Bankroll Tracker",
])

# ── Tab 1: High Interest ───────────────────────────────────────────────────────

def picks_table(pick_list, max_rows=50, show_context=False):
    """Render a styled picks dataframe."""
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
            row["Season Rate"] = f"{p.get('season_rate', 0):.2f}" if p.get('season_rate') is not None else "—"
            row["Recent Rate"] = f"{p.get('recent_rate', 0):.2f}" if p.get('recent_rate') is not None else "—"
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
        colors = {"STRONG": "background-color:#22c55e;color:#000",
                  "HIGH":   "background-color:#86efac;color:#000",
                  "MEDIUM": "background-color:#fbbf24;color:#000",
                  "LOW":    "background-color:#94a3b8;color:#000"}
        return colors.get(val, "")

    def color_risk(val):
        colors = {"LOW":    "background-color:#22c55e;color:#000",
                  "MEDIUM": "background-color:#f97316;color:#000",
                  "HIGH":   "background-color:#ef4444;color:#fff"}
        return colors.get(val, "")

    style_fn = df.style.map if hasattr(df.style, "map") else df.style.applymap
    styled = style_fn(color_conf, subset=["Confidence"])
    style_fn2 = styled.map if hasattr(styled, "map") else styled.applymap
    styled = style_fn2(color_risk, subset=["Risk"])
    st.dataframe(styled, use_container_width=True, hide_index=True)


with tab1:
    st.header("🔥 High Interest Picks")
    st.caption(
        "Picks on genuinely contested lines — lines ≥ 1.0, or More on a 0.5 line where the stat is competitive. "
        "Excludes obvious Less picks on 0.5 HR/SB/Doubles that platforms rarely offer."
    )

    col1, col2, col3, col4 = st.columns(4)
    hi_strong = sum(1 for p in high_interest if p["confidence_tier"] == "STRONG")
    hi_high   = sum(1 for p in high_interest if p["confidence_tier"] == "HIGH")
    hi_medium = sum(1 for p in high_interest if p["confidence_tier"] == "MEDIUM")
    col1.metric("High Interest Picks", len(high_interest))
    col2.metric("STRONG", hi_strong)
    col3.metric("HIGH", hi_high)
    col4.metric("MEDIUM", hi_medium)

    st.divider()

    # Stat type filter
    stat_types = sorted(set(p["stat_type"] for p in high_interest))
    selected_stats = st.multiselect("Filter by stat type:", stat_types, default=[], key="hi_stats")
    hi_filtered = [p for p in high_interest if not selected_stats or p["stat_type"] in selected_stats]

    show_ctx = st.toggle("Show season rate / recent form / matchup context", value=False)
    picks_table(hi_filtered, max_rows=75, show_context=show_ctx)
    st.caption(
        "**Model %** = blended prediction (55% recent 14-day form + 45% season avg), adjusted for opposing pitcher.  "
        "**Edge** = Model % − 50% implied.  "
        "**EV/$100** = expected value per $100 per leg.  "
        "**Stake** = quarter-Kelly for your bankroll."
    )

# ── Tab 2: Today's Picks (all) ─────────────────────────────────────────────────

with tab2:
    st.header("Today's Top Picks")
    st.caption("All +EV picks including 0.5 lines. Use the 🔥 High Interest tab for competitive lines only.")

    col1, col2, col3, col4 = st.columns(4)
    strong = sum(1 for p in best if p["confidence_tier"] == "STRONG")
    high   = sum(1 for p in best if p["confidence_tier"] == "HIGH")
    medium = sum(1 for p in best if p["confidence_tier"] == "MEDIUM")
    col1.metric("Total Picks", len(best))
    col2.metric("STRONG", strong)
    col3.metric("HIGH", high)
    col4.metric("MEDIUM", medium)

    st.divider()
    picks_table(best, max_rows=75)
    st.caption(
        "**Model %** = model's estimated probability.  "
        "**Edge** = Model % − 50% implied.  "
        "**EV/$100** = expected value per $100 per leg.  "
        "**Stake** = quarter-Kelly for your bankroll."
    )

# ── Tab 3: Game Predictions ────────────────────────────────────────────────────

with tab3:
    st.header("Today's Games")

    if not games:
        st.info("No games found for today. Try refreshing.")
    else:
        for g in games:
            with st.expander(
                f"**{g['away_team']}** @ **{g['home_team']}**  —  {g['away_starter']} vs {g['home_starter']}",
                expanded=False,
            ):
                col1, col2, col3 = st.columns(3)
                col1.markdown(f"**Away:** {g['away_team']}  \n**Starter:** {g['away_starter']}")
                col2.markdown(f"**Home:** {g['home_team']}  \n**Starter:** {g['home_starter']}")
                col3.markdown(f"**Venue:** {g.get('venue', 'N/A')}")

                game_picks = [p for p in high_interest if p.get("player_team") in [g["home_team"], g["away_team"]]]
                if game_picks:
                    st.markdown(f"**{len(game_picks)} high-interest picks for this game:**")
                    rows = [{
                        "Player":     p["player_name"],
                        "Stat":       p["stat_type"],
                        "Line":       p["line"],
                        "Pick":       p["direction"],
                        "Model %":    f"{p['model_prob']:.1%}",
                        "Edge":       f"{p['edge']:+.1%}",
                        "Confidence": p["confidence_tier"],
                        "Risk":       p["risk_profile"],
                        "Platform":   p["platform"],
                    } for p in game_picks[:15]]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.caption("No high-interest picks for this game.")

# ── Tab 4: Player Props ────────────────────────────────────────────────────────

with tab4:
    st.header("Player Props — Platform Comparison")
    st.caption("Same player-prop shown across PrizePicks and Underdog side-by-side.")

    search = st.text_input("Search player name…", "")

    hi_comparison = platform_comparison(high_interest)
    comp_items = list(hi_comparison.items())
    if search:
        comp_items = [item for item in comp_items if search.lower() in item[0][0].lower()]

    if not comp_items:
        st.info("No props match your search.")
    else:
        for (player, stat), platform_picks in comp_items[:50]:
            platform_picks_sorted = sorted(platform_picks, key=lambda x: x["edge"], reverse=True)

            with st.expander(f"**{player}** — {stat}", expanded=False):
                rows = [{
                    "Platform":   p["platform"],
                    "Line":       p["line"],
                    "Pick":       p["direction"],
                    "Model %":    f"{p['model_prob']:.1%}",
                    "Edge":       f"{p['edge']:+.1%}",
                    "EV/$100":    f"${p['ev_per_100']:+.1f}",
                    "Confidence": p["confidence_tier"],
                    "Risk":       p["risk_profile"],
                } for p in platform_picks_sorted]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ── Tab 5: Bankroll Tracker ────────────────────────────────────────────────────

with tab5:
    st.header("Bankroll Tracker")

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Current Bankroll", f"${bankroll:,.2f}")
        st.divider()
        st.subheader("Recommended Stakes")
        st.caption("Quarter-Kelly sizing on high-interest picks.")

        st.caption(f"1 unit = ${unit_size:.0f}")
        stake_rows = []
        for p in high_interest[:20]:
            stake_rows.append({
                "Player":        p["player_name"],
                "Pick":          f"{p['stat_type']} {p['direction']} {p['line']}",
                "Confidence":    p["confidence_tier"],
                "Units":         f"{p.get('units', 0):.1f}u",
                "Stake ($)":     f"${p['stake_dollars']:.2f}",
                "Potential Win": f"${p['potential_win']:.2f}",
                "R/R Ratio":     f"{p['risk_reward_ratio']:.1f}x",
            })
        if stake_rows:
            st.dataframe(pd.DataFrame(stake_rows), use_container_width=True, hide_index=True)

    with col2:
        st.subheader("PrizePicks Slip Builder")
        st.caption("Pick 2–6 legs from High Interest picks to see slip EV.")

        from analysis.ev import ev_slip
        slip_picks = [p["selection"] for p in high_interest[:30]]
        selected = st.multiselect("Select picks for your slip:", slip_picks, max_selections=6)
        slip_size = len(selected)

        if slip_size >= 2:
            selected_probs = []
            for sel in selected:
                match = next((p for p in high_interest if p["selection"] == sel), None)
                if match:
                    selected_probs.append(match["model_prob"])

            result = ev_slip(selected_probs, "prizepicks", slip_size)
            if result:
                st.metric("Slip Size", f"{slip_size}-pick Power Play")
                st.metric("Payout Multiplier", f"{result['multiplier']}x")
                st.metric("Model P(all hit)", f"{result['p_all_hit']:.1%}")
                ev_val = result["ev_per_100"]
                st.metric(
                    "EV per $100 entry",
                    f"${ev_val:+.2f}",
                    delta="Positive edge" if ev_val > 0 else "Negative edge",
                    delta_color="normal" if ev_val > 0 else "inverse",
                )
        elif slip_size == 1:
            st.info("Select at least 2 picks to build a slip.")
        else:
            st.info("Select picks above to calculate slip EV.")
