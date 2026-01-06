#!/usr/bin/env python3
"""
Live Maker Bot - First-Mover Maker Rebates Strategy

Deploy maker orders on Polymarket 15-minute crypto markets to:
1. Capture maker rebates from the new fee structure (introduced Jan 6, 2026)
2. Gather real data about fill rates, spreads, and rebate economics
3. Learn what works before scaling up

SAFETY FEATURES:
- Micro position sizes ($5-10 per side)
- Kill switch file (.kill_switch)
- Daily loss limit ($20)
- Comprehensive logging

STRATEGY:
- Place YES and NO bids at aggressive prices (e.g., $0.45 each)
- If both fill: guaranteed profit at resolution + rebates
- If one fills: 50/50 on resolution, but learn about fill dynamics

Usage:
    # Run the bot
    python -m src.maker.live_maker_bot

    # Check status
    python -m src.maker.live_maker_bot --status

    # Emergency stop
    touch .kill_switch
"""

import json
import os
import sys
import time
import signal
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from decimal import Decimal
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('maker_bot.log')
    ]
)
logger = logging.getLogger(__name__)

# Apply Cloudflare bypass BEFORE importing py-clob-client
try:
    from src.maker.cloudflare_bypass import patch_clob_client
except ImportError:
    try:
        from cloudflare_bypass import patch_clob_client
    except ImportError:
        logger.warning("Cloudflare bypass not available")

# Try to import py-clob-client
try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType as ClobOrderType
    from py_clob_client.order_builder.constants import BUY, SELL
    CLOB_AVAILABLE = True
except ImportError:
    logger.warning("py-clob-client not installed - running in simulation mode")
    CLOB_AVAILABLE = False

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =============================================================================
# Configuration
# =============================================================================

@dataclass
class BotConfig:
    """Bot configuration with safety limits."""
    # Position sizing (MICRO for learning)
    position_size_usd: float = 5.0      # $5 per side (YES and NO)
    max_position_per_market: float = 10.0  # $10 total per market
    max_concurrent_markets: int = 2     # 1 BTC + 1 ETH

    # Pricing strategy
    bid_price_yes: float = 0.45         # Bid this much for YES
    bid_price_no: float = 0.45          # Bid this much for NO
    # If both fill at 0.45: cost = $0.90, payout = $1.00, profit = $0.10 + rebates

    # Safety limits
    max_daily_loss: float = 20.0        # Stop if down $20
    max_consecutive_losses: int = 5     # Pause after 5 losses

    # Timing
    min_seconds_to_resolution: int = 120  # Don't enter < 2 min to resolution
    max_seconds_to_resolution: int = 840  # Don't enter > 14 min (too early)
    cycle_interval_seconds: int = 30    # Check markets every 30 seconds

    # Files
    kill_switch_file: str = ".kill_switch"
    state_file: str = "maker_bot_state.json"

    # API
    gamma_api: str = "https://gamma-api.polymarket.com"
    clob_api: str = "https://clob.polymarket.com"


@dataclass
class BotState:
    """Persistent bot state."""
    total_pnl: float = 0.0
    daily_pnl: float = 0.0
    total_trades: int = 0
    daily_trades: int = 0
    consecutive_losses: int = 0
    last_reset_date: str = ""

    # Tracking
    orders_placed: int = 0
    orders_filled: int = 0
    yes_fills: int = 0
    no_fills: int = 0
    both_fills: int = 0

    # Current positions
    active_orders: Dict = field(default_factory=dict)
    positions: Dict = field(default_factory=dict)

    # Learning data
    fill_prices: List[float] = field(default_factory=list)
    spreads_observed: List[float] = field(default_factory=list)


# =============================================================================
# Market Discovery
# =============================================================================

