#!/bin/bash
# Launch multiple Claude agents in parallel for strategy optimization
# Each agent runs in its own terminal window with full context

PROJECT_DIR="/Users/shem/Desktop/polymarket_starter/polymarket_starter"

echo "Launching 4 optimization agents in parallel..."

# Terminal 1: Strategy Optimizer (Kelly criterion, position sizing)
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && cat .claude/commands/strategy_optimizer.md | claude --dangerously-skip-permissions"
    set custom title of front window to "Agent 1: Strategy Optimizer"
end tell
EOF

sleep 3

# Terminal 2: Backtest & Simulation Agent
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && echo 'Read CLAUDE.md, ORDERBOOK_SIGNAL_FINDINGS.md, MODEL_IMPROVEMENTS.md, MARKET_CONSTRAINTS_AND_FEES.md. Build a compound growth backtester using data/account88888_trades_joined.json and data/tracker/trades.db. Simulate different position sizing strategies (fixed, Kelly, fractional Kelly 0.25x/0.5x) and confidence thresholds (0.4, 0.5, 0.6). Output: scripts/compound_growth_backtester.py and BACKTEST_RESULTS.md with growth curves, max drawdown, Sharpe ratio for each strategy.' | claude --dangerously-skip-permissions"
    set custom title of front window to "Agent 2: Backtester"
end tell
EOF

sleep 3

# Terminal 3: Signal Enhancement Agent
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && echo 'Read CLAUDE.md, ORDERBOOK_SIGNAL_FINDINGS.md, MODEL_IMPROVEMENTS.md. Analyze if we can improve signal quality or find additional signals. Look at scripts/reverse_engineer/*.py for existing analysis. Focus on: 1) Can we combine orderbook + momentum + ML model for higher accuracy? 2) Are there time-of-day effects? 3) Can we detect regime changes? Output: SIGNAL_ENHANCEMENT_REPORT.md with findings and updated signal logic if improvements found.' | claude --dangerously-skip-permissions"
    set custom title of front window to "Agent 3: Signal Enhancer"
end tell
EOF

sleep 3

# Terminal 4: Fee Optimization & Execution Agent
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && echo 'Read CLAUDE.md, MARKET_CONSTRAINTS_AND_FEES.md, src/trading/executor.py, src/trading/live_bot.py. Optimize for maximum profit by: 1) Analyze if maker orders (0% fee + rebates) are feasible vs taker orders (0-3% fee) 2) Calculate optimal entry timing within 15-min windows 3) Model fee impact on compound growth 4) Recommend execution strategy. Output: EXECUTION_OPTIMIZATION.md and update executor.py if improvements found.' | claude --dangerously-skip-permissions"
    set custom title of front window to "Agent 4: Execution Optimizer"
end tell
EOF

echo ""
echo "✅ All 4 agents launched!"
echo ""
echo "Agent 1: Strategy Optimizer - Kelly criterion, position sizing"
echo "Agent 2: Backtester - Compound growth simulation"
echo "Agent 3: Signal Enhancer - Improve signal accuracy"
echo "Agent 4: Execution Optimizer - Fee/timing optimization"
echo ""
echo "Monitor progress in each terminal window."
echo "Results will be written to project directory."
