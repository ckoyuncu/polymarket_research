#!/bin/bash
# Launch Round 2 Agents
# Run agents 6 and 7 in parallel (P0 critical fixes)
# Then agent 8 for paper trading validation

set -e

echo "=========================================="
echo "Round 2 Agents - Launching"
echo "=========================================="

# Check we're on main or a clean branch
BRANCH=$(git branch --show-current)
echo "Current branch: $BRANCH"

echo ""
echo "Phase 1: Critical Fixes (P0)"
echo "-------------------------------------------"
echo "Agent 6: Executor Hardening (timeouts, retries, kill switch)"
echo "Agent 7: Balance Checker (on-chain USDC query)"
echo ""
echo "These agents can run IN PARALLEL."
echo ""

# Phase 1 commands (run in parallel)
cat << 'EOF'
# To launch Agent 6:
git checkout -b agent-6/executor-hardening
# Run Agent 6 prompt from .claude/commands/agents_round2.md

# To launch Agent 7 (in parallel):
git checkout -b agent-7/balance-checker
# Run Agent 7 prompt from .claude/commands/agents_round2.md
EOF

echo ""
echo "Phase 2: Validation"
echo "-------------------------------------------"
echo "Agent 8: Paper Trading Validator (3-7 days)"
echo ""
echo "Run AFTER Phase 1 PRs are merged."
echo ""

cat << 'EOF'
# To launch Agent 8:
git checkout -b agent-8/paper-trading-validation
# Run Agent 8 prompt from .claude/commands/agents_round2.md
EOF

echo ""
echo "Phase 3: Reliability"
echo "-------------------------------------------"
echo "Agent 9: WebSocket Reliability"
echo ""
echo "Can run in parallel with Phase 2."
echo ""

cat << 'EOF'
# To launch Agent 9:
git checkout -b agent-9/websocket-reliability
# Run Agent 9 prompt from .claude/commands/agents_round2.md
EOF

echo ""
echo "Phase 4: Nice to Have"
echo "-------------------------------------------"
echo "Agent 10: Monitoring & Alerts"
echo ""

cat << 'EOF'
# To launch Agent 10:
git checkout -b agent-10/monitoring
# Run Agent 10 prompt from .claude/commands/agents_round2.md
EOF

echo ""
echo "=========================================="
echo "Ready to launch Round 2 agents!"
echo "See .claude/commands/agents_round2.md for prompts"
echo "=========================================="
