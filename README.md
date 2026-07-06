# MLB Bet: AI-Powered MLB Betting Decision Tool

A tool that projects MLB player stat outcomes, compares model probabilities against live pick'em platform lines, and surfaces positive expected value (+EV) picks with confidence scores, risk profiles, and Kelly-sized stakes.

Built for Texas-legal pick'em platforms: **PrizePicks** and **Underdog Fantasy**.

---

## Live Demo

🚀 **[bet-mlb.streamlit.app](https://bet-mlb.streamlit.app)**

---

## What it does

1. **Fetches live prop lines** from PrizePicks and Underdog Fantasy (standard lines only — goblins/demons change the payout and are excluded)
2. **Predicts player stat outcomes** using a 5-layer model:
   - Season per-game averages (3-year recency-weighted)
   - Recent form blend (last 14 days at 55%, season at 45%)
   - Opposing pitcher matchup (K-rate + arsenal whiff rate vs league average)
   - Park factor adjustment (venue run environment)
   - Platoon split adjustment (batter hand vs pitcher hand)
3. **Computes edge** — model probability vs the real pick'em break-even (~57.7% per leg for a 2-pick 3x slip), not a 50% coin flip
4. **Ranks picks** by confidence tier (STRONG / HIGH / MEDIUM / LOW) and risk profile
5. **Sizes stakes** using fractional Kelly (0.25×) on the 2-pick slip probability
6. **Compares lines** across platforms side-by-side to find the best line for each pick

---

## Stack

| Layer | Tool |
|---|---|
| Player stats | `pybaseball` (Statcast, Baseball Reference) |
| Live prop lines | PrizePicks API · Underdog API |
| Schedule & lineups | MLB Stats API (official, free) |
| Prediction engine | Recency-weighted rate profiles → Poisson distribution |
| Dashboard | Streamlit |
| Storage (local) | SQLite |

---

## Dashboard

| Tab | What it shows |
|---|---|
| 🔥 High Interest | Picks on competitive lines (≥1.0, or More on contested 0.5 stats) |
| 🎯 Today's Picks | All +EV picks |
| ⚾ Game Predictions | Per-game breakdown with picks for each matchup |
| 📊 Player Props | Same prop across PrizePicks vs Underdog side-by-side |
| 💰 Bankroll Tracker | Quarter-Kelly stakes in units + PrizePicks slip builder |

---

## Local Setup

### 1. Clone and install

```bash
git clone https://github.com/rahulrajadm/mlb-bet.git
cd mlb-bet
pip install -r requirements.txt
```

### 2. Seed historical data (one-time, ~10 min)

```bash
python pipeline/historical.py
python models/train.py
python pipeline/handedness.py
```

### 3. Run daily

```bash
./start.sh
```

Or with the alias (add to `.zshrc`):

```bash
alias mlb-bet="/path/to/mlb-bet/start.sh"
```

---

## How the model works

Each player prop prediction is built in 5 layers:

```
Base rate (season avg, recency-weighted over 2024–26)
  → Blend with recent 14-day form (55% recent / 45% season)
    → Adjust for opposing pitcher K-rate & arsenal whiff rate
      → Adjust for ballpark run environment (e.g. Coors +13.5%)
        → Adjust for platoon matchup (batter hand vs pitcher hand)
          → Poisson distribution → P(stat > line)
            → Edge = P(pick side) − 57.7% break-even (2-pick 3x)
```

Pitcher props are strikeouts only — other pitcher stats (earned runs,
pitch count, outs) have no per-game rate model and are skipped rather
than mispriced.

**Confidence tiers** are tied to edge size (vs break-even):

| Tier | Edge |
|---|---|
| STRONG | > 12% |
| HIGH | 8–12% |
| MEDIUM | 4–8% |
| LOW | < 4% |

**Risk profiles** are based on stat-type variance:

| Profile | Stats |
|---|---|
| LOW | Hits, Hits+Runs+RBIs |
| MEDIUM | Walks, Strikeouts, RBIs, Runs, Total Bases |
| HIGH | Home Runs, Stolen Bases, Singles, Doubles |

---

## Project Structure

```
mlb-bet/
├── pipeline/         # Data ingestion (PrizePicks, Underdog, MLB API, recent form, etc.)
├── models/           # Player profile training + prop prediction engine
├── analysis/         # EV, confidence, risk, Kelly calculation
├── picks/            # Pick assembly, filtering, and ranking engine
├── ui/
│   ├── app.py        # Local Streamlit dashboard (uses SQLite)
│   └── app_cloud.py  # Cloud Streamlit dashboard (in-memory, no SQLite)
├── utils/            # SQLite, date, and name-matching helpers
├── data/models/      # Pre-built player rate profiles (committed)
└── start.sh          # Daily launcher script
```

---

## Built by

**Rahul Raja Durai Murugan**

BS Biomedical Engineering, UT Austin · MS Engineering Data Science & AI, University of Houston (incoming)

[LinkedIn](https://linkedin.com/in/rahulrajadm) · [GitHub](https://github.com/rahulrajadm) · rahulrdm13@gmail.com

---

## Disclaimer

This tool is for informational and educational purposes. It is designed for legal pick'em DFS platforms. Always gamble responsibly.
