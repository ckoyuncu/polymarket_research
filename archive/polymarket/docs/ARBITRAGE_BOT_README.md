# Arbitrage Bot - Quick Start Guide

## What This Bot Does

This bot exploits the price lag between Binance spot prices and Polymarket 15-minute resolution markets. It's the same strategy used by profitable traders like Account88888.

**The Strategy:**
1. Watch Binance BTC/ETH prices in real-time (WebSocket)
2. Find Polymarket markets that resolve based on price at specific times (e.g., "Will BTC be above $95,000 at 12:15?")
3. When the 15-minute window is about to close, check if the outcome is clear
4. If BTC is clearly above/below the strike, place a bet before the market adjusts
5. Profit from the lag between Binance and Polymarket

## Installation

The bot is already set up in this repository. Just make sure you have the dependencies:

```bash
# Install dependencies
pip install websocket-client python-dotenv

# Or use the virtual environment
source venv/bin/activate
```

## Quick Start

### 1. Paper Trading (Recommended First)

Start with paper trading to test the bot without risking real money:

```bash
python run_arbitrage_bot.py
```

This will:
- Connect to Binance for real-time prices
- Scan Polymarket for arbitrage opportunities
- Simulate trades without placing real orders
- Show you what the bot would do in real-time

### 2. Check Bot Status

After running for a while, check the results:

```bash
python run_arbitrage_bot.py --status
```

### 3. Test Individual Components

Test the Binance feed:
```bash
python src/feeds/binance_feed.py
```

Test the market calendar:
```bash
python src/arbitrage/market_calendar.py
```

Test the decision engine:
```bash
python src/arbitrage/decision_engine.py
```

## Configuration

Edit the `.env` file or set environment variables:

```bash
# Arbitrage settings
ARB_MIN_EDGE=0.005              # 0.5% minimum edge (don't trade if edge is smaller)
ARB_MAX_POSITION_SIZE=50        # $50 max per trade
ARB_MAX_DAILY_TRADES=100        # Max 100 trades per day
ARB_MIN_LIQUIDITY=500           # Only trade markets with >$500 liquidity
```

## Live Trading (Advanced)

**WARNING:** Only use live trading after:
1. Running paper trading for at least 3-7 days
2. Understanding how the bot works
3. Verifying positive results in paper trading
4. Starting with small amounts ($100-500)

### Setup for Live Trading

1. Get Polymarket API credentials:
   - Go to Polymarket settings
   - Generate API key, secret, and passphrase
   - **NEVER** share these or commit them to git

2. Add credentials to `.env`:
   ```bash
   POLYMARKET_API_KEY=your_key
   POLYMARKET_API_SECRET=your_secret
   POLYMARKET_PASSPHRASE=your_passphrase
   ```

3. Start live trading:
   ```bash
   python run_arbitrage_bot.py --live
   ```

4. Start small:
   ```bash
   # $25 max per trade
   python run_arbitrage_bot.py --live --max-position 25
   ```

## How the Bot Works

### Components

1. **Binance Feed** (`src/feeds/binance_feed.py`)
   - WebSocket connection to Binance
   - Real-time BTC/ETH prices
   - <100ms latency

2. **Market Calendar** (`src/arbitrage/market_calendar.py`)
   - Tracks 15-minute windows (:00, :15, :30, :45)
   - Generates alerts at different phases:
     - WATCHING (60-30s before): Start monitoring
     - READY (30-10s before): Calculate positions
     - EXECUTING (10-2s before): Place trades
     - CLOSED: Window closed

3. **Market Scanner** (`src/arbitrage/market_scanner.py`)
   - Finds active Polymarket markets
   - Filters for 15-minute resolution
   - Extracts strike prices from questions
   - Checks liquidity

4. **Decision Engine** (`src/arbitrage/decision_engine.py`)
   - Compares Binance price to strike price
   - Calculates edge
   - Determines if trade is worth it
   - Sizes positions based on confidence

5. **Bot Orchestrator** (`src/arbitrage/bot.py`)
   - Coordinates all components
   - Manages state and tracking
   - Executes trades
   - Records P&L

### Trading Logic

The bot only trades when ALL these conditions are met:

1. **Timing:** 2-30 seconds before window close
2. **Edge:** Price is >0.5% above or below strike
3. **Market mispricing:** Polymarket odds don't reflect reality
4. **Liquidity:** Market has sufficient volume
5. **Confidence:** High confidence in the outcome
6. **Limits:** Haven't hit daily trade limit

### Example Trade

```
Time: 12:14:45 UTC (15 seconds before 12:15)
Market: "Will BTC be above $95,000 at 12:15?"
Binance Price: $95,600 (clearly above)
Strike: $95,000
Edge: 0.63%

Polymarket Odds:
  YES: 0.55 (should be ~0.95)
  NO: 0.45

Decision: BUY YES
Size: 50 shares @ $0.60 = $30
Expected Profit: $20 (50 shares * $0.40 profit per share)
```

