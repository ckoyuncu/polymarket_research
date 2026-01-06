#!/bin/bash
# Launch agents to fix backtester issues
# Agent 1: Fix backtester to use actual ML model confidence
# Agent 2: Run backtester on larger account88888 dataset

PROJECT_DIR="/Users/shem/Desktop/polymarket_starter/polymarket_starter"

echo "Launching 2 backtest fix agents..."

# Agent 1: Fix ML Confidence in Backtester
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && echo 'TASK: Fix the compound_growth_backtester.py to use ACTUAL ML model confidence instead of the fake price-based proxy.

PROBLEM: Current backtester (scripts/compound_growth_backtester.py) lines 117-120 calculate confidence as:
  price_conf = abs(price - 0.5) * 1.5
  time_conf = (seconds_until_close / 900) * 0.3
  confidence = price_conf + time_conf
This is NOT the ML model confidence from MODEL_IMPROVEMENTS.md.

SOLUTION:
1. Load the trained model from data/models/signal_discovery_model_v2.ubj
2. Load features from data/features/*.parquet files
3. For each trade, get actual model prediction probability
4. Use abs(prediction - 0.5) * 2 as true confidence
5. Re-run backtest with proper confidence filtering

FILES TO READ:
- scripts/compound_growth_backtester.py (current broken implementation)
- scripts/reverse_engineer/signal_discovery_model_v2.py (how model is trained/used)
- MODEL_IMPROVEMENTS.md (confidence threshold analysis)
- data/models/ and data/features/ directories

OUTPUT:
- Updated scripts/compound_growth_backtester.py with ML confidence
- BACKTEST_RESULTS_ML_CONFIDENCE.md with new results' | claude --dangerously-skip-permissions"
    set custom title of front window to "Agent: Fix ML Confidence"
end tell
EOF

sleep 3

# Agent 2: Backtest on Large Dataset
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && echo 'TASK: Create a new backtester that runs on the FULL account88888 dataset (2.9M trades) for statistically significant results.

PROBLEM: Current backtester only uses 239 unique market windows from trades.db, resulting in only 12-57 trades after filtering. This sample is too small for reliable conclusions.

SOLUTION:
1. Load data/account88888_trades_joined.json (2.9M trades)
2. Parse the trades structure and extract relevant fields
3. Group by 15-minute windows
4. Calculate outcomes (did price go UP or DOWN in that window)
5. Apply position sizing strategies (fixed, kelly, quarter_kelly)
6. Run compound growth simulation with proper sample size
7. Calculate statistics: returns, drawdown, Sharpe, win rate

FILES TO READ:
- CLAUDE.md (project context)
- data/account88888_trades_joined.json (large dataset - check structure first)
- scripts/compound_growth_backtester.py (current implementation for reference)
- MARKET_CONSTRAINTS_AND_FEES.md (fee calculations)

OUTPUT:
- scripts/large_dataset_backtester.py (new backtester for 2.9M trades)
- BACKTEST_RESULTS_LARGE.md with statistically significant results
- Include: sample size, confidence intervals, statistical significance tests' | claude --dangerously-skip-permissions"
    set custom title of front window to "Agent: Large Dataset Backtest"
end tell
EOF

echo ""
echo "✅ 2 agents launched!"
echo ""
echo "Agent 1: Fix ML Confidence - Use actual model predictions"
echo "Agent 2: Large Dataset - Backtest on 2.9M trades"
echo ""
echo "Monitor progress in terminal windows."
