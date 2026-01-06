# Multi-Agent Architecture: Maker Rebates Bot

## System Overview

```
                    ┌─────────────────────────────────────┐
                    │          SENTINEL MONITOR           │
                    │   (Watches all agents, alerts on    │
                    │         errors, tracks health)      │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │         GRAND ORCHESTRATOR          │
                    │   (Coordinates, schedules markets,  │
                    │     makes GO/NO-GO decisions)       │
                    └──────────────┬──────────────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
    ┌───────────┐           ┌───────────┐           ┌───────────┐
    │  PHASE 1  │           │  PHASE 2  │           │  PHASE 3  │
    │Foundation │──────────▶│  Market   │──────────▶│   Live    │
    │   Build   │           │  Making   │           │ Optimize  │
    └───────────┘           └───────────┘           └───────────┘
          │                        │                        │
    ┌─────┴─────┐            ┌─────┴─────┐            ┌─────┴─────┐
    │           │            │           │            │           │
 Agent 1    Agent 2       Agent 3    Agent 4       Agent 5    Agent 6
 API        Paper         Order      Position      Rebate     Strategy
 Client     Trading       Executor   Manager       Tracker    Optimizer
    │           │            │           │            │           │
    └─────┬─────┘            └─────┬─────┘            └─────┬─────┘
          │                        │                        │
          ▼                        ▼                        ▼
    ┌───────────┐           ┌───────────┐           ┌───────────┐
    │    QA     │           │    QA     │           │    QA     │
    │ Validator │           │ Validator │           │ Validator │
    └───────────┘           └───────────┘           └───────────┘
```

---

## Agent Definitions

### SENTINEL MONITOR (Top-Level Observer)

**File:** `.claude/agents/sentinel-monitor.md`

**Role:**
- Watches all agent outputs for errors
- Monitors bot health (balances, positions)
- Alerts on anomalies (stuck orders, missing rebates)
- Can pause/resume orchestrator

**Always Running:** Yes (background monitor)

---

### GRAND ORCHESTRATOR (Coordinator)

**File:** `.claude/commands/maker-orchestrator.md`

**Role:**
- Coordinates all phase progression
- Schedules market windows (every 15 min)
- Makes GO/NO-GO decisions for each market
- Tracks cumulative performance

**Commands:**
```bash
/maker-orchestrator              # Full run
/maker-orchestrator --status     # Show current state
/maker-orchestrator --phase 1    # Run specific phase
```

---

## Phase 1: Foundation (Build Infrastructure)

### Agent 1: API Client Builder

**File:** `.claude/agents/api-client.md`

**Purpose:** Build Polymarket CLOB API client

**Deliverables:**
```
src/api/
├── clob_client.py        # Order placement, cancellation
├── market_data.py        # Price feeds, orderbook
├── account.py            # Balance, positions
└── websocket.py          # Real-time updates
```

**Success Criteria:**
- [ ] Can fetch market data
- [ ] Can place limit orders
- [ ] Can cancel orders
- [ ] Can check balances
- [ ] WebSocket streams working

---

### Agent 2: Paper Trading Simulator

**File:** `.claude/agents/paper-trading.md`

**Purpose:** Safe testing without real funds

**Deliverables:**
```
src/paper/
├── simulator.py          # Order matching simulation
├── position_tracker.py   # Virtual positions
└── rebate_estimator.py   # Estimate expected rebates
```

**Success Criteria:**
- [ ] Simulates order fills
- [ ] Tracks virtual P&L
- [ ] Estimates rebates
- [ ] Logs all activity

---

### QA-1: Phase 1 Validator

**Checks:**
1. API connectivity test
2. Order placement test (paper mode)
3. Balance fetch test
4. WebSocket stability (5 min)

---

## Phase 2: Market Making Core

### Agent 3: Order Executor

**File:** `.claude/agents/order-executor.md`

**Purpose:** Place synchronized YES/NO orders

**Deliverables:**
```
src/maker/
├── executor.py           # Dual order placement
├── synchronizer.py       # Ensure both legs fill
├── pricing.py            # Calculate optimal prices
└── slippage.py          # Handle price movement
```

**Key Logic:**
```python
async def place_maker_position(market_id: str, size: float):
    """Place delta-neutral position."""
    # Get current prices
    yes_price, no_price = await get_best_prices(market_id)

    # Only proceed if both sides available
    if yes_price + no_price > 1.0:
        return  # No opportunity

    # Place both orders as maker (limit orders)
    yes_order = await place_limit_order(
        market_id, side="YES", price=yes_price, size=size
    )
    no_order = await place_limit_order(
        market_id, side="NO", price=no_price, size=size
    )

    return yes_order, no_order
```

**Success Criteria:**
- [ ] Places synchronized orders
- [ ] Handles partial fills
- [ ] Cancels orphaned orders
- [ ] Tracks fill status

---

### Agent 4: Position Manager

**File:** `.claude/agents/position-manager.md`

**Purpose:** Track all open positions and ensure delta-neutral

**Deliverables:**
```
src/positions/
├── manager.py            # Position tracking
├── delta_checker.py      # Verify neutrality
├── reconciler.py         # Match with exchange
└── reporter.py           # Position reports
```

**Key Metrics:**
- Total YES exposure
- Total NO exposure
- Delta (should be ~0)
- Open positions count
- Locked capital

**Success Criteria:**
- [ ] Accurate position tracking
- [ ] Delta calculation correct
- [ ] Reconciles with exchange
- [ ] Alerts on imbalance

