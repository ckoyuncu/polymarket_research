"""
Arbitrage Bot

Main orchestrator that coordinates all components to execute
the arbitrage strategy.
"""
import time
import json
from typing import Optional, Dict, List
from datetime import datetime
from pathlib import Path

from .market_calendar import MarketCalendar, WindowEvent, WindowPhase
from .market_scanner import MarketScanner, ArbitrageMarket
from .decision_engine import DecisionEngine, TradeSignal, MarketState, TradeAction
from ..feeds.binance_feed import BinanceFeed, PriceTick
from ..config import DATA_DIR


class ArbitrageBot:
    """
    High-frequency arbitrage bot for Polymarket.

    Exploits price lag between Binance spot prices and Polymarket
    15-minute resolution markets.

    Features:
    - Real-time Binance price feed
    - Market scanning and filtering
    - Automated decision making
    - Position tracking
    - P&L reporting
    - Paper trading mode

    Example:
        bot = ArbitrageBot(
            data_api=data_api,
            executor=executor,
            dry_run=True
        )

        bot.start()

        # Bot runs until stopped
        time.sleep(3600)  # Run for 1 hour

        bot.stop()
        print(bot.get_stats())
    """

    def __init__(
        self,
        data_api,
        executor=None,
        dry_run: bool = True,
        min_edge: float = 0.003,  # 0.3% (lowered based on Account88888 analysis)
        max_position_size: float = 100.0,  # 40% of $250 (increased for better opportunity capture)
        max_daily_trades: int = 200,  # Account88888 does 200/day
        min_liquidity: float = 500.0,
        starting_capital: float = 250.0,
        enable_compounding: bool = True,
        max_risk_per_trade_pct: float = 0.04,  # 4% of bankroll (Account88888 pattern)
        kelly_fraction: float = 0.25,  # Quarter Kelly for safety
        # Circuit breakers - BASED ON COMPLETE 2269 TRADE ANALYSIS
        # Simulated 23% win rate: avg max streak 25.8, 95th pct 36, 99th pct 42
        max_daily_loss: float = 125.0,  # $125 = 50% (let variance play out fully)
        max_consecutive_losses: int = 25,  # Average max streak at 23% WR is 25.8
        min_bankroll: float = 50.0,  # $50 = 20% (real stop point)
        cooldown_after_loss: int = 0,  # No cooldown - trade through losses like Account88888
    ):
        """
        Initialize arbitrage bot.

        Args:
            data_api: DataAPIClient instance
            executor: Trading executor (SafeExecutor or None for paper trading)
            dry_run: If True, don't actually trade
            min_edge: Minimum edge to trade (0.005 = 0.5%)
            max_position_size: Max position size in USD
            max_daily_trades: Max trades per day
            min_liquidity: Min market liquidity in USD
            starting_capital: Starting bankroll in USD (default $250)
            enable_compounding: If True, position sizes scale with bankroll
            max_risk_per_trade_pct: Max % of bankroll to risk per trade
            kelly_fraction: Fraction of Kelly criterion to use (0.25 = quarter Kelly)
            max_daily_loss: Stop trading if daily loss exceeds this
            max_consecutive_losses: Stop trading after N consecutive losses
            min_bankroll: Stop trading if bankroll drops below this
            cooldown_after_loss: Skip N windows after a loss
        """
        # Configuration
        self.dry_run = dry_run
        self.max_daily_trades = max_daily_trades

        # Circuit breaker configuration
        self.max_daily_loss = max_daily_loss
        self.max_consecutive_losses = max_consecutive_losses
        self.min_bankroll = min_bankroll
        self.cooldown_after_loss = cooldown_after_loss

        # Circuit breaker tracking
        self.consecutive_losses = 0
        self.daily_loss = 0.0
        self.cooldown_windows_remaining = 0
        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""

        # Compounding configuration
        self.starting_capital = starting_capital
        self.current_bankroll = starting_capital
        self.enable_compounding = enable_compounding
        self.max_risk_per_trade_pct = max_risk_per_trade_pct
        self.kelly_fraction = kelly_fraction
        self.base_max_position = max_position_size

        # Components
        self.binance = BinanceFeed()
        self.calendar = MarketCalendar()
        self.scanner = MarketScanner(data_api)
        self.scanner.min_liquidity = min_liquidity
        self.decision = DecisionEngine(
            min_edge=min_edge,
            max_position_size=self._calculate_max_position(),
            min_position_size=max(5.0, starting_capital * 0.02),  # Min 2% or $5
        )
        self.executor = executor

        # State
        self._running = False
        self._current_phase = WindowPhase.IDLE
        self._last_state_save = 0

        # Tracking
        self.trades_today = 0
        self.positions: List[Dict] = []
        self.trade_history: List[Dict] = []

        # Stats
        self.stats = {
            "start_time": None,
            "starting_capital": starting_capital,
            "current_bankroll": starting_capital,
            "peak_bankroll": starting_capital,
            "trades_executed": 0,
            "trades_won": 0,
            "trades_lost": 0,
            "total_pnl": 0.0,
            "signals_generated": 0,
            "signals_traded": 0,
            "windows_watched": 0,
        }

        # Data directory
        self.data_dir = DATA_DIR / "arbitrage"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Subscribe to events
        self.calendar.subscribe(self._on_window_event)
        self.binance.subscribe(self._on_price_update)

        print(f"🤖 Arbitrage bot initialized")
        print(f"   Mode: {'DRY RUN' if dry_run else 'LIVE TRADING'}")
        print(f"   Starting capital: ${starting_capital:.2f}")
        print(f"   Compounding: {'ENABLED' if enable_compounding else 'DISABLED'}")
        print(f"   Min edge: {min_edge:.2%}")
        print(f"   Max position: ${self._calculate_max_position():.2f}")
        print(f"   Max risk/trade: {max_risk_per_trade_pct:.1%}")
        print(f"   Max daily trades: {max_daily_trades}")
        print(f"\n🛡️  Circuit Breakers:")
        print(f"   Max daily loss: ${max_daily_loss:.2f}")
        print(f"   Max consecutive losses: {max_consecutive_losses}")
        print(f"   Min bankroll (stop): ${min_bankroll:.2f}")
        print(f"   Cooldown after loss: {cooldown_after_loss} window(s)")

    def _calculate_max_position(self) -> float:
        """
        Calculate max position size based on current bankroll.

        Uses Account88888's sizing pattern:
        - Risk max 2% of bankroll per trade
        - Scale position with Kelly criterion
        - Cap at base_max_position for safety
        """
        if not self.enable_compounding:
            return self.base_max_position

        # Max risk = 2% of bankroll
        max_risk = self.current_bankroll * self.max_risk_per_trade_pct

        # Apply Kelly fraction for safety
        kelly_position = max_risk / self.kelly_fraction if self.kelly_fraction > 0 else max_risk

        # Cap at base max or 10% of bankroll
        max_allowed = min(self.base_max_position, self.current_bankroll * 0.10)

        return min(kelly_position, max_allowed)

    def _update_bankroll(self, pnl: float):
        """
        Update bankroll after a trade resolves.

        Args:
            pnl: Profit/loss from the trade
        """
        self.current_bankroll += pnl
        self.stats["current_bankroll"] = self.current_bankroll
        self.stats["total_pnl"] = self.current_bankroll - self.starting_capital

        # Track peak for drawdown calculation
        if self.current_bankroll > self.stats["peak_bankroll"]:
            self.stats["peak_bankroll"] = self.current_bankroll

        # Update decision engine with new position sizing
        if self.enable_compounding:
            self.decision.max_position_size = self._calculate_max_position()
            self.decision.min_position_size = max(5.0, self.current_bankroll * 0.02)

        # Log bankroll update
        roi = (self.current_bankroll / self.starting_capital - 1) * 100
        print(f"   💰 Bankroll: ${self.current_bankroll:.2f} ({roi:+.1f}% ROI)")

    def get_drawdown(self) -> float:
        """Calculate current drawdown from peak."""
        if self.stats["peak_bankroll"] <= 0:
            return 0.0
        return (self.stats["peak_bankroll"] - self.current_bankroll) / self.stats["peak_bankroll"]

    def _check_circuit_breakers(self) -> tuple[bool, str]:
        """
        Check if any circuit breakers are triggered.

        Returns:
            (can_trade, reason): Tuple of whether trading is allowed and reason if not
        """
        # Check if already triggered
        if self.circuit_breaker_triggered:
            return False, self.circuit_breaker_reason

        # Check cooldown
        if self.cooldown_windows_remaining > 0:
            return False, f"Cooldown active ({self.cooldown_windows_remaining} windows remaining)"

        # Check min bankroll
        if self.current_bankroll < self.min_bankroll:
            self.circuit_breaker_triggered = True
            self.circuit_breaker_reason = f"Bankroll ${self.current_bankroll:.2f} below minimum ${self.min_bankroll:.2f}"
            return False, self.circuit_breaker_reason

        # Check daily loss
        if self.daily_loss >= self.max_daily_loss:
            self.circuit_breaker_triggered = True
            self.circuit_breaker_reason = f"Daily loss ${self.daily_loss:.2f} exceeds max ${self.max_daily_loss:.2f}"
            return False, self.circuit_breaker_reason

        # Check consecutive losses
        if self.consecutive_losses >= self.max_consecutive_losses:
            self.circuit_breaker_triggered = True
            self.circuit_breaker_reason = f"{self.consecutive_losses} consecutive losses (max: {self.max_consecutive_losses})"
            return False, self.circuit_breaker_reason

        return True, ""

    def _record_trade_result(self, pnl: float, won: bool):
        """
        Record the result of a trade for circuit breaker tracking.

        Args:
            pnl: Profit/loss from the trade
            won: Whether the trade was a winner
        """
        # Update bankroll
        self._update_bankroll(pnl)

        # Update stats
        if won:
            self.stats["trades_won"] += 1
            self.consecutive_losses = 0
            print(f"   ✅ WIN: +${pnl:.2f}")
        else:
            self.stats["trades_lost"] += 1
            self.consecutive_losses += 1
            self.daily_loss += abs(pnl)
            self.cooldown_windows_remaining = self.cooldown_after_loss
            print(f"   ❌ LOSS: -${abs(pnl):.2f}")
            print(f"   📊 Consecutive losses: {self.consecutive_losses}/{self.max_consecutive_losses}")
            print(f"   📊 Daily loss: ${self.daily_loss:.2f}/${self.max_daily_loss:.2f}")

            # Check if we should pause
            if self.cooldown_after_loss > 0:
                print(f"   ⏸️  Entering cooldown for {self.cooldown_after_loss} window(s)")

        # Check circuit breakers after recording
        can_trade, reason = self._check_circuit_breakers()
        if not can_trade:
            print(f"\n🛑 CIRCUIT BREAKER TRIGGERED: {reason}")
            print(f"   Bot will stop trading until manually reset")

    def _decrement_cooldown(self):
        """Called at the end of each window to decrement cooldown counter."""
        if self.cooldown_windows_remaining > 0:
            self.cooldown_windows_remaining -= 1
            if self.cooldown_windows_remaining == 0:
                print(f"   ▶️  Cooldown ended, resuming trading")

    def reset_circuit_breakers(self):
        """
        Manually reset circuit breakers.

        Call this to resume trading after a circuit breaker was triggered.
        """
        self.circuit_breaker_triggered = False
        self.circuit_breaker_reason = ""
        self.consecutive_losses = 0
        self.cooldown_windows_remaining = 0
        print("🔄 Circuit breakers reset - trading resumed")

    def reset_daily_stats(self):
        """Reset daily statistics. Call at start of each trading day."""
        self.daily_loss = 0.0
        self.trades_today = 0
        print("📅 Daily stats reset")

    def start(self):
        """Start the bot."""
        if self._running:
            print("Bot already running")
            return

        self._running = True
        self.stats["start_time"] = time.time()
        self._last_state_save = time.time()

        # Start Binance feed
        self.binance.start()

        # Wait for prices
        print("Waiting for Binance prices...")
        time.sleep(3)

        if not self.binance.is_healthy():
            print("⚠️  Binance feed not healthy")
            return

        print(f"✅ Bot started at {datetime.now().strftime('%H:%M:%S UTC')}")

        # Save initial state
        self._save_state()

        # Main loop
        try:
            while self._running:
                self._main_loop()
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n🛑 Stopping bot...")
            self.stop()

    def stop(self):
        """Stop the bot."""
        self._running = False
        self.binance.stop()
        self._save_state()
        print("✅ Bot stopped")

    def _main_loop(self):
        """Main bot loop (called every second)."""
        # Update calendar
        self.calendar.update()

        # Periodic state save (every 30 seconds)
        if time.time() - self._last_state_save >= 30:
            self._save_state()
            self._last_state_save = time.time()

        # Get current phase
        event = self.calendar.get_current_event()
        phase = event.phase

        # Phase-specific actions
        if phase == WindowPhase.WATCHING:
            # 60-30s before window
            # Scan for markets
            if self._current_phase != phase:
                self._on_watching_phase(event)

        elif phase == WindowPhase.READY:
            # 30-10s before window
            # Calculate positions
            if self._current_phase != phase:
                self._on_ready_phase(event)

        elif phase == WindowPhase.EXECUTING:
            # 10-2s before window
            # Execute trades
            self._on_executing_phase(event)

        elif phase == WindowPhase.CLOSED:
            # Window just closed
            if self._current_phase != phase:
                self._on_closed_phase(event)

        self._current_phase = phase

    def _on_window_event(self, event: WindowEvent):
        """Handle window phase changes."""
        print(f"\n⏰ Window event: {event.phase.value}")
        print(f"   Next window: {event.window_time.strftime('%H:%M:%S')}")
        print(f"   Time until: {event.seconds_until:.0f}s")

    def _on_price_update(self, tick: PriceTick):
        """Handle price updates from Binance."""
        # Only log occasionally to avoid spam
        if self._current_phase == WindowPhase.EXECUTING:
            symbol = tick.symbol.replace("USDT", "")
            print(f"   💹 {symbol}: ${tick.price:,.2f}")

    def _on_watching_phase(self, event: WindowEvent):
        """Handle WATCHING phase (60-30s before)."""
        print(f"👀 Watching phase - scanning markets...")

        # Scan for markets
        markets = self.scanner.find_markets_for_next_window(event.window_time)

        print(f"   Found {len(markets)} markets for this window")

        self.stats["windows_watched"] += 1

    def _on_ready_phase(self, event: WindowEvent):
        """Handle READY phase (30-10s before)."""
        print(f"🎯 Ready phase - analyzing positions...")

        # Get markets for this window
        markets = self.scanner.find_markets_for_next_window(event.window_time)

        for market in markets:
            self._analyze_market(market)

    def _on_executing_phase(self, event: WindowEvent):
        """Handle EXECUTING phase (10-2s before)."""
        # Get markets for this window
        markets = self.scanner.find_markets_for_next_window(event.window_time)

        for market in markets:
            signal = self._analyze_market(market)

            if signal and signal.should_trade:
                self._execute_signal(signal, market)

    def _on_closed_phase(self, event: WindowEvent):
        """Handle CLOSED phase (window just closed)."""
        print(f"✅ Window closed - waiting for next...")

        # Decrement cooldown counter
        self._decrement_cooldown()

    def _analyze_market(self, market: ArbitrageMarket) -> Optional[TradeSignal]:
        """
        Analyze a market and generate signal.

        Args:
            market: Market to analyze

        Returns:
            TradeSignal or None
        """
        # Get current price from Binance
        current_price = self.binance.get_price(market.asset)

        if not current_price:
            return None

        # Check if this is an "Up or Down" style market
        question_lower = market.question.lower()
        is_up_or_down = "up or down" in question_lower or "up/down" in question_lower

        # Build market state
        state = MarketState(
            asset=market.asset,
            strike_price=market.strike_price,
            current_price=current_price,
            is_above_strike_question=market.is_above_strike,
            yes_token_id=market.yes_token_id,
            no_token_id=market.no_token_id,
            yes_price=market.yes_price,
            no_price=market.no_price,
            seconds_until_close=market.seconds_until_resolution,
            liquidity=market.liquidity,
            is_up_or_down_market=is_up_or_down,
            previous_price=market.strike_price  # For up/down, strike_price represents reference
        )

        # Generate signal
        signal = self.decision.analyze(state)

        self.stats["signals_generated"] += 1

        if signal.should_trade:
            print(f"\n🔔 SIGNAL: {signal.action.value}")
            print(f"   Market: {market.question[:60]}...")
            print(f"   Price: {market.asset} ${current_price:,.2f} vs ${market.strike_price:,.0f}")
            print(f"   Edge: {signal.edge:.2%}")
            print(f"   Confidence: {signal.confidence:.2%}")
            print(f"   R:R Ratio: {signal.reward_risk_ratio:.1f}:1")
            print(f"   Size: {signal.size:.1f} @ ${signal.max_price:.3f}")
            print(f"   Expected: +${signal.expected_payout:.2f} / -${signal.risk_amount:.2f}")
        else:
            # Log rejected signals for debugging
            print(f"   ⏭️  SKIP: {market.asset} ${current_price:,.0f} vs ${market.strike_price:,.0f} | {signal.reason}")

        return signal

    def _execute_signal(self, signal: TradeSignal, market: ArbitrageMarket):
        """
        Execute a trade signal.

        Args:
            signal: Trade signal
            market: Market to trade
        """
        # Check circuit breakers first
        can_trade, reason = self._check_circuit_breakers()
        if not can_trade:
            print(f"   🛑 BLOCKED by circuit breaker: {reason}")
            return

        # Check daily limit
        if self.trades_today >= self.max_daily_trades:
            print("   ⚠️  Daily trade limit reached")
            return

        self.stats["signals_traded"] += 1

        # Determine side
        side = "buy" if signal.action in [TradeAction.BUY_YES, TradeAction.BUY_NO] else "sell"

        # Execute
        if self.dry_run or not self.executor:
            # Paper trading
            print(f"   📝 PAPER TRADE: {side.upper()} {signal.size:.0f} @ ${signal.max_price:.3f}")

            # Record trade
            trade = {
                "timestamp": time.time(),
                "market_id": market.condition_id,
                "action": signal.action.value,
                "size": signal.size,
                "price": signal.max_price,
                "edge": signal.edge,
                "confidence": signal.confidence,
                "paper_trade": True
            }

            self.trade_history.append(trade)
            self.trades_today += 1
            self.stats["trades_executed"] += 1

        else:
            # Live trading
            print(f"   💰 LIVE TRADE: {side.upper()} {signal.size:.0f} @ ${signal.max_price:.3f}")

            result = self.executor.place_order(
                token_id=signal.token_id,
                side=side,
                size=signal.size,
                price=signal.max_price,
                skip_confirmation=True
            )

            if result.success:
                print(f"   ✅ Order placed: {result.order_id}")

                # Record trade
                trade = {
                    "timestamp": time.time(),
                    "market_id": market.condition_id,
                    "action": signal.action.value,
                    "size": signal.size,
                    "price": result.filled_price,
                    "edge": signal.edge,
                    "confidence": signal.confidence,
                    "order_id": result.order_id,
                    "paper_trade": False
                }

                self.trade_history.append(trade)
                self.trades_today += 1
                self.stats["trades_executed"] += 1

            else:
                print(f"   ❌ Order failed: {result.message}")

        self._save_state()

    def _save_state(self):
        """Save bot state to disk."""
        filepath = self.data_dir / "bot_state.json"

        # Include dry_run in stats for status API
        stats_with_mode = self.stats.copy()
        stats_with_mode["dry_run"] = self.dry_run

        state = {
            "stats": stats_with_mode,
            "trades_today": self.trades_today,
            "trade_history": self.trade_history[-100:],  # Last 100 trades
            # Circuit breaker state
            "circuit_breaker": {
                "triggered": self.circuit_breaker_triggered,
                "reason": self.circuit_breaker_reason,
                "consecutive_losses": self.consecutive_losses,
                "daily_loss": self.daily_loss,
                "cooldown_remaining": self.cooldown_windows_remaining,
            },
            "bankroll": {
                "starting": self.starting_capital,
                "current": self.current_bankroll,
                "peak": self.stats.get("peak_bankroll", self.starting_capital),
                "drawdown": self.get_drawdown(),
            }
        }

        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)

    def get_stats(self) -> Dict:
        """Get bot statistics."""
        stats = self.stats.copy()

        # Calculate win rate
        total_completed = stats["trades_won"] + stats["trades_lost"]
        if total_completed > 0:
            stats["win_rate"] = stats["trades_won"] / total_completed
        else:
            stats["win_rate"] = 0.0

        # Calculate uptime
        if stats["start_time"]:
            stats["uptime_seconds"] = time.time() - stats["start_time"]
        else:
            stats["uptime_seconds"] = 0

        # Add current state
        stats["running"] = self._running
        stats["trades_today"] = self.trades_today
        stats["binance_healthy"] = self.binance.is_healthy()

        return stats

    def print_status(self):
        """Print current bot status."""
        stats = self.get_stats()

        print("\n" + "="*60)
        print("ARBITRAGE BOT STATUS")
        print("="*60)

        print(f"\nRunning: {stats['running']}")
        print(f"Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"Uptime: {stats['uptime_seconds']:.0f}s")

        print(f"\n--- Trading Stats ---")
        print(f"Trades today: {stats['trades_today']}/{self.max_daily_trades}")
        print(f"Total trades: {stats['trades_executed']}")
        print(f"Win rate: {stats['win_rate']:.1%}")
        print(f"Total P&L: ${stats['total_pnl']:.2f}")

        print(f"\n--- Signals ---")
        print(f"Signals generated: {stats['signals_generated']}")
        print(f"Signals traded: {stats['signals_traded']}")
        if stats['signals_generated'] > 0:
            hit_rate = stats['signals_traded'] / stats['signals_generated']
            print(f"Hit rate: {hit_rate:.1%}")

        print(f"\n--- Bankroll ---")
        print(f"Starting: ${self.starting_capital:.2f}")
        print(f"Current: ${self.current_bankroll:.2f}")
        roi = (self.current_bankroll / self.starting_capital - 1) * 100
        print(f"ROI: {roi:+.1f}%")
        print(f"Drawdown: {self.get_drawdown():.1%}")

        print(f"\n--- Circuit Breakers ---")
        if self.circuit_breaker_triggered:
            print(f"🛑 TRIGGERED: {self.circuit_breaker_reason}")
        else:
            print(f"Status: ✅ Active")
        print(f"Consecutive losses: {self.consecutive_losses}/{self.max_consecutive_losses}")
        print(f"Daily loss: ${self.daily_loss:.2f}/${self.max_daily_loss:.2f}")
        if self.cooldown_windows_remaining > 0:
            print(f"Cooldown: {self.cooldown_windows_remaining} window(s) remaining")

        print(f"\n--- System ---")
        print(f"Binance feed: {'✅ Healthy' if stats['binance_healthy'] else '❌ Unhealthy'}")
        print(f"Windows watched: {stats['windows_watched']}")

        binance_stats = self.binance.get_stats()
        print(f"Price updates: {binance_stats['updates_received']}")

        print("="*60 + "\n")


def test_bot():
    """Test the arbitrage bot."""
    print("Testing Arbitrage Bot...\n")

    # Create mock executor
    from ..trading.executor import SafeExecutor

    bot = ArbitrageBot(
        data_api=None,  # Would be real API in production
        executor=None,  # Paper trading
        dry_run=True,
        min_edge=0.005,
        max_position_size=50
    )

    # Run for a short time
    print("Starting bot (will run for 30 seconds)...")
    print("Press Ctrl+C to stop early\n")

    import threading

    def run_bot():
        bot.start()

    thread = threading.Thread(target=run_bot, daemon=True)
    thread.start()

    time.sleep(30)

    bot.stop()

    # Print stats
    bot.print_status()

    print("\n✅ Test complete")


if __name__ == "__main__":
    test_bot()
