# EC2 Quick Start Guide

Your arbitrage bot is deployed and ready to run on AWS EC2!

## Instance Details

- **Instance ID**: i-0cdad747158f0b0f5
- **Public IP**: 13.221.129.24
- **SSH Key**: ~/.ssh/polymarket-bot-key.pem
- **Region**: ap-southeast-1

## Step 1: Connect to EC2

```bash
ssh -i ~/.ssh/polymarket-bot-key.pem ubuntu@13.221.129.24
```

## Step 2: Navigate to Bot Directory

```bash
cd ~/polymarket_starter
source venv/bin/activate
```

## Step 3: Create Environment File

```bash
nano .env
```

Add the following (replace with your actual credentials):

```bash
# Polymarket API Credentials (optional for paper trading)
POLYMARKET_API_KEY=your_key_here
POLYMARKET_API_SECRET=your_secret_here
POLYMARKET_PASSPHRASE=your_passphrase_here

# Arbitrage Bot Configuration
ARB_MIN_EDGE=0.005              # 0.5% minimum edge
ARB_MAX_POSITION_SIZE=50        # $50 max per trade
ARB_MAX_DAILY_TRADES=100        # 100 trades per day
ARB_MIN_LIQUIDITY=500           # $500 min market liquidity
ARB_EXECUTION_WINDOW_START=2    # 2 seconds before close
ARB_EXECUTION_WINDOW_END=30     # 30 seconds before close
ARB_MIN_CONFIDENCE=0.6          # 60% minimum confidence

# Optional: Telegram Alerts
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

Save with: `Ctrl+O`, `Enter`, `Ctrl+X`

## Step 4: Start Bot in Paper Trading Mode (SAFE)

```bash
# Run in foreground to see output
python scripts/run_arbitrage_bot.py
```

**Expected Output:**
```
📝 PAPER TRADING MODE (no real money)
=========================================
Polymarket Arbitrage Bot - v1.0
=========================================

Configuration:
  Min Edge: 0.5%
  Max Position: $50.0
  Max Daily Trades: 100
  Mode: PAPER TRADING

Starting Binance price feed...
✅ Connected to Binance WebSocket
📊 BTC: $42,150.00 | ETH: $2,250.00

Initializing market calendar...
⏰ Next window: 16:45:00 (in 8m 32s)

Bot is running... Press Ctrl+C to stop
```

## Step 5: Run in Background (24/7 Operation)

Once you've confirmed it works, run it in the background using `screen`:

```bash
# Start a screen session
screen -S arbitrage-bot

# Run the bot
python scripts/run_arbitrage_bot.py

# Detach from screen: Press Ctrl+A, then D
```

**To reconnect later:**
```bash
screen -r arbitrage-bot
```

**To stop the bot:**
```bash
# Reconnect to screen
screen -r arbitrage-bot

# Press Ctrl+C to stop bot

# Exit screen
exit
```

## Step 6: Check Bot Status

```bash
python scripts/run_arbitrage_bot.py --status
```

**Expected Output:**
```
=========================================
Bot Status
=========================================
Status: Running
Uptime: 2h 15m 32s
Current Phase: WATCHING

Current Window: 17:00:00 (in 3m 12s)
BTC Price: $42,180.00
ETH Price: $2,255.00

Active Markets: 3
Total Positions: 0
Total Trades: 12
Win Rate: 58.3% (7 wins, 5 losses)
Total P&L: +$18.50 (paper money)
```

## Monitoring Commands

```bash
# View recent trades
tail -f logs/trades.log

# Check if bot is running
ps aux | grep run_arbitrage_bot

# Check system resources
htop

# Check network connectivity
ping api.binance.com
```

## Paper Trading Validation (3-7 Days)

Before switching to live trading:

1. **Let it run for 3-7 days** in paper trading mode
2. **Monitor win rate**: Should be >55% to be profitable
3. **Check edge accuracy**: Verify price lag is consistently exploitable
4. **Review trade logs**: Ensure no errors or missed opportunities

**Target Metrics:**
- Win Rate: 55-65%
- Average Edge: 0.5-1.0%
- Daily Trades: 50-200 (market dependent)
- Expected Monthly ROI: 5-15% (if profitable)

## Switch to Live Trading (ONLY AFTER VALIDATION)

⚠️ **WARNING: This uses real money!**

```bash
# Ensure .env has your Polymarket API credentials
nano .env

# Run in live mode
python scripts/run_arbitrage_bot.py --live
```

## Cost Management

**Current Setup:**
- Instance: t2.micro (FREE within free tier)
- Storage: 8GB (FREE within free tier)
- Estimated cost: **$0/month** (if within free tier limits)

**After Free Tier:**
- ~$7-10/month

**To Stop Instance (Save Money):**
```bash
# From your local machine
aws ec2 stop-instances --instance-ids i-0cdad747158f0b0f5
```

**To Start Instance Again:**
```bash
aws ec2 start-instances --instance-ids i-0cdad747158f0b0f5

# Get new public IP (it changes after stop/start)
aws ec2 describe-instances --instance-ids i-0cdad747158f0b0f5 \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text
```

## Troubleshooting

### Bot Won't Start

```bash
# Check Python version
python --version  # Should be 3.11+

# Reinstall dependencies
source venv/bin/activate
pip install websocket-client python-dotenv pydantic sqlalchemy

# Check for errors
python scripts/run_arbitrage_bot.py
```

### Binance Connection Issues

```bash
# Test connectivity
ping api.binance.com

# Check if WebSocket port is open
telnet stream.binance.com 9443
```

### No Markets Found

This is expected initially. The market scanner needs:
- Active 15-minute resolution markets on Polymarket
- Sufficient liquidity (>$500)
- Clear strike prices in question text

If no markets are found, the bot will wait for the next window.

## Need Help?

- Full deployment guide: `docs/DEPLOYMENT.md`
- Testing guide: `docs/TESTING_GUIDE.md`
- Project tracker: `docs/TRACKER.md`

## Security Reminders

- ✅ Never commit `.env` to git
- ✅ Keep SSH key (`polymarket-bot-key.pem`) secure
- ✅ Start with paper trading, validate before live
- ✅ Use small position sizes initially
- ✅ Monitor daily for first week

---

**Ready to Start?**

```bash
# Connect to EC2
ssh -i ~/.ssh/polymarket-bot-key.pem ubuntu@13.221.129.24

# Navigate and activate
cd ~/polymarket_starter
source venv/bin/activate

# Create .env (if not exists)
nano .env

# Start bot
python scripts/run_arbitrage_bot.py
```

Good luck! 🚀
