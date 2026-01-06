# Arbitrage Bot Implementation Plan

## Executive Summary

Build a high-frequency arbitrage bot that replicates the strategy used by Account88888 and other top performers: exploiting the price lag between Binance spot prices and Polymarket 15-minute resolution markets.

**Strategy:** Watch Binance BTC/ETH prices in real-time and bet on Polymarket outcomes before the market adjusts to price movements at 15-minute window closes.

---

## Architecture Overview

```
┌─────────────────┐
│ Binance Feed    │ ──> WebSocket <100ms latency
│ (BTC/ETH Price) │
└────────┬────────┘
         │
         v
┌─────────────────┐
│ Market Scanner  │ ──> Find active 15-min markets
│                 │     Track resolution times
└────────┬────────┘
         │
         v
┌─────────────────┐
│ Decision Engine │ ──> Calculate edge
│                 │     Determine position
└────────┬────────┘
         │
         v
┌─────────────────┐
│ Order Executor  │ ──> Place orders via CLOB
│ (Fast path)     │     <200ms execution
└─────────────────┘
```

---

## Components

### 1. Binance Price Feed (`src/feeds/binance_feed.py`)

**Purpose:** Real-time BTC/ETH spot prices via WebSocket

**Features:**
- WebSocket connection to Binance streams
- Track BTCUSDT and ETHUSDT
- Sub-100ms update latency
- Auto-reconnect on disconnect
- Price caching with timestamps

**Data structure:**
```python
{
    "symbol": "BTCUSDT",
    "price": 95234.56,
    "timestamp": 1704388800000,
    "latency_ms": 45
}
```

---

### 2. Market Calendar (`src/arbitrage/market_calendar.py`)

**Purpose:** Track 15-minute window resolution times

**Features:**
- Detect active markets with 15-min resolution
- Calculate next window close time
- Alert when approaching window close (T-60s, T-30s, T-10s)
- Track which markets are currently tradeable

**Window detection:**
```
15-minute windows close at:
- :00, :15, :30, :45 of every hour

Trigger times:
- T-60s: Start watching price
- T-30s: Calculate initial position
- T-10s: Ready to execute
- T-5s: EXECUTE if edge detected
- T+0s: Market resolves
```

---

### 3. Decision Engine (`src/arbitrage/decision_engine.py`)

**Purpose:** Determine when to trade and what position to take

**Logic:**
```python
def should_trade(current_price, strike_price, seconds_to_close, market_odds):
    """
    Determine if we should trade.

    Rules:
    1. Only trade within 30s of window close
    2. Only trade if price is clearly above/below strike (>0.5% edge)
    3. Only trade if Polymarket odds don't reflect reality
    4. Check volume/liquidity
    """

    if seconds_to_close > 30:
        return None  # Too early

    if seconds_to_close < 2:
        return None  # Too late (slippage risk)

    # Calculate edge
    edge = abs(current_price - strike_price) / strike_price

    if edge < 0.005:  # Less than 0.5%
        return None  # Edge too small

    # Determine position
    if current_price > strike_price * 1.005:
        return "BUY_YES"
    elif current_price < strike_price * 0.995:
        return "BUY_NO"

    return None
```

**Safety checks:**
- Minimum edge threshold (0.5%)
- Maximum position size ($50)
- Daily trade limit (100 trades)
- Circuit breaker on consecutive losses

---

### 4. Market Scanner (`src/arbitrage/market_scanner.py`)

**Purpose:** Find active 15-minute markets

**Features:**
- Query Polymarket for active markets
- Filter for:
  - 15-minute resolution markets
  - BTC/ETH price-based outcomes
  - Sufficient liquidity (>$500)
  - Not yet resolved
- Cache market metadata

**Market detection:**
```python
{
    "condition_id": "0xabc123...",
    "question": "Will BTC be above $95,000 at 12:15 UTC?",
    "strike_price": 95000,
    "resolution_time": 1704388800,  # Unix timestamp
    "yes_token_id": "0xdef456...",
    "no_token_id": "0xghi789...",
    "current_yes_price": 0.45,
    "current_no_price": 0.55,
    "liquidity": 2500
}
```

---

### 5. Arbitrage Orchestrator (`src/arbitrage/bot.py`)

**Purpose:** Main loop that coordinates all components

**Flow:**
```python
1. Connect to Binance feed
2. Scan for active markets
3. For each market approaching resolution:
   a. Get current Binance price
   b. Calculate edge
   c. Determine position
   d. Execute trade if profitable
4. Monitor positions until resolution
5. Track P&L
```

