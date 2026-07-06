# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MLB player-prop pick'em tool: a 5-layer heuristic prediction (recency-weighted season profiles → 14-day form blend → opposing-pitcher matchup + arsenal → park factor → platoon split) feeds a Poisson distribution to get P(stat > line) for live PrizePicks/Underdog lines, then surfaces +EV picks with confidence tiers, risk profiles, and quarter-Kelly stakes. Deployed at https://bet-mlb.streamlit.app.

There are **no trained ML models**: `data/models/*.pkl` are joblib-pickled pandas DataFrames of per-game rates (season-weighted 2024/25/26 at 0.15/0.30/0.55). There are also no game-outcome predictions — the "Game Predictions" tab shows the schedule plus that game's player-prop picks. `plan.md` is the original design doc; large parts of it (moneyline/totals models, Fliff, DK Pick6, Polymarket) were never built.

## Commands

```bash
# One-time local setup
pip install -r requirements.txt
cp .env.example .env                  # ODDS_API_KEY (only used by pipeline/odds_api.py, currently unused)
python pipeline/historical.py         # (re)seed data/mlb_bet.db from pybaseball (~10 min; tables are rebuilt, safe to re-run mid-season)
python models/train.py                # build batter/pitcher profile .pkl files (committed in data/models/)
python pipeline/handedness.py         # batter/pitcher handedness (needs batter_game_logs from the seeding step)

# Daily local run (refreshes SQLite from free sources, then opens the dashboard)
./start.sh

# Run the local dashboard directly
streamlit run ui/app.py

# There is no test suite. Modules have __main__ smoke blocks — run them directly:
python models/props.py                # prop predictions from local DB
python picks/engine.py                # full pick build from local DB
python pipeline/prizepicks.py         # live PrizePicks fetch (free) + saves to SQLite
```

`predict_props` prints filter diagnostics to stderr (`[props] lines=... non_standard=... unmodeled=... no_stat=... passed=...` plus `unknown_stat_types`); **check these after any change to stat mapping or filters** — an unmapped stat name means silently skipped lines.

## Two entry points, two data paths

- **`ui/app_cloud.py`** — the deployed app (Streamlit Community Cloud). No SQLite for live data: everything is fetched in-memory inside `load_all_data()` (`st.cache_data`, no TTL — deliberate) and only refetched when someone enters the passcode (`REFRESH_CODE` in `st.secrets`) and hits Refresh, which calls `st.cache_data.clear()`.
- **`ui/app.py`** — local dashboard backed by SQLite (`data/mlb_bet.db`), populated by the `pipeline/*.py` scripts that `start.sh` runs.

Because of this split, `predict_props()` and `build_picks()` take optional in-memory kwargs (`lines_data`, `games_data`, `recent_batting_data`, `recent_pitching_data`, `pitcher_stats_data`, `handedness_data`, `confirmed_players_data`, `arsenal_data`) and fall back to SQLite when `None`. **Preserve this convention when changing signatures — a change that only handles one path silently breaks the other app.** The committed profile `.pkl` files are the only pre-baked data the cloud app has; handedness on cloud comes from `fetch_lineup_handedness()` (MLB API), so the platoon layer only activates there once lineups post.

In `app_cloud.py`'s `load_picks_cloud`, **every parameter must participate in the `st.cache_data` key** — a leading underscore excludes a param from hashing, which once made the platform filter a silent no-op.

Deployment = push to `main`; Streamlit Cloud auto-redeploys. Secrets on cloud: `REFRESH_CODE` only.

## Data sources and costs

- **The Odds API** (`ODDS_API_KEY` in `.env`): the **only metered source** (~500 free credits/month). Touched only by `pipeline/odds_api.py` — one `get_all_odds()` = 3 requests. **Nothing in the app calls it anymore** (the odds it saves were never consumed); it's kept as a standalone script for future game-market work. **Never trigger it without asking the user first.**
- **PrizePicks / Underdog**: free unofficial JSON endpoints, no auth. Underdog team UUIDs are resolved to abbreviations via `stats.underdogfantasy.com/v1/teams` at fetch time.
- **MLB Stats API** (`statsapi.mlb.com`): schedule, probable starters, confirmed lineups, handedness. Official, free, no key.
- **pybaseball** (Baseball-Reference / Statcast scrapes): seeding, 14-day recent form, season pitcher stats, arsenal whiff rates. Free but rate-limited scraping — slow, and **B-Ref names arrive mojibake'd** (see name matching below).
- **Polymarket** (`pipeline/polymarket.py`): free public API, standalone script, not wired into either UI.

## Prediction pipeline (the big picture)

```
prop lines (PrizePicks/Underdog)   schedule+lineups (MLB API)   profiles (.pkl) + SQLite/in-memory form
              │                              │                                 │
              └──────────► models/props.py: predict_props() ◄─────────────────┘
                    5 layers → Poisson → pick More/Less, edge vs break-even
                             │
                    picks/engine.py: build_picks()
                    filters (MIN_EDGE=0.04, prob∈[0.10,0.90], platform-realistic)
                    + EV/confidence/risk/Kelly from analysis/
```

