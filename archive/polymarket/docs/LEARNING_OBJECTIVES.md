# Learning Objectives - Live Trading Bot

**Date:** January 6, 2026
**Capital:** $300
**Philosophy:** Survive to learn, not profit to win

---

## Primary Goal

Learn whether our signal hypotheses work in live trading conditions, not to maximize profit. The $300 is tuition money for trading education.

---

## Data to Collect

### 1. Signal Quality Data

For every market window (15-min), record:

| Field | Description | Purpose |
|-------|-------------|---------|
| `timestamp` | When decision was made | Timing analysis |
| `asset` | BTC or ETH | Per-asset performance |
| `time_to_close_sec` | Seconds before window close | Optimal entry timing |
| `binance_price` | Current Binance price | Price reference |
| `window_start_price` | Price at window start | Momentum calculation |
| `momentum` | % price change since start | ETH signal quality |
| `orderbook_imbalance` | Net bid/ask imbalance | BTC signal quality |
| `direction` | up/down prediction | Signal validation |
| `confidence` | 0-1 confidence score | Threshold tuning |
| `decision` | trade/skip/killed | Decision audit |
| `reason` | Why decision was made | Debug & learning |

### 2. Execution Data

For every trade executed:

| Field | Description | Purpose |
|-------|-------------|---------|
| `order_id` | Exchange order ID | Execution tracking |
| `position_size` | Shares bought | P&L calculation |
| `entry_price` | Price paid | Cost basis |
| `slippage` | Expected vs actual price | Execution quality |
| `latency_ms` | Order to fill time | Speed analysis |

### 3. Outcome Data

For every resolved trade:

| Field | Description | Purpose |
|-------|-------------|---------|
| `resolution` | Actual outcome (up/down) | Ground truth |
| `outcome` | win/loss | Performance |
| `profit` | P&L in USD | Financial tracking |
| `confidence_correct` | Was high confidence right? | Calibration |

---

## Metrics to Track

### Signal Quality Metrics

1. **Accuracy by Signal Type**
   - BTC orderbook-only accuracy
   - BTC orderbook+momentum accuracy
   - ETH momentum-only accuracy
   - ETH momentum+orderbook accuracy

2. **Accuracy by Threshold**
   - Accuracy at different imbalance thresholds (0.2, 0.3, 0.5)
   - Accuracy at different momentum thresholds (0.1%, 0.2%, 0.5%)

3. **Confidence Calibration**
   - When we predict 80% confidence, do we win 80% of time?
   - Plot: Predicted confidence vs Actual win rate

### Execution Metrics

1. **Fill Rate**
   - % of orders that fill (FOK may reject)

2. **Slippage**
   - Average slippage from quoted to filled price
   - Slippage by time to close

3. **Latency**
   - Time from signal to order submission
   - Time from submission to fill

### Risk Metrics

1. **Drawdown**
   - Maximum drawdown in session
   - Maximum consecutive losses

2. **Recovery**
   - Time to recover from drawdowns
   - P&L after pause periods

---

## Decision Log Template

### Per-Trade Decision Record

```json
{
  "timestamp": "2026-01-06T14:45:30Z",
  "market_slug": "btc-updown-15m-1736175600",
  "asset": "BTC",

  "market_state": {
    "binance_price": 98234.50,
    "window_start_price": 98100.00,
    "momentum_pct": 0.137,
    "orderbook_imbalance": 0.62,
    "time_to_close_sec": 45,
    "up_ask_price": 0.48,
    "down_ask_price": 0.52
  },

  "signal": {
    "direction": "up",
    "confidence": 0.85,
    "btc_rule": "OB >= 0.5 (83.3% expected)",
    "confirmation": "momentum agrees",
    "reason": "OB_imbal=0.620, momentum=0.137%, OB+momentum_agree"
  },

  "decision": {
    "action": "trade",
    "position_size_usd": 15.00,
    "entry_price": 0.48,
    "shares": 31.25
  },

  "risk_check": {
    "daily_pnl": -5.50,
    "trades_today": 8,
    "consecutive_losses": 1,
    "risk_approved": true
  },

  "outcome": {
    "resolution": "up",
    "result": "win",
    "profit_usd": 16.25,
    "actual_vs_predicted": "correct"
  }
}
```

---

## Questions to Answer

### Week 1: Signal Validation

1. Does the BTC orderbook signal work in live conditions?
   - Target: >75% accuracy (vs 83.3% historical)

2. Does the ETH momentum signal work in live conditions?
   - Target: >80% accuracy (vs 88.9% historical)

3. Is there execution slippage that erodes edge?
   - Measure: Average slippage as % of position

4. What is the optimal entry timing?
   - Test: 60s, 45s, 30s before close

### Week 2: Execution Optimization

1. What order type works best? (FOK vs GTC)
2. What position sizing maximizes risk-adjusted returns?
3. How often do we get filled at desired price?

### Week 3: Risk Calibration

1. What is the true drawdown profile?
2. How does pause-after-loss affect recovery?
3. Should we adjust position size based on confidence?

---

## Success Criteria

### Minimum Success (Survive)
- [ ] Complete 50+ trades without kill switch trigger
- [ ] Maximum 30% capital loss ($90)
- [ ] Collect clean data for all trades

### Good Success (Learn)
- [ ] Validate BTC orderbook signal (>70% accuracy)
- [ ] Validate ETH momentum signal (>75% accuracy)
- [ ] Understand execution slippage (<2% average)

### Great Success (Profitable Learning)
- [ ] Positive P&L after 100+ trades
- [ ] Identify optimal entry timing window
- [ ] Calibrated confidence thresholds

---

## Daily Review Checklist

After each trading session:

1. **Data Quality**
   - [ ] All trades logged with complete data
   - [ ] No missing outcomes
   - [ ] Timestamps are accurate

2. **Signal Analysis**
   - [ ] Calculate accuracy for each signal type
   - [ ] Note any signal failures and why
   - [ ] Update confidence thresholds if needed

3. **Execution Review**
   - [ ] Check fill rate
   - [ ] Measure slippage
   - [ ] Note any rejected orders

4. **Risk Review**
   - [ ] Daily P&L within limits
   - [ ] Consecutive losses handled correctly
   - [ ] Kill switch functioning

5. **Learning Notes**
   - [ ] What surprised you today?
   - [ ] Any pattern changes noticed?
   - [ ] What should be adjusted tomorrow?

---

## Data Files

All data is stored in `data/live_trading/`:

| File | Description |
|------|-------------|
| `decisions.jsonl` | Every trading decision (trade/skip) |
| `daily_stats.json` | Daily aggregated statistics |
| `live_bot.log` | Full execution log with timestamps |

---

## Analysis Scripts (TODO)

- [ ] `scripts/analyze_live_trading.py` - Daily performance report
- [ ] `scripts/calibrate_confidence.py` - Confidence vs actual accuracy
- [ ] `scripts/slippage_analysis.py` - Execution quality report
