#!/usr/bin/env python3
"""
Post-Resolution Spread Capture Bot

Replicates Account88888's strategy:
- Trade AFTER 15-minute markets resolve
- Buy both UP and DOWN tokens
- Capture spread from market inefficiencies
- Target ~0.5% edge per trade

Key insight: Account88888 traded at mid-market prices (~$0.32-0.50)
using the AMM/market maker mechanism, not limit orders.
"""

import os
import sys
import json
import time
import logging
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.arbitrage.resolution_monitor import ResolutionMonitor, Market15m
from src.trading.executor import LiveExecutor, SafeExecutor, OrderResult


class BotState(Enum):
    """Bot operational states."""
    STOPPED = "stopped"
    WATCHING = "watching"
    TRADING = "trading"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class Position:
    """Open position tracker."""
    market_slug: str
    token_id: str
    outcome: str  # "Up" or "Down"
    entry_price: float
    size: float
    entry_time: int
    order_id: str

    @property
    def cost(self) -> float:
        return self.entry_price * self.size


@dataclass
class TradeStats:
    """Trading statistics."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_volume: float = 0.0
    total_profit: float = 0.0
    total_fees: float = 0.0

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0
        return self.winning_trades / self.total_trades

    @property
    def net_profit(self) -> float:
        return self.total_profit - self.total_fees


@dataclass
class BotConfig:
    """Bot configuration."""
    # Capital management
    starting_capital: float = 250.0
    max_position_pct: float = 0.10  # Max 10% per trade
    max_total_exposure_pct: float = 0.40  # Max 40% total exposure

    # Edge requirements
    min_edge_pct: float = 0.003  # 0.3% minimum
    target_edge_pct: float = 0.005  # 0.5% target

    # Timing
    min_seconds_after_resolution: int = 5
    max_seconds_after_resolution: int = 600  # 10 minutes

    # Risk management
    max_daily_loss: float = 50.0
    max_consecutive_losses: int = 10
    min_liquidity: float = 50.0

    # Trading parameters
    order_type: str = "GTC"  # GTC for better fills


class PostResolutionBot:
    """
    Post-resolution spread capture bot.

    Strategy:
    1. Monitor for market resolutions
    2. When market resolves, check for spread opportunity
    3. If spread > min_edge, buy tokens
    4. Exit when spread captured or timeout
    """

    CLOB_API = "https://clob.polymarket.com"

    def __init__(
        self,
        config: Optional[BotConfig] = None,
        live: bool = False,
        data_dir: Optional[Path] = None,
    ):
        self.config = config or BotConfig()
        self.live = live
        self.data_dir = data_dir or Path("data/post_resolution")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Components
        self.monitor = ResolutionMonitor(self.data_dir)
        self.executor = SafeExecutor(
            dry_run=not live,
            max_order_size=self.config.starting_capital * self.config.max_position_pct * 1.5,  # Allow buffer for exits
            max_daily_orders=200
        )

        # State
        self.state = BotState.STOPPED
        self.capital = self.config.starting_capital
        self.positions: Dict[str, Position] = {}
        self.stats = TradeStats()

        # Risk tracking
        self.daily_pnl = 0.0
        self.consecutive_losses = 0
        self.last_trade_time = 0

        # Setup logging
        self._setup_logging()

    def _setup_logging(self):
        """Setup logging."""
        log_file = self.data_dir / "bot.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger("PostResolutionBot")

    def get_market_price(self, token_id: str, side: str = "buy") -> Optional[float]:
        """Get current market price from CLOB API."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/price",
                params={"token_id": token_id, "side": side},
                timeout=10
            )
            if response.ok:
                data = response.json()
                return float(data.get("price", 0))
        except Exception as e:
            self.logger.error(f"Error getting price: {e}")
        return None

    def get_midpoint(self, token_id: str) -> Optional[float]:
        """Get midpoint price."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/midpoint",
                params={"token_id": token_id},
                timeout=10
            )
            if response.ok:
                data = response.json()
                return float(data.get("mid", 0))
        except Exception as e:
            self.logger.error(f"Error getting midpoint: {e}")
        return None

    def calculate_edge(self, market: Market15m) -> Tuple[Optional[Dict], Optional[Dict]]:
        """
        Calculate trading edge for a resolved market.

        Returns (up_opportunity, down_opportunity) dicts or None.
        """
        now = time.time()
        seconds_after = now - market.end_timestamp

        # Check timing window
        if seconds_after < self.config.min_seconds_after_resolution:
            return None, None
        if seconds_after > self.config.max_seconds_after_resolution:
            return None, None

        up_opp = None
        down_opp = None

        # Get UP token prices
        up_buy = self.get_market_price(market.token_up, "buy")
        up_sell = self.get_market_price(market.token_up, "sell")

        if up_buy and up_sell and up_buy > 0 and up_sell > up_buy:
            spread = up_sell - up_buy
            edge = spread / up_buy

            if edge >= self.config.min_edge_pct:
                up_opp = {
                    "token_id": market.token_up,
                    "outcome": "Up",
                    "buy_price": up_buy,
                    "sell_price": up_sell,
                    "spread": spread,
                    "edge_pct": edge,
                }

        # Get DOWN token prices
        down_buy = self.get_market_price(market.token_down, "buy")
        down_sell = self.get_market_price(market.token_down, "sell")

        if down_buy and down_sell and down_buy > 0 and down_sell > down_buy:
            spread = down_sell - down_buy
            edge = spread / down_buy

            if edge >= self.config.min_edge_pct:
                down_opp = {
                    "token_id": market.token_down,
                    "outcome": "Down",
                    "buy_price": down_buy,
                    "sell_price": down_sell,
                    "spread": spread,
                    "edge_pct": edge,
                }

        return up_opp, down_opp

    def calculate_position_size(self, price: float) -> float:
        """Calculate position size based on capital and risk."""
        max_by_capital = self.capital * self.config.max_position_pct
        max_by_exposure = (
            self.capital * self.config.max_total_exposure_pct -
            sum(p.cost for p in self.positions.values())
        )

        max_value = min(max_by_capital, max_by_exposure)
        if max_value <= 0:
            return 0

        size = max_value / price
        return round(size, 2)

    def should_trade(self) -> Tuple[bool, str]:
        """Check if trading should proceed."""
        # Check executor
        if not self.executor.is_ready():
            return False, f"Executor not ready: {self.executor.get_error()}"

        # Check capital
        if self.capital < 10:
            return False, "Insufficient capital"

        # Check daily loss limit
        if self.daily_pnl < -self.config.max_daily_loss:
            return False, f"Daily loss limit hit: ${-self.daily_pnl:.2f}"

        # Check consecutive losses
        if self.consecutive_losses >= self.config.max_consecutive_losses:
            return False, f"Too many consecutive losses: {self.consecutive_losses}"

        # Check exposure
        current_exposure = sum(p.cost for p in self.positions.values())
        max_exposure = self.capital * self.config.max_total_exposure_pct
        if current_exposure >= max_exposure:
            return False, f"Max exposure reached: ${current_exposure:.2f}"

        return True, "OK"

    def execute_trade(
        self,
        market: Market15m,
        opportunity: Dict
    ) -> Optional[Position]:
        """Execute a trade for an opportunity."""
        token_id = opportunity["token_id"]
        buy_price = opportunity["buy_price"]
        outcome = opportunity["outcome"]

        # Calculate size
        size = self.calculate_position_size(buy_price)
        if size < 5:  # Minimum size
            self.logger.info(f"Size too small: {size}")
            return None

        # Execute buy
        self.logger.info(f"Executing BUY {outcome} @ ${buy_price:.4f} x {size:.1f}")

        result = self.executor.place_order(
            token_id=token_id,
            side="buy",
            size=size,
            price=buy_price,
        )

        if not result.success:
            self.logger.error(f"Order failed: {result.message}")
            return None

        # Create position
        position = Position(
            market_slug=market.slug,
            token_id=token_id,
            outcome=outcome,
            entry_price=buy_price,
            size=result.filled_size if result.filled_size > 0 else size,
            entry_time=int(time.time()),
            order_id=result.order_id or "",
        )

        self.positions[token_id] = position
        self.stats.total_trades += 1
        self.stats.total_volume += position.cost
        self.last_trade_time = time.time()

        self.logger.info(f"Position opened: {outcome} ${position.cost:.2f}")
        return position

    def check_exits(self):
        """Check positions for exit opportunities."""
        for token_id, position in list(self.positions.items()):
            # Get current sell price
            sell_price = self.get_market_price(token_id, "sell")

            if not sell_price:
                continue

            # Check for profit
            profit_pct = (sell_price - position.entry_price) / position.entry_price

            should_exit = False
            reason = ""

            # Take profit at target edge
            if profit_pct >= self.config.target_edge_pct:
                should_exit = True
                reason = f"Target reached: {profit_pct*100:.2f}%"

            # Stop loss at -3%
            elif profit_pct <= -0.03:
                should_exit = True
                reason = f"Stop loss: {profit_pct*100:.2f}%"

            # Timeout (10 min)
            elif time.time() - position.entry_time > 600:
                should_exit = True
                reason = "Timeout"

            if should_exit:
                self._exit_position(token_id, sell_price, reason)

    def _exit_position(self, token_id: str, exit_price: float, reason: str):
        """Exit a position."""
        position = self.positions.get(token_id)
        if not position:
            return

        # Execute sell
        self.logger.info(f"Exiting {position.outcome} @ ${exit_price:.4f}: {reason}")

        result = self.executor.place_order(
            token_id=token_id,
            side="sell",
            size=position.size,
            price=exit_price,
        )

        if not result.success:
            self.logger.error(f"Exit failed: {result.message}")
            return

        # Calculate P&L
        exit_value = exit_price * position.size
        entry_cost = position.entry_price * position.size
        gross_profit = exit_value - entry_cost
        fees = entry_cost * 0.01 + exit_value * 0.01  # 1% taker fee each side
        net_profit = gross_profit - fees

        # Update stats
        self.stats.total_profit += gross_profit
        self.stats.total_fees += fees
        self.daily_pnl += net_profit

        if net_profit > 0:
            self.stats.winning_trades += 1
            self.consecutive_losses = 0
        else:
            self.stats.losing_trades += 1
            self.consecutive_losses += 1

        self.logger.info(
            f"Position closed: {position.outcome} "
            f"P&L: ${net_profit:.2f} ({net_profit/entry_cost*100:.2f}%)"
        )

        # Remove position
        del self.positions[token_id]

    def run_cycle(self):
        """Run one trading cycle."""
        # Check if we should trade
        can_trade, reason = self.should_trade()
        if not can_trade:
            self.logger.debug(f"Not trading: {reason}")
            return

        # Discover new markets
        self.monitor.discover_markets(hours_ahead=1, hours_behind=0.25)

        # Check for resolutions
        self.monitor.check_resolutions()

        # Get recently resolved markets
        recently_resolved = self.monitor.get_recently_resolved(within_seconds=600)

        for market in recently_resolved:
            # Skip if we already have a position in this market
            if market.token_up in self.positions or market.token_down in self.positions:
                continue

            # Calculate edge
            up_opp, down_opp = self.calculate_edge(market)

            # Trade UP if opportunity exists
            if up_opp and up_opp["edge_pct"] >= self.config.min_edge_pct:
                self.execute_trade(market, up_opp)

            # Trade DOWN if opportunity exists
            if down_opp and down_opp["edge_pct"] >= self.config.min_edge_pct:
                self.execute_trade(market, down_opp)

        # Check for exits
        self.check_exits()

    def start(self):
        """Start the bot."""
        self.state = BotState.WATCHING
        self.logger.info(f"Bot started {'LIVE' if self.live else 'PAPER'}")
        self.logger.info(f"Capital: ${self.capital:.2f}")
        self.logger.info(f"Min edge: {self.config.min_edge_pct*100:.2f}%")

    def stop(self):
        """Stop the bot."""
        self.state = BotState.STOPPED
        self.logger.info("Bot stopped")
        self.save_state()

    def save_state(self):
        """Save bot state to disk."""
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "live": self.live,
            "capital": self.capital,
            "daily_pnl": self.daily_pnl,
            "positions": {k: {
                "market_slug": v.market_slug,
                "token_id": v.token_id,
                "outcome": v.outcome,
                "entry_price": v.entry_price,
                "size": v.size,
                "entry_time": v.entry_time,
            } for k, v in self.positions.items()},
            "stats": {
                "total_trades": self.stats.total_trades,
                "winning_trades": self.stats.winning_trades,
                "losing_trades": self.stats.losing_trades,
                "total_volume": self.stats.total_volume,
                "total_profit": self.stats.total_profit,
                "total_fees": self.stats.total_fees,
            }
        }

        filepath = self.data_dir / "bot_state.json"
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)

    def load_state(self):
        """Load bot state from disk."""
        filepath = self.data_dir / "bot_state.json"

        if not filepath.exists():
            return

        try:
            with open(filepath) as f:
                state = json.load(f)

            self.capital = state.get("capital", self.config.starting_capital)
            self.daily_pnl = state.get("daily_pnl", 0)

            stats = state.get("stats", {})
            self.stats.total_trades = stats.get("total_trades", 0)
            self.stats.winning_trades = stats.get("winning_trades", 0)
            self.stats.losing_trades = stats.get("losing_trades", 0)
            self.stats.total_volume = stats.get("total_volume", 0)
            self.stats.total_profit = stats.get("total_profit", 0)
            self.stats.total_fees = stats.get("total_fees", 0)

        except Exception as e:
            self.logger.error(f"Error loading state: {e}")

    def print_status(self):
        """Print current bot status."""
        print("\n" + "=" * 60)
        print("POST-RESOLUTION BOT STATUS")
        print("=" * 60)
        print(f"State: {self.state.value}")
        print(f"Mode: {'LIVE' if self.live else 'PAPER'}")
        print(f"\nCapital: ${self.capital:.2f}")
        print(f"Daily P&L: ${self.daily_pnl:.2f}")
        print(f"Open positions: {len(self.positions)}")

        if self.positions:
            print("\nPositions:")
            for pos in self.positions.values():
                print(f"  {pos.outcome}: ${pos.cost:.2f} @ ${pos.entry_price:.4f}")

        print(f"\nStats:")
        print(f"  Trades: {self.stats.total_trades}")
        print(f"  Win rate: {self.stats.win_rate*100:.1f}%")
        print(f"  Volume: ${self.stats.total_volume:.2f}")
        print(f"  Net P&L: ${self.stats.net_profit:.2f}")

        # Monitor status
        self.monitor.print_status()


def main():
    """Test the bot."""
    # Load environment
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    config = BotConfig(
        starting_capital=250,
        min_edge_pct=0.003,
        max_position_pct=0.10,
    )

    bot = PostResolutionBot(config=config, live=False)
    bot.start()

    print("\nRunning test cycle...")
    bot.run_cycle()

    bot.print_status()
    bot.stop()


if __name__ == "__main__":
    main()
