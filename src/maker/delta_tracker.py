"""
Delta Tracker for monitoring delta-neutral positions in the Maker Rebates Bot.

This module provides position tracking and delta monitoring for a portfolio of
delta-neutral YES/NO position pairs. It ensures the portfolio maintains zero
directional exposure and alerts when rebalancing is needed.

Example:
    >>> tracker = DeltaTracker(max_delta_pct=0.05)
    >>> tracker.add_position("market-1", yes_size=50, no_size=50, prices={"yes": 0.50, "no": 0.50})
    >>> print(f"Delta: {tracker.get_delta()}, Total exposure: {tracker.get_total_exposure()}")
    >>> if tracker.needs_rebalance():
    ...     print("Rebalancing required!")

Note:
    Delta = sum of (yes_size - no_size) across all positions.
    For perfect delta-neutrality, delta should be 0.
    Alert threshold is configurable via max_delta_pct (default 5%).
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class TrackedPosition:
    """
    Represents a tracked delta-neutral position pair (YES + NO).

    Attributes:
        market_id: The market identifier.
        yes_size: Size of the YES position (contracts/shares).
        no_size: Size of the NO position (contracts/shares).
        yes_price: Price paid for YES position (0-1).
        no_price: Price paid for NO position (0-1).
        total_cost: Total cost to open both positions.
        created_at: When the position was opened.
        last_updated: When the position was last updated.
    """

    market_id: str
    yes_size: Decimal
    no_size: Decimal
    yes_price: Decimal
    no_price: Decimal
    total_cost: Decimal
    created_at: datetime = field(default_factory=_utc_now)
    last_updated: datetime = field(default_factory=_utc_now)

    @property
    def delta(self) -> Decimal:
        """
        Calculate the delta exposure of this position.

        For a perfectly delta-neutral position, this should be 0.
        Positive delta = long YES bias, Negative delta = long NO bias.

        Returns:
            Delta exposure: yes_size - no_size (should be ~0 for delta-neutral).
        """
        return self.yes_size - self.no_size

    @property
    def is_delta_neutral(self) -> bool:
        """Check if position is delta-neutral (within 1% tolerance)."""
        total_size = self.yes_size + self.no_size
        if total_size == Decimal("0"):
            return True
        delta_pct = abs(self.delta / total_size)
        return delta_pct < Decimal("0.01")

    @property
    def yes_exposure(self) -> Decimal:
        """Calculate the dollar exposure on the YES side."""
        return self.yes_size * self.yes_price

    @property
    def no_exposure(self) -> Decimal:
        """Calculate the dollar exposure on the NO side."""
        return self.no_size * self.no_price

    def to_dict(self) -> dict[str, Any]:
        """Convert position to dictionary representation."""
        return {
            "market_id": self.market_id,
            "yes_size": str(self.yes_size),
            "no_size": str(self.no_size),
            "yes_price": str(self.yes_price),
            "no_price": str(self.no_price),
            "total_cost": str(self.total_cost),
            "delta": str(self.delta),
            "is_delta_neutral": self.is_delta_neutral,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }


class DeltaTrackerError(Exception):
    """Raised when delta tracker operations fail."""

    pass


class DeltaTracker:
    """
    Tracks delta-neutral positions and monitors portfolio delta exposure.

    This tracker maintains a registry of all open YES/NO position pairs and
    calculates the total delta exposure across the portfolio. It alerts when
    the delta exceeds the configured threshold, indicating rebalancing is needed.

    Attributes:
        max_delta_pct: Maximum allowed delta as percentage of total exposure (default 5%).
        positions: Dictionary of tracked positions, keyed by market_id.

    Example:
        >>> tracker = DeltaTracker(max_delta_pct=0.05)
        >>> tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        >>> delta = tracker.get_delta()
        >>> if tracker.needs_rebalance():
        ...     report = tracker.get_position_report()
        ...     print(f"Rebalancing needed: {report}")
    """

    def __init__(self, max_delta_pct: float = 0.05):
        """
        Initialize the delta tracker.

        Args:
            max_delta_pct: Maximum allowed delta as percentage of total exposure.
                          Default 0.05 (5%).
        """
        self.max_delta_pct = Decimal(str(max_delta_pct))
        self.positions: dict[str, TrackedPosition] = {}

        logger.info(f"DeltaTracker initialized with max_delta_pct={max_delta_pct}")

    def add_position(
        self,
        market_id: str,
        yes_size: float,
        no_size: float,
        prices: dict[str, float],
    ) -> TrackedPosition:
        """
        Add a new delta-neutral position to track.

        Args:
            market_id: Unique identifier for the market.
            yes_size: Size of the YES position.
            no_size: Size of the NO position.
            prices: Dictionary with "yes" and "no" price keys.

        Returns:
            The created TrackedPosition.

        Raises:
            DeltaTrackerError: If market_id already exists or prices invalid.
        """
        # Validate inputs
        if market_id in self.positions:
            raise DeltaTrackerError(f"Position for market {market_id} already exists")

        if "yes" not in prices or "no" not in prices:
            raise DeltaTrackerError("Prices dict must contain 'yes' and 'no' keys")

        yes_size_decimal = Decimal(str(yes_size))
        no_size_decimal = Decimal(str(no_size))
        yes_price_decimal = Decimal(str(prices["yes"]))
        no_price_decimal = Decimal(str(prices["no"]))

        # Validate prices
        if not (Decimal("0") < yes_price_decimal <= Decimal("1")):
            raise DeltaTrackerError(f"YES price must be between 0 and 1, got {prices['yes']}")

        if not (Decimal("0") < no_price_decimal <= Decimal("1")):
            raise DeltaTrackerError(f"NO price must be between 0 and 1, got {prices['no']}")

        # Validate sizes
        if yes_size_decimal <= Decimal("0"):
            raise DeltaTrackerError(f"YES size must be positive, got {yes_size}")

        if no_size_decimal <= Decimal("0"):
            raise DeltaTrackerError(f"NO size must be positive, got {no_size}")

        # Calculate total cost
        yes_cost = yes_size_decimal * yes_price_decimal
        no_cost = no_size_decimal * no_price_decimal
        total_cost = yes_cost + no_cost

        # Create position
        position = TrackedPosition(
            market_id=market_id,
            yes_size=yes_size_decimal,
            no_size=no_size_decimal,
            yes_price=yes_price_decimal,
            no_price=no_price_decimal,
            total_cost=total_cost,
        )

        # Store position
        self.positions[market_id] = position

        # Check if rebalancing is needed
        if self.needs_rebalance():
            logger.warning(
                f"Delta exceeds threshold after adding {market_id}: "
                f"delta={self.get_delta()}, threshold={self._get_delta_threshold()}"
            )

        logger.info(
            f"Added position {market_id}: YES={yes_size}@{prices['yes']}, "
            f"NO={no_size}@{prices['no']}, delta={position.delta}"
        )

        return position

    def remove_position(self, market_id: str) -> Optional[TrackedPosition]:
        """
        Remove a position when market resolves.

        Args:
            market_id: The market identifier to remove.

        Returns:
            The removed TrackedPosition, or None if not found.
        """
        position = self.positions.pop(market_id, None)

        if position is not None:
            logger.info(
                f"Removed position {market_id}: delta was {position.delta}, "
                f"portfolio delta now {self.get_delta()}"
            )
        else:
            logger.warning(f"Attempted to remove non-existent position {market_id}")

        return position

    def get_position(self, market_id: str) -> Optional[TrackedPosition]:
        """
        Get a specific position by market_id.

        Args:
            market_id: The market identifier.

        Returns:
            The TrackedPosition, or None if not found.
        """
        return self.positions.get(market_id)

    def get_delta(self) -> float:
        """
        Calculate current total delta exposure across all open positions.

        A perfectly delta-neutral portfolio should have delta = 0.
        Positive delta = net long YES, negative delta = net long NO.

        Returns:
            Total delta: sum of (yes_size - no_size) for all positions.
        """
        total_delta = Decimal("0")
        for position in self.positions.values():
            total_delta += position.delta

        return float(total_delta)

    def get_total_exposure(self) -> float:
        """
        Calculate total capital at risk across all positions.

        Returns:
            Total exposure: sum of total_cost for all positions.
        """
        total_exposure = Decimal("0")
        for position in self.positions.values():
            total_exposure += position.total_cost

        return float(total_exposure)

    def get_yes_exposure(self) -> float:
        """
        Calculate total YES side exposure across all positions.

        Returns:
            Total YES exposure in dollars.
        """
        total_yes = Decimal("0")
        for position in self.positions.values():
            total_yes += position.yes_exposure

        return float(total_yes)

    def get_no_exposure(self) -> float:
        """
        Calculate total NO side exposure across all positions.

        Returns:
            Total NO exposure in dollars.
        """
        total_no = Decimal("0")
        for position in self.positions.values():
            total_no += position.no_exposure

        return float(total_no)

    def needs_rebalance(self) -> bool:
        """
        Check if rebalancing is needed based on delta threshold.

        Returns:
            True if absolute delta exceeds max_delta_pct of total exposure.
        """
        if not self.positions:
            return False

        delta = Decimal(str(self.get_delta()))
        threshold = self._get_delta_threshold()

        return abs(delta) > threshold

    def get_position_report(self) -> dict[str, Any]:
        """
        Generate comprehensive position summary report.

        Returns:
            Dictionary containing:
            - Total positions count
            - Total exposure
            - Current delta
            - Delta percentage of total exposure
            - YES/NO exposure breakdown
            - Individual position details
            - Rebalancing status
        """
        total_exposure = Decimal(str(self.get_total_exposure()))
        delta = Decimal(str(self.get_delta()))
        yes_exposure = Decimal(str(self.get_yes_exposure()))
        no_exposure = Decimal(str(self.get_no_exposure()))

        # Calculate delta percentage
        if total_exposure > Decimal("0"):
            delta_pct = (abs(delta) / total_exposure * Decimal("100")).quantize(
                Decimal("0.01")
            )
        else:
            delta_pct = Decimal("0")

        # Compile individual position details
        position_details = [pos.to_dict() for pos in self.positions.values()]

        # Identify non-neutral positions
        non_neutral = [
            pos.market_id for pos in self.positions.values() if not pos.is_delta_neutral
        ]

        return {
            "total_positions": len(self.positions),
            "total_exposure": str(total_exposure),
            "total_delta": str(delta),
            "delta_pct": str(delta_pct),
            "max_delta_pct": str(self.max_delta_pct * Decimal("100")),
            "needs_rebalance": self.needs_rebalance(),
            "delta_threshold": str(self._get_delta_threshold()),
            "yes_exposure": str(yes_exposure),
            "no_exposure": str(no_exposure),
            "exposure_imbalance": str(yes_exposure - no_exposure),
            "positions": position_details,
            "non_neutral_positions": non_neutral,
            "is_portfolio_neutral": abs(delta) < Decimal("0.01"),
        }

    def reconcile_with_exchange(
        self, exchange_positions: dict[str, dict[str, float]]
    ) -> dict[str, Any]:
        """
        Reconcile tracked positions with exchange records.

        Args:
            exchange_positions: Dictionary mapping market_id to position data.
                               Expected format: {market_id: {"yes_size": X, "no_size": Y}}

        Returns:
            Reconciliation report with discrepancies and status.
        """
        discrepancies = []
        missing_in_tracker = []
        missing_in_exchange = []

        # Check positions in tracker
        for market_id, position in self.positions.items():
            if market_id not in exchange_positions:
                missing_in_exchange.append(
                    {
                        "market_id": market_id,
                        "tracker_yes_size": str(position.yes_size),
                        "tracker_no_size": str(position.no_size),
                    }
                )
            else:
                exchange_pos = exchange_positions[market_id]
                exchange_yes = Decimal(str(exchange_pos.get("yes_size", 0)))
                exchange_no = Decimal(str(exchange_pos.get("no_size", 0)))

                # Check for discrepancies (allow small tolerance for rounding)
                tolerance = Decimal("0.0001")
                yes_diff = abs(position.yes_size - exchange_yes)
                no_diff = abs(position.no_size - exchange_no)

                if yes_diff > tolerance or no_diff > tolerance:
                    discrepancies.append(
                        {
                            "market_id": market_id,
                            "tracker_yes": str(position.yes_size),
                            "tracker_no": str(position.no_size),
                            "exchange_yes": str(exchange_yes),
                            "exchange_no": str(exchange_no),
                            "yes_diff": str(yes_diff),
                            "no_diff": str(no_diff),
                        }
                    )

        # Check for positions in exchange but not in tracker
        for market_id in exchange_positions:
            if market_id not in self.positions:
                exchange_pos = exchange_positions[market_id]
                missing_in_tracker.append(
                    {
                        "market_id": market_id,
                        "exchange_yes_size": str(exchange_pos.get("yes_size", 0)),
                        "exchange_no_size": str(exchange_pos.get("no_size", 0)),
                    }
                )

        # Log discrepancies
        if discrepancies or missing_in_tracker or missing_in_exchange:
            logger.warning(
                f"Reconciliation found issues: {len(discrepancies)} discrepancies, "
                f"{len(missing_in_tracker)} missing in tracker, "
                f"{len(missing_in_exchange)} missing in exchange"
            )
        else:
            logger.info("Reconciliation successful: all positions match")

        return {
            "reconciled": len(discrepancies) == 0
            and len(missing_in_tracker) == 0
            and len(missing_in_exchange) == 0,
            "total_checked": len(self.positions) + len(missing_in_tracker),
            "discrepancies": discrepancies,
            "missing_in_tracker": missing_in_tracker,
            "missing_in_exchange": missing_in_exchange,
        }

    def get_rebalancing_suggestion(self) -> dict[str, Any]:
        """
        Generate rebalancing suggestions when delta exceeds threshold.

        Returns:
            Dictionary with rebalancing suggestions including:
            - Current delta and threshold
            - Suggested trade direction
            - Estimated trade size
        """
        delta = Decimal(str(self.get_delta()))
        threshold = self._get_delta_threshold()

        if abs(delta) <= threshold:
            return {
                "needs_rebalancing": False,
                "current_delta": str(delta),
                "threshold": str(threshold),
                "message": "Portfolio is within delta threshold",
            }

        # Determine rebalancing direction
        if delta > Decimal("0"):
            # Net long YES, need to reduce YES or increase NO
            direction = "reduce_yes_or_increase_no"
            suggested_trade = "Sell YES or Buy NO"
        else:
            # Net long NO, need to reduce NO or increase YES
            direction = "reduce_no_or_increase_yes"
            suggested_trade = "Sell NO or Buy YES"

        # Estimate trade size needed
        excess_delta = abs(delta) - threshold
        trade_size = excess_delta  # Simplified: actual implementation may vary

        return {
            "needs_rebalancing": True,
            "current_delta": str(delta),
            "threshold": str(threshold),
            "excess_delta": str(excess_delta),
            "direction": direction,
            "suggested_trade": suggested_trade,
            "estimated_trade_size": str(trade_size),
            "message": f"Delta {delta} exceeds threshold {threshold}. Consider {suggested_trade}.",
        }

    def _get_delta_threshold(self) -> Decimal:
        """
        Calculate the absolute delta threshold based on total exposure.

        Returns:
            Absolute delta threshold (max_delta_pct * total_exposure).
        """
        total_exposure = Decimal(str(self.get_total_exposure()))
        return self.max_delta_pct * total_exposure

    def reset(self) -> None:
        """Clear all tracked positions."""
        self.positions.clear()
        logger.info("DeltaTracker reset: all positions cleared")

    def __len__(self) -> int:
        """Return number of tracked positions."""
        return len(self.positions)

    def __contains__(self, market_id: str) -> bool:
        """Check if a market_id is being tracked."""
        return market_id in self.positions

    def __repr__(self) -> str:
        """String representation of DeltaTracker."""
        return (
            f"DeltaTracker(positions={len(self.positions)}, "
            f"delta={self.get_delta():.4f}, "
            f"exposure={self.get_total_exposure():.2f}, "
            f"needs_rebalance={self.needs_rebalance()})"
        )
