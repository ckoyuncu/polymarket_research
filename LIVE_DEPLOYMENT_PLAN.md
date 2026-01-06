# Live Deployment Plan: First-Mover Maker Bot

**Date**: 2026-01-06
**Status**: PLANNING
**Goal**: Deploy live bot to capture rebates and gather real market data

---

## Executive Summary

The 3% taker fee and maker rebates were introduced TODAY. We have a first-mover opportunity to:
1. Provide liquidity before competition arrives
2. Capture maker rebates from the daily pool
3. Gather REAL data about fills, spreads, and rebate economics

**Strategy**: Deploy with MICRO positions ($5-10 per side) to learn while minimizing risk.

---

## Safety Framework

### Position Limits (STRICT)
| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max position per market | $10 | Learn with minimal risk |
| Max concurrent positions | 2 | One BTC, one ETH |
| Max daily loss | $20 | Hard stop |
| Max total exposure | $40 | Absolute ceiling |

### Safety Mechanisms
1. **Kill Switch**: `touch .kill_switch` stops all trading
2. **Circuit Breakers**: Auto-stop on consecutive losses
3. **Position Reconciliation**: Verify positions every cycle
4. **Logging**: Every order, fill, and decision recorded

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR                          │
│  - Coordinates all components                            │
│  - Enforces safety limits                                │
│  - Manages state                                         │
└─────────────────────────────────────────────────────────┘
           │              │              │
           ▼              ▼              ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  MARKET FINDER  │ │  SPREAD MONITOR │ │  REBATE TRACKER │
│  - Find active  │ │  - Track spreads│ │  - Monitor USDC │
│    15m markets  │ │  - Alert on     │ │  - Track daily  │
│  - Get token IDs│ │    tightening   │ │    rebate pool  │
└─────────────────┘ └─────────────────┘ └─────────────────┘
           │              │              │
           ▼              ▼              ▼
┌─────────────────────────────────────────────────────────┐
│                   MICRO TRADER                           │
│  - Place maker orders at configurable spreads            │
│  - Delta-neutral: YES + NO simultaneously                │
│  - Track fills and P&L                                   │
│  - Report learnings                                      │
└─────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│                   DATA COLLECTOR                         │
│  - Log all orderbook snapshots                           │
│  - Record all our orders and fills                       │
│  - Track competitor activity                             │
│  - Calculate actual rebate earnings                      │
└─────────────────────────────────────────────────────────┘
```

---

## Parallel Agent Deployment

### Round 1: Infrastructure (Parallel)
```
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ spread-monitor  │  │ rebate-tracker  │  │  data-logger    │
│   Build spread  │  │  Track USDC     │  │  Log everything │
│   monitoring    │  │  balance for    │  │  for analysis   │
│                 │  │  rebates        │  │                 │
└─────────────────┘  └─────────────────┘  └─────────────────┘
```

### Round 2: Trading Core (Parallel)
```
┌─────────────────┐  ┌─────────────────┐
│  micro-trader   │  │  safety-system  │
│  Place small    │  │  Kill switch,   │
│  maker orders   │  │  circuit breaker│
└─────────────────┘  └─────────────────┘
```

### Round 3: Integration
```
┌─────────────────┐
│   orchestrator  │
│  Tie it all     │
│  together       │
└─────────────────┘
```

---

## Trading Strategy: Exploratory Maker

### Approach
Since spreads are currently 98%, we'll test different price levels:

**Phase 1: Aggressive Pricing (Test Fills)**
- Place YES bid at $0.45, NO bid at $0.45
- Total cost if both fill: $0.90 (guaranteed $1.00 at resolution = $0.10 profit + rebates)
- Risk: Unlikely to fill at current spread

**Phase 2: Mid-Range (If Phase 1 doesn't fill)**
- Place YES bid at $0.30, NO bid at $0.30
- If both fill: Pay $0.60, get $1.00 = $0.40 profit + rebates
- More likely to fill but still aggressive

**Phase 3: Extreme (Last Resort)**
- Place YES bid at $0.10, NO bid at $0.10
- If both fill: Pay $0.20, get $1.00 = $0.80 profit + rebates
- Very conservative, competing with existing liquidity

### Key Learning Questions
1. At what price levels do we get fills?
2. How much rebate do we actually receive?
3. Are there other makers competing?
4. Does our activity tighten spreads?

---

## Data Collection Requirements

### Per-Market Metrics
- [ ] Orderbook snapshots (every 10s)
- [ ] Our order placement times
- [ ] Fill confirmations and prices
- [ ] Time to fill (if any)
- [ ] Competitor orders appearing
- [ ] Spread evolution over 15-min window

### Daily Metrics
- [ ] Total volume traded
- [ ] Rebates received (check USDC balance)
- [ ] Win/loss from resolution
- [ ] Net P&L breakdown

### Analysis Output
- [ ] Fill rate by price level
- [ ] Rebate economics ($ earned per $ volume)
- [ ] Spread dynamics (tightening trend?)
- [ ] Competitor analysis

---

## Go-Live Checklist

### Pre-Launch
- [ ] USDC balance verified (need ~$50 buffer)
- [ ] Kill switch tested
- [ ] Logging working
- [ ] Paper trade 3 cycles successfully

### Launch Criteria
- [ ] All safety mechanisms active
- [ ] Monitoring dashboard running
- [ ] Alert system configured
- [ ] Emergency contacts set

### Post-Launch Monitoring
- [ ] Check positions every 15 min
- [ ] Review logs every hour
- [ ] Daily P&L reconciliation
- [ ] Rebate verification (next day)

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| No fills (wide spread) | HIGH | Low (no loss) | Test multiple price levels |
| One-sided fill | MEDIUM | $5-10 loss | Small position size |
| API failure | LOW | Orphan orders | Aggressive cancellation |
| Rebate program changes | LOW | Strategy invalid | Monitor announcements |

**Maximum Possible Loss**: $40 (absolute worst case, all positions lose)
**Expected Learning Value**: HIGH (real market data, actual rebate numbers)

---

## Success Metrics

### Week 1 Goals
1. Successfully place and cancel orders
2. Get at least ONE fill to test execution
3. Receive at least ONE rebate payment
4. Collect 1000+ orderbook snapshots

### Decision Points
- **If fills happen easily**: Increase position size gradually
- **If no fills at aggressive prices**: Market not ready, continue monitoring
- **If rebates are significant**: Scale up strategy
- **If spreads tighten**: Adjust pricing to stay competitive

---

## Commands

```bash
# Start the live bot
python scripts/run_live_bot.py --mode micro --max-position 10

# Monitor status
python scripts/run_live_bot.py --status

# Emergency stop
touch .kill_switch

# View logs
tail -f logs/live_trading.log

# Check rebates
python scripts/check_rebates.py
```

---

*Plan created: 2026-01-06*
*Status: Ready for approval*