Key conventions — read these before touching probabilities:

1. **Edges are measured against the pick'em break-even, never 0.50.** `analysis/ev.py:breakeven_prob` gives the per-leg break-even for the baseline 2-pick 3x slip: (1/3)^(1/2) ≈ 0.5774. `implied_prob` on every prediction is this break-even. "EV / 100" is per-leg edge ×100 (a display convention), while `ev_slip` does real multiplier math for the slip builder.
2. **Everything is per-game rates + Poisson.** `prob_more_less()` handles x.5 lines as P(X ≥ ceil(line)) and whole-number lines as push-conditioned probabilities (P(X = line) is a refund, not a win or loss).
3. **Only `odds_type == "standard"` lines are priced.** PrizePicks goblins/demons are More-only with different payouts our EV math can't price; they're fetched and stored but skipped with a diagnostics counter. Payout tables in `ev.py` were verified Jul 2026 (PP 3-pick is 6x, 6-pick 37.5x) — re-verify if slips look mispriced.
4. **Pitcher props are strikeouts only** (`PITCHER_PROP_STATS` = PP "Pitcher Strikeouts", UD "Strikeouts"), priced off blended K-per-start × arsenal whiff adjustment. Every other pitcher stat (ER, hits allowed, pitch count, outs) is in `UNMODELED_STATS` — **do not** route them through the K path; that once made "More earned runs allowed on a good pitcher" the app's #1 pick.
5. **Kelly** sizes each leg as a 2-pick slip: the Kelly input is `model_prob ** 2` at 3x (analysis/kelly.py), quarter-Kelly, capped at 10% of bankroll. Sizing a leg as a standalone 3x bet at the leg probability produces 20%+ stakes — don't regress to it.
6. **Lineup filter**: once MLB lineups post, only confirmed batters get batter-prop predictions; probable pitchers are included in the confirmed set and pitcher props are additionally exempt (lineups list batters only).
7. Multi-player combo props ("Robbie Ray + Edward Cabrera", team "SF/CHC") are intentionally skipped via `UNMODELED_STATS` / unmapped teams.

## Stat, team, and player-name sync (easy to break)

- **Stat names**: a platform stat must appear in `STAT_MAP` (models/props.py) or the line is skipped (counted in `unknown_stat_types`). A new stat needs updates in **three places together**: `STAT_MAP` (+ `STAT_DISPLAY` + `RECENT_COL_MAP` for batter stats), the variance sets in `analysis/risk.py`, and `NO_LESS_AT_HALF` in `picks/engine.py` if it's a rare-event stat. Platforms spell the same stat differently (PP "Walks" / UD "Batter Walks"; PP "Hits+Runs+RBIs" / UD "Hits + Runs + RBIs") — both spellings must be present everywhere. Cross-platform dedupe and the comparison tab key on `stat_key`/`stat_display` (the canonical form), never the raw platform spelling.
- **Deliberately unmodeled stats** live in `UNMODELED_STATS` — fantasy scores (no rate column, not Poisson), non-K pitcher stats, combos, 1st-inning exotics. Add there rather than letting a stat fall into `unknown_stat_types` if the skip is intentional.
- **Team identity**: MLB Stats API uses full names, PrizePicks abbreviations, Underdog UUIDs (resolved to abbreviations at fetch). All lookups (opponent starter, venue, game grouping) convert via `pipeline/team_names.py:to_full_name()` — exact dict mapping, no substring matching. An unmapped abbreviation means no matchup/park/platoon adjustment and the pick missing from its game card; add it to `TEAM_ABBR_TO_NAME`.
- **Player names**: all matching goes through `utils/names.py` — `clean_name` repairs B-Ref mojibake, `normalize_name` strips accents/suffixes ("Fernando Tatis Jr." ≡ "fernando tatis"), and `make_lookup` refuses ambiguous last-name fallbacks instead of blending two players. Never match names with raw `.str.contains` — "Jr." names match the wrong player.
- **Park factors** (`pipeline/park_factors.py`) are keyed by venue name exactly as the MLB Stats API returns it; stadium renames (Daikin Park, Rate Field, UNIQLO Field at Dodger Stadium…) silently become league-average until added.
- **Dates**: "today" is always US Central via `utils/dates.py` (`today_str`, `local_day_utc_bounds`). Naive `date.today()` / SQLite `DATE('now')` are UTC-relative and roll to tomorrow at 7pm CDT — exactly when games start. Prop-line filtering uses UTC bounds of the Central day.

## Known modeling caveats (deliberate, deferred)

- "EV / 100" is per-leg edge ×100, not payout-weighted slip EV; the slip builder (`ev_slip`) assumes independent legs, so same-game stacks are mispriced.
- Kelly's 2-pick pairing assumes the other leg is equally strong and independent.
- The arsenal whiff adjustment multiplies a K/GS blend that already reflects the pitcher's whiff ability — mild double counting, dampened for the batter path (0.3×).
- Underdog's payout table beyond 5 picks is unverified; UD non-standard payout variants aren't fetched.
- Season profiles refresh only when `pipeline/historical.py` + `models/train.py` are re-run; mid-season the current year's rows are partial-season aggregates.
