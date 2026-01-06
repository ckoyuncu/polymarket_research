#!/usr/bin/env python3
"""
Live Trading Bot - Learning-First Approach

A conservative live trading bot focused on learning, not profit maximization.
Capital: $300, Goal: Survive to learn.

IMPORTANT SAFETY FEATURES:
1. Kill switches: Keyboard, loss limit, error threshold
2. Conservative limits: $15/trade max, $30/day max loss, 20 trades/day
3. Consecutive loss pause: 3 losses = 30 minute pause
4. Detailed logging of every decision

Trading Rules (from ORDERBOOK_SIGNAL_FINDINGS.md):
- BTC: Orderbook imbalance >= 0.5 (83.3% accuracy)
- ETH: Early momentum, NOT orderbook (88.9% accuracy)
- Combined: When OB + momentum agree (84.8% BTC, 95.7% ETH)

Usage:
    # Paper trading (default, SAFE)
    python -m src.trading.live_bot

    # Live trading (USE WITH CAUTION)
    python -m src.trading.live_bot --live

    # Check status only
    python -m src.trading.live_bot --status
"""

import json
import os
import sys
import time
import signal
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from enum import Enum
import logging

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.trading.executor import SafeExecutor, OrderType, OrderResult


# ==============================================================================
# Configuration
# ==============================================================================

@dataclass
class BotConfig:
    """Conservative bot configuration for $300 capital."""

    # Capital constraints
    total_capital: float = 300.0
    max_position_size: float = 15.0  # 5% of capital per trade
    max_daily_loss: float = 30.0      # 10% of capital
    max_trades_per_day: int = 20

    # Risk controls
    consecutive_loss_pause_count: int = 3
    consecutive_loss_pause_minutes: int = 30
    max_consecutive_errors: int = 3

    # Signal thresholds (from ORDERBOOK_SIGNAL_FINDINGS.md)
    btc_imbalance_threshold: float = 0.5  # 83.3% accuracy
    eth_momentum_threshold: float = 0.001  # 0.1% price change
    min_confidence: float = 0.6  # Minimum confidence to trade

    # Timing
    min_time_before_close_sec: int = 30  # Don't trade in last 30s
    max_time_before_close_sec: int = 60  # Trade in last 30-60s window
    poll_interval_sec: int = 5

    # Execution
    dry_run: bool = True  # SAFE by default

    @classmethod
    def from_json(cls, path: str) -> "BotConfig":
        """Load config from JSON file."""
        with open(path, 'r') as f:
            data = json.load(f)
        return cls(**data)

    def to_json(self, path: str):
        """Save config to JSON file."""
        with open(path, 'w') as f:
            json.dump(asdict(self), f, indent=2)


# ==============================================================================
# Data Classes
# ==============================================================================

class BotState(Enum):
    """Bot operating states."""
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"  # Due to consecutive losses
    STOPPED = "stopped"
    KILLED = "killed"  # Kill switch triggered


@dataclass
class TradeDecision:
    """Record of a trading decision (trade or skip)."""
    timestamp: str
    asset: str
    market_slug: str
    decision: str  # "trade", "skip", "killed"
    direction: Optional[str] = None  # "up" or "down"
    confidence: float = 0.0
    reason: str = ""

    # Market state at decision time
    binance_price: float = 0.0
    window_start_price: float = 0.0
    orderbook_imbalance: float = 0.0
    momentum: float = 0.0
    time_to_close_sec: int = 0

    # Execution details (if traded)
    order_id: Optional[str] = None
    position_size: float = 0.0
    entry_price: float = 0.0

    # Outcome (filled after resolution)
    outcome: Optional[str] = None  # "win", "loss", None
    profit: Optional[float] = None
    resolution: Optional[str] = None


@dataclass
class DailyStats:
    """Daily trading statistics."""
    date: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    consecutive_losses: int = 0
    pause_until: Optional[float] = None
    errors: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0.0


# ==============================================================================
# Kill Switch Handler
# ==============================================================================