**State machine:**
```
IDLE → SCANNING → WATCHING → READY → EXECUTING → MONITORING → SETTLED
```

---

## Configuration

### Environment Variables
```bash
# Binance (no auth needed for public price feed)
BINANCE_WS_URL=wss://stream.binance.com:9443/ws

# Polymarket (existing)
POLYMARKET_API_KEY=your_key
POLYMARKET_API_SECRET=your_secret
POLYMARKET_PASSPHRASE=your_passphrase

# Bot settings
ARB_MIN_EDGE=0.005           # 0.5% minimum edge
ARB_MAX_POSITION_SIZE=50     # $50 max per trade
ARB_MAX_DAILY_TRADES=100     # 100 trades per day
ARB_EXECUTION_WINDOW=30      # Execute within 30s of close
ARB_MIN_LIQUIDITY=500        # $500 min market liquidity
```

### Risk Management
```python
CIRCUIT_BREAKERS = {
    "max_consecutive_losses": 5,
    "max_daily_loss": 100,  # $100
    "min_win_rate": 0.45,   # 45% (over 20 trades)
    "max_slippage": 0.02    # 2%
}
```

---

## Implementation Timeline

### Phase 1: Data Infrastructure (4-6 hours)
- [x] Binance WebSocket feed
- [x] Market calendar detector
- [x] Market scanner

### Phase 2: Decision Logic (2-3 hours)
- [x] Decision engine
- [x] Edge calculation
- [x] Position sizing

### Phase 3: Integration (2-3 hours)
- [x] Orchestrator main loop
- [x] Position tracking
- [x] P&L reporting

### Phase 4: Testing (3-4 hours)
- [x] Paper trading mode
- [x] Backtesting on historical data
- [x] Dry-run with live feeds

### Phase 5: Production (1-2 hours)
- [x] Live trading (small size)
- [x] Monitoring dashboard
- [x] Alert integration

**Total: 12-18 hours of focused work**

---

## Success Metrics

### Target Performance
- Win rate: >55%
- Average edge captured: 0.3-0.8%
- Execution latency: <500ms from signal to order
- Daily P&L: +$5-20 on $500 capital

### Stop Conditions
- Win rate drops below 45% (over 50 trades)
- Daily loss exceeds $100
- 5+ consecutive losses
- Execution latency exceeds 2 seconds consistently

---

## Risk Assessment

### Technical Risks
1. **Latency** - Solution: Co-locate near Binance/Polymarket servers
2. **API rate limits** - Solution: Cache aggressively, batch requests
3. **WebSocket disconnects** - Solution: Auto-reconnect with exponential backoff
4. **Order slippage** - Solution: Use limit orders with narrow spreads

### Market Risks
1. **Competition** - Other bots doing the same thing
2. **Market moves before execution** - Stop loss triggers
3. **Low liquidity** - Filter for min liquidity
4. **Polymarket bugs** - Start small, monitor carefully

### Financial Risks
1. **Consecutive losses** - Circuit breakers
2. **Capital depletion** - Position size limits
3. **Fees eating profits** - Calculate net edge after fees

---

## Next Steps

1. **Install dependencies:**
   ```bash
   pip install websocket-client
   ```

2. **Create file structure:**
   ```
   src/feeds/
   ├── __init__.py
   └── binance_feed.py

   src/arbitrage/
   ├── __init__.py
   ├── market_calendar.py
   ├── market_scanner.py
   ├── decision_engine.py
   └── bot.py
   ```

3. **Implement components** in order:
   - Binance feed (test standalone)
   - Market scanner (test with Polymarket API)
   - Market calendar (test time calculations)
   - Decision engine (unit tests)
   - Orchestrator (integration test)

4. **Paper trade for 3-7 days** before going live

5. **Start live with $100 capital** and scale up if profitable

---

## Open Questions

1. **Which markets to prioritize?**
   - BTC-only first, then add ETH
   - Focus on high-liquidity markets (>$1K)

2. **What strike prices work best?**
   - Analyze historical data
   - Likely: Strikes near current price (±1-2%)

3. **How much latency is acceptable?**
   - Target: <500ms total (price update → order placed)
   - Test with paper trading

4. **Should we use market or limit orders?**
   - Limit orders for better pricing
   - But risk not filling in time
   - Start with market orders, optimize later

---

*This plan is a living document. Update as we learn from testing and production.*
