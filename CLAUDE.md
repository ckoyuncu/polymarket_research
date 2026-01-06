# Project Context for Agents

## Tech Stack
- Python 3.10+
- SQLAlchemy (storage)
- Pydantic (validation)
- py-clob-client (Polymarket API)
- Streamlit (dashboard)

## Key Paths

### Trading Logic
- `src/trading/executor.py` - Order execution (FOK, limit, market) **[NEEDS: timeouts, retries, balance check]**
- `src/trading/live_bot.py` - Conservative live trading bot (Agent 2)
- `src/trading/positions.py` - Position tracking
- `src/api/clob_ws.py` - WebSocket feeds **[NEEDS: auto-reconnect]**
- `src/api/gamma.py` - Gamma API client

### Analysis & Models
- `scripts/reverse_engineer/signal_discovery_model_v2.py` - ML model V2 (67.7% base, 90%+ with thresholds)
- `scripts/reverse_engineer/signal_discovery_model.py` - V1 (DEPRECATED: had data leakage)
- `scripts/reverse_engineer/deep_orderbook_analysis.py` - Orderbook signals
- `ORDERBOOK_SIGNAL_FINDINGS.md` - Trading rules (BTC: 84.8%, ETH: 95.7%)
- `MODEL_IMPROVEMENTS.md` - Model V2 methodology and results

### Tests
- `tests/test_executor.py` - 25 tests for order execution (Agent 1)
- `tests/test_risk_controls.py` - 25 tests for circuit breakers (Agent 1)

### Documentation
- `LIVE_READINESS_ASSESSMENT.md` - Production readiness gaps (Agent 1)
- `MARKET_CONSTRAINTS_AND_FEES.md` - Fee structure analysis (Agent 4)
- `SYSTEM_SYNTHESIS.md` - Go/No-Go recommendation (Agent 5)
- `NEXT_PHASE.md` - Round 2 plan

### Data
- `data/account88888_trades_joined.json` - 2.9M trades
- `data/features/*.parquet` - Engineered features
- `data/models/signal_discovery_model_v2.ubj` - Trained model V2
- `src/storage/db.py` - SQLite trades.db

### Config
- `.env` - Credentials (POLYMARKET_PRIVATE_KEY, POLYMARKET_FUNDER)
- `config/account88888_strategy.json` - Strategy params

## Commands
```bash
source venv/bin/activate
python scripts/reverse_engineer/signal_discovery_model_v2.py       # Train model V2
python -m src.trading.live_bot                                     # Paper trading (default)
python -m src.trading.live_bot --live                              # Live trading (CAUTION)
pytest tests/                                                       # Run tests (50 tests)
```

## Architecture
- Account88888 reverse engineering: ~67% baseline win rate
- With confidence >= 0.4: 90%+ win rate (44% trade coverage)
- Signal: Orderbook imbalance (BTC) + momentum (ETH)
- No MEV/priority ordering used (confirmed via block analysis)

## Trading Rules (From Analysis)
```
BTC: Trade when |orderbook_imbalance| >= 0.5 → 83.3% accuracy
ETH: Follow early momentum, not orderbook → 88.9% accuracy
Combined: When OB + momentum agree → 84.8% BTC, 95.7% ETH

CRITICAL: Only trade when model confidence >= 0.4 (90%+ accuracy)
CRITICAL: Only trade when market odds < 80% (preserve edge)
```

## Fee Structure (From Agent 4)
- Maker: 0% + rebates
- Taker: 0-3% variable (highest at 50% odds, lowest at extremes)
- Break-even: ~52% accuracy required at 50% odds
- Our edge: 84% accuracy provides 32.7% margin

## Conventions
- Black formatter, 100 char line length
- Commit format: `type(scope): message`
- Branch format: `agent-N/description`
- All agents create PRs when done

## Current Status (Post Round 1)
- **Recommendation:** CONDITIONAL GO
- ML model V2: 67.7% base → 90%+ with thresholds
- Test coverage: 50 tests (executor + risk controls)
- Executor gaps: Needs timeouts, retries, balance check
- Paper trading: Ready (use `python -m src.trading.live_bot`)
- Live trading: **BLOCKED** until P0 fixes complete

## P0 Fixes Required Before Live Trading
1. Add API timeouts (5s) to executor.py
2. Add retry logic (3 attempts with backoff)
3. Implement balance pre-check
4. Paper trade 3-7 days

## Capital Constraint
- $300 budget
- Goal: Learning + capital preservation
- Max $15/trade (5% of capital)
- Max $30/day loss
- Kill switch required

## Round 2 Agent Prompts
See `.claude/commands/agents_round2.md` for next agent definitions.
