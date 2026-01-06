# Compound Growth Backtest Results

**Generated:** 2026-01-06 15:32 UTC
**Initial Capital:** $300
**Data Source:** trades.db (Account88888 trades with known outcomes)

---

## Executive Summary

- **Best Return:** kelly_conf60 (+902.2%)
- **Best Risk-Adjusted:** fixed_1pct_conf60 (Sharpe: 73.28)
- **Lowest Drawdown:** fixed_1pct_conf60 (3.0%)

---

## Results Summary

| Strategy | Conf | Trades | Return | Final $ | Max DD | Sharpe | Win Rate | PF |
|----------|------|--------|--------|---------|--------|--------|----------|-----|
| fixed_1pct | 0.4 | 57 | +25.9% | $378 | 7.5% | 24.24 | 50.9% | 1.81 |
| fixed_1pct | 0.5 | 29 | +25.3% | $376 | 4.9% | 34.85 | 51.7% | 2.61 |
| fixed_1pct | 0.6 | 12 | +33.5% | $400 | 3.0% | 73.28 | 66.7% | 7.98 |
| fixed_2pct | 0.4 | 57 | +50.9% | $453 | 12.8% | 23.03 | 50.9% | 1.71 |
| fixed_2pct | 0.5 | 29 | +50.0% | $450 | 9.6% | 33.53 | 51.7% | 2.43 |
| fixed_2pct | 0.6 | 12 | +70.4% | $511 | 5.9% | 71.73 | 66.7% | 7.26 |
| fixed_5pct | 0.4 | 57 | +111.5% | $635 | 29.8% | 19.37 | 50.9% | 1.50 |
| fixed_5pct | 0.5 | 29 | +114.2% | $643 | 18.1% | 29.55 | 51.7% | 2.04 |
| fixed_5pct | 0.6 | 12 | +197.7% | $893 | 14.3% | 67.45 | 66.7% | 5.76 |
| half_kelly | 0.4 | 56 | +14.8% | $344 | 86.5% | 1.14 | 50.0% | 1.02 |
| half_kelly | 0.5 | 28 | +107.2% | $621 | 58.4% | 10.91 | 50.0% | 1.22 |
| half_kelly | 0.6 | 12 | +894.8% | $2984 | 20.0% | 51.81 | 66.7% | 2.92 |
| kelly | 0.4 | 56 | +18.2% | $355 | 86.4% | 1.39 | 50.0% | 1.03 |
| kelly | 0.5 | 28 | +109.3% | $628 | 58.0% | 11.09 | 50.0% | 1.22 |
| kelly | 0.6 | 12 | +902.2% | $3006 | 20.0% | 52.23 | 66.7% | 2.93 |
| quarter_kelly | 0.4 | 56 | +118.7% | $656 | 63.0% | 9.93 | 50.0% | 1.20 |
| quarter_kelly | 0.5 | 28 | +165.7% | $797 | 40.9% | 19.80 | 50.0% | 1.50 |
| quarter_kelly | 0.6 | 12 | +561.8% | $1985 | 33.0% | 58.62 | 66.7% | 3.86 |

---

## Position Sizing Strategy Comparison

### Fixed Fraction Strategies

Fixed fraction strategies bet a constant percentage of current capital.

- **1PCT:** Avg Return +28.2%, Avg Max DD 5.1%
- **2PCT:** Avg Return +57.1%, Avg Max DD 9.4%
- **5PCT:** Avg Return +141.2%, Avg Max DD 20.7%

### Kelly Criterion Strategies

Kelly criterion optimizes position size for maximum compound growth.

- **quarter_kelly:** Avg Return +282.1%, Avg Max DD 45.6%, Avg Sharpe 29.45
- **half_kelly:** Avg Return +338.9%, Avg Max DD 55.0%, Avg Sharpe 21.29
- **kelly:** Avg Return +343.2%, Avg Max DD 54.8%, Avg Sharpe 21.57

---

## Confidence Threshold Analysis

Higher thresholds filter for higher-confidence signals.

- **Confidence >= 0.4:** 56 avg trades, +56.7% avg return, 50.4% win rate
- **Confidence >= 0.5:** 28 avg trades, +95.3% avg return, 50.9% win rate
- **Confidence >= 0.6:** 12 avg trades, +443.4% avg return, 66.7% win rate

---

## Growth Curves

Capital growth over time for select strategies:

```
Strategy                     Start     End       Return
-------------------------------------------------------
kelly_conf60                 $300     $3006     +902.2%
half_kelly_conf60            $300     $2984     +894.8%
quarter_kelly_conf60         $300     $1985     +561.8%
fixed_5pct_conf60            $300     $893     +197.7%
quarter_kelly_conf50         $300     $797     +165.7%
quarter_kelly_conf40         $300     $656     +118.7%
```

---

## Risk Analysis

### Drawdown Distribution

| Strategy | Max Drawdown | Recovery Factor* |
|----------|--------------|------------------|
| fixed_1pct_conf60 | 3.0% | 11.26 |
| fixed_1pct_conf50 | 4.9% | 5.17 |
| fixed_2pct_conf60 | 5.9% | 11.97 |
| fixed_1pct_conf40 | 7.5% | 3.44 |
| fixed_2pct_conf50 | 9.6% | 5.21 |
| fixed_2pct_conf40 | 12.8% | 3.98 |
| fixed_5pct_conf60 | 14.3% | 13.86 |
| fixed_5pct_conf50 | 18.1% | 6.33 |
| kelly_conf60 | 20.0% | 45.11 |
| half_kelly_conf60 | 20.0% | 44.74 |
| fixed_5pct_conf40 | 29.8% | 3.74 |
| quarter_kelly_conf60 | 33.0% | 17.02 |
| quarter_kelly_conf50 | 40.9% | 4.05 |
| kelly_conf50 | 58.0% | 1.88 |
| half_kelly_conf50 | 58.4% | 1.84 |
| quarter_kelly_conf40 | 63.0% | 1.88 |
| kelly_conf40 | 86.4% | 0.21 |
| half_kelly_conf40 | 86.5% | 0.17 |

*Recovery Factor = Total Return / Max Drawdown (higher is better)

---

## Recommendations

Based on the backtest results with $300 capital constraint:

### Recommended Strategy: **fixed_2pct** with confidence >= 0.6

- Expected return: +70.4%
- Max drawdown: 5.9%
- Sharpe ratio: 71.73
- Win rate: 66.7%

### Capital Constraints Compliance

Per CLAUDE.md:
- Max $15/trade (5% of $300) - quarter_kelly and fixed strategies comply
- Max $30/day loss - monitor with circuit breaker

---

## Methodology

### Data
- Source: `data/tracker/trades.db`
- Trades with known UP/DOWN resolution outcomes
- One trade per 15-minute market window

### Position Sizing

1. **Fixed (1%, 2%, 5%):** Constant fraction of capital
2. **Quarter Kelly:** 25% of optimal Kelly fraction
3. **Half Kelly:** 50% of optimal Kelly fraction
4. **Full Kelly:** Theoretically optimal (high variance)

### Fee Model

Variable taker fee: ~3% at 50% odds, ~0% at extremes
```python
fee = 0.03 * (1 - (|odds - 0.5| / 0.5)^2)
```

### Confidence Thresholds

From MODEL_IMPROVEMENTS.md:
- >= 0.4: ~90.2% expected accuracy
- >= 0.5: ~92% expected accuracy
- >= 0.6: ~94.2% expected accuracy

---

*Generated by compound_growth_backtester.py on 2026-01-06 15:32 UTC*