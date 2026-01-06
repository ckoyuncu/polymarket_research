#!/bin/bash
#
# EC2 Deployment Script for Batch Wallet Extraction
#
# Extracts trade history for top 50 wallets sequentially.
# Estimated time: ~2-3 days
#
# Usage:
#   export ETHERSCAN_API_KEY="your-key"
#   ./run_batch_extraction_ec2.sh
#

set -e

ETHERSCAN_KEY="${ETHERSCAN_API_KEY:-}"

if [ -z "$ETHERSCAN_KEY" ]; then
    echo "ERROR: ETHERSCAN_API_KEY not set"
    exit 1
fi

# Check tmux
if ! command -v tmux &> /dev/null; then
    echo "Installing tmux..."
    sudo apt-get update && sudo apt-get install -y tmux
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
SESSION_NAME="batch_extraction"

echo "=============================================="
echo "Batch Wallet Extractor - EC2 Deployment"
echo "=============================================="
echo "Session: $SESSION_NAME"
echo "Estimated time: ~2-3 days"
echo ""

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session '$SESSION_NAME' already exists!"
    echo "  Attach: tmux attach -t $SESSION_NAME"
    echo "  Kill:   tmux kill-session -t $SESSION_NAME"
    exit 1
fi

# Create and run
tmux new-session -d -s "$SESSION_NAME" -c "$PROJECT_DIR"
tmux send-keys -t "$SESSION_NAME" "cd $PROJECT_DIR && source venv/bin/activate" Enter
tmux send-keys -t "$SESSION_NAME" "export ETHERSCAN_API_KEY='$ETHERSCAN_KEY'" Enter
tmux send-keys -t "$SESSION_NAME" "python scripts/batch_wallet_extractor.py 2>&1 | tee batch_extraction.log" Enter

echo "Batch extraction started!"
echo ""
echo "Commands:"
echo "  View progress:  tmux attach -t $SESSION_NAME"
echo "  Detach:         Ctrl+B, then D"
echo "  View log:       tail -f batch_extraction.log"
echo "  Kill:           tmux kill-session -t $SESSION_NAME"
echo ""
echo "Outputs will be saved to: data/trades_*.json"