class KillSwitch:
    """Multi-trigger kill switch for safety."""

    def __init__(self, config: BotConfig):
        self.config = config
        self.triggered = False
        self.reason = ""
        self._lock = threading.Lock()

        # Register signal handlers
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Handle keyboard interrupt."""
        self.trigger("Keyboard interrupt (Ctrl+C)")

    def trigger(self, reason: str):
        """Trigger the kill switch."""
        with self._lock:
            if not self.triggered:
                self.triggered = True
                self.reason = reason
                logging.critical(f"KILL SWITCH TRIGGERED: {reason}")

    def check_loss_limit(self, daily_pnl: float) -> bool:
        """Check if daily loss limit exceeded."""
        if daily_pnl <= -self.config.max_daily_loss:
            self.trigger(f"Daily loss limit exceeded: ${daily_pnl:.2f}")
            return True
        return False

    def check_error_limit(self, consecutive_errors: int) -> bool:
        """Check if error threshold exceeded."""
        if consecutive_errors >= self.config.max_consecutive_errors:
            self.trigger(f"Consecutive errors: {consecutive_errors}")
            return True
        return False

    def is_killed(self) -> bool:
        """Check if kill switch was triggered."""
        return self.triggered


# ==============================================================================
# Signal Generator
# ==============================================================================

class SignalGenerator:
    """Generate trading signals based on ORDERBOOK_SIGNAL_FINDINGS.md rules."""

    CLOB_API = "https://clob.polymarket.com"

    def __init__(self, config: BotConfig):
        self.config = config
        self.binance_prices: Dict[str, float] = {}
        self.window_start_prices: Dict[str, float] = {}

    def fetch_binance_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from Binance."""
        try:
            pair = f"{symbol}USDT"
            for base_url in ["https://api.binance.com", "https://api.binance.us"]:
                try:
                    response = requests.get(
                        f"{base_url}/api/v3/ticker/price",
                        params={"symbol": pair},
                        timeout=2
                    )
                    if response.ok:
                        return float(response.json()["price"])
                except:
                    continue
        except Exception as e:
            logging.warning(f"Binance price fetch failed: {e}")
        return None

    def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch orderbook for a token."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
                timeout=5
            )
            if response.ok:
                return response.json()
        except Exception as e:
            logging.warning(f"Orderbook fetch failed: {e}")
        return None

    def calculate_orderbook_imbalance(self, book: dict) -> float:
        """Calculate orderbook imbalance (-1 to +1)."""
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        bid_depth = sum(float(b.get("size", 0)) for b in bids[:5])
        ask_depth = sum(float(a.get("size", 0)) for a in asks[:5])
        total = bid_depth + ask_depth

        if total == 0:
            return 0.0
        return (bid_depth - ask_depth) / total

    def update_prices(self):
        """Update current Binance prices."""
        for asset in ["BTC", "ETH"]:
            price = self.fetch_binance_price(asset)
            if price:
                self.binance_prices[asset] = price

    def record_window_start(self, asset: str, window_start: int):
        """Record price at window start for momentum calculation."""
        key = f"{asset}_{window_start}"
        if key not in self.window_start_prices:
            price = self.binance_prices.get(asset)
            if price:
                self.window_start_prices[key] = price

    def get_momentum(self, asset: str, window_start: int) -> float:
        """Calculate price momentum since window start."""
        key = f"{asset}_{window_start}"
        start_price = self.window_start_prices.get(key)
        current_price = self.binance_prices.get(asset)

        if not start_price or not current_price:
            return 0.0

        return (current_price - start_price) / start_price

    def generate_btc_signal(
        self,
        token_up: str,
        token_down: str,
        window_start: int
    ) -> Tuple[Optional[str], float, str]:
        """
        Generate BTC signal based on orderbook imbalance.

        Rule: IF |orderbook_imbalance| >= 0.5: TRADE direction = sign(imbalance)
        Expected accuracy: 83.3%

        Returns: (direction, confidence, reason)
        """
        book_up = self.fetch_orderbook(token_up)
        book_down = self.fetch_orderbook(token_down)

        if not book_up or not book_down:
            return None, 0.0, "Failed to fetch orderbooks"

        up_imbalance = self.calculate_orderbook_imbalance(book_up)
        down_imbalance = self.calculate_orderbook_imbalance(book_down)

        # Net imbalance: positive = bet UP, negative = bet DOWN
        net_imbalance = up_imbalance - down_imbalance

        # Also get momentum for confirmation
        momentum = self.get_momentum("BTC", window_start)

        reason_parts = [
            f"OB_imbal={net_imbalance:.3f}",
            f"momentum={momentum*100:.3f}%"
        ]

        # Primary signal: orderbook imbalance
        if abs(net_imbalance) >= self.config.btc_imbalance_threshold:
            direction = "up" if net_imbalance > 0 else "down"

            # Check if momentum confirms (higher confidence)
            momentum_confirms = (
                (direction == "up" and momentum > 0) or
                (direction == "down" and momentum < 0)
            )

            if momentum_confirms:
                # OB + momentum agree: 84.8% accuracy
                confidence = 0.85
                reason_parts.append("OB+momentum_agree")
            else:
                # OB alone: 83.3% accuracy
                confidence = 0.83
                reason_parts.append("OB_signal_only")

            return direction, confidence, ", ".join(reason_parts)

        return None, 0.0, f"Below threshold: {', '.join(reason_parts)}"

    def generate_eth_signal(
        self,
        token_up: str,
        token_down: str,
        window_start: int
    ) -> Tuple[Optional[str], float, str]:
        """
        Generate ETH signal based on early momentum.

        Rule: IF early_momentum_direction = UP/DOWN: TRADE that direction
        Expected accuracy: 88.9%

        NOTE: Orderbook alone is UNRELIABLE for ETH (57.8%)

        Returns: (direction, confidence, reason)
        """
        momentum = self.get_momentum("ETH", window_start)

        book_up = self.fetch_orderbook(token_up)
        book_down = self.fetch_orderbook(token_down)

        ob_imbalance = 0.0
        if book_up and book_down:
            up_imbal = self.calculate_orderbook_imbalance(book_up)
            down_imbal = self.calculate_orderbook_imbalance(book_down)
            ob_imbalance = up_imbal - down_imbal

        reason_parts = [
            f"momentum={momentum*100:.3f}%",
            f"OB_imbal={ob_imbalance:.3f}"
        ]

        # Primary signal: momentum (NOT orderbook for ETH!)
        if abs(momentum) >= self.config.eth_momentum_threshold:
            direction = "up" if momentum > 0 else "down"

            # Check if orderbook confirms (higher confidence)
            ob_confirms = (
                (direction == "up" and ob_imbalance > 0.2) or
                (direction == "down" and ob_imbalance < -0.2)
            )

            if ob_confirms:
                # OB + momentum agree: 95.7% accuracy
                confidence = 0.96
                reason_parts.append("momentum+OB_agree")
            else:
                # Momentum alone: 88.9% accuracy
                confidence = 0.89
                reason_parts.append("momentum_signal_only")

            return direction, confidence, ", ".join(reason_parts)

        return None, 0.0, f"Below threshold: {', '.join(reason_parts)}"


