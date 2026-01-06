#!/bin/bash
# Launch script for multi-agent trading system

REPO_ROOT=$(pwd)
BRANCHES=(
  "agent-1/test-production-readiness"
  "agent-2/live-trading-bot"
  "agent-3/model-improvements"
  "agent-4/market-mechanics-research"
)

echo "=== Multi-Agent Trading System Launcher ==="
echo ""
echo "Prerequisites:"
echo "  - Git repository initialized"
echo "  - Claude Code installed"
echo ""
echo "Instructions:"
echo "  1. Open 4 separate terminal windows"
echo "  2. In each terminal, run ONE of these commands:"
echo ""

for i in "${!BRANCHES[@]}"; do
  AGENT_NUM=$((i + 1))
  echo "  Terminal $AGENT_NUM:"
  echo "    cd $REPO_ROOT && git checkout -b ${BRANCHES[$i]} main && claude"
  echo "    Then paste Agent $AGENT_NUM prompt from .claude/commands/agents.md"
  echo ""
done

echo "  After Agents 1-4 complete, run Agent 5:"
echo "    cd $REPO_ROOT && git checkout -b agent-5/meta-synthesis main && claude"
echo ""
echo "=== Tips ==="
echo "  - Use /clear between major tasks"
echo "  - Use /compact if context fills up mid-task"
echo "  - Each agent should commit frequently"
echo "  - Create PR when done: gh pr create --title 'Agent N: Description'"
echo ""
echo "=== Quick View of Agent Prompts ==="
echo "  cat .claude/commands/agents.md"
echo ""
