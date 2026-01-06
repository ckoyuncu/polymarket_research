#!/bin/bash
#
# EC2 Deployment Script for Blockchain Trade Extractor
#
# This script runs the blockchain trade extractor in a tmux session
# so it survives SSH disconnection.
#
# Usage:
#   ./run_extraction_ec2.sh --wallet <address> [--full|--test]
#
# Requirements:
#   - tmux (sudo apt install tmux)
#   - Python 3.9+
#   - Virtual environment at ./venv
#

set -e

# Parse arguments
WALLET=""
MODE="--full"

while [[ $# -gt 0 ]]; do
    case $1 in
        --wallet)
            WALLET="$2"
            shift 2
            ;;
        --test)
            MODE="--test"
            shift
            ;;
        --full)
            MODE="--full"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

if [ -z "$WALLET" ]; then
    echo "Usage: $0 --wallet <address> [--full|--test]"
    echo ""
    echo "Options:"
    echo "  --wallet  Wallet address to extract trades for (required)"
    echo "  --full    Full extraction from first activity (default)"
    echo "  --test    Test mode - last 10k blocks only"
    exit 1
fi

# Check if tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "tmux not found. Installing..."
    sudo apt-get update && sudo apt-get install -y tmux
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Session name based on wallet
WALLET_SHORT="${WALLET:0:10}"
SESSION_NAME="extraction_${WALLET_SHORT}"

echo "=============================================="
echo "Blockchain Trade Extractor - EC2 Deployment"
echo "=============================================="
echo "Wallet: $WALLET"
echo "Mode: $MODE"
echo "Session: $SESSION_NAME"
echo "Project: $PROJECT_DIR"
echo ""

# Check if session already exists
if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "Session '$SESSION_NAME' already exists!"
    echo ""
    echo "Options:"
    echo "  Attach to session: tmux attach -t $SESSION_NAME"
    echo "  Kill and restart:  tmux kill-session -t $SESSION_NAME && $0 $@"
    echo ""
    exit 1
fi

# Create tmux session and run extraction
echo "Starting extraction in tmux session..."
tmux new-session -d -s "$SESSION_NAME" -c "$PROJECT_DIR"

# Run the extraction script
tmux send-keys -t "$SESSION_NAME" "cd $PROJECT_DIR && source venv/bin/activate" Enter
tmux send-keys -t "$SESSION_NAME" "python scripts/blockchain_trade_extractor.py --wallet $WALLET $MODE 2>&1 | tee extraction_${WALLET_SHORT}.log" Enter

echo ""
echo "Extraction started in background!"
echo ""
echo "Commands:"
echo "  View progress:  tmux attach -t $SESSION_NAME"
echo "  Detach from:    Ctrl+B, then D"
echo "  View log:       tail -f extraction_${WALLET_SHORT}.log"
echo "  Kill session:   tmux kill-session -t $SESSION_NAME"
echo ""
echo "The extraction will continue even if you disconnect SSH."
