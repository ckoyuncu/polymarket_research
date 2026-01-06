"""
Main Bot Runner for Delta-Neutral Maker Rebates Strategy.

This module integrates all maker bot components into a single cohesive trading bot
that can run in paper mode (default) or live mode with proper risk controls.

Key Features:
- Paper mode by default (NEVER trades live unless --live flag)
- Kill switch check every cycle
- Position limits enforced
- Delta tracking integration
- Clean shutdown on Ctrl+C

Example:
    >>> bot = MakerBot(paper_mode=True)
    >>> await bot.run()

Components:
    - MarketFinder: Discovers 15-minute crypto markets
    - DeltaTracker: Tracks delta-neutral positions
    - RiskMonitor: Enforces risk limits and kill switch
    - MakerPaperSimulator: Paper trading simulation
    - DualOrderExecutor: Live order execution (live mode only)

Safety:
    - Paper mode is the default
    - Kill switch file (.kill_switch) halts all trading
    - Daily loss limit triggers kill switch
    - Position limits prevent over-exposure
"""

import asyncio
import logging
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from .market_finder import MarketFinder, Market15Min
from .delta_tracker import DeltaTracker
from .risk_limits import RiskMonitor
from .paper_simulator import MakerPaperSimulator
from .dual_order import DualOrderExecutor, DualOrderResult

