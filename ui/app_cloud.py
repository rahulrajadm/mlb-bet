"""
MLB Bet — Streamlit Community Cloud version.
Fetches all data in-memory (no SQLite for live data). Refresh is passcode-gated.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
from datetime import datetime, timezone

from pipeline.schedule import fetch_today_schedule
from pipeline.prizepicks import fetch_mlb_lines as pp_fetch
from pipeline.underdog import fetch_mlb_lines as ud_fetch
from pipeline.recent_form import pull_recent_batting, pull_recent_pitching
from pipeline.pitcher_stats import pull_pitcher_stats, pull_recent_pitcher_form, blend_pitcher_stats
from pipeline.pitcher_arsenal import pull_arsenal_stats, compute_weighted_whiff
from pipeline.handedness import fetch_lineup_handedness
from pipeline.lineups import get_confirmed_players
from pipeline.team_names import to_abbr, to_full_name
from pipeline.team_stats import fetch_team_stats
from pipeline.odds_api import fetch_all_odds_rows
from picks.engine import build_picks, best_picks_per_player, platform_comparison, is_high_interest, line_type_rows
from models.game_model import predict_games, best_game_edges
from analysis.confidence import TIER_RANK
from analysis.ev import ev_slip
from utils.dates import APP_TZ

st.set_page_config(
    page_title="MLB Bet",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

EDGE_HELP = (
    "**Model %** = 55% recent 14-day form + 45% season avg, adjusted for pitcher, park & platoon.  "
    "**Edge** = Model % − 57.7% break-even (2-pick 3x slip).  "
    "**EV / 100** = edge per 100 wagered per leg.  "
    "**Units** = quarter-Kelly stake sized as a leg of a 2-pick slip."
)

# ── In-memory data loading (cached) ───────────────────────────────────────────

@st.cache_data(show_spinner=False)
def load_all_data():
    """Fetch all live data in-memory. Cached until a passcode refresh."""
    games       = fetch_today_schedule()
    pp_lines    = pp_fetch()
    ud_lines    = ud_fetch()
    rec_bat     = pull_recent_batting()
    rec_pit     = pull_recent_pitching()
    pit_stats   = blend_pitcher_stats(pull_pitcher_stats(), pull_recent_pitcher_form())

    # Statcast arsenal (whiff-rate) profiles — keeps cloud predictions in step
    # with local runs, where this comes from SQLite
    try:
        arsenal = compute_weighted_whiff(pull_arsenal_stats())
    except Exception:
        arsenal = pd.DataFrame()

    # Handedness for today's confirmed lineups + probable starters
    try:
        hand_db = fetch_lineup_handedness()
    except Exception:
        hand_db = {}

    # Confirmed lineups (batters + probable pitchers)
    try:
        confirmed = get_confirmed_players()
    except Exception:
        confirmed = set()

    # Team run rates for the game model (free MLB StatsAPI)
    try:
        team_stats = fetch_team_stats()
    except Exception:
        team_stats = {}

    # Game odds are metered (The Odds API): only fetch if a key is configured
    # in secrets, and only here (refresh is passcode-gated, never per-visitor).
    game_odds = []
    try:
        odds_key = st.secrets.get("ODDS_API_KEY")
    except Exception:
        odds_key = None
    if odds_key:
        try:
            game_odds = fetch_all_odds_rows(odds_key)
        except Exception:
            game_odds = []

    # Combine all prop lines
    all_lines = []
    for p in pp_lines + ud_lines:
        p.setdefault("fetched_at", datetime.now(timezone.utc).isoformat())
        all_lines.append(p)

    return {
        "games":     games,
        "lines":     all_lines,
        "rec_bat":   rec_bat,
        "rec_pit":   rec_pit,
        "pit_stats": pit_stats,
        "arsenal":   arsenal,
        "hand_db":   hand_db,
        "confirmed": confirmed,
        "team_stats": team_stats,
        "game_odds":  game_odds,
        "fetched_at": datetime.now(APP_TZ).strftime("%b %d %Y, %I:%M %p"),
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
        if st.button("Refresh All Data", width="stretch"):
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
    line_type_labels = st.multiselect(
        "Line type",
        ["Standard", "Goblin", "Demon"],
        default=["Standard"],
        help="Only Standard lines are EV-priced. Goblins/demons are More-only "
             "with payouts PrizePicks doesn't expose, so they show in Player "
             "Props as view-only (line + P(More)), never as staked picks.",
    )

LINE_TYPE_MAP = {"Standard": "standard", "Goblin": "goblin", "Demon": "demon"}
selected_odds_types = {LINE_TYPE_MAP[l] for l in line_type_labels} or {"standard"}
alt_odds_types = tuple(sorted(selected_odds_types - {"standard"}))
ALT_BADGE = {"goblin": "🟢 Goblin", "demon": "🔴 Demon"}

# ── Load data ──────────────────────────────────────────────────────────────────

with st.spinner("Loading today's picks…"):
    data = load_all_data()

games_list = data["games"]

with st.sidebar:
    st.divider()
    if len(data["confirmed"]) > 0:
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

# Build picks from in-memory data. All parameters participate in the cache
# key — an underscore prefix would silently exclude one (that bug made the
# platform filter a no-op for months).
@st.cache_data(show_spinner=False)
def load_picks_cloud(bankroll, unit_size, min_conf, platforms_key, cache_key):
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
        arsenal_data=data["arsenal"],
    )
    filtered = [p for p in all_picks if p["platform"] in platforms_key] if platforms_key else all_picks
    min_rank = TIER_RANK.get(min_conf, 1)
    return [p for p in filtered if TIER_RANK.get(p["confidence_tier"], 0) >= min_rank]

# View-only goblin/demon rows. Like load_picks_cloud, EVERY argument must
# participate in the cache key — alt_types and cache_key included — or the
# line-type control would silently freeze.
@st.cache_data(show_spinner=False)
def load_alt_lines_cloud(alt_types, cache_key):
    if not alt_types:
        return []
    return line_type_rows(
        alt_types,
        lines_data=data["lines"],
        games_data=data["games"],
        recent_batting_data=data["rec_bat"],
        recent_pitching_data=data["rec_pit"],
        pitcher_stats_data=data["pit_stats"],
        handedness_data=data["hand_db"],
        confirmed_players_data=data["confirmed"],
        arsenal_data=data["arsenal"],
    )

@st.cache_data(show_spinner=False)
def load_game_preds_cloud(cache_key):
    return predict_games(
        games_data=data["games"],
        team_stats_data=data.get("team_stats"),
        pitcher_stats_data=data["pit_stats"],
        odds_data=data.get("game_odds") or None,
    )

filtered = load_picks_cloud(bankroll, unit_size, min_conf, tuple(platforms), data["fetched_at"])
hi_pool  = [p for p in filtered if is_high_interest(p)]
best     = best_picks_per_player(filtered)
hi       = best_picks_per_player(hi_pool)
comp     = platform_comparison(hi_pool)
alt_rows = load_alt_lines_cloud(alt_odds_types, data["fetched_at"])
game_preds      = load_game_preds_cloud(data["fetched_at"])
game_pred_by_id = {str(gm["game_id"]): gm for gm in game_preds}

def render_game_markets(gm):
    """One game's model markets (moneyline / run line / totals) with book
    edges where odds are loaded."""
    st.markdown(
        f"**Model projection:** {gm['away_team']} **{gm['e_away']}** — "
        f"**{gm['e_home']}** {gm['home_team']}  ·  total **{gm['proj_total']}**"
    )
    st.dataframe(pd.DataFrame([{
        "Market":    m["market"], "Selection": m["side"],
        "Model %":   f"{m['model_prob']:.1%}",
        "Book %":    f"{m['book_prob']:.1%}" if m["book_prob"] is not None else "—",
        "Edge":      f"{m['edge']:+.1%}"     if m["edge"] is not None else "—",
        "EV/100":    f"{m['ev_100']:+.1f}"   if m["ev_100"] is not None else "—",
    } for m in gm["markets"]]), width="stretch", hide_index=True)
    if not gm["has_odds"]:
        st.caption("Model projection only — book odds unavailable "
                   "(set ODDS_API_KEY in secrets to price edges).")

def render_player_props(std_comparison, alt_view, search):
    """Player Props tab body: standard priced picks plus view-only
    goblin/demon lines, grouped by (player, canonical stat)."""
    alt_by_key = {}
    for r in alt_view:
        alt_by_key.setdefault((r["player_name"], r["stat_display"]), []).append(r)

    keys = set(std_comparison) | set(alt_by_key)
    if search:
        keys = {k for k in keys if search.lower() in k[0].lower()}

    def sort_key(k):
        std = std_comparison.get(k, [])
        return (1 if std else 0,
                len({p["platform"] for p in std}),
                max((p["edge"] for p in std), default=-1.0))

    ordered = sorted(keys, key=sort_key, reverse=True)
    if not ordered:
        st.info("No props match your search.")
        return

    for key in ordered[:60]:
        player, stat = key
        std  = sorted(std_comparison.get(key, []), key=lambda x: x["edge"], reverse=True)
        alts = sorted(alt_by_key.get(key, []),     key=lambda x: (x["odds_type"], x["line"]))
        label = f"**{player}** — {stat}" + ("  ·  view-only" if alts and not std else "")
        with st.expander(label, expanded=False):
            if std:
                st.dataframe(pd.DataFrame([{
                    "Platform": p["platform"], "Stat name": p["stat_type"],
                    "Line": f"{p['line']:g}", "Pick": p["direction"],
                    "Model %": f"{p['model_prob']:.1%}", "Edge": f"{p['edge']:+.1%}",
                    "EV/100": f"{p['ev_per_100']:+.1f}",
                    "Confidence": p["confidence_tier"], "Risk": p["risk_profile"],
                } for p in std]), width="stretch", hide_index=True)
            if alts:
                st.caption("Alt lines (view only — not EV-priced):")
                st.dataframe(pd.DataFrame([{
                    "Platform": a["platform"], "Type": ALT_BADGE.get(a["odds_type"], a["odds_type"]),
                    "Line": f"{a['line']:g}", "Pick": "More", "P(More)": f"{a['model_prob']:.1%}",
                } for a in alts]), width="stretch", hide_index=True)

# ── Shared helpers ─────────────────────────────────────────────────────────────

def picks_table(pick_list, max_rows=75, show_context=False):
    rows = []
    for p in pick_list[:max_rows]:
        row = {
            "Player":        p["player_name"],
            "Team":          to_abbr(p["player_team"]),
            "Stat":          p["stat_type"],
            "Line":          f"{p['line']:g}",
            "Pick":          p["direction"],
            "Model %":       f"{p['model_prob']:.1%}",
            "Edge":          f"{p['edge']:+.1%}",
            "EV / 100":      f"{p['ev_per_100']:+.1f}",
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

    styled = df.style.map(color_conf, subset=["Confidence"]).map(color_risk, subset=["Risk"])
    st.dataframe(styled, width="stretch", hide_index=True)


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
    stat_types   = sorted(set(p["stat_display"] for p in hi))
    sel_stats    = st.multiselect("Filter by stat:", stat_types, default=[], key="hi_stats")
    hi_filtered  = [p for p in hi if not sel_stats or p["stat_display"] in sel_stats]
    show_ctx     = st.toggle("Show season/recent/matchup context", value=False)
    picks_table(hi_filtered, show_context=show_ctx)
    st.caption(EDGE_HELP)

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
    st.caption(EDGE_HELP)

# ── Tab 3: Game Predictions ────────────────────────────────────────────────────

with tab3:
    timestamp_bar(data["fetched_at"])
    st.header("Today's Games")
    st.caption("Game markets (moneyline · run line · totals) from a team "
               "run-expectation model. Book edges show when odds are loaded.")

    game_edges = best_game_edges(game_preds)
    if game_edges:
        st.markdown("**🎯 Top game-market edges today:**")
        st.dataframe(pd.DataFrame([{
            "Game": b["matchup"], "Market": b["market"], "Pick": b["side"],
            "Model %": f"{b['model_prob']:.1%}", "Book %": f"{b['book_prob']:.1%}",
            "Edge": f"{b['edge']:+.1%}", "EV/100": f"{b['ev_100']:+.1f}",
        } for b in game_edges[:12]]), width="stretch", hide_index=True)
        st.divider()

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

                gm = game_pred_by_id.get(str(g.get("game_id", "")))
                if gm:
                    render_game_markets(gm)
                st.divider()

                game_teams = {g["home_team"], g["away_team"]}
                game_picks = [p for p in hi if to_full_name(p.get("player_team", "")) in game_teams]
                if game_picks:
                    st.markdown(f"**{len(game_picks)} high-interest picks:**")
                    rows = [{
                        "Player": p["player_name"], "Stat": p["stat_type"],
                        "Line": f"{p['line']:g}", "Pick": p["direction"],
                        "Model %": f"{p['model_prob']:.1%}", "Edge": f"{p['edge']:+.1%}",
                        "Confidence": p["confidence_tier"], "Risk": p["risk_profile"],
                        "Platform": p["platform"],
                    } for p in game_picks[:15]]
                    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
                else:
                    st.caption("No high-interest picks for this game.")

# ── Tab 4: Player Props ────────────────────────────────────────────────────────

with tab4:
    timestamp_bar(data["fetched_at"])
    st.header("Player Props — Platform Comparison")
    show_standard = "standard" in selected_odds_types
    if alt_odds_types:
        st.caption("🟢 Goblin / 🔴 Demon lines are More-only and can't be EV-priced "
                   "(PrizePicks hides their payout) — shown view-only as line + P(More).")
    search   = st.text_input("Search player name…", "")
    alt_view = [r for r in alt_rows if (not platforms or r["platform"] in platforms)]
    render_player_props(comp if show_standard else {}, alt_view, search)

# ── Tab 5: Bankroll Tracker ────────────────────────────────────────────────────

with tab5:
    timestamp_bar(data["fetched_at"])
    st.header("Bankroll Tracker")
    c1, c2 = st.columns(2)

    with c1:
        st.metric("Bankroll", f"${bankroll:,.2f}")
        st.caption(f"1 unit = ${unit_size:.0f}")
        st.divider()
        st.subheader("Recommended Stakes")
        st.caption("Quarter-Kelly sizing, as legs of a 2-pick slip.")
        rows = [{
            "Player":        p["player_name"],
            "Pick":          f"{p['stat_display']} {p['direction']} {p['line']:g}",
            "Confidence":    p["confidence_tier"],
            "Units":         f"{p.get('units', 0):.1f}u",
            "Stake ($)":     f"${p['stake_dollars']:.2f}",
            "Potential Win": f"${p['potential_win']:.2f}",
        } for p in hi[:20]]
        if rows:
            st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    with c2:
        st.subheader("PrizePicks Slip Builder")
        st.caption(
            "Select 2–6 high-interest picks to calculate slip EV. "
            "Assumes independent legs — avoid stacking picks from the same game."
        )
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
                st.metric("EV per 100",        f"${ev_val:+.2f}",
                          delta="Positive edge" if ev_val > 0 else "Negative edge",
                          delta_color="normal" if ev_val > 0 else "inverse")
        elif len(selected) == 1:
            st.info("Select at least 2 picks.")
        else:
            st.info("Select picks above to calculate slip EV.")
