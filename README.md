# Polymarket Research

Live maker bot and research tools for Polymarket 15-minute crypto markets.

## Current Status

**Live Deployment** (Jan 6, 2026)
- Maker bot running 24/7 on Tokyo EC2 (13.231.67.98)
- Placing delta-neutral orders on BTC/ETH 15-min Up/Down markets
- Capturing maker rebates from new fee structure (introduced Jan 6, 2026)

## Repository Structure

```
polymarket_research/
├── src/
│   ├── maker/               # Live maker bot
│   │   ├── live_maker_bot.py    # Main bot (deployed)
│   │   ├── cloudflare_bypass.py # Browser headers for API
│   │   ├── dual_order.py        # Synchronized YES/NO orders
│   │   ├── delta_tracker.py     # Position tracking
│   │   ├── risk_limits.py       # Kill switch, limits
│   │   └── paper_simulator.py   # Paper trading
│   ├── backtest/maker/      # Backtesting infrastructure
│   ├── exchanges/           # Hyperliquid client
│   └── api/                 # CLOB & Gamma API clients
│
├── tests/                   # Comprehensive test suite
├── systemd/                 # 24/7 service configs
├── archive/polymarket/      # Old research code & data
└── docs/                    # Documentation
```

## Large Data Files

Large data files are **excluded from git** but available locally at:

```
/Users/shem/Desktop/polymarket_starter/polymarket_starter/
```

| File | Size | Location |
|------|------|----------|
| `data/account88888_trades_joined.json` | 1.3GB | polymarket_starter |
| `data/ec2_transfers/transfers_*.jsonl` | 5GB+ | polymarket_starter |
| `data/token_to_market.json` | 101MB | polymarket_starter |
| `data/binance_klines_full.csv` | 8MB | polymarket_starter |

To access these files, reference them from the local path or symlink:
```bash
ln -s /Users/shem/Desktop/polymarket_starter/polymarket_starter/data ./data_local
```

## EC2 Instances

| Instance | Region | IP | Purpose | Status |
|----------|--------|-----|---------|--------|
| polymarket-arbitrage-bot | ap-northeast-1 | 13.231.67.98 | **Maker bot (LIVE)** | Running |
| polymarket-logger-us-east | us-east-1 | 13.222.131.86 | Data collection | Cloudflare blocked |

```bash
# SSH to Tokyo (maker bot)
ssh -i ~/.ssh/polymarket-bot-key-tokyo.pem ubuntu@13.231.67.98

# Check bot logs
journalctl -u maker-bot.service -f

# Emergency stop
sudo systemctl stop maker-bot.service
```

## Quick Start

```bash
# Clone
git clone https://github.com/ckoyuncu/polymarket_research.git
cd polymarket_research

# Setup
python3 -m venv venv && source venv/bin/activate
pip install py-clob-client python-dotenv

# Create .env with credentials
cat > .env << EOF
POLYMARKET_PRIVATE_KEY=your_key_here
POLYMARKET_FUNDER=your_address_here
EOF

# Run maker bot locally
python -m src.maker.live_maker_bot --bid-yes 0.45 --bid-no 0.45 --size 5.0
```

## Maker Bot Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--bid-yes` | 0.45 | Bid price for YES shares |
| `--bid-no` | 0.45 | Bid price for NO shares |
| `--size` | 5.0 | USD per side |
| `--max-loss` | 20.0 | Daily loss limit |

## Safety Features

- Kill switch: `touch .kill_switch` to stop
- Position limits: $10/market, 2 markets max
- Daily loss limit: $20
- Auto-cancel orders before resolution

## Related Repository

The original research data lives in `polymarket_starter`:
- `/Users/shem/Desktop/polymarket_starter/polymarket_starter/`
- Contains large data files, historical analysis, Account88888 research
- See `archive/polymarket/` for migrated code from that repo

---

**Last Updated:** 2026-01-06
