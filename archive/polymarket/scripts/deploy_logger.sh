#!/bin/bash
#
# Deploy Logger Infrastructure to EC2
#
# Usage:
#   ./deploy_logger.sh tokyo      # Deploy to Tokyo region
#   ./deploy_logger.sh us-east    # Deploy to US-East region
#
# Prerequisites:
#   - SSH key at ~/.ssh/polymarket-bot-key-tokyo.pem (for tokyo)
#   - SSH key at ~/.ssh/polymarket-bot-key-us-east.pem (for us-east)
#   - EC2 instance running Ubuntu 22.04
#

set -e

REGION="${1:-tokyo}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Configuration based on region
if [ "$REGION" = "tokyo" ]; then
    SSH_KEY="$HOME/.ssh/polymarket-bot-key-tokyo.pem"
    EC2_HOST="ubuntu@13.115.71.162"
    REGION_NAME="tokyo"
elif [ "$REGION" = "us-east" ]; then
    SSH_KEY="$HOME/.ssh/polymarket-bot-key-us-east.pem"
    EC2_HOST="ubuntu@13.222.131.86"
    REGION_NAME="us-east"
else
    echo "Unknown region: $REGION"
    echo "Usage: $0 [tokyo|us-east]"
    exit 1
fi

echo "============================================================"
echo "Deploying Logger Infrastructure"
echo "============================================================"
echo "Region: $REGION_NAME"
echo "Host: $EC2_HOST"
echo "SSH Key: $SSH_KEY"
echo ""

# Check SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found: $SSH_KEY"
    exit 1
fi

# Test SSH connectivity
echo "Testing SSH connectivity..."
ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$EC2_HOST" "echo 'SSH connection successful'"

echo ""
echo "Step 1: Installing system dependencies..."
ssh -i "$SSH_KEY" "$EC2_HOST" << 'REMOTE_SCRIPT'
set -e

# Update package list
sudo apt-get update -qq

# Install required packages
sudo apt-get install -y -qq python3-pip python3-venv chrony

# Configure NTP for accurate timestamps
sudo systemctl enable chrony
sudo systemctl start chrony

# Create data directory
sudo mkdir -p /data/logs/health
sudo chown -R ubuntu:ubuntu /data

echo "System dependencies installed"
REMOTE_SCRIPT

echo ""
echo "Step 2: Syncing project files..."

# Create tarball of necessary files
cd "$PROJECT_DIR"
tar czf /tmp/polymarket_logger.tar.gz \
    src/logging/ \
    src/feeds/ \
    src/api/ \
    src/__init__.py \
    scripts/multi_exchange_logger.py \
    scripts/polymarket_logger.py \
    scripts/validate_logger.py \
    systemd/

# Upload tarball
scp -i "$SSH_KEY" /tmp/polymarket_logger.tar.gz "$EC2_HOST:/tmp/"

# Extract and set up
ssh -i "$SSH_KEY" "$EC2_HOST" << REMOTE_SCRIPT
set -e

# Create project directory
mkdir -p ~/polymarket_starter

# Extract files
cd ~/polymarket_starter
tar xzf /tmp/polymarket_logger.tar.gz

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi

# Install Python dependencies
source venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet websocket-client requests

echo "Project files synced"
REMOTE_SCRIPT

echo ""
echo "Step 3: Installing systemd services..."
ssh -i "$SSH_KEY" "$EC2_HOST" << REMOTE_SCRIPT
set -e

# Copy systemd files
sudo cp ~/polymarket_starter/systemd/*.service /etc/systemd/system/

# Update region in service files
sudo sed -i "s/REGION_PLACEHOLDER/$REGION_NAME/g" /etc/systemd/system/multi_exchange_logger.service
sudo sed -i "s/REGION_PLACEHOLDER/$REGION_NAME/g" /etc/systemd/system/polymarket_logger.service

# Reload systemd
sudo systemctl daemon-reload

# Enable services (but don't start yet)
sudo systemctl enable multi_exchange_logger.service
sudo systemctl enable polymarket_logger.service

echo "Systemd services installed"
REMOTE_SCRIPT

echo ""
echo "Step 4: Running validation tests..."
ssh -i "$SSH_KEY" "$EC2_HOST" << 'REMOTE_SCRIPT'
set -e
cd ~/polymarket_starter
source venv/bin/activate
python scripts/validate_logger.py
REMOTE_SCRIPT

echo ""
echo "Step 5: Starting services..."
ssh -i "$SSH_KEY" "$EC2_HOST" << 'REMOTE_SCRIPT'
set -e

# Start services
sudo systemctl start multi_exchange_logger.service
sudo systemctl start polymarket_logger.service

# Wait a moment for them to initialize
sleep 5

# Check status
echo ""
echo "Service Status:"
echo "---------------"
sudo systemctl status multi_exchange_logger.service --no-pager | head -15
echo ""
sudo systemctl status polymarket_logger.service --no-pager | head -15

# Check health files
echo ""
echo "Health Status:"
echo "--------------"
if [ -f /data/logs/health/multi_exchange_logger.json ]; then
    cat /data/logs/health/multi_exchange_logger.json
fi
echo ""
if [ -f /data/logs/health/polymarket_logger.json ]; then
    cat /data/logs/health/polymarket_logger.json
fi
REMOTE_SCRIPT

echo ""
echo "============================================================"
echo "Deployment Complete!"
echo "============================================================"
echo ""
echo "Services running on $EC2_HOST:"
echo "  - multi_exchange_logger.service"
echo "  - polymarket_logger.service"
echo ""
echo "Log directories:"
echo "  - /data/logs/YYYY-MM-DD/prices_HH.jsonl.gz"
echo "  - /data/logs/YYYY-MM-DD/polymarket_books_HH.jsonl.gz"
echo ""
echo "Useful commands:"
echo "  # Check service status"
echo "  ssh -i $SSH_KEY $EC2_HOST 'sudo systemctl status multi_exchange_logger'"
echo ""
echo "  # View logs"
echo "  ssh -i $SSH_KEY $EC2_HOST 'sudo journalctl -u multi_exchange_logger -f'"
echo ""
echo "  # Download log files"
echo "  scp -i $SSH_KEY '$EC2_HOST:/data/logs/2026-01-05/*.gz' ./logs/"
echo ""

# Cleanup
rm -f /tmp/polymarket_logger.tar.gz
