# Research Synthesis & Action Plan

**Date:** January 6, 2026
**Purpose:** Consolidate findings from 5 research streams into actionable next steps

---

## Executive Summary

| Research Area | Key Finding | Implication |
|--------------|-------------|-------------|
| **Strategy Analysis** | Account88888 has +0.85% edge but 3% fees wipe it out | Current strategy is NET LOSING |
| **Low-Odds Markets** | 0-20% price range has +7.4% edge | Potential profitable subset |
| **BTC Futures Fees** | dYdX 0% fees (promo), Hyperliquid -0.003% rebates | Alternative venue available |
| **Orderflow Strategies** | Mean reversion works in ranging markets | Framework for new strategy |
| **Repo Audit** | System is production-ready (85% confidence) | Code is NOT the blocker |

**Bottom Line:** The code is ready. The strategy needs pivoting.

---

## Critical Discovery: Fees Exceed Edge

```
Account88888 P&L Breakdown:
├── Prediction Edge:     +$401,751  (+0.85% × $47.3M volume)
├── Polymarket Fees:     -$720,424  (~1.5% effective fee, up to 3% taker)
└── Net Result:          -$318,673  LOSING MONEY
```

**The system works perfectly but is trading a losing strategy.**

---

## Four Paths to Profitability

### Path A: Focus on Low-Odds Polymarket Trades (Lowest Risk)

**Edge by Price Bucket:**
| Entry Price | Edge | Fee Impact | Net |
|-------------|------|------------|-----|
| 0-10% | **+7.4%** | ~0.5% | **+6.9%** ✅ |
| 10-20% | **+2.6%** | ~1.0% | **+1.6%** ✅ |
| 20-30% | +0.9% | ~1.5% | -0.6% ❌ |
| 30-60% | ~0% | ~2-3% | -2-3% ❌ |

**Action:**
1. Filter trades to only 0-20% price range
2. Expected edge after fees: +1.6% to +6.9%
3. Volume will drop significantly (fewer opportunities)
4. Paper trade this subset for 2 weeks

**Pros:** Uses existing system, proven edge
**Cons:** Low volume, limited opportunities

---

### Path B: Maker-Only Polymarket Strategy (Medium Risk)

**Current:** Mix of maker/taker orders → paying 1.5%+ fees
**Target:** 100% limit orders → 0% fees + rebates

**Calculation:**
| Execution | Fee | With +0.85% Edge | Net |
|-----------|-----|------------------|-----|
| 100% Taker | 3% | +0.85% - 3% | **-2.15%** ❌ |
| 70/30 Mix | 1.5% | +0.85% - 1.5% | **-0.65%** ❌ |
| 100% Maker | 0% | +0.85% - 0% | **+0.85%** ✅ |

**Challenge:** 15-minute markets may not have time for limit orders to fill

**Action:**
1. Backtest maker-only execution on historical data
2. Measure fill rate on limit orders
3. Calculate opportunity cost of missed trades

**Pros:** Uses existing edge, no strategy change
**Cons:** May miss most opportunities, untested feasibility

---

### Path C: Pivot to BTC Perpetual Futures (Higher Risk, Higher Reward)

**Why BTC Futures:**
- dYdX: 0% fees on BTC perpetuals (Season 10 promo, Q1 2026)
- Hyperliquid: -0.003% maker rebates (get PAID to trade)
- Binance: 0.02% maker / 0.05% taker (much lower than Polymarket)
- 24/7 markets with deep liquidity

**Strategy from Research:**
1. **Mean Reversion on Daily/4H timeframe**
   - Z-Score < -2.0 → Long
   - Z-Score > +2.0 → Short
   - Target: Return to mean
   - Win rate: 60-70% in ranging markets

2. **Funding Rate Arbitrage**
   - Funding > +0.1% → Short bias (longs overextended)
   - Funding < -0.1% → Long bias (shorts overextended)
   - Combined with price at key levels

3. **Value Area Reversion**
   - Price below VAL → Long to POC
   - Price above VAH → Short to POC
   - Win rate: 65-75%

**Data Stack (FREE):**
- Binance WebSocket: Real-time orderbook, trades (no API key needed)
- Tardis.dev: Historical tick data (first day of month free)
- CoinGlass: Liquidation heatmaps, funding rates (web dashboard free)

**Execution Stack:**
- Phase 1: dYdX (0% fees while promo lasts)
- Phase 2: Hyperliquid (maker rebates long-term)
- Backup: Binance (best liquidity)

**Action:**
1. Set up Binance WebSocket feed for BTC data
2. Backtest mean reversion on Tardis.dev historical data
3. Paper trade on dYdX for 2 weeks
4. Go live with $50 (test capital) if paper trading profitable

**Pros:** Zero/negative fees possible, large liquid market
**Cons:** New market, new infrastructure, learning curve

---

### Path D: Hybrid Approach (Recommended)

**Combine best elements of all paths:**

**Week 1-2: Quick Wins**
1. Filter Polymarket trades to 0-20% price range only
2. Paper trade filtered strategy
3. Measure actual edge vs expected

**Week 2-4: Infrastructure**
1. Set up Binance WebSocket for BTC data
2. Download Tardis.dev free sample data
3. Backtest mean reversion strategies

**Month 2: Parallel Testing**
1. Continue Polymarket low-odds trading (small capital)
2. Paper trade BTC mean reversion on dYdX
3. Compare risk-adjusted returns

**Month 3+: Scale Winner**
1. Allocate capital to best-performing strategy
2. Consider running both if both are profitable
3. Diversification reduces single-strategy risk

