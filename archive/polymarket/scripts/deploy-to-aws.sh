#!/bin/bash

# AWS EC2 Deployment Script for Arbitrage Bot
# This script automates the entire AWS EC2 setup

set -e  # Exit on error

echo "=========================================="
echo "AWS EC2 Deployment for Arbitrage Bot"
echo "=========================================="
echo ""

# Check if AWS CLI is configured
if ! aws sts get-caller-identity &> /dev/null; then
    echo "❌ AWS CLI not configured!"
    echo ""
    echo "Please run: aws configure"
    echo ""
    echo "You'll need:"
    echo "  1. AWS Access Key ID"
    echo "  2. AWS Secret Access Key"
    echo "  3. Default region (recommend: us-east-1)"
    echo ""
    exit 1
fi

echo "✅ AWS CLI configured"
echo ""

# Variables
KEY_NAME="polymarket-bot-key"
INSTANCE_TYPE="t2.micro"  # Free tier eligible
AMI_ID="ami-0c7217cdde317cfec"  # Ubuntu 22.04 LTS in us-east-1
SECURITY_GROUP_NAME="polymarket-bot-sg"
INSTANCE_NAME="polymarket-arbitrage-bot"

echo "Configuration:"
echo "  Key Name: $KEY_NAME"
echo "  Instance Type: $INSTANCE_TYPE"
echo "  Security Group: $SECURITY_GROUP_NAME"
echo ""

# Get current region
REGION=$(aws configure get region)
echo "Region: $REGION"
echo ""

# Create key pair if it doesn't exist
if ! aws ec2 describe-key-pairs --key-names "$KEY_NAME" &> /dev/null; then
    echo "Creating SSH key pair..."
    aws ec2 create-key-pair \
        --key-name "$KEY_NAME" \
        --query 'KeyMaterial' \
        --output text > ~/.ssh/"$KEY_NAME".pem

    chmod 400 ~/.ssh/"$KEY_NAME".pem
    echo "✅ Key pair created and saved to ~/.ssh/$KEY_NAME.pem"
else
    echo "✅ Key pair already exists"
fi
echo ""

# Create security group if it doesn't exist
if ! aws ec2 describe-security-groups --group-names "$SECURITY_GROUP_NAME" &> /dev/null; then
    echo "Creating security group..."

    # Get VPC ID
    VPC_ID=$(aws ec2 describe-vpcs --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text)

    # Create security group
    SG_ID=$(aws ec2 create-security-group \
        --group-name "$SECURITY_GROUP_NAME" \
        --description "Security group for Polymarket arbitrage bot" \
        --vpc-id "$VPC_ID" \
        --query 'GroupId' \
        --output text)

    # Get your public IP
    MY_IP=$(curl -s https://checkip.amazonaws.com)

    # Allow SSH from your IP
    aws ec2 authorize-security-group-ingress \
        --group-id "$SG_ID" \
        --protocol tcp \
        --port 22 \
        --cidr "$MY_IP/32"

    # Allow all outbound traffic (default, but explicitly setting)
    echo "✅ Security group created: $SG_ID"
    echo "   SSH allowed from: $MY_IP"
else
    SG_ID=$(aws ec2 describe-security-groups --group-names "$SECURITY_GROUP_NAME" --query "SecurityGroups[0].GroupId" --output text)
    echo "✅ Security group already exists: $SG_ID"
fi
echo ""

# Launch EC2 instance
echo "Launching EC2 instance..."
echo "  This will take ~2 minutes..."

INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "✅ Instance launched: $INSTANCE_ID"
echo ""

# Wait for instance to be running
echo "Waiting for instance to start..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID"
echo "✅ Instance is running"
echo ""

# Get public IP
PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo "=========================================="
echo "✅ EC2 Instance Created Successfully!"
echo "=========================================="
echo ""
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo "SSH Key: ~/.ssh/$KEY_NAME.pem"
echo ""
echo "Connect with:"
echo "  ssh -i ~/.ssh/$KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo ""
echo "Waiting 30 seconds for SSH to be ready..."
sleep 30

# Create deployment script for the instance
cat > /tmp/setup-bot.sh << 'EOF'
#!/bin/bash
set -e

echo "Setting up Polymarket Arbitrage Bot..."

# Update system
sudo apt update && sudo apt upgrade -y

# Install Python 3.11
sudo apt install -y python3.11 python3.11-venv python3-pip git screen

# Clone repository (you'll need to push to git first)
if [ ! -d "polymarket_starter" ]; then
    echo "Repository URL needed - please clone manually"
    echo "Run: git clone YOUR_REPO_URL"
else
    cd polymarket_starter
    git pull
fi

echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. cd polymarket_starter"
echo "2. python3.11 -m venv venv"
echo "3. source venv/bin/activate"
echo "4. pip install websocket-client python-dotenv pydantic sqlalchemy"
echo "5. Create .env file with your credentials"
echo "6. python scripts/run_arbitrage_bot.py"
EOF

# Copy setup script to instance
echo "Uploading setup script..."
scp -i ~/.ssh/"$KEY_NAME".pem \
    -o StrictHostKeyChecking=no \
    /tmp/setup-bot.sh ubuntu@"$PUBLIC_IP":~/

echo ""
echo "=========================================="
echo "🚀 Ready to Deploy!"
echo "=========================================="
echo ""
echo "1. SSH into instance:"
echo "   ssh -i ~/.ssh/$KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo ""
echo "2. Run setup script:"
echo "   bash ~/setup-bot.sh"
echo ""
echo "Or I can SSH and deploy automatically..."
read -p "Auto-deploy now? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Connecting and deploying..."

    ssh -i ~/.ssh/"$KEY_NAME".pem \
        -o StrictHostKeyChecking=no \
        ubuntu@"$PUBLIC_IP" 'bash -s' < /tmp/setup-bot.sh

    echo ""
    echo "✅ Deployment complete!"
    echo ""
    echo "Connect with:"
    echo "  ssh -i ~/.ssh/$KEY_NAME.pem ubuntu@$PUBLIC_IP"
fi

echo ""
echo "=========================================="
echo "Instance Details"
echo "=========================================="
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo "Region: $REGION"
echo "Instance Type: $INSTANCE_TYPE"
echo ""
echo "Estimated cost: ~$7-10/month (or FREE if on free tier)"
echo ""
echo "To stop instance (save money):"
echo "  aws ec2 stop-instances --instance-ids $INSTANCE_ID"
echo ""
echo "To start instance again:"
echo "  aws ec2 start-instances --instance-ids $INSTANCE_ID"
echo ""
echo "To terminate instance:"
echo "  aws ec2 terminate-instances --instance-ids $INSTANCE_ID"
echo ""