# ==============================================================================
# Trade Logger
# ==============================================================================

class TradeLogger:
    """Detailed logging of all trading decisions and outcomes."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.decisions_file = data_dir / "decisions.jsonl"
        self.stats_file = data_dir / "daily_stats.json"

        # Setup logging
        log_file = data_dir / "live_bot.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler()
            ]
        )

    def log_decision(self, decision: TradeDecision):
        """Log a trading decision."""
        with open(self.decisions_file, 'a') as f:
            f.write(json.dumps(asdict(decision)) + "\n")

        # Also log to console/file
        if decision.decision == "trade":
            logging.info(
                f"TRADE: {decision.asset} {decision.direction.upper()} "
                f"conf={decision.confidence:.1%} | {decision.reason}"
            )
        elif decision.decision == "skip":
            logging.debug(f"SKIP: {decision.asset} | {decision.reason}")
        elif decision.decision == "killed":
            logging.critical(f"KILLED: {decision.reason}")

    def log_outcome(self, decision: TradeDecision):
        """Log trade outcome after resolution."""
        logging.info(
            f"OUTCOME: {decision.asset} {decision.resolution.upper()} | "
            f"We bet {decision.direction.upper()} | "
            f"{decision.outcome.upper()} ${decision.profit:+.2f}"
        )

    def save_daily_stats(self, stats: DailyStats):
        """Save daily statistics."""
        # Load existing stats
        all_stats = {}
        if self.stats_file.exists():
            with open(self.stats_file, 'r') as f:
                all_stats = json.load(f)

        all_stats[stats.date] = asdict(stats)

        with open(self.stats_file, 'w') as f:
            json.dump(all_stats, f, indent=2)

    def load_daily_stats(self, date: str) -> Optional[DailyStats]:
        """Load daily statistics."""
        if not self.stats_file.exists():
            return None

        with open(self.stats_file, 'r') as f:
            all_stats = json.load(f)

        if date in all_stats:
            return DailyStats(**all_stats[date])
        return None


# ==============================================================================
# Main Bot
# ==============================================================================

class LiveTradingBot:
    """
    Conservative live trading bot focused on learning.

    Key Safety Features:
    1. Kill switch (keyboard, loss limit, errors)
    2. Conservative limits ($15/trade, $30/day max loss)
    3. Consecutive loss pause (3 losses = 30 min pause)
    4. Detailed logging
    """

    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, config: BotConfig):
        self.config = config
        self.state = BotState.STARTING

        # Components
        self.kill_switch = KillSwitch(config)
        self.signal_gen = SignalGenerator(config)
        self.executor = SafeExecutor(
            dry_run=config.dry_run,
            max_order_size=config.max_position_size,
            max_daily_orders=config.max_trades_per_day
        )

        # Data directory
        data_dir = PROJECT_ROOT / "data" / "live_trading"
        self.logger = TradeLogger(data_dir)

        # Daily stats
        today = datetime.now().strftime("%Y-%m-%d")
        self.daily_stats = self.logger.load_daily_stats(today) or DailyStats(date=today)

        # Open trades (waiting for resolution)
        self.open_trades: Dict[str, TradeDecision] = {}

        # Consecutive error tracking
        self.consecutive_errors = 0

    def get_market_info(self, asset: str) -> Optional[dict]:
        """Get current 15-min market info."""
        now = int(time.time())
        current_slot = now - (now % 900) + 900  # Next 15-min boundary
        window_start = current_slot - 900
        slug = f"{asset.lower()}-updown-15m-{window_start}"

        try:
            response = requests.get(
                f"{self.GAMMA_API}/markets/slug/{slug}",
                timeout=10
            )
            if response.ok:
                data = response.json()
                clob_ids = data.get("clobTokenIds", [])
                outcomes = data.get("outcomes", [])

                if isinstance(clob_ids, str):
                    clob_ids = json.loads(clob_ids)
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)

                token_up = token_down = None
                for i, outcome in enumerate(outcomes):
                    if outcome.lower() == "up" and i < len(clob_ids):
                        token_up = clob_ids[i]
                    elif outcome.lower() == "down" and i < len(clob_ids):
                        token_down = clob_ids[i]

                return {
                    "slug": slug,
                    "window_start": window_start,
                    "window_end": current_slot,
                    "token_up": token_up,
                    "token_down": token_down,
                    "asset": asset,
                }
        except Exception as e:
            logging.warning(f"Failed to get market info: {e}")
        return None

    def get_entry_price(self, token_id: str) -> Optional[float]:
        """Get best ask price for entry."""
        book = self.signal_gen.fetch_orderbook(token_id)
        if book:
            asks = book.get("asks", [])
            if asks:
                return float(asks[0]["price"])
        return None

    def check_risk_controls(self) -> Tuple[bool, str]:
        """
        Check all risk controls before trading.

        Returns: (can_trade, reason)
        """
        # Kill switch
        if self.kill_switch.is_killed():
            return False, f"Kill switch: {self.kill_switch.reason}"

        # Daily loss limit
        if self.daily_stats.total_pnl <= -self.config.max_daily_loss:
            return False, f"Daily loss limit: ${self.daily_stats.total_pnl:.2f}"

        # Daily trade limit
        if self.daily_stats.trades >= self.config.max_trades_per_day:
            return False, f"Daily trade limit: {self.daily_stats.trades}"

        # Consecutive loss pause
        if self.daily_stats.pause_until:
            if time.time() < self.daily_stats.pause_until:
                remaining = int(self.daily_stats.pause_until - time.time())
                return False, f"Paused for {remaining}s (consecutive losses)"
            else:
                # Pause expired
                self.daily_stats.pause_until = None
                self.daily_stats.consecutive_losses = 0

        return True, "OK"

    def should_trade(self, market: dict) -> Tuple[bool, str]:
        """Check if we should trade this market window."""
        now = time.time()
        time_to_close = market["window_end"] - now

        # Check timing window
        if time_to_close < self.config.min_time_before_close_sec:
            return False, f"Too close to close: {time_to_close:.0f}s"

        if time_to_close > self.config.max_time_before_close_sec:
            return False, f"Too early: {time_to_close:.0f}s before close"

        # Check if already traded this market
        if market["slug"] in self.open_trades:
            return False, "Already traded this market"

        return True, "OK"

    def execute_trade(
        self,
        market: dict,
        direction: str,
        confidence: float,
        reason: str
    ) -> TradeDecision:
        """Execute a trade with full logging."""
        asset = market["asset"]
        token_id = market["token_up"] if direction == "up" else market["token_down"]

        # Get entry price
        entry_price = self.get_entry_price(token_id)
        if not entry_price:
            decision = TradeDecision(
                timestamp=datetime.now().isoformat(),
                asset=asset,
                market_slug=market["slug"],
                decision="skip",
                direction=direction,
                confidence=confidence,
                reason=f"Failed to get entry price: {reason}",
                time_to_close_sec=int(market["window_end"] - time.time()),
            )
            self.logger.log_decision(decision)
            return decision

        # Calculate position size (shares)
        position_size = min(
            self.config.max_position_size / entry_price,
            self.config.max_position_size  # Shares capped at max
        )

        # Execute order
        result = self.executor.place_order(
            token_id=token_id,
            side="buy",
            size=position_size,
            price=entry_price,
            order_type=OrderType.FOK
        )

        # Record decision
        momentum = self.signal_gen.get_momentum(asset, market["window_start"])
        binance_price = self.signal_gen.binance_prices.get(asset, 0)
        window_start_price = self.signal_gen.window_start_prices.get(
            f"{asset}_{market['window_start']}", 0
        )

        decision = TradeDecision(
            timestamp=datetime.now().isoformat(),
            asset=asset,
            market_slug=market["slug"],
            decision="trade" if result.success else "skip",
            direction=direction,
            confidence=confidence,
            reason=reason if result.success else f"Order failed: {result.message}",
            binance_price=binance_price,
            window_start_price=window_start_price,
            orderbook_imbalance=0.0,  # Could add this
            momentum=momentum,
            time_to_close_sec=int(market["window_end"] - time.time()),
            order_id=result.order_id,
            position_size=position_size,
            entry_price=entry_price,
        )

        self.logger.log_decision(decision)

        if result.success:
            self.open_trades[market["slug"]] = decision
            self.daily_stats.trades += 1
            self.consecutive_errors = 0
        else:
            self.consecutive_errors += 1
            self.kill_switch.check_error_limit(self.consecutive_errors)

        return decision

    def check_resolutions(self):
        """Check if any open trades have resolved."""
        now = time.time()

        for slug, trade in list(self.open_trades.items()):
            # Parse window end from slug
            try:
                parts = slug.split("-")
                window_start = int(parts[-1])
                window_end = window_start + 900
            except:
                continue

            # Wait for resolution
            if now < window_end + 30:
                continue

            # Determine outcome from Binance
            asset = trade.asset
            start_price = self.signal_gen.window_start_prices.get(
                f"{asset}_{window_start}"
            )
            end_price = self.signal_gen.binance_prices.get(asset)

            if not start_price or not end_price:
                continue

            resolution = "up" if end_price > start_price else "down"
            trade.resolution = resolution

            # Calculate P&L
            if trade.direction == resolution:
                # Win: payout is 1.0 per token, we bought at entry_price
                profit = trade.position_size * (1.0 - trade.entry_price)
                trade.outcome = "win"
                trade.profit = profit
                self.daily_stats.wins += 1
                self.daily_stats.consecutive_losses = 0
            else:
                # Loss: we lose our stake
                loss = trade.position_size * trade.entry_price
                trade.outcome = "loss"
                trade.profit = -loss
                self.daily_stats.losses += 1
                self.daily_stats.consecutive_losses += 1

                # Check consecutive loss pause
                if self.daily_stats.consecutive_losses >= self.config.consecutive_loss_pause_count:
                    pause_duration = self.config.consecutive_loss_pause_minutes * 60
                    self.daily_stats.pause_until = time.time() + pause_duration
                    logging.warning(
                        f"PAUSING: {self.daily_stats.consecutive_losses} consecutive losses. "
                        f"Resuming in {self.config.consecutive_loss_pause_minutes} minutes."
                    )

            self.daily_stats.total_pnl += trade.profit
            self.logger.log_outcome(trade)

            # Check loss limit
            self.kill_switch.check_loss_limit(self.daily_stats.total_pnl)

            # Remove from open trades
            del self.open_trades[slug]

        # Save stats
        self.logger.save_daily_stats(self.daily_stats)

    def process_market(self, asset: str):
        """Process a single asset market."""
        # Update prices
        self.signal_gen.update_prices()

        # Get market info
        market = self.get_market_info(asset)
        if not market:
            return

        # Record window start price
        self.signal_gen.record_window_start(asset, market["window_start"])

        # Check if we should trade
        can_trade, reason = self.should_trade(market)
        if not can_trade:
            return  # Silent skip

        # Check risk controls
        can_trade, reason = self.check_risk_controls()
        if not can_trade:
            logging.debug(f"Risk control: {reason}")
            return

        # Generate signal based on asset
        if asset == "BTC":
            direction, confidence, reason = self.signal_gen.generate_btc_signal(
                market["token_up"],
                market["token_down"],
                market["window_start"]
            )
        else:  # ETH
            direction, confidence, reason = self.signal_gen.generate_eth_signal(
                market["token_up"],
                market["token_down"],
                market["window_start"]
            )

        # Check if signal is strong enough
        if not direction or confidence < self.config.min_confidence:
            decision = TradeDecision(
                timestamp=datetime.now().isoformat(),
                asset=asset,
                market_slug=market["slug"],
                decision="skip",
                confidence=confidence,
                reason=reason,
                time_to_close_sec=int(market["window_end"] - time.time()),
            )
            self.logger.log_decision(decision)
            return

        # Execute trade
        self.execute_trade(market, direction, confidence, reason)

    def print_status(self):
        """Print current bot status."""
        mode = "PAPER" if self.config.dry_run else "LIVE"

        print(f"\n{'='*60}")
        print(f"LIVE TRADING BOT - {mode} MODE")
        print(f"{'='*60}")
        print(f"State: {self.state.value}")
        print(f"Kill Switch: {'TRIGGERED' if self.kill_switch.is_killed() else 'OK'}")

        print(f"\n--- Today's Stats ({self.daily_stats.date}) ---")
        print(f"Trades: {self.daily_stats.trades}/{self.config.max_trades_per_day}")
        print(f"Wins: {self.daily_stats.wins}, Losses: {self.daily_stats.losses}")
        print(f"Win Rate: {self.daily_stats.win_rate:.1%}")
        print(f"P&L: ${self.daily_stats.total_pnl:+.2f}")
        print(f"Consecutive Losses: {self.daily_stats.consecutive_losses}")

        if self.daily_stats.pause_until:
            remaining = max(0, self.daily_stats.pause_until - time.time())
            print(f"PAUSED: {remaining:.0f}s remaining")

        print(f"\n--- Open Trades: {len(self.open_trades)} ---")
        for slug, trade in self.open_trades.items():
            print(f"  {trade.asset} {trade.direction.upper()} @ ${trade.entry_price:.3f}")

        print(f"\n--- Prices ---")
        for asset in ["BTC", "ETH"]:
            price = self.signal_gen.binance_prices.get(asset, 0)
            print(f"  {asset}: ${price:,.2f}")

    def run(self, duration_minutes: int = 60):
        """Run the trading bot."""
        mode = "PAPER" if self.config.dry_run else "LIVE"

        logging.info("=" * 60)
        logging.info(f"STARTING LIVE TRADING BOT - {mode} MODE")
        logging.info("=" * 60)
        logging.info(f"Capital: ${self.config.total_capital}")
        logging.info(f"Max position: ${self.config.max_position_size}")
        logging.info(f"Max daily loss: ${self.config.max_daily_loss}")
        logging.info(f"Duration: {duration_minutes} minutes")
        logging.info("Press Ctrl+C to stop")
        logging.info("")

        self.state = BotState.RUNNING
        end_time = time.time() + (duration_minutes * 60)
        last_status = 0

        try:
            while time.time() < end_time:
                # Check kill switch
                if self.kill_switch.is_killed():
                    self.state = BotState.KILLED
                    break

                # Check if paused
                if self.daily_stats.pause_until and time.time() < self.daily_stats.pause_until:
                    self.state = BotState.PAUSED
                else:
                    self.state = BotState.RUNNING

                # Process markets
                if self.state == BotState.RUNNING:
                    for asset in ["BTC", "ETH"]:
                        try:
                            self.process_market(asset)
                        except Exception as e:
                            logging.error(f"Error processing {asset}: {e}")
                            self.consecutive_errors += 1
                            self.kill_switch.check_error_limit(self.consecutive_errors)

                # Check resolutions
                self.check_resolutions()

                # Print status every 60 seconds
                now = time.time()
                if now - last_status > 60:
                    self.print_status()
                    last_status = now

                time.sleep(self.config.poll_interval_sec)

        except KeyboardInterrupt:
            self.kill_switch.trigger("Keyboard interrupt")
            self.state = BotState.KILLED

        # Final status
        self.state = BotState.STOPPED
        logging.info("")
        logging.info("=" * 60)
        logging.info("BOT STOPPED")
        logging.info("=" * 60)
        self.print_status()

        # Save final stats
        self.logger.save_daily_stats(self.daily_stats)


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main():
    """Run the live trading bot."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Conservative Live Trading Bot (Learning-First)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable LIVE trading (default: paper trading)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in minutes (default: 60)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to config JSON file"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and exit"
    )

    args = parser.parse_args()

    # Load or create config
    if args.config and Path(args.config).exists():
        config = BotConfig.from_json(args.config)
    else:
        config = BotConfig()

    # Override dry_run if --live
    if args.live:
        config.dry_run = False
        print("\n" + "!" * 60)
        print("!!! LIVE TRADING MODE - REAL MONEY AT RISK !!!")
        print("!" * 60)
        print(f"\nCapital: ${config.total_capital}")
        print(f"Max position: ${config.max_position_size}")
        print(f"Max daily loss: ${config.max_daily_loss}")
        confirm = input("\nType 'YES' to confirm: ").strip()
        if confirm != "YES":
            print("Aborted.")
            return

    bot = LiveTradingBot(config)

    if args.status:
        bot.print_status()
        return

    bot.run(duration_minutes=args.duration)


if __name__ == "__main__":
    main()
