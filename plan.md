# MLB Bet: AI-Powered MLB Betting Decision Tool

A local, zero-cost tool that predicts MLB game outcomes and player performance, then recommends the best bet and platform across the Texas-legal platforms you have access to — with confidence scores and risk-reward analysis on every pick.

---

## Texas Context

Traditional sports betting is not legal in Texas. All platforms below are legal alternatives:

| Platform | Type | How it works |
|---|---|---|
| **PrizePicks** | Pick'em DFS | Pick More/Less on 2–6 player props; fixed multipliers |
| **Underdog Fantasy** | Pick'em DFS | Higher/Lower on 2–5 props; up to 20x; insurance on 4–5 picks |
| **DraftKings Pick6** | Pick'em DFS | More/Less on 2+ props; peer-to-peer contests |
| **Chalkboard** | Pick'em DFS | More/Less props; Shield Play allows misses |
| **Sleeper** | Pick'em / Prediction | More/Less props + prediction markets (launched Feb 2026) |
| **Betr** | Pick'em DFS | More/Less props (Betr Picks available in TX; Betr Sportsbook is not) |
| **Fliff** | Sweepstakes | Traditional-style odds (moneyline, spread, totals, props) with virtual currency redeemable for cash |
| **DraftKings Predictions** | Prediction market | Yes/No event contracts; price = implied probability; CFTC-regulated |
| **Polymarket** | Prediction market | Yes/No contracts on MLB outcomes; full public API; price = implied prob |

---

## Output Per Pick

Every pick the tool surfaces includes:

| Field | Description |
|---|---|
| **Selection** | Explicit pick: "Gerrit Cole K > 7.5", "NYY to win", "Over 8.5 runs" |
| **Best platform** | Which of your platforms has the most favorable line for this pick |
| **Platform comparison** | Side-by-side lines across all relevant platforms |
| **Model prediction** | What the model thinks will happen (e.g., Cole projects for 8.2 Ks) |
| **Model probability** | Probability the pick hits (e.g., 64%) |
| **Implied probability** | What the platform's line/price implies (e.g., 52%) |
| **Edge** | Model prob − implied prob (e.g., +12%) |
| **Expected Value** | EV per $100 wagered or per entry unit |
| **Confidence tier** | STRONG / HIGH / MEDIUM / LOW |
| **Risk profile** | LOW / MEDIUM / HIGH based on variance and bet type |
| **Kelly stake** | Recommended % of bankroll for this pick |
| **Risk-reward ratio** | Potential payout vs downside at that stake |

### Confidence Tiers

| Tier | Edge | Notes |
|---|---|---|
| STRONG | > 12% | Model historically accurate > 70% in this prob range |
| HIGH | 8–12% | Model accurate 60–70% |
| MEDIUM | 4–8% | Model accurate 55–60% |
| LOW | < 4% | Shown but not recommended |

### Risk Profiles

| Profile | Bet type |
|---|---|
| LOW | Moneyline/game picks on strong favorites; prediction market near-certainties |
| MEDIUM | Totals, run line, mainstream player props (hits, RBIs) |
| HIGH | Multi-leg pick'em slips, pitcher props, underdog predictions |

---

## Platform-Specific EV Logic

Each platform type has a different payout structure — EV is calculated correctly for each:

### Pick'em Platforms (PrizePicks, Underdog, DK Pick6, Chalkboard, Betr Picks, Sleeper)
- Model predicts the player's actual stat value
- Compare to platform's prop line (More/Less threshold)
- EV based on fixed multiplier for that platform and slip size
- **PrizePicks Power Play multipliers:** 2-pick=3x, 3-pick=5x, 4-pick=10x, 5-pick=20x, 6-pick=25x
- **Underdog:** up to 20x; insurance on 4–5 pick entries
- Line comparison: find which platform sets the most favorable line for a given prop

### Sweepstakes (Fliff)
- Traditional American odds → implied probability → EV same as a sportsbook

### Prediction Markets (Polymarket, DraftKings Predictions)
- Market price (e.g., 0.62) = implied probability (62%)
- EV = (model_prob × $1) − price per share
- Polymarket has a full public API — easiest data source

---

## Data Sources

| Source | Data | Access |
|---|---|---|
| `pybaseball` | Historical Statcast, game logs, FanGraphs | Free Python library |
| MLB Stats API | Today's schedule, lineups, starting pitchers | Free, no key |
| PrizePicks API | Live prop lines (unofficial JSON endpoint) | Free, no auth |
| Underdog API | Live prop lines | GitHub scraper (aidanhall21/underdog-fantasy-pickem-scraper) |
| Polymarket API | MLB prediction market prices | Official free public API, no auth |
| DK Predictions | MLB event contracts | Scrape / Apify |
| Fliff | Odds | Mobile scrape (best effort) |
| Chalkboard / Sleeper / Betr | Prop lines | Best-effort scrape |

---

## Project Structure

