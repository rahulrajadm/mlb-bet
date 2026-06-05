# MLB Bet: AI-Powered MLB Betting Decision Tool

An ML-driven tool that predicts MLB player and game outcomes, compares model probabilities against live pick'em platform lines, and surfaces positive expected value (+EV) picks with confidence scores, risk profiles, and Kelly-sized stakes.

Built for Texas-legal pick'em and prediction market platforms: **PrizePicks, Underdog Fantasy, DraftKings Pick6, Chalkboard, Sleeper, Betr, Fliff, Polymarket**.

---

## Live Demo

🚀 **[bet-mlb.streamlit.app](https://bet-mlb.streamlit.app)**

---

## What it does

1. **Fetches live prop lines** from PrizePicks and Underdog Fantasy
2. **Predicts player stat outcomes** using a 5-layer model:
   - Season per-game averages (3-year recency-weighted)
   - Recent form blend (last 14 days at 55%, season at 45%)
   - Opposing pitcher matchup (K/9 vs league average)
   - Park factor adjustment (venue run environment)
   - Platoon split adjustment (batter hand vs pitcher hand)
3. **Computes edge** — model probability vs 50% implied (pick'em baseline)
4. **Ranks picks** by confidence tier (STRONG / HIGH / MEDIUM / LOW) and risk profile
5. **Sizes stakes** using fractional Kelly criterion (0.25×)
6. **Compares lines** across platforms side-by-side to find the best line for each pick

---

## Results

- Generates 900+ high-interest picks per day across PrizePicks and Underdog
- 5-layer prediction model covering season form, recent form, pitcher matchup, park factors, and platoon splits
- Slip builder calculates EV for PrizePicks Power Play entries (2–6 legs)

---

## Stack

| Layer | Tool |
|---|---|
| Player stats | `pybaseball` (Statcast, Baseball Reference) |
| Live prop lines | PrizePicks API · Underdog API |
| Schedule & lineups | MLB Stats API (official, free) |
| Odds reference | The Odds API |
| Prediction engine | Poisson distribution · XGBoost profiles |
| Dashboard | Streamlit |
| Storage (local) | SQLite |

---

## Dashboard

| Tab | What it shows |
|---|---|
| 🔥 High Interest | Picks on competitive lines (≥1.0 or More on contested 0.5 stats) |
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

### 2. Set environment variables

```bash
cp .env.example .env
```

Add your free [The Odds API](https://the-odds-api.com) key to `.env`:

```
ODDS_API_KEY=your_key_here
```

### 3. Seed historical data (one-time, ~10 min)

```bash
python pipeline/historical.py
python pipeline/handedness.py
```

### 4. Run daily

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
Base rate (season avg)
  → Blend with recent 14-day form (55% recent / 45% season)
    → Adjust for opposing pitcher K-rate vs league avg (8.8 K/9)
      → Adjust for ballpark run environment (e.g. Coors +13.5%, Petco -4.5%)
        → Adjust for platoon matchup (RHB vs LHP: +4%, same-hand: -1.8%)
          → Poisson distribution → P(stat > line)
            → Edge = P(More or Less) − 50% implied
```

**Confidence tiers** are tied to edge size:

| Tier | Edge |
|---|---|
| STRONG | > 15% |
| HIGH | 10–15% |
| MEDIUM | 5–10% |
| LOW | < 5% |

**Risk profiles** are based on stat-type variance:

| Profile | Stats |
|---|---|
| LOW | Fantasy score, Hits+Runs+RBIs |
| MEDIUM | Hits, RBIs, Strikeouts, Total Bases |
| HIGH | Home Runs, Stolen Bases, Doubles |

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
├── utils/            # SQLite helpers
├── data/models/      # Pre-trained player profiles (committed)
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
