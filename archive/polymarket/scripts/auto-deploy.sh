#!/bin/bash
# Automated AWS EC2 deployment (non-interactive)

set -e

echo "🚀 Starting AWS EC2 deployment..."

# Variables
REGION="ap-northeast-1"  # Tokyo - lowest latency to Binance
KEY_NAME="polymarket-bot-key-tokyo"
INSTANCE_TYPE="t2.micro"
AMI_ID="ami-0d49f1fe982e06148"  # Ubuntu 22.04 LTS ap-northeast-1
SG_NAME="polymarket-bot-sg-tokyo"
INSTANCE_NAME="polymarket-arbitrage-bot"

# Step 1: Create key pair
echo "📋 Step 1/5: Creating SSH key pair in $REGION..."
if ! aws ec2 describe-key-pairs --region "$REGION" --key-names "$KEY_NAME" 2>/dev/null; then
    aws ec2 create-key-pair \
        --region "$REGION" \
        --key-name "$KEY_NAME" \
        --query 'KeyMaterial' \
        --output text > ~/.ssh/"$KEY_NAME".pem
    chmod 400 ~/.ssh/"$KEY_NAME".pem
    echo "✅ Key pair created: ~/.ssh/$KEY_NAME.pem"
else
    echo "✅ Key pair already exists"
fi

# Step 2: Create security group
echo "📋 Step 2/5: Creating security group..."
if ! aws ec2 describe-security-groups --region "$REGION" --group-names "$SG_NAME" 2>/dev/null; then
    VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text)

    SG_ID=$(aws ec2 create-security-group \
        --region "$REGION" \
        --group-name "$SG_NAME" \
        --description "Polymarket bot security group" \
        --vpc-id "$VPC_ID" \
        --query 'GroupId' \
        --output text)

    MY_IP=$(curl -s https://checkip.amazonaws.com)

    aws ec2 authorize-security-group-ingress \
        --region "$REGION" \
        --group-id "$SG_ID" \
        --protocol tcp \
        --port 22 \
        --cidr "$MY_IP/32"

    echo "✅ Security group created: $SG_ID"
else
    SG_ID=$(aws ec2 describe-security-groups --region "$REGION" --group-names "$SG_NAME" --query "SecurityGroups[0].GroupId" --output text)
    echo "✅ Security group exists: $SG_ID"
fi

# Step 3: Launch instance
echo "📋 Step 3/5: Launching EC2 instance in $REGION..."
INSTANCE_ID=$(aws ec2 run-instances \
    --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SG_ID" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$INSTANCE_NAME}]" \
    --query 'Instances[0].InstanceId' \
    --output text)

echo "✅ Instance launched: $INSTANCE_ID"

# Step 4: Wait for instance
echo "📋 Step 4/5: Waiting for instance to start (this takes ~60 seconds)..."
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"
echo "✅ Instance is running"

# Step 5: Get public IP
echo "📋 Step 5/5: Getting instance details..."
PUBLIC_IP=$(aws ec2 describe-instances \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

echo ""
echo "=========================================="
echo "✅ EC2 INSTANCE CREATED!"
echo "=========================================="
echo ""
echo "Region: $REGION (Tokyo - Low latency to Binance)"
echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"
echo "SSH Key: ~/.ssh/$KEY_NAME.pem"
echo ""
echo "Connect with:"
echo "  ssh -i ~/.ssh/$KEY_NAME.pem ubuntu@$PUBLIC_IP"
echo ""
echo "Estimated cost: ~\$7-10/month (FREE on free tier)"
echo ""
echo "Management commands:"
echo "  Stop:  aws ec2 stop-instances --region $REGION --instance-ids $INSTANCE_ID"
echo "  Start: aws ec2 start-instances --region $REGION --instance-ids $INSTANCE_ID"
echo "  Kill:  aws ec2 terminate-instances --region $REGION --instance-ids $INSTANCE_ID"
echo ""

# Save details to file
cat > instance-details.txt << EOF
Instance ID: $INSTANCE_ID
Public IP: $PUBLIC_IP
SSH Command: ssh -i ~/.ssh/$KEY_NAME.pem ubuntu@$PUBLIC_IP
Created: $(date)
EOF

echo "Instance details saved to: instance-details.txt"
echo ""