```
mlb-bet/
├── plan.md
├── .env.example              # POLYMARKET_API_KEY (optional), others if needed
├── requirements.txt
├── data/
│   └── mlb_bet.db            # SQLite: stats, lines, picks, model outputs
├── pipeline/
│   ├── historical.py         # pybaseball: 3–5 seasons of game logs + Statcast
│   ├── schedule.py           # MLB Stats API: today's schedule + lineups
│   ├── prizepicks.py         # PrizePicks prop lines (JSON endpoint)
│   ├── underdog.py           # Underdog prop lines (GitHub scraper)
│   ├── polymarket.py         # Polymarket MLB markets (official API)
│   └── sweepstakes.py        # Fliff + other platforms (best-effort scrape)
├── models/
│   ├── train.py              # Feature engineering + train/eval all models
│   ├── moneyline.py          # Win/loss classifier (for Fliff, Polymarket)
│   ├── totals.py             # Over/under classifier (for Fliff, pick'em totals)
│   └── props.py              # Per-player stat regressors (primary model — feeds all pick'em)
├── analysis/
│   ├── ev.py                 # EV logic per platform type (pick'em multipliers, prediction market prices, odds)
│   ├── confidence.py         # Tier assignment from edge + calibration
│   ├── risk.py               # Risk profile from bet type + variance
│   └── kelly.py              # Fractional Kelly (0.25×) stake sizing
├── picks/
│   └── engine.py             # Assembles analysis → structured pick objects; ranks by EV; tags best platform
├── ui/
│   └── app.py                # Streamlit dashboard
└── utils/
    └── db.py                 # SQLite schema + helpers
```

---

## Build Order

### Phase 1 — Data Pipeline
- [ ] `utils/db.py` — SQLite schema: games, player_stats, prop_lines, predictions, picks tables
- [ ] `pipeline/historical.py` — pull 3–5 seasons of game logs + Statcast via pybaseball
- [ ] `pipeline/schedule.py` — today's schedule + starting lineups from MLB Stats API
- [ ] `pipeline/prizepicks.py` — pull today's MLB prop lines from PrizePicks JSON endpoint
- [ ] `pipeline/underdog.py` — pull today's MLB prop lines from Underdog
- [ ] `pipeline/polymarket.py` — pull active MLB markets from Polymarket public API
- [ ] `pipeline/sweepstakes.py` — best-effort pull from Fliff and other platforms

### Phase 2 — Models
- [ ] `models/train.py` — feature engineering + train/eval all models; serialize to disk
- [ ] `models/props.py` — **primary model**: per-player XGBoost regressors predicting actual stat values (Ks, hits, total bases, HR, RBI) using Statcast features (K%, barrel rate, hard hit %, wOBA, opposing pitcher ERA)
- [ ] `models/moneyline.py` — team win classifier (for Fliff odds + Polymarket game picks)
- [ ] `models/totals.py` — total runs classifier (for Fliff totals + pick'em run totals)

### Phase 3 — Analysis Engine
- [ ] `analysis/ev.py` — EV calculation per platform type; pick'em uses multiplier table; prediction markets use price; Fliff uses American odds
- [ ] `analysis/confidence.py` — assign tier from edge + model calibration curve
- [ ] `analysis/risk.py` — assign risk profile per bet type
- [ ] `analysis/kelly.py` — fractional Kelly stake as % of bankroll
- [ ] `picks/engine.py` — assemble all picks; cross-platform line comparison; tag best platform per pick; rank by EV; filter to +EV

### Phase 4 — UI
- [ ] `ui/app.py` — Streamlit dashboard:
  - **Today's Picks** — ranked +EV picks: selection, best platform, confidence badge, risk badge, EV, Kelly stake
  - **Player Props** — all player prop predictions vs each platform's line; best platform highlighted
  - **Game Predictions** — moneyline/totals model output vs Fliff odds + Polymarket prices
  - **Platform Comparison** — full grid: same prop across PrizePicks / Underdog / DK Pick6 / Chalkboard / Sleeper
  - **Bankroll Tracker** — enter bankroll, see dollar amounts for Kelly stakes
  - Color-coding: green = STRONG/HIGH confidence, yellow = MEDIUM, gray = LOW

### Phase 5 — Polish
- [ ] `.env.example` + setup instructions
- [ ] One-command run: `streamlit run ui/app.py`
- [ ] Daily data refresh script
- [ ] Model recalibration (weekly)
- [ ] Slip builder: auto-generate optimal multi-pick PrizePicks/Underdog slips from top props

---

## Key Design Decisions

- **Props model is the core** — since most of your platforms are pick'em, predicting actual player stat values is more important than game outcomes. The props model feeds every pick'em platform.
- **Platform comparison built-in** — the same Gerrit Cole strikeout line might be 7.5 on PrizePicks and 8.5 on Underdog; the tool finds which gives you more edge.
- **Polymarket is the easiest integration** — full public API, no auth, real-time prices. Best data source for game outcome probabilities.
- **PrizePicks + Underdog are the priority pick'em sources** — both have accessible APIs/scrapers and are the largest platforms you're on.
- **Fractional Kelly (0.25×)** — standard sharp practice; full Kelly is too aggressive for variance inherent in props.
- **Confidence from calibration, not just edge** — tiers are pegged to historical model accuracy at each probability range.
- **Risk is separate from confidence** — a high-confidence prop can still be high-risk (props are volatile); both dimensions shown.

---

## Setup (after build)

```bash
cd mlb-bet
pip install -r requirements.txt
python pipeline/historical.py     # one-time: pull historical data (~10–15 min)
python models/train.py            # one-time: train all models (~5 min)
streamlit run ui/app.py           # daily: run dashboard, get today's picks
```

---

## Built by

Rahul Raja Durai Murugan
BS Biomedical Engineering, UT Austin · MS Engineering Data Science & AI, University of Houston (incoming)
