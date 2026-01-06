"""Configuration management for trading-lab."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent

# Data directory
DATA_DIR = PROJECT_ROOT / "data"

# Database configuration
DB_PATH = os.getenv("DB_PATH", "data/alpha.db")
DB_FULL_PATH = PROJECT_ROOT / DB_PATH

# Polymarket API
POLYMARKET_API_KEY = os.getenv("POLYMARKET_API_KEY", "")

# Wallet tracking
WALLETS_TO_TRACK = [
    w.strip() 
    for w in os.getenv("WALLETS_TO_TRACK", "").split(",") 
    if w.strip()
]

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_FULL_PATH.parent.mkdir(parents=True, exist_ok=True)
