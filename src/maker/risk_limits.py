"""
Risk Monitoring System for Maker Rebates Strategy.

This module provides comprehensive risk controls specifically designed for the
delta-neutral maker rebates strategy with strict capital preservation.

Features:
- File-based kill switch for emergency stop
- Position size limits ($100 per market, max 3 concurrent)
- Daily loss tracking with $30 limit
- Alert system for delta, balance, and execution issues
- Real-time risk monitoring and reporting

Configuration ($300 budget):
- Max $100 per market (both legs combined)
- Max 3 concurrent positions
- Max $300 total exposure
- Max $30 daily loss (kill switch activates)
- Max 5% delta exposure allowed

Example:
    >>> from src.maker.risk_limits import RiskMonitor
    >>> from decimal import Decimal
    >>>
    >>> config = {
    ...     "max_daily_loss": 30,
    ...     "max_position_size": 100,
    ...     "max_concurrent": 3,
    ...     "max_delta_pct": 0.05,
    ... }
    >>> monitor = RiskMonitor(config)
    >>>
    >>> # Check before opening position
    >>> can_open, reason = monitor.can_open_position(size=50.0)
    >>> if can_open:
    ...     monitor.record_position_opened("market-123", 50.0)
    >>>
    >>> # Record P&L
    >>> monitor.record_pnl(amount=2.50)
    >>>
    >>> # Check kill switch
    >>> if monitor.check_kill_switch():
    ...     print("Emergency stop activated!")
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _utc_today() -> date:
    """Get current UTC date."""
    return datetime.now(timezone.utc).date()


@dataclass
class Alert:
    """
    Risk alert notification.

    Attributes:
        timestamp: When the alert was generated.
        level: Alert severity (INFO, WARNING, CRITICAL).
        category: Alert category (DELTA, BALANCE, EXECUTION, LOSS).
        message: Human-readable alert message.
        data: Additional alert context data.
    """

    timestamp: datetime
    level: str  # INFO, WARNING, CRITICAL
    category: str  # DELTA, BALANCE, EXECUTION, LOSS
    message: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert alert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "data": self.data,
        }


class RiskMonitor:
    """
    Risk monitoring system for maker rebates strategy.

    Enforces all safety limits and provides kill switch functionality.
    Designed for a conservative $300 budget with strict capital preservation.

    Configuration:
        max_daily_loss: Maximum daily loss before kill switch (default $30).
        max_position_size: Maximum size per market position (default $100).
        max_concurrent: Maximum concurrent positions (default 3).
        max_total_exposure: Maximum total exposure (default $300).
        max_delta_pct: Maximum delta percentage (default 5%).
        kill_switch_file: Path to kill switch file (default .kill_switch).
        balance_alert_drop_pct: Balance drop % for alert (default 10%).

    Attributes:
        config: Configuration dictionary.
        is_halted: Whether trading is currently halted.
        halt_reason: Reason for current halt (if halted).
        alerts: List of generated alerts.
    """

    def __init__(
        self,
        config: Optional[dict] = None,
        project_root: Optional[Path] = None,
    ) -> None:
        """
        Initialize risk monitor.

        Args:
            config: Configuration dictionary with risk limits.
            project_root: Project root directory for kill switch file.
                         Defaults to current working directory.
        """
        # Default configuration
        default_config = {
            "max_daily_loss": 30.0,
            "max_position_size": 100.0,
            "max_concurrent": 3,
            "max_total_exposure": 300.0,
            "max_delta_pct": 0.05,
            "kill_switch_file": ".kill_switch",
            "balance_alert_drop_pct": 0.10,
        }

        self.config = {**default_config, **(config or {})}

        # Convert numeric values to Decimal
        self._max_daily_loss = Decimal(str(self.config["max_daily_loss"]))
        self._max_position_size = Decimal(str(self.config["max_position_size"]))
        self._max_total_exposure = Decimal(str(self.config["max_total_exposure"]))
        self._max_delta_pct = Decimal(str(self.config["max_delta_pct"]))
        self._balance_alert_drop_pct = Decimal(str(self.config["balance_alert_drop_pct"]))
        self._max_concurrent = int(self.config["max_concurrent"])

        # Kill switch path
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._kill_switch_path = self.project_root / self.config["kill_switch_file"]

        # State tracking
        self._is_halted = False
        self._halt_reason: Optional[str] = None

        # Daily tracking
        self._current_date: date = _utc_today()
        self._daily_pnl = Decimal("0")
        self._daily_pnl_history: list[dict] = []

        # Position tracking (market_id -> notional value)
        self._positions: dict[str, Decimal] = {}

        # Balance tracking
        self._initial_balance: Optional[Decimal] = None
        self._current_balance: Optional[Decimal] = None
        self._peak_balance: Optional[Decimal] = None

        # Alerts
        self.alerts: list[Alert] = []

        # Execution failure tracking
        self._execution_failures = 0
        self._execution_failure_window = 10  # Last N attempts

        logger.info(
            f"RiskMonitor initialized: max_daily_loss=${self._max_daily_loss}, "
            f"max_position=${self._max_position_size}, max_concurrent={self._max_concurrent}"
        )

    @property
    def is_halted(self) -> bool:
        """Check if trading is halted (including kill switch)."""
        return self._is_halted or self.check_kill_switch()

    @property
    def halt_reason(self) -> Optional[str]:
        """Get reason for current halt."""
        if self.check_kill_switch():
            return "Kill switch file detected"
        return self._halt_reason

    def check_kill_switch(self) -> bool:
        """
        Check if kill switch file exists.

        The kill switch is activated by creating a `.kill_switch` file
        in the project root directory. This provides an emergency stop
        mechanism that can be triggered externally.

        Returns:
            True if kill switch is active, False otherwise.
        """
        return self._kill_switch_path.exists()

    def activate_kill_switch(self, reason: str = "Manual activation") -> None:
        """
        Activate the kill switch by creating the file.

        This immediately halts all trading activity. The file contains
        a timestamp and reason for activation.

        Args:
            reason: Reason for activating kill switch.
        """
        try:
            with open(self._kill_switch_path, "w") as f:
                f.write(f"Kill switch activated at {_utc_now().isoformat()}\n")
                f.write(f"Reason: {reason}\n")

            self._add_alert(
                level="CRITICAL",
                category="KILL_SWITCH",
                message=f"Kill switch ACTIVATED: {reason}",
            )

            logger.critical(f"Kill switch ACTIVATED: {reason}")
        except IOError as e:
            logger.error(f"Failed to create kill switch file: {e}")

    def deactivate_kill_switch(self) -> bool:
        """
        Deactivate the kill switch by removing the file.

        Returns:
            True if successfully deactivated, False otherwise.
        """
        try:
            if self._kill_switch_path.exists():
                os.remove(self._kill_switch_path)
                self._add_alert(
                    level="INFO",
                    category="KILL_SWITCH",
                    message="Kill switch DEACTIVATED",
                )
                logger.info("Kill switch DEACTIVATED")
                return True
            return True
        except IOError as e:
            logger.error(f"Failed to remove kill switch file: {e}")
            return False

    def _check_daily_reset(self) -> None:
        """Reset daily counters if new day."""
        today = _utc_today()
        if today != self._current_date:
            # Save yesterday's data
            self._daily_pnl_history.append(
                {
                    "date": str(self._current_date),
                    "pnl": float(self._daily_pnl),
                }
            )

            logger.info(
                f"Daily reset: Previous day P&L=${self._daily_pnl}, "
                f"Date={self._current_date}"
            )

            # Reset for new day
            self._current_date = today
            self._daily_pnl = Decimal("0")

            # Auto-resume if halted due to daily loss limit
            if self._halt_reason == "Daily loss limit exceeded":
                self._is_halted = False
                self._halt_reason = None
                logger.info("Auto-resumed after daily reset")

    def can_open_position(
        self,
        size: float,
        market_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Check if a new position can be opened.

        Validates against all risk limits including:
        - Kill switch status
        - Position size limit
        - Concurrent position limit
        - Total exposure limit
        - Daily loss limit

        Args:
            size: Position size (notional value in dollars).
            market_id: Optional market identifier.

        Returns:
            Tuple of (can_open, reason). If can_open is False, reason
            explains why.
        """
        self._check_daily_reset()

        size_decimal = Decimal(str(size))

        # Kill switch check (highest priority)
        if self.check_kill_switch():
            return False, "Kill switch is active"

        # Manual halt check
        if self._is_halted:
            return False, f"Trading halted: {self._halt_reason}"

        # Daily loss limit
        if self._daily_pnl <= -self._max_daily_loss:
            self.activate_kill_switch("Daily loss limit exceeded")
            return False, f"Daily loss limit exceeded: ${self._daily_pnl}"

        # Position size limit
        if size_decimal > self._max_position_size:
            return (
                False,
                f"Position size ${size_decimal} exceeds limit ${self._max_position_size}",
            )

        # Check if already have position in this market
        if market_id and market_id in self._positions:
            existing_size = self._positions[market_id]
            total_size = existing_size + size_decimal
            if total_size > self._max_position_size:
                return (
                    False,
                    f"Total position size ${total_size} would exceed limit "
                    f"${self._max_position_size} for market {market_id}",
                )

        # Concurrent positions limit
        open_positions = len(self._positions)
        if market_id not in self._positions and open_positions >= self._max_concurrent:
            return (
                False,
                f"Maximum concurrent positions ({self._max_concurrent}) reached",
            )

        # Total exposure limit
        current_exposure = sum(abs(v) for v in self._positions.values())
        new_exposure = current_exposure + size_decimal

        if new_exposure > self._max_total_exposure:
            return (
                False,
                f"Total exposure ${new_exposure} would exceed ${self._max_total_exposure}",
            )

        return True, "OK"

    def record_position_opened(
        self,
        market_id: str,
        size: float,
        delta: Optional[float] = None,
    ) -> None:
        """
        Record that a position was opened.

        Args:
            market_id: Market identifier.
            size: Position size (notional value).
            delta: Optional delta exposure of the position.
        """
        size_decimal = Decimal(str(size))

        if market_id in self._positions:
            self._positions[market_id] += size_decimal
        else:
            self._positions[market_id] = size_decimal

        logger.info(f"Position opened: {market_id}, size=${size_decimal}")

        # Check delta if provided
        if delta is not None:
            self._check_delta_alert(delta)

    def record_position_closed(
        self,
        market_id: str,
        pnl: Optional[float] = None,
    ) -> None:
        """
        Record that a position was closed.

        Args:
            market_id: Market identifier.
            pnl: Optional profit/loss from the position.
        """
        if market_id in self._positions:
            del self._positions[market_id]
            logger.info(f"Position closed: {market_id}")

            if pnl is not None:
                self.record_pnl(pnl)

    def record_pnl(self, amount: float) -> None:
        """
        Record profit/loss for daily tracking.

        Args:
            amount: P&L amount (positive for profit, negative for loss).
        """
        self._check_daily_reset()

        amount_decimal = Decimal(str(amount))
        self._daily_pnl += amount_decimal

        logger.info(f"P&L recorded: ${amount_decimal}, Daily total: ${self._daily_pnl}")

        # Check if approaching daily loss limit
        if self._daily_pnl < Decimal("0"):
            remaining = self._max_daily_loss + self._daily_pnl
            if remaining <= self._max_daily_loss * Decimal("0.2"):  # 20% remaining
                self._add_alert(
                    level="WARNING",
                    category="LOSS",
                    message=f"Approaching daily loss limit: ${remaining:.2f} remaining",
                    data={"daily_pnl": float(self._daily_pnl), "remaining": float(remaining)},
                )

        # Check if daily loss limit exceeded
        if self._daily_pnl <= -self._max_daily_loss:
            self.activate_kill_switch(f"Daily loss limit exceeded: ${self._daily_pnl}")

    def is_daily_limit_hit(self) -> bool:
        """
        Check if daily loss limit has been reached.

        Returns:
            True if daily loss limit hit, False otherwise.
        """
        self._check_daily_reset()
        return self._daily_pnl <= -self._max_daily_loss

    def update_balance(self, balance: float) -> None:
        """
        Update current balance for tracking.

        Args:
            balance: Current account balance.
        """
        balance_decimal = Decimal(str(balance))

        # Set initial balance if not set
        if self._initial_balance is None:
            self._initial_balance = balance_decimal
            self._peak_balance = balance_decimal

        self._current_balance = balance_decimal

        # Update peak balance
        if self._peak_balance is None or balance_decimal > self._peak_balance:
            self._peak_balance = balance_decimal

        # Check for significant balance drop
        if self._initial_balance and self._initial_balance > 0:
            drop = (self._initial_balance - balance_decimal) / self._initial_balance
            if drop >= self._balance_alert_drop_pct:
                self._add_alert(
                    level="WARNING",
                    category="BALANCE",
                    message=f"Balance dropped {drop:.1%} from initial",
                    data={
                        "initial_balance": float(self._initial_balance),
                        "current_balance": float(balance_decimal),
                        "drop_pct": float(drop),
                    },
                )

    def check_delta(self, delta: float, total_exposure: float) -> tuple[bool, str]:
        """
        Check if delta is within acceptable limits.

        Args:
            delta: Current delta exposure (positive or negative).
            total_exposure: Total position exposure.

        Returns:
            Tuple of (within_limit, message).
        """
        delta_decimal = Decimal(str(delta))
        exposure_decimal = Decimal(str(total_exposure))

        if exposure_decimal == 0:
            return True, "No exposure"

        delta_pct = abs(delta_decimal / exposure_decimal)

        if delta_pct > self._max_delta_pct:
            self._add_alert(
                level="WARNING",
                category="DELTA",
                message=f"Delta {delta_pct:.1%} exceeds limit {self._max_delta_pct:.1%}",
                data={"delta": float(delta_decimal), "delta_pct": float(delta_pct)},
            )
            return False, f"Delta {delta_pct:.1%} exceeds {self._max_delta_pct:.1%}"

        return True, "OK"

    def _check_delta_alert(self, delta: float) -> None:
        """Internal helper to check delta and generate alerts."""
        current_exposure = sum(abs(v) for v in self._positions.values())
        if current_exposure > 0:
            self.check_delta(delta, float(current_exposure))

    def record_execution_failure(self, reason: str) -> None:
        """
        Record an order execution failure.

        Args:
            reason: Reason for execution failure.
        """
        self._execution_failures += 1

        self._add_alert(
            level="WARNING",
            category="EXECUTION",
            message=f"Order execution failed: {reason}",
            data={"failure_count": self._execution_failures},
        )

        logger.warning(f"Execution failure #{self._execution_failures}: {reason}")

    def reset_execution_failures(self) -> None:
        """Reset execution failure counter."""
        self._execution_failures = 0

    def get_risk_report(self) -> dict[str, Any]:
        """
        Get comprehensive risk status report.

        Returns:
            Dictionary with all risk metrics and status.
        """
        self._check_daily_reset()

        current_exposure = sum(abs(v) for v in self._positions.values())
        open_positions = len(self._positions)

        # Calculate daily loss remaining
        daily_loss_remaining = self._max_daily_loss + self._daily_pnl

        # Calculate position capacity
        positions_remaining = self._max_concurrent - open_positions
        exposure_remaining = self._max_total_exposure - current_exposure

        report = {
            # Status
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "kill_switch_active": self.check_kill_switch(),
            "kill_switch_path": str(self._kill_switch_path),
            # Daily limits
            "date": str(self._current_date),
            "daily_pnl": float(self._daily_pnl),
            "daily_loss_limit": float(self._max_daily_loss),
            "daily_loss_remaining": float(daily_loss_remaining),
            "daily_limit_hit": self.is_daily_limit_hit(),
            # Positions
            "open_positions": open_positions,
            "max_concurrent": self._max_concurrent,
            "positions_remaining": positions_remaining,
            "current_exposure": float(current_exposure),
            "max_exposure": float(self._max_total_exposure),
            "exposure_remaining": float(exposure_remaining),
            "exposure_utilization": (
                float(current_exposure / self._max_total_exposure)
                if self._max_total_exposure > 0
                else 0
            ),
            # Limits
            "max_position_size": float(self._max_position_size),
            "max_delta_pct": float(self._max_delta_pct),
            # Balance
            "initial_balance": float(self._initial_balance) if self._initial_balance else None,
            "current_balance": float(self._current_balance) if self._current_balance else None,
            "peak_balance": float(self._peak_balance) if self._peak_balance else None,
            # Execution
            "execution_failures": self._execution_failures,
            # Alerts
            "alert_count": len(self.alerts),
            "recent_alerts": [a.to_dict() for a in self.alerts[-5:]],
        }

        return report

    def _add_alert(
        self,
        level: str,
        category: str,
        message: str,
        data: Optional[dict] = None,
    ) -> None:
        """
        Add an alert to the alert list.

        Args:
            level: Alert level (INFO, WARNING, CRITICAL).
            category: Alert category.
            message: Alert message.
            data: Additional alert data.
        """
        alert = Alert(
            timestamp=_utc_now(),
            level=level,
            category=category,
            message=message,
            data=data or {},
        )

        self.alerts.append(alert)

        # Keep only last 100 alerts
        if len(self.alerts) > 100:
            self.alerts = self.alerts[-100:]

    def get_alerts(
        self,
        level: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get recent alerts, optionally filtered.

        Args:
            level: Filter by alert level (INFO, WARNING, CRITICAL).
            category: Filter by category.
            limit: Maximum number of alerts to return.

        Returns:
            List of alert dictionaries.
        """
        alerts = self.alerts

        if level:
            alerts = [a for a in alerts if a.level == level]

        if category:
            alerts = [a for a in alerts if a.category == category]

        return [a.to_dict() for a in alerts[-limit:]]

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self.alerts = []

    def save_state(self, filepath: Path) -> None:
        """
        Save risk monitor state to file.

        Args:
            filepath: Path to save state file.
        """
        state = {
            "timestamp": _utc_now().isoformat(),
            "config": self.config,
            "daily_pnl": float(self._daily_pnl),
            "current_date": str(self._current_date),
            "positions": {k: float(v) for k, v in self._positions.items()},
            "is_halted": self._is_halted,
            "halt_reason": self._halt_reason,
            "daily_pnl_history": self._daily_pnl_history,
            "alerts": [a.to_dict() for a in self.alerts],
        }

        try:
            with open(filepath, "w") as f:
                json.dump(state, f, indent=2)
            logger.info(f"Risk monitor state saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save risk monitor state: {e}")

    def load_state(self, filepath: Path) -> bool:
        """
        Load risk monitor state from file.

        Args:
            filepath: Path to state file.

        Returns:
            True if successfully loaded, False otherwise.
        """
        try:
            with open(filepath) as f:
                state = json.load(f)

            self._daily_pnl = Decimal(str(state["daily_pnl"]))
            self._current_date = date.fromisoformat(state["current_date"])
            self._positions = {k: Decimal(str(v)) for k, v in state["positions"].items()}
            self._is_halted = state["is_halted"]
            self._halt_reason = state.get("halt_reason")
            self._daily_pnl_history = state.get("daily_pnl_history", [])

            logger.info(f"Risk monitor state loaded from {filepath}")
            return True
        except Exception as e:
            logger.error(f"Failed to load risk monitor state: {e}")
            return False

    def __repr__(self) -> str:
        status = "HALTED" if self.is_halted else "ACTIVE"
        return (
            f"RiskMonitor(status={status}, daily_pnl=${self._daily_pnl}, "
            f"positions={len(self._positions)})"
        )