## Monitoring

### During Execution

The bot prints real-time updates:
```
🤖 Arbitrage bot initialized
✅ Bot started at 12:10:00 UTC

⏰ Window event: watching
   Next window: 12:15:00
   Time until: 60s

👀 Watching phase - scanning markets...
   Found 3 markets for this window

🎯 Ready phase - analyzing positions...

🔔 SIGNAL: buy_yes
   Market: Will BTC be above $95,000 at 12:15 UTC?
   Price: BTC $95,600 vs $95,000
   Edge: 0.63%
   Confidence: 78.5%
   Size: 50.0 @ $0.600

📝 PAPER TRADE: BUY 50 @ $0.600
```

### After Running

Check results:
```bash
python run_arbitrage_bot.py --status
```

View saved data:
- `data/arbitrage/bot_state.json` - Current state
- `data/arbitrage/session_report.json` - Last session report
- `data/trading/order_history.json` - Order history (if live trading)

## Safety Features

The bot includes multiple safety mechanisms:

1. **Paper Trading Mode** (default)
   - No real money used
   - Test before going live

2. **Position Limits**
   - Max position size per trade
   - Daily trade limits

3. **Edge Threshold**
   - Only trade when edge is clear
   - Avoid marginal trades

4. **Confidence Scoring**
   - Calculate confidence for each trade
   - Skip low-confidence opportunities

5. **Execution Windows**
   - Only trade at optimal times
   - Avoid being too early or too late

6. **Rate Limiting**
   - Respect API rate limits
   - Avoid getting blocked

## Troubleshooting

### Bot won't start
```
Check:
- Python virtual environment is activated
- websocket-client is installed
- Internet connection is working
```

### No price updates
```
Check:
- Binance WebSocket connection
- Firewall not blocking WebSocket
- Run: python src/feeds/binance_feed.py
```

### No markets found
```
Possible reasons:
- No active 15-min markets right now
- Market scanner not fully implemented (see note below)
- Polymarket API changed
```

### Live trading not working
```
Check:
- API credentials in .env file
- Credentials are correct
- Account has funds
- Run: python run_arbitrage_bot.py --status
```

## Important Notes

### Market Scanner Status

⚠️ **The market scanner (`src/arbitrage/market_scanner.py`) is currently a placeholder.**

To make it fully functional, you need to:

1. Find the correct Polymarket API endpoint for listing active markets
2. Implement filtering for 15-minute resolution markets
3. Parse market questions to extract strike prices and resolution times
4. Get current YES/NO prices for each market

This requires:
- Understanding Polymarket's market data structure
- Knowing which API endpoints to use
- Testing with real market data

**Recommendation:** Start by manually identifying a few active 15-minute markets and hardcode them for testing. Once the bot proves profitable with manual markets, invest time in building the automated scanner.

### Expected Performance

Based on analysis of Account88888:

- **Win rate:** 55-65% (if execution is fast enough)
- **Edge per trade:** 0.3-0.8%
- **Daily trades:** 50-200 (depending on market availability)
- **ROI:** 5-15% per month (on winning trades)

**However:**
- You're competing with other bots
- Execution speed matters
- Market conditions change
- Results may vary

### Risk Warnings

1. **This is experimental** - Not guaranteed to work
2. **Speed matters** - You might be too slow vs other bots
3. **Markets can change** - Strategy might stop working
4. **Start small** - Test with amounts you can afford to lose
5. **Monitor closely** - Don't leave it running unsupervised

## Next Steps

1. **Run paper trading for 3-7 days**
   ```bash
   python run_arbitrage_bot.py
   ```

2. **Analyze results**
   - Check win rate
   - Calculate average edge captured
   - Verify execution timing

3. **If results are good:**
   - Start live with small amounts ($100)
   - Monitor for first day
   - Scale up gradually if profitable

4. **If results are poor:**
   - Check execution latency
   - Adjust edge threshold
   - Consider different markets
   - May need faster infrastructure

## Support

For issues or questions:

1. Check the logs in `logs/` directory
2. Review `ARBITRAGE_BOT_PLAN.md` for architecture details
3. Test individual components
4. Check Polymarket API documentation
5. Review the code with comments

## Files Reference

| File | Purpose |
|------|---------|
| `run_arbitrage_bot.py` | Main entry point |
| `src/feeds/binance_feed.py` | Binance WebSocket feed |
| `src/arbitrage/market_calendar.py` | Window timing |
| `src/arbitrage/market_scanner.py` | Market discovery |
| `src/arbitrage/decision_engine.py` | Trade decisions |
| `src/arbitrage/bot.py` | Main orchestrator |
| `ARBITRAGE_BOT_PLAN.md` | Architecture docs |
| `.env.example` | Configuration template |

---

**Good luck and trade responsibly!**
