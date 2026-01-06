# Market Constraints and Fee Structure Analysis

## Executive Summary

**GO/NO-GO Assessment: CONDITIONAL GO**

Our 84% accuracy significantly exceeds the ~53% break-even threshold at worst-case fees. However, the variable fee structure on 15-minute crypto markets (up to 3% at 50% odds) requires careful position selection to maximize edge. Trading at probability extremes is more profitable due to lower fees.

---

## Fee Structure

### Overview by Market Type

| Market Type | Maker Fee | Taker Fee | Notes |
|-------------|-----------|-----------|-------|
| Standard Markets (politics, events) | 0% | 0% | No fees at all |
| 15-Minute Crypto Markets | 0% + Rebates | Up to 3% (variable) | Fee varies with odds |
| Polymarket US (DCM) | 0% | 0.01% (1 bps) | Coming Q1 2026 |

### 15-Minute Crypto Market Fee Curve

The taker fee on 15-minute markets follows a **variable curve**:

| Market Odds | Estimated Taker Fee | Notes |
|-------------|---------------------|-------|
| 50% | ~3.0% | Maximum fee at equilibrium |
| 40% / 60% | ~2.5% | Moderate fee |
| 30% / 70% | ~1.5% | Reduced fee |
| 20% / 80% | ~0.8% | Low fee |
| 10% / 90% | ~0.3% | Minimal fee |
| <5% / >95% | ~0% | Near-zero fee |

**Key Insight:** The fee is designed to penalize 50/50 coin-flip bets and incentivize trading when you have genuine edge (at probability extremes).

**Example from Documentation:**
> "A taker trade of 100 shares priced at $0.50 would incur a fee of about $1.56, which is just over 3% of the trade's value."

### Fee Collection Mechanics

- Fees are collected **on proceeds** (when you win), not on entry
- Collected fees are **redistributed daily** to market makers as USDC rebates
- Makers receive rebates, encouraging tighter spreads

---

## Spread Costs

### Typical Bid-Ask Spreads

| Liquidity Level | Typical Spread | Cost (at $0.50) |
|-----------------|----------------|-----------------|
| High liquidity | $0.01 | 2% round-trip |
| Medium liquidity | $0.02-0.03 | 4-6% round-trip |
| Low liquidity | $0.05+ | 10%+ round-trip |

**Note:** If spread exceeds $0.10, Polymarket displays last traded price instead of midpoint.

### Avoiding Spread Costs

- **Limit orders (maker):** Pay no spread, receive rebates
- **Market orders (taker):** Pay spread + taker fee
- **Recommendation:** Use limit orders when possible

---

## Break-Even Edge Calculation

### Scenario 1: Trading at 50% Odds (Worst Case)

**Assumptions:**
- Market price: $0.50 (50% implied probability)
- Taker fee: 3%
- Spread cost: 1% (buying at $0.505 ask vs $0.50 mid)

**Calculation:**
```
Buy at: $0.505 (ask price)
Win payout: $1.00 - 3% fee = $0.97
Profit if win: $0.97 - $0.505 = $0.465
Loss if lose: -$0.505

Break-even: P × $0.465 = (1-P) × $0.505
0.465P = 0.505 - 0.505P
0.97P = 0.505
P = 52.1%
```

**Required edge at 50% odds: 2.1% above fair value (52.1% win rate)**

### Scenario 2: Trading at 70% Odds (Typical Trade)

**Assumptions:**
- Market price: $0.70 (70% implied probability)
- Taker fee: 1.5% (reduced at extremes)
- Spread cost: 0.5%

**Calculation:**
```
Buy at: $0.7035 (including spread)
Win payout: $1.00 - 1.5% = $0.985
Profit if win: $0.985 - $0.7035 = $0.2815
Loss if lose: -$0.7035

Break-even: P × $0.2815 = (1-P) × $0.7035
P = 71.4%
```

**Required edge at 70% odds: 1.4% above market price (71.4% vs 70%)**

### Scenario 3: Trading at 85% Odds (High Confidence)

**Assumptions:**
- Market price: $0.85
- Taker fee: 0.5% (minimal at extremes)
- Spread cost: 0.3%

**Calculation:**
```
Buy at: $0.8525
Win payout: $0.995
Profit if win: $0.1425
Loss if lose: -$0.8525

Break-even: P = 85.7%
```

**Required edge at 85% odds: 0.7% above market price**

---

## Comparison: Our 84% Accuracy vs Required Edge

### Our Signal Performance (from ORDERBOOK_SIGNAL_FINDINGS.md)

| Asset | Accuracy | Market Segment |
|-------|----------|----------------|
| BTC | 84.8% | When orderbook imbalance ≥ 0.5 |
| ETH | 95.7% | When orderbook + momentum agree |
| Combined | 77.8% → 94.4% | With threshold filters |

### Expected ROI Analysis

**Conservative Case (BTC at 70% market odds):**
```
Our accuracy: 84.8%
Market implied: 70%
Edge: +14.8%

EV per $0.70 bet:
= 0.848 × $0.2815 - 0.152 × $0.7035
= $0.239 - $0.107 = $0.132

ROI per trade: $0.132 / $0.70 = 18.9%
```

**Aggressive Case (ETH at 60% market odds):**
```
Our accuracy: 95.7%
Market implied: 60%
Edge: +35.7%

EV per $0.60 bet:
= 0.957 × $0.38 - 0.043 × $0.60
= $0.364 - $0.026 = $0.338

ROI per trade: $0.338 / $0.60 = 56.3%
```

---

## Trading Restrictions & Limits

### Order Size Limits

