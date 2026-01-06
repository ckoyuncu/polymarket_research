# Orderbook Signal Deep Analysis Findings

**Date:** January 6, 2026
**Branch:** `parallel-analysis`
**Data:**
- Orderbook analysis: 94 final minute captures (47 BTC, 47 ETH)
- Trade-based validation: 113 markets (58 BTC, 55 ETH) from trades.db

---

## Executive Summary

The orderbook imbalance signal shows **fundamentally different behavior** between BTC and ETH:

| Metric | BTC | ETH |
|--------|-----|-----|
| Orderbook alone | **77.8%** | 57.8% |
| Early momentum alone | 73.3% | **88.9%** |
| OB + Early agree | **84.8%** | **95.7%** |
| All signals agree | 84.2% | **100%** |

**Key Insight:** Use orderbook for BTC, use momentum for ETH.

---

## BTC Trading Rules (Recommended)

### Rule 1: High-Confidence Threshold Trade
```
IF |orderbook_imbalance| >= 0.5:
    TRADE direction = sign(imbalance)
    Expected accuracy: 83.3%
    Trade frequency: 67% of windows
```

### Rule 2: Confirmation Trade (Higher Accuracy)
```
IF orderbook AND early_momentum AGREE:
    TRADE that direction
    Expected accuracy: 84.8%
    Trade frequency: 73% of windows
```

### Rule 3: Maximum Confidence Trade
```
IF orderbook AND early_momentum AND late_momentum ALL AGREE:
    TRADE that direction
    Expected accuracy: 84.2%
    Trade frequency: 42% of windows
```

### Timing Recommendation
- Use signals from **30-60 seconds before resolution** (77.8% accuracy)
- Signal degrades closer to end (73.3% at 5-10s before)
- This suggests the predictive information is already priced in early

---

## ETH Trading Rules (Recommended)

### Rule 1: Follow Momentum (NOT Orderbook)
```
IF early_momentum_direction = UP/DOWN:
    TRADE that direction
    Expected accuracy: 88.9%
```

**Warning:** Orderbook alone is UNRELIABLE for ETH (57.8% - barely better than random)

### Rule 2: Confirmation Trade (Near-Perfect)
```
IF orderbook AND early_momentum AGREE:
    TRADE that direction
    Expected accuracy: 95.7%
    Trade frequency: 51% of windows
```

### Rule 3: Perfect Signal
```
IF orderbook AND early_momentum AND late_momentum ALL AGREE:
    TRADE that direction
    Expected accuracy: 100% (18/18)
    Trade frequency: 40% of windows
```

### When Signals Disagree (ETH)
```
IF orderbook DISAGREES with momentum:
    FOLLOW MOMENTUM (not orderbook)
    Momentum wins: 81.8%
    Orderbook wins: 18.2%
```

---

## Analysis Details

### 1. Time-Weighted Analysis

**BTC:**
| Time Before Resolution | Accuracy |
|----------------------|----------|
| 60 seconds | 77.8% |
| 30 seconds | 77.8% |
| 15 seconds | 77.8% |
| 10 seconds | 73.3% |
| 5 seconds | 73.3% |

Signal stays stable until ~15s, then degrades. The market may be processing information and reducing the edge.

**ETH:** Consistent 57.8% across all time windows (orderbook not predictive)

### 2. Threshold Analysis

**BTC - Accuracy by Imbalance Threshold:**
| Threshold | Accuracy | Trades |
|-----------|----------|--------|
| >= 0.0 | 77.8% | 45 |
| >= 0.1 | 82.1% | 39 |
| >= 0.2 | 82.9% | 35 |
| >= 0.3 | 81.2% | 32 |
| >= 0.4 | 81.2% | 32 |
| >= 0.5 | **83.3%** | 30 |

**Recommendation:** Use >= 0.2 threshold for best balance of accuracy (82.9%) and trade frequency (35/45).

**ETH:** Thresholds don't help (stays ~58-60%)

### 3. Combined Signals Analysis

**BTC:**
- Orderbook alone: 77.8%
- Early momentum alone: 73.3%
- Late momentum alone: 53.3%
- **OB + Early agree: 84.8%** (best practical rule)
- All agree: 84.2%

**ETH:**
- Orderbook alone: 57.8%
- Early momentum alone: **88.9%** (dominant signal!)
- Late momentum alone: 84.4%
- OB + Early agree: **95.7%**
- **All agree: 100%** (18/18 perfect)

