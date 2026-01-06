# Reverse Engineering Account88888's Strategy

This directory contains scripts to systematically identify Account88888's signal source that enables their 97.9% win rate on Polymarket 15-minute markets.

## Overview

**The Mystery**: Account88888 has ~30% edge over the base momentum rate (~67-69%). These scripts test hypotheses across timing, external data, orderbook patterns, and ML signal extraction.

## Scripts by Phase

### Phase 1: Timing Analysis

| Script | Purpose |
|--------|---------|
| `subsecond_timing_analyzer.py` | Analyze trade timing at sub-second granularity |
| `final_minute_tracker.py` | Real-time capture of final 60 seconds before resolution |
| `block_position_analyzer.py` | Analyze tx position within blocks, MEV patterns, gas percentiles |

### Phase 2: External Data Feeds

| Script | Purpose |
|--------|---------|
| `multi_exchange_tracker.py` | Track prices across exchanges (Binance.US, Coinbase, Kraken) |
| `trade_vs_exchange_leader.py` | Correlate Account88888's trades with which exchange moved first |

### Phase 3: Orderbook Microstructure

| Script | Purpose |
|--------|---------|
| `orderbook_imbalance_analyzer.py` | Correlate trade direction with orderbook state |
| `spread_dynamics_analyzer.py` | Analyze spread patterns for predictive signals |

### Phase 4: On-Chain Intelligence

| Script | Purpose |
|--------|---------|
| `gas_pattern_analyzer.py` | Analyze gas usage, priority trading, final minute premiums |
| `competitor_tracker.py` | Track other traders in same markets, timing relationships |

### Phase 5: ML Signal Extraction

| Script | Purpose |
|--------|---------|
| `feature_engineering.py` | Create comprehensive feature set from trades + prices |
| `signal_discovery_model.py` | Train XGBoost to predict 88888's direction (74% accuracy) |
| `outcome_predictor.py` | Predict actual market outcome to compare feature importance |

### Phase 7: Validation

| Script | Purpose |
|--------|---------|
| `hypothesis_backtester.py` | Systematically backtest signal hypotheses |
| `live_signal_tester.py` | Paper trade multiple strategies in real-time |

### Support Scripts

| Script | Purpose |
|--------|---------|
| `run_all_trackers.sh` | Start all real-time trackers in background |
| `tracker_health_monitor.py` | Monitor tracker process health, memory, output |

## Running Real-Time Trackers

**Important**: All real-time trackers should run on EC2, not locally.

```bash
# SSH to EC2
ssh -i ~/.ssh/polymarket-bot-key-us-east.pem ubuntu@13.222.131.86

# Start all trackers (24 hours)
cd ~/polymarket_starter
./scripts/reverse_engineer/run_all_trackers.sh

# Check health
python3 scripts/reverse_engineer/tracker_health_monitor.py --once
```

## Running Analysis Scripts

Analysis scripts use existing data files:

```bash
# Feature engineering
python scripts/reverse_engineer/feature_engineering.py --sample 50000

# Train signal discovery model
python scripts/reverse_engineer/signal_discovery_model.py

# Backtest hypotheses
python scripts/reverse_engineer/hypothesis_backtester.py --hypothesis momentum_10min

# Analyze gas patterns
python scripts/reverse_engineer/gas_pattern_analyzer.py --sample 500

# Track competitors
python scripts/reverse_engineer/competitor_tracker.py --limit 500000
```

## Data Files

| File | Description |
|------|-------------|
| `data/account88888_trades_joined.json` | 2.9M trades with tx_hash, block, timestamp, price, side |
| `data/binance_klines_full.csv` | 1-min Binance candles for 31 days |
| `data/token_to_market.json` | Token ID to market slug mapping |

## Key Findings So Far

1. **Signal Discovery Model**: 74% accuracy predicting 88888's direction
   - Top features: momentum_from_window_start, seconds_to_resolution, volatility

2. **Timing**: Trades cluster 6.4 minutes into 15-min window on average

3. **Hedging**: 4.44x hedge ratio (buys BOTH sides, favors one)

4. **Base Rate**: Simple momentum gives ~67-69% win rate

5. **Unexplained Edge**: ~30% above base rate still unidentified

## Technical Notes

- Binance WebSocket blocked in US regions (451 error)
- Scripts use Binance.US REST API polling instead
- All trackers save to `data/research/` subdirectories