class MarketFinder:
    """Find active 15-minute crypto markets."""

    # Browser-like headers to avoid Cloudflare blocks
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, config: BotConfig):
        self.config = config
        self.assets = ["btc", "eth"]

    def get_next_15m_timestamp(self) -> int:
        """Get Unix timestamp for next 15-minute boundary."""
        now = int(time.time())
        return ((now // 900) + 1) * 900

    def build_slug(self, asset: str, timestamp: int) -> str:
        """Build market slug."""
        return f"{asset.lower()}-updown-15m-{timestamp}"

    def fetch_market(self, slug: str) -> Optional[Dict]:
        """Fetch market by slug."""
        try:
            resp = requests.get(
                f"{self.config.gamma_api}/markets",
                params={"slug": slug},
                headers=self.HEADERS,
                timeout=10
            )
            data = resp.json()
            return data[0] if data else None
        except Exception as e:
            logger.error(f"Error fetching market {slug}: {e}")
            return None

    def find_active_markets(self) -> List[Dict]:
        """Find currently tradeable 15-minute markets."""
        markets = []
        base_ts = self.get_next_15m_timestamp()

        # Check current and next window
        timestamps = [base_ts, base_ts + 900]

        for asset in self.assets:
            for ts in timestamps:
                slug = self.build_slug(asset, ts)
                market = self.fetch_market(slug)

                if not market:
                    continue

                # Check if market is accepting orders
                if not market.get("acceptingOrders", False):
                    logger.debug(f"{slug}: Not accepting orders")
                    continue

                seconds_left = ts - int(time.time())

                # Check if within our trading window
                if (self.config.min_seconds_to_resolution <= seconds_left <=
                    self.config.max_seconds_to_resolution):

                    market['_seconds_left'] = seconds_left
                    market['_end_timestamp'] = ts
                    market['_asset'] = asset.upper()
                    markets.append(market)
                    logger.info(f"Found active market: {slug} ({seconds_left}s left)")
                    break  # Only one market per asset

        return markets


# =============================================================================
# Order Execution
# =============================================================================

class OrderExecutor:
    """Execute orders on Polymarket CLOB."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.client = None
        self._init_client()

    def _init_client(self):
        """Initialize CLOB client."""
        if not CLOB_AVAILABLE:
            logger.warning("CLOB client not available - simulation mode")
            return

        private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        funder = os.getenv("POLYMARKET_FUNDER")

        if not private_key:
            logger.error("POLYMARKET_PRIVATE_KEY not set!")
            return

        try:
            self.client = ClobClient(
                host=self.config.clob_api,
                key=private_key,
                chain_id=137,
                funder=funder,
                signature_type=2  # POLY_GNOSIS_SAFE
            )
            # Derive API credentials
            self.client.set_api_creds(self.client.derive_api_key())
            logger.info("CLOB client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            self.client = None

    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Get orderbook for a token."""
        try:
            resp = requests.get(
                f"{self.config.clob_api}/book",
                params={"token_id": token_id},
                timeout=10
            )
            return resp.json()
        except Exception as e:
            logger.error(f"Error fetching orderbook: {e}")
            return None

    def place_limit_order(
        self,
        token_id: str,
        side: str,  # "BUY" or "SELL"
        price: float,
        size: float
    ) -> Optional[Dict]:
        """Place a limit order."""
        if not self.client:
            logger.warning(f"SIMULATION: Would place {side} order for {size} @ ${price}")
            return {"simulated": True, "id": f"sim_{int(time.time())}"}

        try:
            order_args = OrderArgs(
                price=price,
                size=size,
                side=BUY if side == "BUY" else SELL,
                token_id=token_id
            )

            signed_order = self.client.create_order(order_args)
            result = self.client.post_order(signed_order, ClobOrderType.GTC)

            logger.info(f"Order placed: {side} {size} @ ${price} -> {result}")
            return result

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            return None

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if not self.client:
            logger.warning(f"SIMULATION: Would cancel order {order_id}")
            return True

        try:
            result = self.client.cancel(order_id)
            logger.info(f"Order cancelled: {order_id} -> {result}")
            return True
        except Exception as e:
            logger.error(f"Error cancelling order: {e}")
            return False

    def get_open_orders(self) -> List[Dict]:
        """Get all open orders."""
        if not self.client:
            return []

        try:
            return self.client.get_orders()
        except Exception as e:
            logger.error(f"Error getting orders: {e}")
            return []

    def cancel_all_orders(self) -> int:
        """Cancel all open orders."""
        if not self.client:
            return 0

        try:
            orders = self.get_open_orders()
            cancelled = 0
            for order in orders:
                if self.cancel_order(order.get('id')):
                    cancelled += 1
            return cancelled
        except Exception as e:
            logger.error(f"Error cancelling all orders: {e}")
            return 0


# =============================================================================
# Main Bot
# =============================================================================

class LiveMakerBot:
    """Main maker bot orchestrator."""

    def __init__(self, config: Optional[BotConfig] = None):
        self.config = config or BotConfig()
        self.state = BotState()
        self.market_finder = MarketFinder(self.config)
        self.executor = OrderExecutor(self.config)
        self.running = False

        # Load state
        self._load_state()

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _load_state(self):
        """Load persistent state."""
        try:
            if Path(self.config.state_file).exists():
                with open(self.config.state_file) as f:
                    data = json.load(f)
                    for key, value in data.items():
                        if hasattr(self.state, key):
                            setattr(self.state, key, value)
                logger.info(f"Loaded state: PnL=${self.state.total_pnl:.2f}")
        except Exception as e:
            logger.error(f"Error loading state: {e}")

    def _save_state(self):
        """Save persistent state."""
        try:
            with open(self.config.state_file, 'w') as f:
                json.dump(asdict(self.state), f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signal."""
        logger.info("Shutdown signal received")
        self.running = False
        self._cleanup()

    def _cleanup(self):
        """Cleanup on shutdown."""
        logger.info("Cleaning up...")
        cancelled = self.executor.cancel_all_orders()
        logger.info(f"Cancelled {cancelled} orders")
        self._save_state()

    def _check_kill_switch(self) -> bool:
        """Check if kill switch is active."""
        return Path(self.config.kill_switch_file).exists()

    def _check_daily_reset(self):
        """Reset daily counters if new day."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.last_reset_date != today:
            logger.info(f"New day - resetting daily counters")
            self.state.daily_pnl = 0.0
            self.state.daily_trades = 0
            self.state.last_reset_date = today
            self._save_state()

    def _check_safety_limits(self) -> Tuple[bool, str]:
        """Check if we're within safety limits."""
        # Kill switch
        if self._check_kill_switch():
            return False, "Kill switch active"

        # Daily loss limit
        if self.state.daily_pnl <= -self.config.max_daily_loss:
            return False, f"Daily loss limit reached: ${self.state.daily_pnl:.2f}"

        # Consecutive losses
        if self.state.consecutive_losses >= self.config.max_consecutive_losses:
            return False, f"Too many consecutive losses: {self.state.consecutive_losses}"

        return True, "OK"

    def _parse_market_tokens(self, market: Dict) -> Tuple[Optional[str], Optional[str]]:
        """Parse YES and NO token IDs from market."""
        token_ids_raw = market.get("clobTokenIds", "[]")
        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw

        if not token_ids or len(token_ids) < 2:
            return None, None

        # Determine which is UP (YES) and which is DOWN (NO)
        outcomes_raw = market.get("outcomes", "[]")
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

        up_idx, down_idx = 0, 1
        for i, outcome in enumerate(outcomes):
            if outcome.upper() in ("UP", "YES"):
                up_idx = i
            elif outcome.upper() in ("DOWN", "NO"):
                down_idx = i

        return token_ids[up_idx], token_ids[down_idx]

    def _place_maker_orders(self, market: Dict) -> Dict:
        """Place YES and NO maker orders for a market."""
        slug = market.get("slug", "")
        yes_token, no_token = self._parse_market_tokens(market)

        if not yes_token or not no_token:
            logger.error(f"Could not parse tokens for {slug}")
            return {"success": False, "reason": "no_tokens"}

        # Calculate sizes
        yes_size = self.config.position_size_usd / self.config.bid_price_yes
        no_size = self.config.position_size_usd / self.config.bid_price_no

        logger.info(f"Placing orders for {slug}:")
        logger.info(f"  YES: BUY {yes_size:.2f} @ ${self.config.bid_price_yes}")
        logger.info(f"  NO:  BUY {no_size:.2f} @ ${self.config.bid_price_no}")

        # Place YES order (buying UP outcome)
        yes_result = self.executor.place_limit_order(
            token_id=yes_token,
            side="BUY",
            price=self.config.bid_price_yes,
            size=yes_size
        )

        # Place NO order (buying DOWN outcome)
        no_result = self.executor.place_limit_order(
            token_id=no_token,
            side="BUY",
            price=self.config.bid_price_no,
            size=no_size
        )

        # Track orders
        self.state.orders_placed += 2

        return {
            "success": True,
            "slug": slug,
            "yes_order": yes_result,
            "no_order": no_result,
            "yes_token": yes_token,
            "no_token": no_token,
        }

    def run_cycle(self):
        """Run one trading cycle."""
        logger.info("=" * 50)
        logger.info(f"Cycle at {datetime.now(timezone.utc).isoformat()}")

        # Check safety
        safe, reason = self._check_safety_limits()
        if not safe:
            logger.warning(f"Safety check failed: {reason}")
            return

        # Find active markets
        markets = self.market_finder.find_active_markets()
        logger.info(f"Found {len(markets)} active markets")

        for market in markets[:self.config.max_concurrent_markets]:
            slug = market.get("slug", "")
            seconds_left = market.get("_seconds_left", 0)
            asset = market.get("_asset", "")

            logger.info(f"Market: {slug} ({seconds_left}s left)")

            # Check orderbook
            yes_token, no_token = self._parse_market_tokens(market)
            if yes_token:
                book = self.executor.get_orderbook(yes_token)
                if book:
                    bids = book.get("bids", [])
                    asks = book.get("asks", [])
                    if bids and asks:
                        best_bid = float(bids[0]["price"])
                        best_ask = float(asks[0]["price"])
                        spread = best_ask - best_bid
                        logger.info(f"  Orderbook: bid=${best_bid:.3f}, ask=${best_ask:.3f}, spread=${spread:.3f}")
                        self.state.spreads_observed.append(spread)

            # Skip if we already have orders in this market
            if slug in self.state.active_orders:
                logger.info(f"  Already have orders in {slug}")
                continue

            # Place orders
            result = self._place_maker_orders(market)
            if result.get("success"):
                self.state.active_orders[slug] = result
                logger.info(f"  Orders placed successfully")
            else:
                logger.warning(f"  Failed to place orders: {result.get('reason')}")

        # Save state
        self._save_state()

    def run(self):
        """Main run loop."""
        logger.info("=" * 60)
        logger.info("LIVE MAKER BOT STARTING")
        logger.info("=" * 60)
        logger.info(f"Config: ${self.config.position_size_usd}/side @ ${self.config.bid_price_yes}/{self.config.bid_price_no}")
        logger.info(f"Max daily loss: ${self.config.max_daily_loss}")
        logger.info(f"Cycle interval: {self.config.cycle_interval_seconds}s")

        self.running = True
        self._check_daily_reset()

        while self.running:
            try:
                self.run_cycle()

                # Sleep until next cycle
                logger.info(f"Sleeping {self.config.cycle_interval_seconds}s...")
                time.sleep(self.config.cycle_interval_seconds)

            except KeyboardInterrupt:
                logger.info("Keyboard interrupt")
                break
            except Exception as e:
                logger.error(f"Error in cycle: {e}")
                time.sleep(10)  # Wait before retrying

        self._cleanup()
        logger.info("Bot stopped")

    def status(self):
        """Print current status."""
        print("\n" + "=" * 50)
        print("MAKER BOT STATUS")
        print("=" * 50)
        print(f"Total P&L:        ${self.state.total_pnl:.2f}")
        print(f"Daily P&L:        ${self.state.daily_pnl:.2f}")
        print(f"Orders placed:    {self.state.orders_placed}")
        print(f"Orders filled:    {self.state.orders_filled}")
        print(f"YES fills:        {self.state.yes_fills}")
        print(f"NO fills:         {self.state.no_fills}")
        print(f"Both fills:       {self.state.both_fills}")
        print(f"Active orders:    {len(self.state.active_orders)}")
        print(f"Spreads observed: {len(self.state.spreads_observed)}")
        if self.state.spreads_observed:
            avg_spread = sum(self.state.spreads_observed) / len(self.state.spreads_observed)
            print(f"Avg spread:       ${avg_spread:.3f}")
        print("=" * 50)


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Live Maker Bot")
    parser.add_argument("--status", action="store_true", help="Show status only")
    parser.add_argument("--bid-yes", type=float, default=0.45, help="YES bid price")
    parser.add_argument("--bid-no", type=float, default=0.45, help="NO bid price")
    parser.add_argument("--size", type=float, default=5.0, help="Position size USD")
    args = parser.parse_args()

    config = BotConfig(
        bid_price_yes=args.bid_yes,
        bid_price_no=args.bid_no,
        position_size_usd=args.size
    )

    bot = LiveMakerBot(config)

    if args.status:
        bot.status()
    else:
        bot.run()


if __name__ == "__main__":
    main()
