# Polymarket Trading Analysis

Analysis and reverse engineering of profitable Polymarket trading strategies, focusing on Account88888's 97.9% win rate on 15-minute Up/Down markets.

## Current Status

**Phase: Reverse Engineering Account88888's Signal** (Jan 6, 2026)

- Built 17 analysis tools to identify Account88888's signal source
- ML model predicts their betting direction with 74% accuracy
- ~30% unexplained edge over base rate still under investigation
- Real-time trackers running on EC2 for data collection

## Key Findings

| Metric | Value |
|--------|-------|
| Win rate | **97.9%** (229/234 markets) |
| Profit source | 97.2% prediction, 2.8% arbitrage |
| Total volume analyzed | $285.9M (2.9M trades) |
| Hedge ratio | 4.44x (buy BOTH sides, favor one) |
| Base momentum rate | ~67-69% |
| **Unexplained edge** | **~30%** |

See [reports/STRATEGY_ANALYSIS.md](reports/STRATEGY_ANALYSIS.md) for detailed findings.

## Repository Structure

```
polymarket_starter/
├── scripts/
│   ├── reverse_engineer/     # Signal analysis tools (17 scripts)
│   ├── analysis/             # Backtest & strategy analysis
│   ├── research/             # Chainlink timing, orderbook research
│   ├── data_pipeline/        # Data extraction & processing
│   └── tests/                # Data validation
│
├── src/
│   ├── arbitrage/            # Arbitrage bot (15-min markets)
│   ├── feeds/                # Price feeds (Binance)
│   ├── trading/              # Order execution
│   └── api/                  # Polymarket API clients
│
├── data/                     # Trade data, price data (gitignored)
├── reports/                  # Analysis reports
├── docs/                     # Documentation
└── archive/deprecated_bots/  # Deprecated strategies
```

## Reverse Engineering Tools

All tools in `scripts/reverse_engineer/`:

| Phase | Script | Purpose |
|-------|--------|---------|
| Timing | `subsecond_timing_analyzer.py` | Sub-second trade timing |
| Timing | `final_minute_tracker.py` | Real-time final 60s capture |
| Timing | `block_position_analyzer.py` | MEV/gas analysis |
| External | `multi_exchange_tracker.py` | Multi-exchange prices |
| External | `trade_vs_exchange_leader.py` | Exchange leadership |
| Orderbook | `orderbook_imbalance_analyzer.py` | Orderbook signals |
| Orderbook | `spread_dynamics_analyzer.py` | Spread patterns |
| On-chain | `gas_pattern_analyzer.py` | Gas usage patterns |
| On-chain | `competitor_tracker.py` | Other traders |
| ML | `feature_engineering.py` | Feature extraction |
| ML | `signal_discovery_model.py` | XGBoost direction predictor |
| ML | `outcome_predictor.py` | Market outcome predictor |
| Validation | `hypothesis_backtester.py` | Backtest hypotheses |
| Validation | `live_signal_tester.py` | Paper trade strategies |

See [scripts/reverse_engineer/README.md](scripts/reverse_engineer/README.md) for usage.

## EC2 Instances

| Instance | Region | Purpose | Status |
|----------|--------|---------|--------|
| polymarket-logger-us-east | us-east-1 | Real-time trackers | Running |

```bash
# SSH Access
ssh -i ~/.ssh/polymarket-bot-key-us-east.pem ubuntu@13.222.131.86

# Check tracker health
python3 scripts/reverse_engineer/tracker_health_monitor.py --once
```

## Quick Start

```bash
# Clone and setup
git clone https://github.com/ckoyuncu/polymarket_starter.git
cd polymarket_starter
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run signal discovery model
python scripts/reverse_engineer/signal_discovery_model.py

# Backtest hypotheses
python scripts/reverse_engineer/hypothesis_backtester.py

# Paper trade strategies (local)
python scripts/reverse_engineer/live_signal_tester.py --duration 60
```

## Data Files

Large data files are gitignored. Key files:

| File | Description |
|------|-------------|
| `data/account88888_trades_joined.json` | 2.9M trades (1.3GB) |
| `data/binance_klines_full.csv` | 31 days of 1-min candles |
| `data/token_to_market.json` | 20,200 token mappings (101MB) |

## Documentation

- [reports/STRATEGY_ANALYSIS.md](reports/STRATEGY_ANALYSIS.md) - Complete strategy analysis
- [scripts/reverse_engineer/README.md](scripts/reverse_engineer/README.md) - Reverse engineering tools
- [docs/ARBITRAGE_BOT_README.md](docs/ARBITRAGE_BOT_README.md) - Arbitrage bot (legacy)

---

**Last Updated:** 2026-01-06
