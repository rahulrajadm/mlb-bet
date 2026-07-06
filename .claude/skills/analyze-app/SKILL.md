---
name: analyze-app
description: Full review of the MLB-bet app — launch and drive both dashboards in a browser, check UI consistency between the local and cloud apps, verify the prediction math end to end, and audit security. Use when the user asks to analyze, review, or audit the app.
---

Analyze the entire MLB-bet Streamlit app: launch the web application, check for UI
consistencies, analyze code to ensure accurate analysis and predictions, and ensure
security is maintained. Read CLAUDE.md first — it documents the two-entry-point split
and the conventions referenced below.

## 1. Launch and drive (not just start)

- **Local app**: `streamlit run ui/app.py --server.port 8599 --server.headless true`
  in the background, then drive it with the Playwright browser tools. If prop lines
  are stale (the CT freshness banner shows it), re-fetch first:
  `python pipeline/prizepicks.py && python pipeline/underdog.py` (free, no auth).
  All refresh sources are free — but pybaseball steps (recent form, pitcher stats)
  are slow rate-limited scrapes, so don't hammer "Refresh All Data" repeatedly.
  Never run `pipeline/odds_api.py` — the only metered source (~500 credits/month),
  standalone, not called by either app.
- **Cloud app** (what production runs): `printf 'REFRESH_CODE = "0000"\n' >
  .streamlit/secrets.toml`, run `ui/app_cloud.py` on port 8600, exercise the
  passcode refresh through the browser with 0000 (free, just slow), and **delete
  `.streamlit/secrets.toml` when done**. Everything live is fetched in-memory in
  `load_all_data()` (`st.cache_data`, no TTL — deliberate); the committed profile
  `.pkl`s are the only pre-baked data it has.
- Click through **all five tabs** (High Interest, Today's Picks, Game Predictions,
  Player Props, Bankroll Tracker) in each app with real data, at desktop (1440px)
  and phone (390px) widths. Exercise the Player Props search box and the platform
  filter (the filter was once a silent no-op — see the cache-key rule below).
- Streamlit servers cache Python modules: after editing shared code, restart the
  server and clear `__pycache__` before re-testing.

## 2. UI consistency

- `ui/app.py` and `ui/app_cloud.py` duplicate display code on purpose. Diff them
  tab-by-tab: same columns and header names, badges, edge coloring, empty states.
  Divergence is a finding unless it's a documented platform difference (passcode
  refresh + last-updated timestamp are cloud-only; sidebar Refresh All Data +
  lineup-status indicator are local-only).
- In `app_cloud.py`'s `load_picks_cloud`, **every parameter must participate in the
  `st.cache_data` key** — a leading underscore excludes a param from hashing and
  silently freezes that control.
- No table may clip columns off-screen at 1440px; metric rows must wrap on mobile.
- The CT timestamp banner must reflect real fetch times on every tab.
- The Game Predictions tab shows schedule + that game's prop picks (there are **no
  game-outcome predictions** — anything implying a moneyline/total model is a bug).
  A game card missing its picks usually means an unmapped team abbreviation.

## 3. Prediction accuracy

- Trace displayed numbers to the pipeline: spot-check one batter prop by hand
  through all 5 layers (season profile rate → 14-day form blend → opposing-pitcher
  k_adj + arsenal → park factor → platoon split → `prob_more_less` Poisson → edge
  vs break-even) and one pitcher-strikeout prop (blended K-per-start × whiff adj).
- Edges are measured against the pick'em break-even (`analysis/ev.py:breakeven_prob`
  ≈ 0.5774 for the 2-pick 3x baseline), **never 0.50**. Whole-number lines must be
  push-conditioned (P(X = line) is a refund). Only `odds_type == "standard"` lines
  are priced — goblins/demons are skipped, not mispriced.
- Pitcher props are strikeouts only; every other pitcher stat must sit in
  `UNMODELED_STATS`, never route through the K path (that once made "More earned
  runs on a good pitcher" the app's #1 pick).
- Run the smoke blocks (`python models/props.py`, `python picks/engine.py`) and read
  the `[props]` stderr counters (`lines / non_standard / unmodeled / no_stat /
  not_confirmed / no_profile / no_edge / passed`) — a jump in `no_stat` or any
  `unknown_stat_types` entry means a stat mapping broke.
- Check the three-place stat-name sync: `STAT_MAP` (+ `STAT_DISPLAY` +
  `RECENT_COL_MAP`) in models/props.py, the variance sets in `analysis/risk.py`,
  and `NO_LESS_AT_HALF` in picks/engine.py — with **both** PP and UD spellings of
  each stat. Verify `pipeline/team_names.py:TEAM_ABBR_TO_NAME` covers every abbr in
  live line data, and park-factor venue keys match current MLB API stadium names.
- Player-name matching must go through `utils/names.py` (never raw
  `.str.contains`); "today" must come from `utils/dates.py` (naive dates roll to
  tomorrow at 7pm CDT, exactly when games start).
- Both data paths must behave identically: SQLite fallback vs in-memory kwargs
  (a change that only handles one path silently breaks the other app). Once lineups
  post, only confirmed batters get batter props; pitcher props are exempt.
- Known deferred caveats are NOT findings: "EV / 100" is per-leg edge ×100 (not
  slip EV), `ev_slip` assumes independent legs, Kelly assumes an equally strong
  2-pick pairing, the arsenal whiff adjustment mildly double-counts, UD payouts
  beyond 5 picks are unverified, and mid-season profiles are partial-year.

## 4. Security

- Secrets: `.env`, `.streamlit/secrets.toml`, and `data/mlb_bet.db` stay gitignored
  and uncommitted; `git log` must be free of keys; `ODDS_API_KEY` must never appear
  in the UI, error states, or tracebacks (check `st.exception` paths).
- The deployed app is public: every visitor action must stay free (true today —
  no metered source is wired in; a finding if that changes) and the refresh
  passcode must be compared against `st.secrets["REFRESH_CODE"]`, never a literal.
  Unlimited passcode-less refresh would also let visitors hammer the free APIs.
- Free-text inputs (player search box) must not reach SQL, eval, or shell — and
  user-typed content must not be interpolated into unescaped HTML
  (`unsafe_allow_html=True` blocks take only app-generated values).
- SQL must be parameterized (`?` placeholders) anywhere user- or platform-derived
  strings meet the database.

## Report format

Lead with a verdict, then findings ranked by severity (crash/money-losing → wrong
numbers → UX → nits), each with file:line and a concrete failure scenario. Fixes only
if asked — this command is a review, not a repair. End by restoring state: stop test
servers you started, delete the temp secrets file, and leave the repo tree clean.
