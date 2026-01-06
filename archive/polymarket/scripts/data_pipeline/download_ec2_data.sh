#!/bin/bash
#
# Download Account88888 blockchain data from EC2 Instance 1
#
# Usage:
#   ./download_ec2_data.sh
#
# Downloads:
#   - transfers_0x7f69983e_erc1155.jsonl (2.9M records, ~2.8GB)
#   - transfers_0x7f69983e_erc20.jsonl (561K records, ~500MB)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$(dirname "$SCRIPT_DIR")")"
DATA_DIR="$PROJECT_DIR/data/ec2_raw"

SSH_KEY="$HOME/.ssh/polymarket-bot-key-tokyo.pem"
EC2_HOST="ubuntu@13.231.67.98"
REMOTE_DATA_DIR="/home/ubuntu/polymarket_starter/data"

echo "============================================================"
echo "Downloading Account88888 Blockchain Data from EC2"
echo "============================================================"
echo "Source: $EC2_HOST:$REMOTE_DATA_DIR"
echo "Destination: $DATA_DIR"
echo ""

# Check SSH key exists
if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found: $SSH_KEY"
    exit 1
fi

# Create destination directory
mkdir -p "$DATA_DIR"

# Test SSH connectivity
echo "Testing SSH connectivity..."
ssh -i "$SSH_KEY" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$EC2_HOST" "echo 'SSH connection successful'"
echo ""

# Check remote file sizes
echo "Checking remote file sizes..."
ssh -i "$SSH_KEY" "$EC2_HOST" "ls -lh $REMOTE_DATA_DIR/transfers_0x7f69983e_*.jsonl"
echo ""

# Download checkpoint first (small file)
echo "Downloading checkpoint..."
scp -i "$SSH_KEY" "$EC2_HOST:$REMOTE_DATA_DIR/checkpoint_0x7f69983e.json" "$DATA_DIR/"
cat "$DATA_DIR/checkpoint_0x7f69983e.json"
echo ""

# Download ERC1155 transfers (larger file)
echo ""
echo "Downloading ERC1155 transfers (this may take a while)..."
echo "File: transfers_0x7f69983e_erc1155.jsonl (~2.8GB)"
time scp -i "$SSH_KEY" -C "$EC2_HOST:$REMOTE_DATA_DIR/transfers_0x7f69983e_erc1155.jsonl" "$DATA_DIR/"

# Download ERC20 transfers
echo ""
echo "Downloading ERC20 transfers..."
echo "File: transfers_0x7f69983e_erc20.jsonl (~500MB)"
time scp -i "$SSH_KEY" -C "$EC2_HOST:$REMOTE_DATA_DIR/transfers_0x7f69983e_erc20.jsonl" "$DATA_DIR/"

# Verify downloads
echo ""
echo "============================================================"
echo "Download Complete!"
echo "============================================================"
echo ""
echo "Local files:"
ls -lh "$DATA_DIR"
echo ""

# Count records
echo "Record counts:"
ERC1155_COUNT=$(wc -l < "$DATA_DIR/transfers_0x7f69983e_erc1155.jsonl")
ERC20_COUNT=$(wc -l < "$DATA_DIR/transfers_0x7f69983e_erc20.jsonl")
echo "  ERC1155 transfers: $ERC1155_COUNT"
echo "  ERC20 transfers: $ERC20_COUNT"
echo ""

# Show sample records
echo "Sample ERC1155 record:"
head -1 "$DATA_DIR/transfers_0x7f69983e_erc1155.jsonl" | python3 -m json.tool 2>/dev/null || head -1 "$DATA_DIR/transfers_0x7f69983e_erc1155.jsonl"
echo ""
echo "Sample ERC20 record:"
head -1 "$DATA_DIR/transfers_0x7f69983e_erc20.jsonl" | python3 -m json.tool 2>/dev/null || head -1 "$DATA_DIR/transfers_0x7f69983e_erc20.jsonl"
