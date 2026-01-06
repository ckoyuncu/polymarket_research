# Cloud Deployment Guide

## Why Deploy to Cloud?

Running the arbitrage bot locally has limitations:
- ❌ Need to keep your computer on 24/7
- ❌ Network interruptions affect trading
- ❌ Higher latency (important for arbitrage)
- ❌ Can't scale easily

**Cloud deployment solves all these issues.**

---

## Deployment Options Comparison

| Option | Difficulty | Cost/Month | Latency | Best For |
|--------|-----------|------------|---------|----------|
| AWS EC2 | Medium | $7-15 | Low | Production trading |
| Railway | Easy | $5-10 | Medium | Quick start |
| Render | Easy | $7+ | Medium | Hobbyist |
| Docker + VPS | Medium | $5-20 | Low | Self-hosted |

---

## Option 1: AWS EC2 (Recommended)

### Why EC2?
- ✅ Lowest latency to financial APIs
- ✅ Full control over infrastructure
- ✅ Can optimize for speed
- ✅ Industry standard for trading bots

### Setup Steps

#### 1. Launch EC2 Instance

```bash
# Instance specs:
Type: t3.micro (2 vCPU, 1GB RAM) - $7.50/month
OS: Ubuntu 22.04 LTS
Region: us-east-1 (closest to most exchanges)
Storage: 20GB SSD

# Security Group:
- Port 22 (SSH) - Your IP only
- All outbound traffic allowed
```

#### 2. Connect and Setup

```bash
# SSH into instance
ssh -i your-key.pem ubuntu@your-instance-ip

# Update system
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3.11 python3.11-venv git

# Clone repository
git clone https://github.com/yourusername/polymarket_starter.git
cd polymarket_starter

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# Install packages
pip install websocket-client python-dotenv pydantic sqlalchemy
```

#### 3. Configure Environment

```bash
# Create .env file
nano .env
```

Add your credentials:
```bash
POLYMARKET_API_KEY=your_key
POLYMARKET_API_SECRET=your_secret
POLYMARKET_PASSPHRASE=your_passphrase

ARB_MIN_EDGE=0.005
ARB_MAX_POSITION_SIZE=50
ARB_MAX_DAILY_TRADES=100
ARB_MIN_LIQUIDITY=500
```

#### 4. Test the Bot

```bash
# Paper trading test
python scripts/run_arbitrage_bot.py

# Let it run for 15 minutes to verify
# Press Ctrl+C to stop
```

#### 5. Setup Systemd Service (Always Running)

```bash
# Create service file
sudo nano /etc/systemd/system/arbitrage-bot.service
```

Paste this configuration:
```ini
[Unit]
Description=Polymarket Arbitrage Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/polymarket_starter
Environment="PATH=/home/ubuntu/polymarket_starter/venv/bin"
ExecStart=/home/ubuntu/polymarket_starter/venv/bin/python scripts/run_arbitrage_bot.py --live
Restart=always
RestartSec=10
StandardOutput=append:/home/ubuntu/polymarket_starter/logs/bot.log
StandardError=append:/home/ubuntu/polymarket_starter/logs/bot-error.log

[Install]
WantedBy=multi-user.target
```

```bash
# Create logs directory
mkdir -p logs

# Enable and start service
sudo systemctl enable arbitrage-bot
sudo systemctl start arbitrage-bot

# Check status
sudo systemctl status arbitrage-bot

# View logs (real-time)
sudo journalctl -u arbitrage-bot -f

# Or view file logs
tail -f logs/bot.log
```

#### 6. Monitoring Commands

```bash
# Check if bot is running
sudo systemctl status arbitrage-bot

# Restart bot
sudo systemctl restart arbitrage-bot

# Stop bot
sudo systemctl stop arbitrage-bot

# View recent logs
sudo journalctl -u arbitrage-bot -n 100

# Check bot status
cd /home/ubuntu/polymarket_starter
source venv/bin/activate
python scripts/run_arbitrage_bot.py --status
```

#### 7. Auto-Updates (Optional)

```bash
# Create update script
nano update-bot.sh
```

```bash
#!/bin/bash
cd /home/ubuntu/polymarket_starter
git pull
source venv/bin/activate
pip install -r requirements.txt --upgrade
sudo systemctl restart arbitrage-bot
```

```bash
chmod +x update-bot.sh

# Setup cron for daily updates at 3 AM
crontab -e
# Add: 0 3 * * * /home/ubuntu/polymarket_starter/update-bot.sh
```

---

## Option 2: Docker Deployment

### Prerequisites
```bash
# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose
sudo apt install docker-compose
```

### Deployment

```bash
# Clone repository
git clone https://github.com/yourusername/polymarket_starter.git
cd polymarket_starter

# Create .env file with credentials
nano .env

# Build and run
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

### Docker Commands

```bash
# Check if running
docker ps

# View logs
docker logs -f polymarket-arbitrage-bot

# Restart
docker-compose restart

# Stop
docker-compose stop

