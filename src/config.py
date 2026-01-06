"""Configuration management for Polymarket Maker Rebates Bot."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Data directory
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

# Database configuration
DB_PATH = os.getenv("DB_PATH", "data/alpha.db")
DB_FULL_PATH = PROJECT_ROOT / DB_PATH
DB_FULL_PATH.parent.mkdir(parents=True, exist_ok=True)

# Polymarket credentials
POLYMARKET_PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY", "")
POLYMARKET_FUNDER = os.getenv("POLYMARKET_FUNDER", "")
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")

# Trading mode: "paper" or "live"
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# =============================================================================
# MAKER REBATES CONFIGURATION
# =============================================================================

# Position sizing (USD per leg - YES and NO)
MAKER_POSITION_SIZE = float(os.getenv("MAKER_POSITION_SIZE", "50"))

# Maximum concurrent positions (YES+NO pairs)
MAKER_MAX_CONCURRENT = int(os.getenv("MAKER_MAX_CONCURRENT", "3"))

# Minimum spread to enter (avoid tight spreads)
MAKER_MIN_SPREAD = float(os.getenv("MAKER_MIN_SPREAD", "0.02"))

# Probability range to trade (safest is 50%, avoid extremes)
MAKER_MIN_PROB = float(os.getenv("MAKER_MIN_PROB", "0.30"))
MAKER_MAX_PROB = float(os.getenv("MAKER_MAX_PROB", "0.70"))

# =============================================================================
# RISK LIMITS
# =============================================================================

# Maximum daily loss before stopping (USD)
MAX_DAILY_LOSS = float(os.getenv("MAX_DAILY_LOSS", "30"))

# Maximum position size per market (USD, both legs combined)
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "100"))

# Maximum delta exposure before rebalancing (percentage of total)
MAX_DELTA_PCT = float(os.getenv("MAX_DELTA_PCT", "0.05"))

# Kill switch file (create this file to halt all trading)
KILL_SWITCH_FILE = PROJECT_ROOT / ".kill_switch"

# =============================================================================
# API ENDPOINTS
# =============================================================================

CLOB_BASE_URL = "https://clob.polymarket.com"
GAMMA_API_URL = "https://gamma-api.polymarket.com"
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"

# Chain configuration (Polygon)
CHAIN_ID = 137

# =============================================================================
# 15-MINUTE CRYPTO MARKET SLUGS
# =============================================================================

CRYPTO_15M_SLUGS = [
    "will-btc-go-up-or-down-next-15-minutes",
    "will-eth-go-up-or-down-next-15-minutes",
]