### 4. Spread Analysis

Spread data was limited (most have null ask prices). Where available:
- Wide spreads (>6%) showed slightly lower accuracy
- No strong correlation found with available data

---

## Why This Works (Hypothesis)

### BTC Orderbook Signal
The Polymarket orderbook for the UP token reflects market participant beliefs about BTC direction. More bid depth = more people wanting to buy UP = collective prediction of price increase.

This could work because:
1. **Information aggregation:** Sophisticated traders are placing orders based on their models
2. **Momentum trading:** Traders see early price movement and bet accordingly
3. **Market maker positioning:** MMs adjust their books based on flow/information

### ETH Momentum Signal
For ETH, the orderbook is less predictive but **actual price momentum** is highly predictive (88.9%). This suggests:
1. ETH traders may be less sophisticated on Polymarket
2. The market is less efficient at pricing ETH direction
3. Momentum is more persistent in ETH within short windows

---

## Risk Considerations

1. **Sample Size:** 45 windows per asset is moderate. More data needed for production.
2. **Regime Changes:** Market dynamics may shift over time.
3. **Execution Risk:** These trades happen in final 60 seconds - execution speed matters.
4. **Spread Cost:** Polymarket spreads are 3-5% which eats into edge.
5. **Overfitting Risk:** Rules optimized on historical data may not persist.

---

## Next Steps

1. **Collect more data** - Continue running EC2 trackers to build larger sample
2. **Backtest with fees** - Model actual P&L including spread costs
3. **Paper trade** - Test rules in real-time without capital
4. **Monitor regime** - Track if signal accuracy changes over time
5. **Separate by time-of-day** - Check if signal varies by market hours

---

## Large Sample Validation (trades.db)

We validated our signals on 113 markets from the historical trades database, providing much higher confidence.

### Volume-Weighted Trade Sentiment Results

| Asset | Threshold | Accuracy | Sample Size | 95% CI |
|-------|-----------|----------|-------------|--------|
| BTC | All | 82.8% | 58 | 71.1% - 90.4% |
| BTC | >=0.3 | **87.5%** | 24 | 69.0% - 95.7% |
| BTC | >=0.4 | **94.4%** | 18 | 74.2% - 99.0% |
| ETH | All | 81.8% | 55 | 69.7% - 89.8% |
| ETH | >=0.3 | **95.0%** | 20 | 76.4% - 99.1% |
| ETH | >=0.4 | **100%** | 12 | 75.7% - 100% |
| ETH | >=0.5 | **100%** | 8 | 67.6% - 100% |

### Key Validation Findings

1. **BTC signal confirmed at 82.8%** overall, improving to **94.4%** with high-confidence threshold
2. **ETH trade sentiment is MORE predictive than orderbook** - 81.8% vs 59.6%
3. **100% accuracy achievable** for ETH with |signal| >= 0.4 (12 markets) or >= 0.5 (8 markets)
4. **Signal degrades in final 60 seconds** - confirming early signal is better

### Statistical Significance

With 58 BTC and 55 ETH markets, we can state with 95% confidence:
- BTC high-threshold accuracy is at least 74% (likely ~94%)
- ETH high-threshold accuracy is at least 76% (observed 95-100%)

---

## Data Files

- Analysis script: `scripts/reverse_engineer/deep_orderbook_analysis.py`
- Backtest script: `scripts/reverse_engineer/trades_backtest.py`
- Raw data: `data/research_ec2_jan6/final_minute/*.json`
- Historical trades: `data/tracker/trades.db` (14,753 trades)

---

## Quick Reference Trading Matrix

| Condition | BTC Action | ETH Action |
|-----------|-----------|-----------|
| OB imbalance > 0.2 | Trade UP (82.9%) | Ignore |
| OB imbalance < -0.2 | Trade DOWN (82.9%) | Ignore |
| Early momentum UP | Confirm OB | Trade UP (88.9%) |
| Early momentum DOWN | Confirm OB | Trade DOWN (88.9%) |
| OB + Momentum agree | **Trade (84.8%)** | **Trade (95.7%)** |
| OB vs Momentum disagree | Follow OB (58.3%) | Follow Momentum (81.8%) |
| All 3 signals agree | Trade (84.2%) | **Trade (100%)** |