from ..config import (
    PROJECT_ROOT,
    MAKER_POSITION_SIZE,
    MAKER_MAX_CONCURRENT,
    MAKER_MIN_SPREAD,
    MAKER_MIN_PROB,
    MAKER_MAX_PROB,
    MAX_DAILY_LOSS,
    MAX_POSITION_SIZE,
    MAX_DELTA_PCT,
)

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class BotState:
    """
    Current state of the maker bot.

    Attributes:
        is_running: Whether the bot is currently running.
        paper_mode: Whether running in paper mode.
        cycle_count: Number of cycles completed.
        positions_opened: Total positions opened this session.
        positions_closed: Total positions closed this session.
        total_pnl: Total P&L this session.
        total_rebates: Total rebates earned this session.
        last_cycle_time: Timestamp of last cycle.
        last_error: Last error message (if any).
    """

    is_running: bool = False
    paper_mode: bool = True
    cycle_count: int = 0
    positions_opened: int = 0
    positions_closed: int = 0
    total_pnl: Decimal = Decimal("0")
    total_rebates: Decimal = Decimal("0")
    last_cycle_time: Optional[datetime] = None
    last_error: Optional[str] = None
    start_time: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert state to dictionary."""
        return {
            "is_running": self.is_running,
            "paper_mode": self.paper_mode,
            "cycle_count": self.cycle_count,
            "positions_opened": self.positions_opened,
            "positions_closed": self.positions_closed,
            "total_pnl": str(self.total_pnl),
            "total_rebates": str(self.total_rebates),
            "last_cycle_time": self.last_cycle_time.isoformat() if self.last_cycle_time else None,
            "last_error": self.last_error,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime_seconds": (
                int((_utc_now() - self.start_time).total_seconds())
                if self.start_time
                else 0
            ),
        }


class MakerBot:
    """
    Main orchestrator for the Delta-Neutral Maker Rebates Strategy.

    This bot integrates all components:
    - MarketFinder: Finds 15-minute crypto markets
    - DeltaTracker: Tracks positions and delta exposure
    - RiskMonitor: Enforces risk limits
    - PaperSimulator: Simulates trades in paper mode
    - DualOrderExecutor: Executes real trades in live mode

    Trading Flow:
    1. Check kill switch
    2. Find next 15-minute market
    3. Check if we can open position (risk limits)
    4. Place delta-neutral orders (paper or live)
    5. Track position in delta tracker
    6. Wait for resolution
    7. Record P&L

    Attributes:
        paper_mode: If True, uses paper trading (default: True)
        market_finder: Discovers 15-minute markets
        delta_tracker: Tracks delta exposure
        risk_monitor: Enforces risk limits
        paper_simulator: Paper trading simulator
        state: Current bot state

    Example:
        >>> bot = MakerBot(paper_mode=True)
        >>> bot.start()  # Non-blocking
        >>> await asyncio.sleep(3600)  # Run for 1 hour
        >>> bot.stop()
    """

    def __init__(
        self,
        paper_mode: bool = True,
        clob_client=None,
        assets: Optional[list[str]] = None,
        position_size: Optional[float] = None,
        max_concurrent: Optional[int] = None,
        min_spread: Optional[float] = None,
        min_prob: Optional[float] = None,
        max_prob: Optional[float] = None,
        max_daily_loss: Optional[float] = None,
        max_position_size: Optional[float] = None,
        max_delta_pct: Optional[float] = None,
        cycle_interval: int = 60,
    ):
        """
        Initialize the maker bot.

        Args:
            paper_mode: If True, use paper trading (default: True, NEVER live by default)
            clob_client: py-clob-client instance for live trading (required for live mode)
            assets: List of assets to trade (default: ["btc", "eth"])
            position_size: Position size per leg in USD (default from config)
            max_concurrent: Maximum concurrent positions (default from config)
            min_spread: Minimum spread to enter (default from config)
            min_prob: Minimum probability to trade (default from config)
            max_prob: Maximum probability to trade (default from config)
            max_daily_loss: Maximum daily loss limit (default from config)
            max_position_size: Maximum position size (default from config)
            max_delta_pct: Maximum delta percentage (default from config)
            cycle_interval: Seconds between trading cycles (default: 60)
        """
        # SAFETY: Paper mode by default
        self.paper_mode = paper_mode
        self._clob_client = clob_client

        # Validate live mode requirements
        if not paper_mode and clob_client is None:
            raise ValueError(
                "Live trading requires a clob_client. "
                "Pass clob_client=<your_client> or use paper_mode=True"
            )

        # Configuration with defaults from config module
        self.assets = assets or ["btc", "eth"]
        self.position_size = Decimal(str(position_size or MAKER_POSITION_SIZE))
        self.max_concurrent = max_concurrent or MAKER_MAX_CONCURRENT
        self.min_spread = min_spread or MAKER_MIN_SPREAD
        self.min_prob = min_prob or MAKER_MIN_PROB
        self.max_prob = max_prob or MAKER_MAX_PROB
        self.cycle_interval = cycle_interval

        # Risk configuration
        risk_config = {
            "max_daily_loss": max_daily_loss or MAX_DAILY_LOSS,
            "max_position_size": max_position_size or MAX_POSITION_SIZE,
            "max_concurrent": self.max_concurrent,
            "max_total_exposure": (max_position_size or MAX_POSITION_SIZE) * self.max_concurrent,
            "max_delta_pct": max_delta_pct or MAX_DELTA_PCT,
        }

        # Initialize components
        self.market_finder = MarketFinder(assets=self.assets)
        self.delta_tracker = DeltaTracker(max_delta_pct=risk_config["max_delta_pct"])
        self.risk_monitor = RiskMonitor(config=risk_config, project_root=PROJECT_ROOT)

        # Paper simulator (always initialized for paper mode)
        self.paper_simulator = MakerPaperSimulator(
            initial_balance=300.0,
            max_position_size=float(self.position_size * 2),  # Both legs
            max_concurrent_positions=self.max_concurrent,
            max_daily_loss=float(risk_config["max_daily_loss"]),
            log_trades=True,
            log_path="data/maker_bot_trades.jsonl",
        )

        # Dual order executor (for live mode)
        self._dual_executor: Optional[DualOrderExecutor] = None
        if not paper_mode and clob_client:
            self._dual_executor = DualOrderExecutor(
                clob_client=clob_client,
                max_position_size=Decimal(str(risk_config["max_position_size"])),
                max_concurrent_positions=self.max_concurrent,
            )

        # State tracking
        self.state = BotState(paper_mode=paper_mode)
        self._shutdown_event = asyncio.Event()

        # Pending market resolutions (market_id -> position_id)
        self._pending_resolutions: dict[str, str] = {}

        # Setup signal handlers
        self._setup_signal_handlers()

        mode_str = "PAPER" if paper_mode else "LIVE"
        logger.info(
            f"MakerBot initialized in {mode_str} mode: "
            f"assets={self.assets}, position_size=${self.position_size}, "
            f"max_concurrent={self.max_concurrent}"
        )

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for clean shutdown."""
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (ValueError, RuntimeError):
            # Signal handlers can only be set in main thread
            pass

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating shutdown...")
        self.stop()

    async def run_cycle(self) -> dict[str, Any]:
        """
        Run one trading cycle.

        A cycle:
        1. Check kill switch
        2. Find active 15-minute markets
        3. Check if we can open new positions
        4. For each market, check entry criteria
        5. Place delta-neutral orders if criteria met
        6. Check for resolved markets
        7. Update state

        Returns:
            Dictionary with cycle results
        """
        cycle_result = {
            "timestamp": _utc_now().isoformat(),
            "cycle_number": self.state.cycle_count + 1,
            "actions": [],
            "errors": [],
        }

        try:
            # 1. Check kill switch
            if self.risk_monitor.check_kill_switch():
                cycle_result["actions"].append("HALTED: Kill switch active")
                logger.warning("Kill switch is active - skipping cycle")
                # Still update cycle state for halted cycles
                self.state.cycle_count += 1
                self.state.last_cycle_time = _utc_now()
                return cycle_result

            # Check if halted for other reasons
            if self.risk_monitor.is_halted:
                reason = self.risk_monitor.halt_reason or "Unknown"
                cycle_result["actions"].append(f"HALTED: {reason}")
                logger.warning(f"Trading halted: {reason}")
                # Still update cycle state for halted cycles
                self.state.cycle_count += 1
                self.state.last_cycle_time = _utc_now()
                return cycle_result

            # 2. Find active 15-minute markets
            markets = self.market_finder.find_active_markets()
            cycle_result["markets_found"] = len(markets)

            if not markets:
                cycle_result["actions"].append("No active markets found")
                logger.debug("No active 15-minute markets found")
                # Still update cycle state even with no markets
                self.state.cycle_count += 1
                self.state.last_cycle_time = _utc_now()
                self.state.last_error = None
                return cycle_result

            # 3. Check position capacity
            open_positions = len(self.delta_tracker.positions)
            can_open_more = open_positions < self.max_concurrent

            if not can_open_more:
                cycle_result["actions"].append(f"Max positions reached ({self.max_concurrent})")
                logger.debug(f"At max concurrent positions: {open_positions}/{self.max_concurrent}")
            else:
                # 4. Try to open positions on available markets
                for market in markets:
                    # Check if we already have a position in this market
                    if market.condition_id in self.delta_tracker.positions:
                        continue

                    # Check entry criteria
                    entry_check = self._check_entry_criteria(market)
                    if not entry_check["pass"]:
                        cycle_result["actions"].append(
                            f"Skip {market.slug}: {entry_check['reason']}"
                        )
                        continue

                    # Check risk limits
                    can_open, reason = self.risk_monitor.can_open_position(
                        size=float(self.position_size * 2),  # Both legs
                        market_id=market.condition_id,
                    )

                    if not can_open:
                        cycle_result["actions"].append(f"Risk blocked {market.slug}: {reason}")
                        logger.info(f"Risk monitor blocked position: {reason}")
                        continue

                    # 5. Place delta-neutral orders
                    result = await self._place_delta_neutral_position(market)

                    if result["success"]:
                        cycle_result["actions"].append(
                            f"Opened position on {market.slug}: "
                            f"YES@{result['yes_price']}, NO@{result['no_price']}"
                        )
                        self.state.positions_opened += 1
                    else:
                        cycle_result["errors"].append(
                            f"Failed to open {market.slug}: {result.get('error', 'Unknown')}"
                        )

                    # Check if we've hit max positions
                    if len(self.delta_tracker.positions) >= self.max_concurrent:
                        break

            # 6. Check for resolved markets
            resolved_results = await self._check_resolutions()
            for res in resolved_results:
                cycle_result["actions"].append(
                    f"Resolved {res['market_id']}: outcome={res['outcome']}, pnl={res['pnl']}"
                )
                self.state.positions_closed += 1
                self.state.total_pnl += Decimal(str(res.get("pnl", 0)))

            # 7. Update state
            self.state.cycle_count += 1
            self.state.last_cycle_time = _utc_now()
            self.state.last_error = None

            # Log summary
            logger.info(
                f"Cycle {self.state.cycle_count} complete: "
                f"actions={len(cycle_result['actions'])}, "
                f"positions={len(self.delta_tracker.positions)}/{self.max_concurrent}"
            )

        except Exception as e:
            error_msg = f"Cycle error: {str(e)}"
            cycle_result["errors"].append(error_msg)
            self.state.last_error = error_msg
            logger.error(error_msg, exc_info=True)

        return cycle_result

    def _check_entry_criteria(self, market: Market15Min) -> dict[str, Any]:
        """
        Check if market meets entry criteria for delta-neutral position.

        Criteria:
        - Minimum time to resolution (60+ seconds)
        - Spread within acceptable range
        - Probability within range (avoid extremes)

        Args:
            market: Market to check

        Returns:
            Dictionary with 'pass' bool and 'reason' string
        """
        # Check time to resolution
        if market.seconds_to_resolution < 60:
            return {
                "pass": False,
                "reason": f"Too close to resolution: {market.seconds_to_resolution}s",
            }

        # Check spread (want positive spread to capture rebates)
        if market.spread < self.min_spread:
            return {
                "pass": False,
                "reason": f"Spread too tight: {market.spread:.3f} < {self.min_spread}",
            }

        # Check probability range (avoid extreme prices)
        yes_price = market.yes_price
        if yes_price < self.min_prob or yes_price > self.max_prob:
            return {
                "pass": False,
                "reason": f"Price outside range: {yes_price:.2f} not in [{self.min_prob}, {self.max_prob}]",
            }

        return {"pass": True, "reason": "All criteria met"}

    async def _place_delta_neutral_position(
        self, market: Market15Min
    ) -> dict[str, Any]:
        """
        Place a delta-neutral position (YES + NO) on the market.

        In paper mode, uses the paper simulator.
        In live mode, uses the dual order executor.

        Args:
            market: Market to trade

        Returns:
            Dictionary with result details
        """
        size = float(self.position_size)
        yes_price = market.yes_price
        no_price = market.no_price

        try:
            if self.paper_mode:
                # Paper trading
                position = self.paper_simulator.place_delta_neutral(
                    market_id=market.condition_id,
                    size=size,
                    yes_price=yes_price,
                    no_price=no_price,
                )

                # Track in delta tracker
                self.delta_tracker.add_position(
                    market_id=market.condition_id,
                    yes_size=size,
                    no_size=size,
                    prices={"yes": yes_price, "no": no_price},
                )

                # Track pending resolution
                self._pending_resolutions[market.condition_id] = position.position_id

                # Record in risk monitor
                self.risk_monitor.record_position_opened(
                    market_id=market.condition_id,
                    size=float(position.total_cost),
                    delta=float(position.delta),
                )

                # Track rebates
                self.state.total_rebates += position.rebates_earned

                logger.info(
                    f"[PAPER] Opened delta-neutral position: {market.slug} "
                    f"YES@{yes_price:.3f}, NO@{no_price:.3f}, "
                    f"cost=${position.total_cost:.2f}, rebates=${position.rebates_earned:.4f}"
                )

                return {
                    "success": True,
                    "mode": "paper",
                    "market_id": market.condition_id,
                    "yes_price": yes_price,
                    "no_price": no_price,
                    "size": size,
                    "total_cost": float(position.total_cost),
                    "rebates": float(position.rebates_earned),
                }

            else:
                # Live trading
                if self._dual_executor is None:
                    return {"success": False, "error": "No dual executor configured"}

                result: DualOrderResult = await self._dual_executor.place_delta_neutral(
                    market=market.slug,
                    yes_token_id=market.yes_token_id,
                    no_token_id=market.no_token_id,
                    size=size,
                    yes_price=yes_price,
                    no_price=no_price,
                )

                if result.success:
                    # Track in delta tracker
                    self.delta_tracker.add_position(
                        market_id=market.condition_id,
                        yes_size=size,
                        no_size=size,
                        prices={"yes": yes_price, "no": no_price},
                    )

                    # Track pending resolution
                    self._pending_resolutions[market.condition_id] = market.slug

                    # Record in risk monitor
                    self.risk_monitor.record_position_opened(
                        market_id=market.condition_id,
                        size=float(result.total_cost),
                        delta=float(result.delta),
                    )

                    logger.info(
                        f"[LIVE] Opened delta-neutral position: {market.slug} "
                        f"YES@{yes_price:.3f}, NO@{no_price:.3f}, "
                        f"cost=${result.total_cost:.2f}"
                    )

                    return {
                        "success": True,
                        "mode": "live",
                        "market_id": market.condition_id,
                        "yes_price": yes_price,
                        "no_price": no_price,
                        "size": size,
                        "total_cost": float(result.total_cost),
                        "yes_order_id": result.yes_order.order_id if result.yes_order else None,
                        "no_order_id": result.no_order.order_id if result.no_order else None,
                    }
                else:
                    self.risk_monitor.record_execution_failure(result.error_message)
                    return {"success": False, "error": result.error_message}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to place delta-neutral position: {error_msg}", exc_info=True)
            self.risk_monitor.record_execution_failure(error_msg)
            return {"success": False, "error": error_msg}

    async def _check_resolutions(self) -> list[dict[str, Any]]:
        """
        Check for and process resolved markets.

        In paper mode, simulates resolution based on market state.
        In live mode, queries the API for resolution status.

        Returns:
            List of resolution results
        """
        results = []

        # Get list of markets we have positions in
        market_ids_to_check = list(self._pending_resolutions.keys())

        for market_id in market_ids_to_check:
            try:
                # In paper mode, we need to check if the market has resolved
                # For now, we'll check if the market's end time has passed
                position = self.delta_tracker.get_position(market_id)
                if position is None:
                    continue

                # Try to get market state
                market = self.market_finder.get_market_by_condition(market_id)

                # Check if market has resolved (time-based for paper mode)
                if market and market.seconds_to_resolution <= 0:
                    # Market has resolved - determine outcome
                    # In paper mode, we'll use a simple heuristic based on final price
                    # In live mode, we'd query the resolution status

                    if self.paper_mode:
                        # Simulate resolution - use YES price > 0.5 means YES wins
                        outcome = "YES" if market.yes_price > 0.5 else "NO"

                        # Simulate in paper simulator
                        pnl = self.paper_simulator.simulate_resolution(market_id, outcome)

                        # Remove from delta tracker
                        self.delta_tracker.remove_position(market_id)

                        # Record in risk monitor
                        self.risk_monitor.record_position_closed(
                            market_id=market_id,
                            pnl=float(pnl),
                        )

                        # Remove from pending
                        del self._pending_resolutions[market_id]

                        results.append({
                            "market_id": market_id,
                            "outcome": outcome,
                            "pnl": float(pnl),
                            "mode": "paper",
                        })

                        logger.info(
                            f"[PAPER] Market {market_id} resolved: outcome={outcome}, pnl=${pnl:.2f}"
                        )

                    else:
                        # Live mode - would need to query actual resolution
                        # For now, log that we're waiting
                        logger.debug(f"Market {market_id} may have resolved - checking...")
                        # TODO: Implement actual resolution checking for live mode

            except Exception as e:
                logger.error(f"Error checking resolution for {market_id}: {e}")

        return results

    async def run(self) -> None:
        """
        Main bot loop.

        Runs trading cycles until stopped or kill switch is activated.
        Checks kill switch every cycle and respects shutdown signals.
        """
        logger.info(f"Starting MakerBot main loop (paper_mode={self.paper_mode})")

        self.state.is_running = True
        self.state.start_time = _utc_now()

        try:
            while not self._shutdown_event.is_set():
                # Check kill switch
                if self.risk_monitor.check_kill_switch():
                    logger.warning("Kill switch detected - stopping bot")
                    break

                # Run cycle
                try:
                    cycle_result = await self.run_cycle()

                    # Log cycle summary
                    if cycle_result.get("errors"):
                        for error in cycle_result["errors"]:
                            logger.error(f"Cycle error: {error}")

                except Exception as e:
                    logger.error(f"Unexpected error in cycle: {e}", exc_info=True)
                    self.state.last_error = str(e)

                # Wait for next cycle
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.cycle_interval,
                    )
                except asyncio.TimeoutError:
                    pass  # Normal timeout, continue to next cycle

        except asyncio.CancelledError:
            logger.info("Bot run cancelled")
        finally:
            self.state.is_running = False
            logger.info("MakerBot stopped")

    def stop(self) -> None:
        """
        Stop the bot gracefully.

        Sets the shutdown event to signal the main loop to exit.
        """
        logger.info("Stopping MakerBot...")
        self._shutdown_event.set()
        self.state.is_running = False

    def start(self) -> asyncio.Task:
        """
        Start the bot as a background task.

        Returns:
            asyncio.Task that can be awaited or cancelled
        """
        return asyncio.create_task(self.run())

    def get_status(self) -> dict[str, Any]:
        """
        Get comprehensive bot status.

        Returns:
            Dictionary with bot state, risk status, and position info
        """
        return {
            "bot_state": self.state.to_dict(),
            "risk_status": self.risk_monitor.get_risk_report(),
            "delta_status": self.delta_tracker.get_position_report(),
            "paper_stats": self.paper_simulator.get_stats() if self.paper_mode else None,
            "pending_resolutions": list(self._pending_resolutions.keys()),
        }

    def activate_kill_switch(self, reason: str = "Manual activation") -> None:
        """
        Activate the kill switch to halt all trading.

        Args:
            reason: Reason for activation (logged)
        """
        self.risk_monitor.activate_kill_switch(reason)
        self.stop()

    def deactivate_kill_switch(self) -> bool:
        """
        Deactivate the kill switch to allow trading.

        Returns:
            True if successfully deactivated
        """
        return self.risk_monitor.deactivate_kill_switch()


async def main():
    """Demo the maker bot in paper mode."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("=" * 70)
    print("Delta-Neutral Maker Rebates Bot Demo")
    print("=" * 70)
    print("\nRunning in PAPER mode (no real trades)")
    print("Press Ctrl+C to stop\n")

    # Create bot in paper mode
    bot = MakerBot(paper_mode=True)

    try:
        # Run for a limited time or until interrupted
        await bot.run()
    except KeyboardInterrupt:
        print("\nShutdown requested...")
    finally:
        bot.stop()
        print("\nFinal Status:")
        status = bot.get_status()
        print(f"  Cycles: {status['bot_state']['cycle_count']}")
        print(f"  Positions opened: {status['bot_state']['positions_opened']}")
        print(f"  Positions closed: {status['bot_state']['positions_closed']}")
        print(f"  Total P&L: {status['bot_state']['total_pnl']}")
        print(f"  Total Rebates: {status['bot_state']['total_rebates']}")


if __name__ == "__main__":
    asyncio.run(main())