---

### QA-2: Phase 2 Validator

**Checks:**
1. Order execution test (paper mode)
2. Delta neutrality verification
3. Position reconciliation
4. 10-market stress test

---

## Phase 3: Live Optimization

### Agent 5: Rebate Tracker

**File:** `.claude/agents/rebate-tracker.md`

**Purpose:** Track and analyze rebate payments

**Deliverables:**
```
src/rebates/
├── tracker.py            # Track rebate payments
├── analyzer.py           # Analyze rebate patterns
├── projector.py          # Project future earnings
└── reporter.py           # Daily/weekly reports
```

**Metrics:**
- Rebates per market
- Rebates per $100 liquidity
- Best/worst time windows
- Competition analysis

**Success Criteria:**
- [ ] Tracks all rebates
- [ ] Matches wallet deposits
- [ ] Calculates ROI
- [ ] Generates reports

---

### Agent 6: Strategy Optimizer

**File:** `.claude/agents/strategy-optimizer.md`

**Purpose:** Optimize timing, sizing, and market selection

**Deliverables:**
```
src/optimizer/
├── market_selector.py    # Pick best markets
├── timing_optimizer.py   # Best entry times
├── size_optimizer.py     # Optimal position size
└── ab_tester.py          # Test strategy variations
```

**Optimization Goals:**
1. Maximize rebates per $ capital
2. Minimize execution risk
3. Find optimal entry timing
4. Identify best markets (BTC vs ETH)

**Success Criteria:**
- [ ] Backtests on historical data
- [ ] A/B tests in paper mode
- [ ] Recommends optimal params
- [ ] Continuous improvement loop

---

### QA-3: Final Validator

**Checks:**
1. Full system integration test
2. 24-hour paper trading run
3. Rebate tracking accuracy
4. Delta neutrality maintained
5. Documentation complete

---

## Skills (Reusable Components)

### `/price-feed`
```yaml
---
name: price-feed
description: Get real-time Polymarket prices. Use when checking market prices or orderbook.
---
```

### `/order-placer`
```yaml
---
name: order-placer
description: Place orders on Polymarket. Use when executing trades.
---
```

### `/balance-checker`
```yaml
---
name: balance-checker
description: Check wallet and position balances. Use when verifying funds.
---
```

### `/rebate-calculator`
```yaml
---
name: rebate-calculator
description: Calculate expected rebates. Use when estimating returns.
---
```

### `/delta-checker`
```yaml
---
name: delta-checker
description: Verify position is delta-neutral. Use when checking risk.
---
```

---

## Orchestration Flow

```python
# Grand Orchestrator pseudo-code

async def run_market_making_cycle():
    while True:
        # Wait for next 15-min window
        await wait_for_next_window()

        # Check conditions
        if not check_balance_sufficient():
            await sentinel.alert("Low balance")
            continue

        if not check_api_healthy():
            await sentinel.alert("API issues")
            continue

        # Get market opportunity
        market = await get_best_market()  # BTC or ETH

        # Execute delta-neutral position
        position = await executor.place_maker_position(
            market_id=market.id,
            size=calculate_position_size()
        )

        # Monitor until resolution
        await position_manager.track(position)

        # After resolution, check rebates
        rebate = await rebate_tracker.check_rebate(position)

        # Log and optimize
        await optimizer.log_result(position, rebate)
        await sentinel.report_health()
```

---

## File Structure

```
polymarket_research/
├── .claude/
│   ├── agents/
│   │   ├── api-client.md           # Agent 1
│   │   ├── paper-trading.md        # Agent 2
│   │   ├── order-executor.md       # Agent 3
│   │   ├── position-manager.md     # Agent 4
│   │   ├── rebate-tracker.md       # Agent 5
│   │   ├── strategy-optimizer.md   # Agent 6
│   │   ├── qa-phase1.md
│   │   ├── qa-phase2.md
│   │   ├── qa-phase3.md
│   │   └── sentinel-monitor.md
│   ├── commands/
│   │   └── maker-orchestrator.md
│   └── skills/
│       ├── price-feed/
│       ├── order-placer/
│       ├── balance-checker/
│       ├── rebate-calculator/
│       └── delta-checker/
├── src/
│   ├── api/                        # Phase 1
│   ├── paper/                      # Phase 1
│   ├── maker/                      # Phase 2
│   ├── positions/                  # Phase 2
│   ├── rebates/                    # Phase 3
│   └── optimizer/                  # Phase 3
├── tests/
├── data/
│   └── rebate_history/
├── logs/
└── config/
    └── maker_config.yaml
```

---

## Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Delta exposure | < 1% | Continuous |
| Order fill rate | > 95% | Per market |
| Rebate capture | > 80% of theoretical | Daily |
| System uptime | > 99% | Per 24h |
| Monthly ROI | > 10% | Monthly |

---

## Risk Controls

1. **Max Position Size:** $100 per market (with $300 capital)
2. **Max Concurrent Markets:** 3
3. **Delta Limit:** Alert if |delta| > 5%
4. **Kill Switch:** Stop all if balance drops 10%
5. **Orphan Order Timeout:** Cancel unfilled leg after 30s

---

## Execution Commands

```bash
# Start orchestrator
/maker-orchestrator

# Check status
/maker-orchestrator --status

# Run specific phase
/maker-orchestrator --phase 1

# Run paper trading test
/maker-orchestrator --paper --markets 10

# Run live (after paper validation)
/maker-orchestrator --live
```
