#!/bin/bash
# Launch 3 agents to find profitable Polymarket wallets
# Applies learnings from Account88888 analysis

PROJECT_DIR="/Users/shem/Desktop/polymarket_starter/polymarket_starter"

echo "=============================================="
echo "LAUNCHING WALLET DISCOVERY AGENTS"
echo "=============================================="
echo ""
echo "Key learnings applied:"
echo "- Full sample sizes only (not small samples)"
echo "- Edge vs market odds (not raw win rate)"
echo "- Account for 3% taker fees"
echo "- Statistical significance required"
echo ""

# Agent 1: Wallet Discovery - Find high-volume wallets
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && cat << 'PROMPT' | claude --dangerously-skip-permissions
TASK: Find high-volume Polymarket wallets to analyze for edge

CONTEXT:
- We analyzed Account88888 (2.9M trades) and found they have +0.85% edge but lose to 3% fees
- Small sample sizes (45-113 trades) gave misleading 84% win rate claims
- We need wallets with LARGE trade counts for statistical validity

YOUR JOB:
1. Research how to find top Polymarket traders:
   - Check Dune Analytics for Polymarket leaderboards
   - Check Polymarket API documentation in src/api/gamma.py
   - Look for existing wallet lists in the repo
   - Search for Polymarket whale trackers online

2. Create a list of 20-50 wallets to analyze:
   - Must have >10,000 trades (for statistical significance)
   - Focus on 15-minute up/down markets
   - Include wallet address and any known info

3. Output: Create data/wallets_to_analyze.json with format:
   [
     {\"wallet\": \"0x...\", \"name\": \"whale_1\", \"source\": \"dune\", \"estimated_trades\": 50000},
     ...
   ]

FILES TO READ:
- CLAUDE.md (project context and learnings)
- STRATEGY_REEVALUATION.md (why Account88888 failed)
- src/api/gamma.py (Polymarket API)
- scripts/batch_wallet_extractor.py (how we extract data)

DO NOT:
- Include wallets with <10,000 trades
- Assume any wallet is profitable without full analysis
- Use small sample sizes

OUTPUT: data/wallets_to_analyze.json + WALLET_DISCOVERY_REPORT.md
PROMPT"
    set custom title of front window to "Agent 1: Wallet Discovery"
end tell
EOF

sleep 3

# Agent 2: Data Extraction Pipeline - Set up extraction for found wallets
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && cat << 'PROMPT' | claude --dangerously-skip-permissions
TASK: Build robust wallet data extraction pipeline

CONTEXT:
- We have scripts/batch_wallet_extractor.py that extracts trades via Etherscan
- Need to extract FULL trade history for wallets (not samples)
- Data must include: wallet, side, price, token_id, timestamp, usdc_amount

YOUR JOB:
1. Review and improve the extraction pipeline:
   - Read scripts/batch_wallet_extractor.py
   - Ensure it handles rate limits properly
   - Add progress tracking for long extractions

2. Create extraction orchestration:
   - Script to run extraction on EC2 (long-running)
   - Resume capability for interrupted extractions
   - Parallel extraction if API allows

3. Create analysis-ready data format:
   - Join trades with market outcomes (like we did for Account88888)
   - Map token_id to market resolution (UP/DOWN)
   - Calculate per-trade P&L

FILES TO READ:
- CLAUDE.md (project context)
- scripts/batch_wallet_extractor.py (existing extractor)
- scripts/data_pipeline/join_transfers_to_trades.py
- data/token_to_market.json (market mappings)

OUTPUT:
- scripts/robust_wallet_extractor.py (improved extractor)
- scripts/prepare_wallet_analysis.py (join with outcomes)
- EXTRACTION_PIPELINE_README.md
PROMPT"
    set custom title of front window to "Agent 2: Data Pipeline"
end tell
EOF

sleep 3

# Agent 3: Profitability Analysis Framework - Create rigorous analysis
osascript <<EOF
tell application "Terminal"
    do script "cd $PROJECT_DIR && cat << 'PROMPT' | claude --dangerously-skip-permissions
TASK: Create rigorous profitability analysis framework

CONTEXT:
- Account88888 had 47.5% raw win rate but +0.85% edge vs market odds
- Raw win rate is MEANINGLESS - must compare to entry price (implied probability)
- 3% taker fee wipes out small edges
- Need statistical significance (confidence intervals, sample size requirements)

YOUR JOB:
1. Create wallet profitability analyzer that:
   - Calculates EDGE vs market odds (not raw win rate)
   - Accounts for fees (variable 0-3% based on price)
   - Requires minimum sample size (>1000 trades per analysis bucket)
   - Calculates confidence intervals

2. Analysis metrics to compute:
   - Overall edge vs market implied probability
   - Edge by price bucket (0-20%, 20-40%, 40-60%, 60-80%, 80-100%)
   - Edge by asset (BTC, ETH, SOL, XRP)
   - Edge by time of day
   - Net P&L after fees
   - Statistical significance (p-values, confidence intervals)

3. Create screening criteria:
   - Minimum edge threshold to be profitable after fees
   - Sample size requirements
   - Consistency checks (edge should be stable over time)

FILES TO READ:
- CLAUDE.md (project context)
- STRATEGY_REEVALUATION.md (how we analyzed Account88888)
- CRITICAL_FINDING_WIN_RATE.md (the full analysis)
- scripts/large_dataset_backtester.py (reference implementation)

OUTPUT:
- scripts/wallet_profitability_analyzer.py
- PROFITABILITY_ANALYSIS_FRAMEWORK.md
- Example output format for analyzed wallets
PROMPT"
    set custom title of front window to "Agent 3: Analysis Framework"
end tell
EOF

echo ""
echo "=============================================="
echo "3 AGENTS LAUNCHED"
echo "=============================================="
echo ""
echo "Agent 1: Wallet Discovery - Finding high-volume wallets"
echo "Agent 2: Data Pipeline - Building extraction infrastructure"
echo "Agent 3: Analysis Framework - Creating rigorous profitability analysis"
echo ""
echo "Monitor progress in Terminal windows."
echo "Results will be in:"
echo "  - data/wallets_to_analyze.json"
echo "  - scripts/robust_wallet_extractor.py"
echo "  - scripts/wallet_profitability_analyzer.py"
echo ""
