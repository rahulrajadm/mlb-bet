#!/bin/bash
# MLB Bet — daily launcher
# Refreshes all data then opens the dashboard

set -e
cd "$(dirname "$0")"

echo "⚾ MLB Bet starting..."
echo ""

echo "📅 Fetching today's schedule..."
python pipeline/schedule.py

echo "📊 Fetching PrizePicks lines..."
python pipeline/prizepicks.py

echo "📊 Fetching Underdog lines..."
python pipeline/underdog.py

echo "📈 Fetching recent form (last 14 days)..."
python pipeline/recent_form.py

echo "⚾ Fetching pitcher stats..."
python pipeline/pitcher_stats.py

echo "🤜 Fetching handedness..."
python pipeline/handedness.py

echo ""
echo "✅ Data ready. Opening dashboard..."
echo ""

streamlit run ui/app.py