---

## System Readiness Assessment

| Component | Status | Notes |
|-----------|--------|-------|
| **Executor** | ✅ Ready | 5s timeouts, 3x retries, balance checks |
| **Risk Manager** | ✅ Ready | $30/day limit, kill switch, circuit breakers |
| **Position Tracker** | ✅ Ready | P&L tracking, persistence |
| **Tests** | ✅ Ready | 50 tests, 85% coverage |
| **Strategy** | ❌ Needs Work | Edge < fees on current approach |
| **Data Pipeline** | ⚠️ Partial | Polymarket ready, BTC needs setup |

**Conclusion:** Code is production-ready. Strategy needs pivoting.

---

## Immediate Action Items

### This Week

1. **Filter Low-Odds Trades** (2 hours)
   - Modify `live_bot.py` to only trade 0-20% price range
   - Add price filter before trade approval
   - Paper trade for 3-5 days

2. **Set Up Binance WebSocket** (4 hours)
   - Create `src/feeds/binance_btc.py`
   - Subscribe to `btcusdt@depth@100ms`, `btcusdt@aggTrade`
   - Store orderbook snapshots locally

3. **Request Tardis.dev Trial** (30 min)
   - Sign up at tardis.dev
   - Download first day of month (free)
   - Get BTC perpetual orderbook data

### Next Week

4. **Backtest Mean Reversion** (1-2 days)
   - Implement Z-Score strategy
   - Test on Tardis.dev data
   - Calculate win rate, R:R, expectancy

5. **Create dYdX Account** (1 hour)
   - Set up wallet
   - Deposit small test amount
   - Verify 0% fee on BTC perpetuals

6. **Paper Trade Both Strategies** (ongoing)
   - Polymarket: Low-odds filtered
   - dYdX: Mean reversion BTC
   - Compare after 2 weeks

---

## Capital Allocation Plan

**Current Capital:** $300

### Conservative Approach (Recommended)

| Allocation | Amount | Strategy | Risk Level |
|------------|--------|----------|------------|
| **Reserve** | $150 (50%) | Hold as safety buffer | None |
| **Polymarket** | $75 (25%) | Low-odds (0-20%) only | Medium |
| **BTC Futures** | $75 (25%) | Mean reversion testing | Medium |

**Rules:**
- Max $15/trade (5% of total capital)
- Max $30/day loss (10% of total capital)
- Stop trading if capital drops below $200 (review strategy)

### Aggressive Approach (Not Recommended Yet)

| Allocation | Amount | Strategy | Risk Level |
|------------|--------|----------|------------|
| **Reserve** | $50 (17%) | Emergency buffer | None |
| **Polymarket** | $100 (33%) | Low-odds + maker-only | Medium-High |
| **BTC Futures** | $150 (50%) | Mean reversion + funding | High |

**Only consider after:**
- 2+ weeks profitable paper trading
- Both strategies showing positive expectancy
- Understanding of new market dynamics

---

## Success Metrics

### Week 1-2 (Paper Trading)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Win Rate (Polymarket low-odds) | >60% | Track all trades |
| Win Rate (BTC mean reversion) | >55% | Track all trades |
| Expected Edge | >2% | (Win% × Avg Win) - (Loss% × Avg Loss) |
| Sharpe Ratio | >1.0 | Return / Volatility |

### Month 1 (Live Testing)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Net P&L | >$0 | Must be profitable |
| Max Drawdown | <15% | No more than $45 loss from peak |
| Trade Count | 20-50 | Enough data for validation |
| Fee Ratio | <10% | Fees / Gross Profit |

### Month 2+ (Scaling)

| Metric | Target | Measurement |
|--------|--------|-------------|
| Monthly Return | >5% | $15+ on $300 capital |
| Win Rate | >55% | Sustained across trades |
| Recovery Factor | >2.0 | Total Profit / Max Drawdown |

---

## Risk Warnings

### Polymarket Risks
- 15-minute markets close quickly (limited reaction time)
- Low-odds markets have lower liquidity
- Maker orders may not fill in time
- Resolution risk (oracle/market errors)

### BTC Futures Risks
- 24/7 market requires monitoring or automation
- Leverage amplifies losses
- Funding rate can work against position
- Exchange counterparty risk (use DEX to mitigate)

### General Risks
- Small capital ($300) means limited diversification
- Learning curve on new markets
- Emotional trading during losses
- Overconfidence after early wins

---

## Files Created/Updated

| File | Purpose |
|------|---------|
| `DATA_SOURCES_RESEARCH.md` | BTC data sources (Binance, Tardis.dev, etc.) |
| `ORDERFLOW_STRATEGY_RESEARCH.md` | Mean reversion strategies |
| `FEE_STRUCTURE_RESEARCH.md` | Exchange fee comparison |
| `STRATEGY_REEVALUATION.md` | Account88888 edge analysis |
| `REPO_AUDIT_REPORT.md` | System production readiness |
| `RESEARCH_SYNTHESIS.md` | This document - action plan |

---

## Next Steps

**Immediate (Today):**
1. Read this synthesis document
2. Decide which path to pursue (A, B, C, or D)
3. Start first action item for chosen path

**This Week:**
1. Complete "This Week" action items above
2. Set up paper trading for chosen strategy
3. Begin collecting data

**Decision Point (2 Weeks):**
1. Review paper trading results
2. Decide: Continue, pivot, or stop
3. If positive: Begin live trading with small capital

---

**Document Version:** 1.0
**Status:** Ready for implementation
**Next Review:** After 2 weeks of paper trading
