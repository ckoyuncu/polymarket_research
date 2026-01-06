# Edge Assessment Report: Account88888 Strategy Analysis

**Generated:** 2026-01-05
**Analyst:** Claude Code
**Sample Period:** December 5-6, 2025 (0.8 days)

---

## Executive Summary

**Key Finding: The strategy configuration was based on incorrect assumptions.**

| Metric | Expected (Config) | Actual (Data) |
|--------|-------------------|---------------|
| Win rate | 23% | 47.4% |
| Execution timing | 2-30 sec before close | 5-15 min before close |
| Strategy type | Price lag arbitrage | Mean reversion (losing) |
| Edge | Positive via payoff ratio | **Negative in sample** |

**Bottom Line:** Account88888 appears to be trading a **mean reversion strategy** that is **underperforming** in this sample period. The market shows strong **momentum continuation** (~64%), making a counter-trend approach unprofitable.

---

## Data Pipeline Results

### Datasets Created

| File | Records | Description |
|------|---------|-------------|
| `data/token_to_market.json` | 454 | Token ID → Market metadata mapping |
| `data/account88888_trades_enriched.json` | 10,000 | Trades with market context |
| `data/binance_klines_88888.csv` | 2,642 | BTC/ETH 1-min prices |
| `reports/backtest_results.json` | 6,728 | Detailed backtest results |

### Data Quality

- ✅ 99.99% of trades matched with market metadata
- ✅ 100% of BTC/ETH BUY trades successfully backtested
- ✅ Resolution timestamps extracted from market slugs
- ✅ Token outcomes (UP/DOWN) determined from market structure

---

## Key Findings

### 1. Timing Discovery

**Previous Assumption (Strategy Config):**
> "Execute 2-30 seconds before 15-min candle close"

**Actual Data:**
| Timing Bucket | Trade Count | % |
|---------------|-------------|---|
| 0-5s before close | 0 | 0.0% |
| 5-15s before close | 0 | 0.0% |
| 15-30s before close | 2 | 0.0% |
| 30-60s before close | 121 | 1.3% |
| 1-5 min before close | 2,503 | 26.2% |
| **>5 min before close** | **6,925** | **72.5%** |

**Median execution: 8-9 minutes before close**

### 2. Token Direction Analysis

Account88888 buys both UP and DOWN tokens:
- UP tokens: 51.4% of BUY trades
- DOWN tokens: 48.6% of BUY trades

This is not a simple "always bet UP" or "always bet DOWN" strategy.

### 3. Market Behavior: Strong Momentum

The 15-minute BTC/ETH markets show **momentum continuation**:

| Initial Direction | Continuation Rate |
|-------------------|-------------------|
| Price UP at trade → UP at close | 63.6% |
| Price DOWN at trade → DOWN at close | 64.2% |
| **Average momentum continuation** | **63.9%** |

### 4. Account88888 Strategy vs Market

| Trading Style | 88888 Trade Count | Win Rate |
|---------------|-------------------|----------|
| WITH momentum | 3,177 (47.2%) | 61.9% |
| AGAINST momentum | 3,551 (52.8%) | 34.3% |

**88888 trades AGAINST momentum more often**, resulting in:
- **Actual win rate: 47.4%**
- **Optimal momentum strategy would achieve: 63.9%**

### 5. Profitability Assessment

| Strategy | Win Rate | Avg Entry | Expected Value |
|----------|----------|-----------|----------------|
| Account88888 (actual) | 47.4% | $0.484 | **-$0.03** (losing) |
| Pure momentum | 63.9% | $0.50 | **+$0.14** (profitable) |
| Mean reversion | 36.1% | $0.50 | **-$0.14** (losing) |

---

## Asset Distribution

| Asset | Trade Count | Avg Size | Total Volume |
|-------|-------------|----------|--------------|
| BTC | 4,126 | $40.00 | $165,044 |
| ETH | 2,864 | $55.31 | $158,407 |
| SOL | 1,507 | $65.71 | $99,020 |
| XRP | 1,502 | $73.74 | $110,757 |

**Note:** 88888 trades multiple assets, not just BTC/ETH.

---

## Recommendations

### 1. DO NOT Copy Account88888's Strategy

The data suggests 88888's approach is **underperforming** in this sample period. Their mean reversion bets are losing against strong market momentum.

### 2. Consider a Momentum Strategy Instead

A simple momentum strategy achieves ~64% win rate:
- If price is UP at trade time → buy UP token
- If price is DOWN at trade time → buy DOWN token
- Trade 5-10 minutes before close (when direction is clear)

**Expected edge at $0.50 entry:**
- EV = 0.64 × $0.50 - 0.36 × $0.50 = **$0.14/trade (28% ROI)**

### 3. Timing Window

For momentum to work, trade **early enough** that:
1. Direction is established (price has moved from window start)
2. There's still time for momentum to continue
3. But not so late that the market has fully priced it in

**Recommended:** 3-7 minutes before close

### 4. Sample Size Warning

This analysis covers only **0.8 days** of trading (Dec 5-6, 2025). Before implementing any strategy:
- Fetch more historical data
- Validate across different market conditions
- Paper trade before going live

---

## Data Backfill Plan

### Current State
- ERC1155 transfers: 2,904,133 records ✅ Complete
- ERC20 transfers: 561,114 records ⚠️ Partial (stopped at block 80558011)

### Backfill Steps

1. **Resume EC2 extraction:**
```bash
ssh -i ~/.ssh/polymarket-bot-key-tokyo.pem ubuntu@13.231.67.98
cd ~/polymarket_starter
python scripts/blockchain_trade_extractor.py --wallet 0x7f69983e --resume
```

2. **Download complete data:**
```bash
./scripts/data_pipeline/download_ec2_data.sh
```

3. **Re-run enrichment pipeline:**
```bash
python scripts/data_pipeline/enrich_trades_with_markets.py \
    --trades data/ec2_raw/trades_complete.json
```

4. **Re-run backtest with complete dataset**

---

## Technical Notes

### Files Created

| Path | Purpose |
|------|---------|
| `scripts/data_pipeline/fetch_market_metadata.py` | Gamma API token→market mapper |
| `scripts/data_pipeline/enrich_trades_with_markets.py` | Trade enrichment |
| `scripts/analysis/backtest_88888_vs_binance.py` | Backtest engine |

### API Sources Used
- **Gamma API:** `https://gamma-api.polymarket.com/markets?clob_token_ids=...`
- **Binance API:** `https://api.binance.com/api/v3/klines`

---

## Appendix: Strategy Config vs Reality

### config/account88888_strategy.json (OUTDATED)
```json
{
  "execution_timing": {
    "execution_window_seconds": [2, 30],  // WRONG
    "description": "Execute 2-30 seconds before 15-min candle close"  // WRONG
  },
  "target_metrics": {
    "win_rate_target": 0.23  // INACCURATE - actual is 47.4%
  }
}
```

### Actual Observed Behavior
- Execution: 5-15 minutes before close
- Win rate: 47.4% (not 23%)
- Strategy: Mean reversion (counter-momentum)
- Result: Underperforming in momentum market

---

*This report was generated by analyzing 10,000 trades from Account88888's on-chain activity and correlating with Binance BTC/ETH price data.*