# Update and restart
git pull
docker-compose up -d --build
```

---

## Option 3: Railway (Easiest)

### Setup

1. **Install Railway CLI:**
```bash
npm install -g @railway/cli
```

2. **Deploy:**
```bash
cd polymarket_starter
railway login
railway init
railway up
```

3. **Add Environment Variables in Railway Dashboard:**
- Go to your project
- Click "Variables"
- Add all variables from `.env`

4. **Monitor:**
- View logs in Railway dashboard
- Set up alerts
- Check metrics

---

## Option 4: DigitalOcean Droplet

Similar to AWS EC2 but simpler interface:

1. Create Droplet ($6/month for Basic)
2. Choose Ubuntu 22.04
3. Follow AWS EC2 steps above
4. Use same systemd setup

---

## Monitoring & Alerts

### Setup Monitoring Script

Create `scripts/monitor.sh`:
```bash
#!/bin/bash

# Check if bot is running
if ! systemctl is-active --quiet arbitrage-bot; then
    echo "Bot is DOWN! Restarting..."
    sudo systemctl start arbitrage-bot

    # Send alert (optional - configure email/Telegram)
    # curl -X POST "https://api.telegram.org/bot<token>/sendMessage" \
    #      -d "chat_id=<your_id>&text=Bot was down, restarted"
fi

# Check if profitable
cd /home/ubuntu/polymarket_starter
source venv/bin/activate
python scripts/run_arbitrage_bot.py --status | grep "Total P&L"
```

```bash
chmod +x scripts/monitor.sh

# Run every 5 minutes
crontab -e
# Add: */5 * * * * /home/ubuntu/polymarket_starter/scripts/monitor.sh
```

### Telegram Alerts (Optional)

Install notification support:
```bash
pip install requests

# Add to bot code (in src/arbitrage/bot.py):
def send_telegram_alert(message):
    import requests
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": message}
        )
```

---

## Cost Comparison

### AWS EC2 (t3.micro)
- Instance: $7.50/month
- Storage: $0.80/month (20GB)
- Data transfer: ~$0.50/month
- **Total: ~$9/month**

### DigitalOcean
- Basic Droplet: $6/month (1GB RAM, 25GB SSD)
- **Total: $6/month**

### Railway/Render
- Free tier available
- Paid: $5-10/month
- **Total: $5-10/month**

---

## Performance Optimization

### For Low Latency Trading:

1. **Choose Right Region:**
   - Use AWS us-east-1 (Northern Virginia)
   - Closest to most financial APIs
   - Test latency: `ping api.binance.com`

2. **Use Faster Instance:**
   - Switch from t3.micro to t3.small if needed
   - More CPU = faster execution

3. **Network Optimization:**
   ```bash
   # Increase TCP buffer sizes
   sudo sysctl -w net.core.rmem_max=16777216
   sudo sysctl -w net.core.wmem_max=16777216
   ```

4. **Process Priority:**
   ```bash
   # Run bot with higher priority
   sudo nice -n -10 python scripts/run_arbitrage_bot.py --live
   ```

---

## Security Best Practices

1. **SSH Key Only (No Passwords):**
   ```bash
   sudo nano /etc/ssh/sshd_config
   # Set: PasswordAuthentication no
   sudo systemctl restart sshd
   ```

2. **Firewall:**
   ```bash
   sudo ufw allow 22/tcp
   sudo ufw enable
   ```

3. **Keep Credentials Secure:**
   ```bash
   chmod 600 .env
   ```

4. **Regular Updates:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

5. **Use Secrets Manager (Production):**
   - AWS Secrets Manager
   - Railway environment variables
   - Never commit `.env` to git

---

## Troubleshooting

### Bot Not Starting
```bash
# Check service status
sudo systemctl status arbitrage-bot

# Check logs
sudo journalctl -u arbitrage-bot -n 50

# Check if Python works
source venv/bin/activate
python scripts/run_arbitrage_bot.py
```

### High CPU Usage
```bash
# Check resource usage
htop

# Reduce trade frequency if needed
# Edit .env: ARB_MAX_DAILY_TRADES=50
```

### Connection Issues
```bash
# Test Binance connectivity
ping api.binance.com

# Test Polymarket connectivity
curl https://clob.polymarket.com

# Check DNS
cat /etc/resolv.conf
```

---

## Recommended Setup (Production)

For **serious trading**, I recommend:

1. **AWS EC2 t3.small** ($15/month)
   - 2 vCPU, 2GB RAM
   - us-east-1 region
   - 20GB SSD storage

2. **Systemd service** for auto-restart

3. **CloudWatch** for monitoring (free tier)

4. **Telegram alerts** for important events

5. **Daily backups** of trade data

6. **Reserved Instance** (save 30% if committed to 1 year)

---

## Quick Start Command Reference

```bash
# AWS EC2 Setup (one command)
curl -fsSL https://raw.githubusercontent.com/yourusername/polymarket_starter/main/scripts/setup-ec2.sh | bash

# Docker Setup
docker-compose up -d

# Railway Setup
railway up
```

---

## Next Steps

1. ✅ Choose deployment option
2. ✅ Follow setup steps above
3. ✅ Test with paper trading first
4. ✅ Monitor for 24-48 hours
5. ✅ Switch to live trading if profitable
6. ✅ Setup monitoring and alerts

**Need help?** Open an issue or check docs/TROUBLESHOOTING.md
