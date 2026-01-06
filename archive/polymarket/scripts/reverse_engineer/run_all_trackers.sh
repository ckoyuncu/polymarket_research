#!/bin/bash
# Run all trackers for Account88888 signal research
# Usage: ./run_all_trackers.sh [duration_hours]
#
# This script starts:
# 1. Multi-Exchange Tracker (Binance/Coinbase/Kraken price comparison)
# 2. Orderbook Imbalance Analyzer (bid/ask depth patterns)
# 3. Final Minute Tracker (high-res data before market close)
# 4. Health Monitor (background status checker)

DURATION_HOURS=${1:-24}
DURATION_SECONDS=$((DURATION_HOURS * 3600))
DURATION_MINUTES=$((DURATION_HOURS * 60))

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
LOG_DIR="$PROJECT_ROOT/logs/trackers"

mkdir -p "$LOG_DIR"
mkdir -p "$PROJECT_ROOT/data/research/final_minute"
mkdir -p "$PROJECT_ROOT/data/research/multi_exchange"
mkdir -p "$PROJECT_ROOT/data/research/orderbook_imbalance"

echo "=========================================="
echo "STARTING ALL TRACKERS"
echo "Duration: $DURATION_HOURS hours"
echo "Log dir: $LOG_DIR"
echo "=========================================="

# Kill any existing trackers
echo "Stopping any existing trackers..."
pkill -f "final_minute_tracker.py" 2>/dev/null
pkill -f "multi_exchange_tracker.py" 2>/dev/null
pkill -f "orderbook_imbalance_analyzer.py" 2>/dev/null
pkill -f "tracker_health_monitor.py" 2>/dev/null
sleep 2

# Start Multi-Exchange Tracker
echo ""
echo "Starting Multi-Exchange Tracker..."
nohup python3 "$SCRIPT_DIR/multi_exchange_tracker.py" --duration $DURATION_SECONDS \
    > "$LOG_DIR/multi_exchange.log" 2>&1 &
echo "  PID: $!"

# Start Orderbook Imbalance Analyzer
echo "Starting Orderbook Imbalance Analyzer..."
nohup python3 "$SCRIPT_DIR/orderbook_imbalance_analyzer.py" --duration $DURATION_MINUTES \
    > "$LOG_DIR/orderbook.log" 2>&1 &
echo "  PID: $!"

# Start Final Minute Tracker
echo "Starting Final Minute Tracker..."
nohup python3 "$SCRIPT_DIR/final_minute_tracker.py" --duration $DURATION_MINUTES \
    > "$LOG_DIR/final_minute.log" 2>&1 &
echo "  PID: $!"

# Wait for processes to start
sleep 3

# Start Health Monitor (in background, logs every 5 min)
echo "Starting Health Monitor..."
nohup python3 "$SCRIPT_DIR/tracker_health_monitor.py" --interval 300 \
    > "$LOG_DIR/health.log" 2>&1 &
echo "  PID: $!"

echo ""
echo "=========================================="
echo "ALL TRACKERS STARTED"
echo "=========================================="
echo ""
echo "Monitor logs with:"
echo "  tail -f $LOG_DIR/multi_exchange.log"
echo "  tail -f $LOG_DIR/orderbook.log"
echo "  tail -f $LOG_DIR/final_minute.log"
echo "  tail -f $LOG_DIR/health.log"
echo ""
echo "Check status:"
echo "  python3 $SCRIPT_DIR/tracker_health_monitor.py --once"
echo ""
echo "Stop all trackers:"
echo "  pkill -f 'tracker.py\|analyzer.py'"
echo ""

# Show initial status
python3 "$SCRIPT_DIR/tracker_health_monitor.py" --once
