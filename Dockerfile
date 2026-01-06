# Dockerfile for Polymarket Arbitrage Bot
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY pyproject.toml ./

# Install Python dependencies
RUN pip install --no-cache-dir \
    pydantic>=2.0.0 \
    python-dotenv>=1.0.0 \
    sqlalchemy>=2.0.0 \
    websocket-client>=1.0.0

# Copy application code
COPY . .

# Create data directory
RUN mkdir -p data/arbitrage

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)"

# Run the bot
CMD ["python", "scripts/run_arbitrage_bot.py", "--live"]
