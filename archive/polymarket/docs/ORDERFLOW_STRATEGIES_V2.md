# Orderflow Strategies Research V2
## Additional Data Providers, Tools & Actionable Strategies

**Date:** 2026-01-06
**Purpose:** Supplement existing orderflow research with new data providers, platforms, and strategies
**Budget Constraint:** $300 capital

---

## Executive Summary

This research expands on our existing orderflow knowledge base with:
1. **New Free Tools**: Kiyotaka (free Z-score indicators), CoinGlass (free web dashboard)
2. **Paid Platforms**: Exocharts ($28-49/mo), TradingLite ($14.95-24.95/mo)
3. **New Strategy Framework**: Delta vs Liquidity trading from Tradingriot
4. **Funding Rate Arbitrage**: Market-neutral strategy with ~33% annualized returns
5. **Options Flow Data**: 25-delta risk reversals for directional bias

### Key Finding for Our Project

Given our constraint (Account88888's +0.85% edge wiped out by 3% fees), the most promising paths are:

1. **Low-Odds Markets (0-20%)**: +7.4% edge, lower fees (~0.5-1%)
2. **Funding Rate Signals**: Use as contrarian indicator, not arbitrage
3. **Liquidation Cluster Fading**: Trade against cascades at exhaustion

---

## 1. New Data Providers & Tools Discovered

### 1.1 Kiyotaka (FREE - RECOMMENDED)

**URL:** https://kiyotaka.ai/

**What It Offers:**
- **Z-Score Indicators**: Pre-built indicators for OI, funding, liquidations
- **Aggregated Volume Footprints**: Merges orderflow from 14+ exchanges
- **Order Book Skew Z-Score**: Identifies aggressive order pulling
- **Put-to-Call Ratio**: Options sentiment tracking
- **Bid-Ask Depth Imbalance**: Shows orderflow imbalance at different depths

**Free Features:**
- Open Levels (daily, weekly, monthly, yearly)
- Bid-Ask Depth Imbalance indicator
- Put to Call Ratio indicator
- Community-shared Z-score indicators (search "abetrade")

**Why It's Valuable:**
- Eliminates guesswork with statistical Z-score approach
- Free access to sophisticated derivatives data
- Aggregated view across major exchanges

**How to Use:**
```
Signal: OI Z-Score > 2.0 + Funding Z-Score > 2.0 + Price at resistance
Action: Consider short bias (overlevered longs)

Signal: OI Z-Score < -2.0 + Funding Z-Score < -2.0 + Price at support
Action: Consider long bias (overlevered shorts)
```

---

### 1.2 Exocharts (PAID: $28-49/month)

**URL:** https://exocharts.com/

**Pricing:**
| Plan | Monthly | 6-Month |
|------|---------|---------|
| Desktop Pro | $49 | $38/mo |
| Web Premium | $28 | $23/mo |

**Features:**
- Footprint charts overlaid on volume profile (unique capability)
- Supported exchanges: BitMEX, Bybit, Binance (Spot/USD-M/COIN-M)
- 6 years of tick-by-tick historical data
- DOM, liquidations, open interest indicators
- VWAP, Bid-Ask Imbalance built-in

**Free Mode:** Limited to SHIBA, DOGE, SOLANA pairs

**Best For:** Serious orderflow traders who need footprint + profile overlays

---

### 1.3 TradingLite (PAID: $14.95-24.95/month)

**URL:** https://tradinglite.com/

**Pricing:**
| Plan | Monthly | Yearly |
|------|---------|--------|
| Silver | $14.95 | $155.40 |
| Gold | $24.95 | $251.40 |

**Features:**
- Real-time liquidity heatmap
- 500+ community indicators
- LitScript custom scripting language
- 15+ exchanges, 400+ pairs
- 3+ years historical data

**Free Trial:** 14 days

**Best For:** Traders who want heatmap visualization and custom indicator creation

---

### 1.4 CoinGlass Liquidation Heatmap (FREE Web)

**URL:** https://www.coinglass.com/pro/futures/LiquidationHeatMap

**What It Shows:**
- Estimated liquidation clusters by price level
- Based on leverage distribution across exchanges
- Historical liquidation data

**Why It Matters:**
- Price tends to move toward liquidation clusters (liquidity hunting)
- Liquidation cascades cause 2-10% rapid moves
- Key levels for stop placement and targets

**2025 Market Context:**
- November 21, 2025: $2.0B liquidated in 24 hours
- September 2025: $1.7B liquidated, $1.6B from longs
- Derivatives = ~75-80% of total crypto volume

**Trading Application:**
```
Setup: Price approaching major liquidation cluster
Signal: Volume spike + CVD divergence at cluster edge
Action: Fade the cascade after exhaustion
Target: Mean reversion to pre-cascade levels
Stop: Beyond cascade extreme
```

---

### 1.5 Options Flow Data Sources

**Primary Source:** Deribit (dominates with $46B of $55B total BTC options OI)

**Free Data:**
- CoinGlass: https://www.coinglass.com/options/Deribit
- The Block: https://www.theblock.co/data/crypto-markets/options

**Paid Data:**
- AD Derivatives (Amberdata): Institutional-grade analytics
- Deribit Insights: https://insights.deribit.com/

**Key Metrics:**
- **25-Delta Risk Reversals**: IV(call) - IV(put)
  - Z-Score > 2.0 = High put skew (bearish sentiment)
  - Z-Score < -2.0 = High call skew (bullish sentiment)
- **Max Pain**: Price where most options expire worthless
- **Put-Call Ratio**: Below 0.4 = bullish, above 0.6 = bearish

---

## 2. New Orderflow Strategies from Tradingriot

Source: https://tradingriot.com/orderflow-trading/

### 2.1 Delta vs Liquidity Framework

**Core Concept:**
- **Delta** = Executed orders (real commitment)
- **Liquidity** = Resting orders (can be fake/spoofed)
- Trade based on delta, not liquidity

### 2.2 CVD Absorption Pattern (HIGHEST PROBABILITY)

**Setup:**
- CVD reaches new extreme (higher CVD high or lower CVD low)
- Price does NOT make corresponding extreme
- Indicates aggressive orders being absorbed by passive liquidity

**Trading Rules:**
```
Bullish Absorption:
- CVD makes higher low
- Price makes lower low (or equal low)
- Signal: Selling pressure absorbed, reversal likely
- Entry: On first bullish delta candle
- Stop: Below absorption low
- Target: Previous swing high or VAH

Bearish Absorption:
- CVD makes lower high
- Price makes higher high (or equal high)
- Signal: Buying pressure absorbed, reversal likely
- Entry: On first bearish delta candle
- Stop: Above absorption high
- Target: Previous swing low or VAL
```

**Why It Works:**
- Shows institutional passive orders absorbing retail aggression
- Indicates smart money positioning opposite to price direction

---

### 2.3 Single Bar Delta Divergence

**Setup:**
- Up candle closes with negative delta
- OR down candle closes with positive delta
- Best at structural support/resistance levels

**Trading Rules:**
```
At Resistance:
- Green candle with delta < -500 (filter for significance)
- Shows buyers absorbed despite up close
- Entry: Short on next candle
- Stop: Above resistance

At Support:
- Red candle with delta > +500
- Shows sellers absorbed despite down close
- Entry: Long on next candle
- Stop: Below support
```

---

### 2.4 Limit-Driven Breakout

**Setup:**
- Large price bar (breakout)
- Minimal CVD change (delta near zero)
- Indicates move driven by passive limit orders, not aggression

**Implication:**
- Move has high conviction (large resting orders)
- Often leads to continuation with minimal pullback
- Best for trend-following, not mean reversion

---

### 2.5 Delta Y-Axis Profile Strategy

**Concept:** Plot cumulative delta per price level through session

**Trading Application:**
```
Long Setup:
- Find price level with high NEGATIVE delta (trapped shorts)
- Enter long at this level
- Target: Shorts covering drives price higher

Short Setup:
- Find price level with high POSITIVE delta (trapped longs)
- Enter short at this level
- Target: Longs exiting drives price lower
```

---

## 3. Funding Rate Strategies

### 3.1 Funding Rate Arbitrage (Market-Neutral)

**How It Works:**
1. When funding is positive (longs pay shorts):
   - Buy spot BTC
   - Short equivalent perpetual position
   - Collect funding every 8 hours

2. When funding is negative (shorts pay longs):
   - Short spot BTC (borrow and sell)
   - Long equivalent perpetual position
   - Collect funding every 8 hours

**Expected Returns (2025 Data):**
- Average funding: 0.015% per 8 hours (50% higher than 2024)
- Annualized: ~16.4% at average funding
- High funding (0.03%): ~32.95% annualized
- Extreme funding (0.1%): ~100%+ annualized

**Example Calculation:**
```
Position: $2,000 each side (spot + perp)
Funding: 0.03% per 8 hours
Income: $2,000 × 0.03% = $0.60 per 8 hours
Daily: $0.60 × 3 = $1.80
Annual: $1.80 × 365 = $657
ROI: $657 / $2,000 = 32.85%
```

**Why NOT Suitable for Our Project:**
- Requires capital on both spot and futures
- $300 budget = $150 each side = $0.045/day = $16.43/year
- Transaction costs would exceed returns at this scale
- Better suited for $10K+ capital

Source: [Gate.com Funding Rate Arbitrage Guide](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166)

---

### 3.2 Funding Rate as Contrarian Signal (FOR OUR PROJECT)

**Better Approach for Small Capital:**

Instead of arbitrage, use extreme funding as a mean reversion signal:

**Setup:**
```
Extreme Positive Funding (>0.05% per 8h):
- Market is overlevered long
- Look for short opportunities at resistance
- Combine with: Price at VAH, RSI >70, bearish CVD divergence

Extreme Negative Funding (<-0.05% per 8h):
- Market is overlevered short
- Look for long opportunities at support
- Combine with: Price at VAL, RSI <30, bullish CVD divergence
```

**Why This Works:**
- Extreme funding often precedes liquidation cascades
- We trade the aftermath, not during the cascade
- No capital split required

---

## 4. Order Book Strategies (from Tradingriot)

Source: https://tradingriot.com/order-book/

### 4.1 Spot vs Futures Order Book

**Key Insight:**
- **Focus on SPOT order books, not futures**
- Large players leave genuine orders in spot markets
- Futures books are mostly market maker liquidity (not directional)

**Why:**
- Spot traders have longer holding periods
- Genuine supply/demand signals
- Less susceptible to manipulation

### 4.2 Order Book Depth Analysis by Timeframe

| Trading Style | Order Book Depth to Monitor |
|---------------|----------------------------|
| Scalping | 1-2.5% from market price |
| Intraday Swing | 5% from market price |
| Multi-day Swing | 10% from market price |

### 4.3 Order Book Skew Strategy

**Setup:**
- Calculate bid/ask volume ratio at relevant depth
- High skew (heavy bids or asks) suggests directional bias

**Trading Rules:**
```
High Bid Skew (bids >> asks):
- Expect support, look for longs
- Warning: Can indicate range-bound market

High Ask Skew (asks >> bids):
- Expect resistance, look for shorts
- Warning: Can indicate range-bound market

Aggressive Order Pulling:
- One side rapidly removes orders
- Creates "air pocket" for price to move through
- Trade in direction of pulled orders
```

**Best Platforms for OB Analysis:**
- Trdr.io (aggregated)
- Mobchart (wider coin selection)
- CoinGlass (free tier)

---

## 5. Liquidation Cascade Strategy

### 5.1 Understanding Liquidation Dynamics

**Cascade Mechanics:**
1. Price hits liquidation cluster
2. Forced closes create market orders in same direction
3. This moves price further into next cluster
4. Self-reinforcing loop creates waterfall/squeeze

**2025 Statistics:**
- BTC futures OI reached $94.12B (October 2025)
- Single-day record: $2.0B liquidated (November 21, 2025)
- Derivatives = 75-80% of crypto volume

### 5.2 Trading the Cascade Aftermath

**DO NOT trade INTO cascades** - price action is unpredictable

**WAIT for cascade exhaustion, then fade:**

**Setup:**
```
1. Identify major liquidation cluster on CoinGlass heatmap
2. Wait for price to pierce cluster
3. Watch for exhaustion signals:
   - Volume declining on successive pushes
   - CVD divergence forming
   - Rejection wicks appearing
   - Delta flipping opposite direction
4. Enter mean reversion trade
5. Target: Pre-cascade price level
6. Stop: Beyond cascade extreme
```

**Why This Works:**
- Cascades are mechanical, not fundamental
- Forced liquidations = temporary price dislocation
- Mean reversion probability high after exhaustion
- Large R:R opportunities (2:1 to 5:1)

---

## 6. Recommended Implementation for Our Project

### 6.1 Given Our Constraints

**Capital:** $300
**Current Edge:** +0.85% (Account88888)
**Problem:** 3% taker fees exceed edge
**Win Rate:** 47.5% raw, varies by price bucket

### 6.2 Highest Probability Strategies

#### Strategy A: Low-Odds Market Focus

From our STRATEGY_REEVALUATION.md:
- 0-10% price range: +7.4% edge
- 10-20% price range: +2.6% edge
- Taker fees at extremes: ~0.5-1%
- **Net Edge: +5.4% to +6.9%**

**Implementation:**
```
1. Filter for markets with prices 0-20%
2. Apply existing signal model
3. Only trade when model confidence >= 0.4
4. Use orderflow confirmation (CVD divergence, absorption)
```

#### Strategy B: Liquidation Fade with Orderflow Confirmation

**Implementation:**
```
1. Monitor CoinGlass liquidation heatmap (free)
2. Identify major liquidation clusters ahead of price
3. Wait for price to hit cluster
4. Confirm exhaustion via:
   - Kiyotaka Z-score indicators (free)
   - CVD divergence on TradingView
5. Enter mean reversion trade
6. R:R target: 2:1 minimum
```

#### Strategy C: Extreme Funding + Technical Confluence

**Implementation:**
```
1. Monitor funding rates on CoinGlass (free)
2. Alert when |funding| > 0.05% per 8h
3. Wait for technical setup:
   - Price at VAH (for shorts) or VAL (for longs)
   - RSI extreme (>70 or <30)
   - CVD divergence
4. Enter trade with orderflow confirmation
```

### 6.3 Recommended Tool Stack (Minimal Cost)

| Tool | Cost | Purpose |
|------|------|---------|
| Kiyotaka | FREE | Z-score indicators, aggregated CVD |
| CoinGlass Web | FREE | Liquidation heatmap, funding rates, OI |
| TradingView | FREE tier | Charting, RSI, Bollinger Bands |
| Binance WebSocket | FREE | Real-time data for execution |
| **Total** | **$0/month** | Complete analysis stack |

### 6.4 Optional Paid Upgrades (If Profitable)

| Tool | Cost | When to Consider |
|------|------|------------------|
| TradingLite | $14.95/mo | After 3 months profitability |
| Exocharts | $28/mo | If footprint analysis shows edge |
| Tradingriot Course | $897 one-time | If serious about orderflow education |
| Tardis.dev | $50-100/mo | For backtesting historical data |

---

## 7. Strategy Comparison Matrix

| Strategy | Edge Potential | Fee Drag | Capital Needed | Complexity | Recommended? |
|----------|---------------|----------|----------------|------------|--------------|
| Low-Odds Focus | +5-7% | Low (1%) | $300 | Low | **YES** |
| Liquidation Fade | +3-5% | Medium (1-2%) | $300 | Medium | **YES** |
| Funding Rate Signal | +2-3% | Medium (1-2%) | $300 | Medium | **YES** |
| CVD Absorption | +2-4% | Variable | $300 | High | **MAYBE** |
| Funding Arbitrage | +16-33% | Low | $10K+ | High | **NO** (capital) |
| Delta Y-Axis Profile | +2-4% | Variable | $300 | Very High | **NO** (complexity) |

---

## 8. Risk Management Updates

### 8.1 Position Sizing with Orderflow

**Base Rules (unchanged):**
- Max $15/trade (5% of $300)
- Max $30/day loss
- Kill switch required

**Enhanced Rules with Orderflow:**
```
Tier 1 Signal (all confirm):
- Technical setup + orderflow confirmation + extreme funding
- Position: Full size ($15)

Tier 2 Signal (partial confirm):
- Technical setup + one orderflow signal
- Position: Half size ($7.50)

Tier 3 Signal (technical only):
- Technical setup without orderflow confirm
- Position: Skip trade or quarter size ($3.75)
```

### 8.2 Exit Management with CVD

**Profit Taking:**
- If CVD diverges against position → Take 50% profit
- If CVD continues in position direction → Hold for full target

**Stop Loss:**
- If CVD confirms stop level (aggressive flow against you) → Exit immediately
- If CVD neutral at stop → May give small buffer

---

## 9. Implementation Roadmap

### Phase 1: Setup (Week 1)
- [ ] Create accounts on Kiyotaka (free)
- [ ] Bookmark CoinGlass dashboards (free)
- [ ] Set up TradingView with RSI, Bollinger Bands, Volume
- [ ] Configure alerts for extreme funding (>0.05%)
- [ ] Configure alerts for major liquidation levels

### Phase 2: Paper Trading (Weeks 2-3)
- [ ] Log all signals with orderflow confirmation
- [ ] Track hypothetical entries/exits
- [ ] Measure hit rate of orderflow confirmation
- [ ] Compare with vs without orderflow filter

### Phase 3: Live Testing (Weeks 4-6)
- [ ] Start with Tier 1 signals only
- [ ] Trade at half size ($7.50)
- [ ] Track actual vs expected results
- [ ] Iterate on confirmation requirements

### Phase 4: Optimization (Month 2+)
- [ ] Analyze which orderflow signals add most value
- [ ] Consider paid tools if edge demonstrated
- [ ] Scale position sizes if profitable
- [ ] Document successful patterns

---

## 10. Key Takeaways

### What's New in This Research

1. **Free Tools Discovered:**
   - Kiyotaka provides Z-score indicators for OI, funding, liquidations
   - These eliminate subjective "extreme" judgments

2. **Delta vs Liquidity Framework:**
   - Trade based on executed orders, not resting orders
   - CVD absorption patterns are highest probability

3. **Spot vs Futures Order Book:**
   - Focus on spot order books for genuine signals
   - Futures books are market maker noise

4. **Liquidation Cascade Fading:**
   - Don't trade during cascades
   - Fade AFTER exhaustion for high R:R

5. **Funding as Signal (not Arbitrage):**
   - Arbitrage requires $10K+ capital
   - Use extreme funding as contrarian indicator instead

### Core Message

**Our best path to profitability combines:**
1. Focus on low-odds markets (0-20%) where we have +7.4% edge
2. Use free orderflow tools (Kiyotaka, CoinGlass) for confirmation
3. Fade liquidation cascades after exhaustion
4. Use extreme funding as directional signal
5. Only trade when multiple signals confirm

---

## 11. Sources & References

### Educational Resources
- [Tradingriot Orderflow Trading Guide](https://tradingriot.com/orderflow-trading/)
- [Tradingriot Cryptocurrency Data](https://tradingriot.com/cryptocurrency-data/)
- [Tradingriot Order Book Analysis](https://tradingriot.com/order-book/)

### Data Platforms
- [Kiyotaka Trading Platform](https://kiyotaka.ai/)
- [Exocharts](https://exocharts.com/)
- [TradingLite](https://tradinglite.com/)
- [CoinGlass Liquidation Heatmap](https://www.coinglass.com/pro/futures/LiquidationHeatMap)
- [CoinGlass Options Data](https://www.coinglass.com/options/Deribit)

### Strategy Research
- [Gate.com Funding Rate Arbitrage 2025](https://www.gate.com/learn/articles/perpetual-contract-funding-rate-arbitrage/2166)
- [Amberdata Funding Rate Arbitrage Guide](https://blog.amberdata.io/the-ultimate-guide-to-funding-rate-arbitrage-amberdata)
- [CoinGlass Liquidation Trading Guide](https://www.coinglass.com/learn/how-to-use-liqmap-to-assist-trading-en)

### Options Data
- [Deribit Insights](https://insights.deribit.com/)
- [The Block Options Data](https://www.theblock.co/data/crypto-markets/options)
- [AD Derivatives (Amberdata)](https://www.amberdata.io/ad-derivatives)

### Orderflow Platforms
- [ATAS Volume Analysis](https://atas.net/)
- [Bookmap Crypto](https://bookmap.com/en/crypto)
- [ClusterDelta](https://clusterdelta.com/orderflow/overview)
- [CoinAnk Footprint](https://coinank.com/proChart)
- [Cignals.io](https://cignals.io/)

---

**Document Version:** 2.0
**Created:** 2026-01-06
**Status:** Research complete - ready for implementation
**Builds On:** ORDERFLOW_STRATEGY_RESEARCH.md, DATA_SOURCES_RESEARCH.md, FEE_STRUCTURE_RESEARCH.md
