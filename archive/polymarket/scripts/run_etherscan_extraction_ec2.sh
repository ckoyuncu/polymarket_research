#!/bin/bash
#
# EC2 Deployment Script for Etherscan Trade Extractor
#
# Run in tmux so it survives SSH disconnection.
# Estimated time: ~2 hours for Account88888 (~1M trades)
#
# Usage:
#   export ETHERSCAN_API_KEY="your-key-here"
#   ./run_etherscan_extraction_ec2.sh --wallet 0x...
#

set -e

WALLET=""
ETHERSCAN_KEY="${ETHERSCAN_API_KEY:-}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --wallet)
            WALLET="$2"
            shift 2
            ;;
        --key)
            ETHERSCAN_KEY="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -z "$WALLET" ]; then
    echo "Usage: $0 --wallet <address> [--key <etherscan_api_key>]"
    exit 1
fi

if [ -z "$ETHERSCAN_KEY" ]; then
    echo "ERROR: ETHERSCAN_API_KEY not set"
    echo "Either export ETHERSCAN_API_KEY or use --key option"
    exit 1
fi

# Check tmux
if ! command -v tmux &> /dev/null; then
    echo "Installing tmux..."
    sudo apt-get update && sudo apt-get install -y tmux
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
WALLET_SHORT="${WALLET:0:10}"
SESSION_NAME="etherscan_${WALLET_SHORT}"

echo "=============================================="
echo "Etherscan V2 Trade Extractor - EC2 Deployment"
echo "=============================================="
echo "Wallet: $WALLET"
echo "Session: $SESSION_NAME"
echo "Estimated time: ~2 hours"
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
tmux send-keys -t "$SESSION_NAME" "python scripts/etherscan_trade_extractor.py --wallet $WALLET --full 2>&1 | tee etherscan_extraction_${WALLET_SHORT}.log" Enter

echo "Extraction started in background!"
echo ""
echo "Commands:"
echo "  View progress:  tmux attach -t $SESSION_NAME"
echo "  Detach:         Ctrl+B, then D"
echo "  View log:       tail -f etherscan_extraction_${WALLET_SHORT}.log"
echo "  Kill:           tmux kill-session -t $SESSION_NAME"
echo ""
echo "Output will be saved to: data/etherscan_trades_${WALLET_SHORT}.json"