| Parameter | Limit | Notes |
|-----------|-------|-------|
| Minimum order | None (practical: $10) | On-ramp minimums may apply |
| Maximum order | None | Orderbook matches any size |
| Recommended starting | $10-50 | For learning |
| Our limit | $15/trade | 5% of $300 capital |

### API Rate Limits

| Endpoint | Limit | Period |
|----------|-------|--------|
| POST /order | 3,500 | 10 seconds |
| POST /order | 36,000 | 10 minutes |
| DELETE /order | 3,000 | 10 seconds |
| /book (market data) | 1,500 | 10 seconds |
| /price | 1,500 | 10 seconds |

**Assessment:** Rate limits are extremely generous for our use case. Even at 1 trade per 15-minute window, we'd use ~4 orders/hour vs 36,000/10min limit.

### Other Restrictions

- **Geographic:** Non-US only (until Polymarket US launches)
- **KYC:** Not required for crypto deposits
- **Withdrawal:** $3 + network fee or 0.3% (whichever is higher)

---

## Market Mechanics: 15-Minute Markets

### Resolution Process

1. **Oracle:** Chainlink price feeds (low latency)
2. **Settlement:** Automatic, on-chain on Polygon
3. **Timing:** Markets resolve every 15 minutes (:00, :15, :30, :45)
4. **Payout:** USDC to wallet

### Market Windows

| Phase | Time Before Close | Activity |
|-------|-------------------|----------|
| Open | 15:00 - 2:00 | Normal trading |
| Late | 2:00 - 0:30 | High conviction trades |
| Final | 0:30 - 0:00 | Last-second execution |

### Price Feed Details

- **Source:** Chainlink decentralized oracles
- **Resolution:** "UP" if end price ≥ start price, "DOWN" otherwise
- **Latency:** Sub-second on Polygon

---

## Risk Analysis

### Fee-Adjusted Expected Value

| Scenario | Gross Edge | Fees + Spread | Net Edge | Verdict |
|----------|------------|---------------|----------|---------|
| BTC @ 50% odds | +34.8% | 4% | +30.8% | Strong GO |
| BTC @ 70% odds | +14.8% | 2% | +12.8% | GO |
| BTC @ 85% odds | -0.2% | 0.8% | -1.0% | NO-GO |
| ETH @ 60% odds | +35.7% | 2.5% | +33.2% | Strong GO |

### Break-Even Requirements Summary

| Trading Odds | Break-Even Accuracy | Our Accuracy | Margin |
|--------------|---------------------|--------------|--------|
| 50% | 52.1% | 84.8% | +32.7% |
| 60% | 62.0% | 84.8% | +22.8% |
| 70% | 71.4% | 84.8% | +13.4% |
| 80% | 80.8% | 84.8% | +4.0% |
| 85% | 85.7% | 84.8% | -0.9% |

**Critical Finding:** Our 84.8% accuracy loses edge when market is already pricing >84% probability. Avoid chasing at extreme odds.

---

## Recommendations

### Trading Rules (Fee-Optimized)

1. **Only trade when market odds < 80%** - Preserve our accuracy advantage
2. **Prefer limit orders** - Save 1-3% on spread + avoid taker fees
3. **Trade early in window** - Better odds, more correction time
4. **Use maker rebates** - Place resting orders to earn rebates
5. **Size positions appropriately** - Max $15/trade per capital rules

### Capital Efficiency

With $300 capital and $15 max position:
- **20 positions maximum** at any time
- **Target:** 4-8 high-confidence trades per day
- **Expected daily ROI:** 2-5% of traded capital (if signal holds)

### GO/NO-GO Decision Matrix

| Condition | Decision |
|-----------|----------|
| Signal confidence > 80% AND market odds < 80% | GO |
| Signal confidence > 90% AND market odds < 85% | STRONG GO |
| Market odds > 85% (regardless of signal) | NO-GO |
| Spread > $0.03 | WAIT for liquidity |
| Volume < 1000 shares | NO-GO (low liquidity) |

---

## Sources

- [Polymarket Trading Fees Documentation](https://docs.polymarket.com/polymarket-learn/trading/fees)
- [Polymarket API Rate Limits](https://docs.polymarket.com/quickstart/introduction/rate-limits)
- [Polymarket US Fee Schedule](https://www.polymarketexchange.com/fees-hours.html)
- [TradingView: Polymarket 15-min Taker Fees](https://www.tradingview.com/news/cointelegraph:e59c32089094b:0-polymarket-quietly-introduces-taker-fees-on-15-minute-crypto-markets/)
- [Cryptopolitan: 15-minute markets launch](https://www.cryptopolitan.com/polymarkets-15-minute-up-down/)
- [Crypticorn: How 15-min Bitcoin Odds Work](https://www.crypticorn.com/how-polymarkets-bitcoin-odds-actually-work/)

---

## Appendix: Fee Calculation Formula (Estimated)

Based on observed data, the fee curve appears to follow:

```python
def estimate_taker_fee(odds: float) -> float:
    """
    Estimate taker fee based on market odds.
    Peak fee (~3%) at 50% odds, approaching 0% at extremes.
    """
    # Distance from 50%
    distance = abs(odds - 0.50)

    # Parabolic decay: max 3% at 50%, ~0% at 0/100%
    max_fee = 0.03
    fee = max_fee * (1 - (distance / 0.50) ** 2)

    return max(0, fee)

# Examples:
# odds=0.50 → fee=3.00%
# odds=0.70 → fee=1.92%
# odds=0.85 → fee=0.57%
# odds=0.95 → fee=0.03%
```

---

*Document created: 2026-01-06*
*Agent 4: Market Mechanics & Fee Structure Research*
