"""
Rebate Tracking System for Maker Rebates Strategy.

This module tracks incoming rebate payments from Polymarket and provides
comprehensive analytics for profitability analysis.

Features:
- Trade recording with market, size, and timestamp tracking
- Rebate detection from USDC transfers
- Trade-rebate linking and attribution
- Per-trade and per-market analytics
- ROI and APY calculations
- Daily, weekly, and total rebate summaries
- Best performing market identification

Rebate Structure (Polymarket):
- Maker rebates: Up to 3% at 50% probability, scaling with distance from 50%
- Rebates paid periodically via USDC transfers to wallet
- Rebate rate: Higher closer to 50% probability

Example:
    >>> from src.maker.rebate_monitor import RebateTracker
    >>> from datetime import datetime, timezone
    >>>
    >>> tracker = RebateTracker()
    >>>
    >>> # Record trades
    >>> tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
    >>> tracker.record_trade("trade-2", "eth-updown-15m", 30.0)
    >>>
    >>> # Record rebate detection
    >>> rebate = tracker.detect_rebate({
    ...     "amount": 1.50,
    ...     "timestamp": datetime.now(timezone.utc).isoformat(),
    ...     "tx_hash": "0x123..."
    ... })
    >>>
    >>> # Get analytics
    >>> stats = tracker.get_rebate_stats()
    >>> roi = tracker.calculate_roi(period_days=7)
    >>> best = tracker.get_best_performing_market()
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


def _parse_timestamp(ts: str | datetime) -> datetime:
    """Parse timestamp from string or return datetime directly."""
    if isinstance(ts, datetime):
        return ts
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@dataclass
class RecordedTrade:
    """
    Represents a recorded trade for rebate tracking.

    Attributes:
        trade_id: Unique identifier for this trade.
        market: Market identifier (e.g., 'btc-updown-15m').
        size: Trade size in USDC.
        timestamp: When the trade was executed.
        attributed_rebate: Rebate amount attributed to this trade.
        rebate_rate: Effective rebate rate for this trade.
    """

    trade_id: str
    market: str
    size: Decimal
    timestamp: datetime
    attributed_rebate: Decimal = Decimal("0")
    rebate_rate: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        """Convert trade to dictionary representation."""
        return {
            "trade_id": self.trade_id,
            "market": self.market,
            "size": str(self.size),
            "timestamp": self.timestamp.isoformat(),
            "attributed_rebate": str(self.attributed_rebate),
            "rebate_rate": str(self.rebate_rate),
        }


@dataclass
class RebateEvent:
    """
    Represents a detected rebate payment.

    Attributes:
        rebate_id: Unique identifier for this rebate.
        amount: Rebate amount in USDC.
        timestamp: When the rebate was received.
        tx_hash: Transaction hash (if available).
        attributed_trades: List of trade_ids this rebate is attributed to.
        raw_data: Original transfer data.
    """

    rebate_id: str
    amount: Decimal
    timestamp: datetime
    tx_hash: Optional[str] = None
    attributed_trades: list[str] = field(default_factory=list)
    raw_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert rebate event to dictionary representation."""
        return {
            "rebate_id": self.rebate_id,
            "amount": str(self.amount),
            "timestamp": self.timestamp.isoformat(),
            "tx_hash": self.tx_hash,
            "attributed_trades": self.attributed_trades,
        }


@dataclass
class MarketStats:
    """
    Statistics for a specific market.

    Attributes:
        market: Market identifier.
        total_volume: Total trading volume in this market.
        total_rebates: Total rebates earned from this market.
        trade_count: Number of trades in this market.
        avg_rebate_rate: Average rebate rate for this market.
    """

    market: str
    total_volume: Decimal = Decimal("0")
    total_rebates: Decimal = Decimal("0")
    trade_count: int = 0
    avg_rebate_rate: Decimal = Decimal("0")

    def to_dict(self) -> dict[str, Any]:
        """Convert market stats to dictionary representation."""
        return {
            "market": self.market,
            "total_volume": str(self.total_volume),
            "total_rebates": str(self.total_rebates),
            "trade_count": self.trade_count,
            "avg_rebate_rate": str(self.avg_rebate_rate),
            "rebate_per_100": str(self.rebate_per_100),
        }

    @property
    def rebate_per_100(self) -> Decimal:
        """Calculate rebate per $100 of volume."""
        if self.total_volume == Decimal("0"):
            return Decimal("0")
        return (self.total_rebates / self.total_volume * Decimal("100")).quantize(
            Decimal("0.0001")
        )


class RebateTrackerError(Exception):
    """Raised when rebate tracker operations fail."""

    pass


class RebateTracker:
    """
    Tracks rebate payments and provides profitability analytics.

    This tracker monitors trades and incoming rebates to calculate
    effective rebate rates, ROI, and identify best performing markets.

    Attributes:
        trades: Dictionary of recorded trades, keyed by trade_id.
        rebates: List of detected rebate events.
        market_stats: Dictionary of per-market statistics.

    Configuration:
        rebate_attribution_window: Time window for attributing rebates to trades.
        expected_rebate_rate: Expected rebate rate for estimation (default 0.1%).

    Example:
        >>> tracker = RebateTracker()
        >>> tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        >>> stats = tracker.get_rebate_stats()
    """

    def __init__(
        self,
        rebate_attribution_window_hours: int = 24,
        expected_rebate_rate: float = 0.001,
    ):
        """
        Initialize the rebate tracker.

        Args:
            rebate_attribution_window_hours: Hours to look back when attributing
                                             rebates to trades (default 24).
            expected_rebate_rate: Expected maker rebate rate for estimation
                                  (default 0.1% = 0.001).
        """
        self.rebate_attribution_window = timedelta(hours=rebate_attribution_window_hours)
        self.expected_rebate_rate = Decimal(str(expected_rebate_rate))

        # Storage
        self.trades: dict[str, RecordedTrade] = {}
        self.rebates: list[RebateEvent] = []
        self.market_stats: dict[str, MarketStats] = {}

        # Tracking
        self._total_volume = Decimal("0")
        self._total_rebates = Decimal("0")
        self._rebate_counter = 0

        logger.info(
            f"RebateTracker initialized: "
            f"attribution_window={rebate_attribution_window_hours}h, "
            f"expected_rate={expected_rebate_rate:.4%}"
        )

    def record_trade(
        self,
        trade_id: str,
        market: str,
        size: float,
        timestamp: Optional[datetime] = None,
    ) -> RecordedTrade:
        """
        Record a trade for rebate tracking.

        Args:
            trade_id: Unique identifier for the trade.
            market: Market identifier (e.g., 'btc-updown-15m').
            size: Trade size in USDC.
            timestamp: Trade timestamp (defaults to now).

        Returns:
            The recorded trade.

        Raises:
            RebateTrackerError: If trade_id already exists.
        """
        if trade_id in self.trades:
            raise RebateTrackerError(f"Trade {trade_id} already recorded")

        size_decimal = Decimal(str(size))

        if size_decimal <= Decimal("0"):
            raise RebateTrackerError(f"Trade size must be positive, got {size}")

        trade = RecordedTrade(
            trade_id=trade_id,
            market=market,
            size=size_decimal,
            timestamp=timestamp or _utc_now(),
        )

        # Store trade
        self.trades[trade_id] = trade

        # Update volume tracking
        self._total_volume += size_decimal

        # Update market stats
        self._update_market_stats_for_trade(trade)

        logger.info(f"Recorded trade {trade_id}: {market}, size=${size_decimal}")

        return trade

    def detect_rebate(
        self,
        usdc_transfer: dict,
    ) -> Optional[RebateEvent]:
        """
        Detect and record a rebate from a USDC transfer.

        This method analyzes an incoming USDC transfer to determine if it
        represents a maker rebate payment. It attributes the rebate to
        recent trades based on the attribution window.

        Args:
            usdc_transfer: Dictionary containing transfer data.
                Required keys:
                - amount: Rebate amount in USDC (float or str).
                Optional keys:
                - timestamp: When the transfer occurred (ISO format or datetime).
                - tx_hash: Transaction hash for the transfer.

        Returns:
            RebateEvent if rebate was detected and recorded, None if not a valid rebate.

        Example:
            >>> rebate = tracker.detect_rebate({
            ...     "amount": 1.50,
            ...     "timestamp": "2025-01-06T12:00:00Z",
            ...     "tx_hash": "0x123..."
            ... })
        """
        # Validate transfer data
        if "amount" not in usdc_transfer:
            logger.warning("USDC transfer missing 'amount' field")
            return None

        try:
            amount = Decimal(str(usdc_transfer["amount"]))
        except (ValueError, TypeError, Exception):
            logger.warning(f"Invalid amount in transfer: {usdc_transfer.get('amount')}")
            return None

        if amount <= Decimal("0"):
            logger.debug(f"Ignoring non-positive transfer: {amount}")
            return None

        # Parse timestamp
        timestamp_raw = usdc_transfer.get("timestamp")
        if timestamp_raw:
            try:
                timestamp = _parse_timestamp(timestamp_raw)
            except (ValueError, TypeError):
                timestamp = _utc_now()
        else:
            timestamp = _utc_now()

        # Generate rebate ID
        self._rebate_counter += 1
        rebate_id = f"rebate-{self._rebate_counter}"

        # Create rebate event
        rebate = RebateEvent(
            rebate_id=rebate_id,
            amount=amount,
            timestamp=timestamp,
            tx_hash=usdc_transfer.get("tx_hash"),
            raw_data=usdc_transfer,
        )

        # Attribute rebate to recent trades
        self._attribute_rebate_to_trades(rebate)

        # Store rebate
        self.rebates.append(rebate)

        # Update totals
        self._total_rebates += amount

        logger.info(
            f"Detected rebate {rebate_id}: ${amount}, "
            f"attributed to {len(rebate.attributed_trades)} trades"
        )

        return rebate

    def _attribute_rebate_to_trades(self, rebate: RebateEvent) -> None:
        """
        Attribute a rebate to recent trades within the attribution window.

        Attribution is done proportionally based on trade volume.

        Args:
            rebate: The rebate event to attribute.
        """
        # Find trades within attribution window
        cutoff_time = rebate.timestamp - self.rebate_attribution_window
        eligible_trades = [
            t
            for t in self.trades.values()
            if t.timestamp >= cutoff_time and t.timestamp <= rebate.timestamp
        ]

        if not eligible_trades:
            logger.debug(f"No eligible trades found for rebate {rebate.rebate_id}")
            return

        # Calculate total volume of eligible trades
        total_eligible_volume = sum(t.size for t in eligible_trades)

        if total_eligible_volume == Decimal("0"):
            return

        # Attribute rebate proportionally
        for trade in eligible_trades:
            proportion = trade.size / total_eligible_volume
            attributed_amount = (rebate.amount * proportion).quantize(Decimal("0.000001"))

            trade.attributed_rebate += attributed_amount

            # Calculate effective rebate rate for this trade
            if trade.size > Decimal("0"):
                trade.rebate_rate = trade.attributed_rebate / trade.size

            rebate.attributed_trades.append(trade.trade_id)

            # Update market stats
            self._update_market_rebate_stats(trade.market, attributed_amount)

    def _update_market_stats_for_trade(self, trade: RecordedTrade) -> None:
        """Update market statistics when a trade is recorded."""
        market = trade.market

        if market not in self.market_stats:
            self.market_stats[market] = MarketStats(market=market)

        stats = self.market_stats[market]
        stats.total_volume += trade.size
        stats.trade_count += 1

    def _update_market_rebate_stats(self, market: str, rebate_amount: Decimal) -> None:
        """Update market rebate statistics."""
        if market not in self.market_stats:
            self.market_stats[market] = MarketStats(market=market)

        stats = self.market_stats[market]
        stats.total_rebates += rebate_amount

        # Update average rebate rate
        if stats.total_volume > Decimal("0"):
            stats.avg_rebate_rate = stats.total_rebates / stats.total_volume

    def get_rebate_stats(self) -> dict[str, Any]:
        """
        Get comprehensive rebate statistics.

        Returns:
            Dictionary containing:
            - Total trades and volume
            - Total rebates earned
            - Average rebate rate
            - Rebate per $100 liquidity
            - Daily and weekly totals
            - Per-market breakdown
        """
        now = _utc_now()
        day_ago = now - timedelta(days=1)
        week_ago = now - timedelta(days=7)

        # Calculate daily rebates
        daily_rebates = sum(
            r.amount for r in self.rebates if r.timestamp >= day_ago
        )

        # Calculate weekly rebates
        weekly_rebates = sum(
            r.amount for r in self.rebates if r.timestamp >= week_ago
        )

        # Calculate daily volume
        daily_volume = sum(
            t.size for t in self.trades.values() if t.timestamp >= day_ago
        )

        # Calculate weekly volume
        weekly_volume = sum(
            t.size for t in self.trades.values() if t.timestamp >= week_ago
        )

        # Calculate average rebate rate
        avg_rebate_rate = Decimal("0")
        if self._total_volume > Decimal("0"):
            avg_rebate_rate = self._total_rebates / self._total_volume

        # Calculate rebate per $100
        rebate_per_100 = Decimal("0")
        if self._total_volume > Decimal("0"):
            rebate_per_100 = self._total_rebates / self._total_volume * Decimal("100")

        return {
            # Totals
            "total_trades": len(self.trades),
            "total_volume": str(self._total_volume),
            "total_rebates": str(self._total_rebates),
            "rebate_events": len(self.rebates),
            # Rates
            "avg_rebate_rate": str(avg_rebate_rate.quantize(Decimal("0.000001"))),
            "avg_rebate_rate_pct": str(
                (avg_rebate_rate * Decimal("100")).quantize(Decimal("0.0001"))
            ),
            "rebate_per_100": str(rebate_per_100.quantize(Decimal("0.0001"))),
            # Daily
            "daily_rebates": str(daily_rebates),
            "daily_volume": str(daily_volume),
            # Weekly
            "weekly_rebates": str(weekly_rebates),
            "weekly_volume": str(weekly_volume),
            # Per-market
            "markets": {
                market: stats.to_dict() for market, stats in self.market_stats.items()
            },
            # Timestamp
            "as_of": now.isoformat(),
        }

    def calculate_roi(self, period_days: int = 7) -> float:
        """
        Calculate return on investment for a given period.

        ROI = (Total Rebates / Total Capital Deployed) * 100

        For daily ROI, this is annualized.

        Args:
            period_days: Number of days to calculate ROI for.

        Returns:
            ROI as a percentage (e.g., 5.0 for 5%).
        """
        if period_days <= 0:
            raise RebateTrackerError("Period days must be positive")

        now = _utc_now()
        period_start = now - timedelta(days=period_days)

        # Calculate rebates in period
        period_rebates = sum(
            r.amount for r in self.rebates if r.timestamp >= period_start
        )

        # Calculate volume in period (capital deployed)
        period_volume = sum(
            t.size for t in self.trades.values() if t.timestamp >= period_start
        )

        if period_volume == Decimal("0"):
            return 0.0

        # Calculate ROI percentage
        roi = float((period_rebates / period_volume) * Decimal("100"))

        return roi

    def calculate_effective_apy(self, period_days: int = 7) -> float:
        """
        Calculate effective annual percentage yield based on recent performance.

        This extrapolates the current rebate rate to an annual basis.

        Args:
            period_days: Number of days of recent data to use for calculation.

        Returns:
            Effective APY as a percentage.
        """
        if period_days <= 0:
            raise RebateTrackerError("Period days must be positive")

        # Get ROI for period
        period_roi = self.calculate_roi(period_days)

        # Annualize: (1 + period_roi/100)^(365/period_days) - 1
        if period_roi <= 0:
            return 0.0

        periods_per_year = 365 / period_days
        apy = ((1 + period_roi / 100) ** periods_per_year - 1) * 100

        return apy

    def get_best_performing_market(self) -> str:
        """
        Get the best performing market by rebate rate.

        Returns:
            Market identifier with highest rebate rate, or empty string if no data.
        """
        if not self.market_stats:
            return ""

        # Filter markets with volume
        markets_with_volume = {
            market: stats
            for market, stats in self.market_stats.items()
            if stats.total_volume > Decimal("0")
        }

        if not markets_with_volume:
            return ""

        # Find market with highest rebate rate
        best_market = max(
            markets_with_volume.keys(),
            key=lambda m: markets_with_volume[m].avg_rebate_rate,
        )

        return best_market

    def get_trade(self, trade_id: str) -> Optional[RecordedTrade]:
        """
        Get a specific trade by ID.

        Args:
            trade_id: Trade identifier.

        Returns:
            The RecordedTrade, or None if not found.
        """
        return self.trades.get(trade_id)

    def get_trades_by_market(self, market: str) -> list[RecordedTrade]:
        """
        Get all trades for a specific market.

        Args:
            market: Market identifier.

        Returns:
            List of trades in the specified market.
        """
        return [t for t in self.trades.values() if t.market == market]

    def get_recent_rebates(self, limit: int = 10) -> list[dict]:
        """
        Get recent rebate events.

        Args:
            limit: Maximum number of rebates to return.

        Returns:
            List of rebate event dictionaries.
        """
        return [r.to_dict() for r in self.rebates[-limit:]]

    def get_market_comparison(self) -> list[dict]:
        """
        Get market comparison sorted by performance.

        Returns:
            List of market statistics sorted by rebate rate (descending).
        """
        markets = list(self.market_stats.values())

        # Sort by rebate rate descending
        markets.sort(key=lambda m: m.avg_rebate_rate, reverse=True)

        return [m.to_dict() for m in markets]

    def save_state(self, filepath: Path) -> None:
        """
        Save tracker state to file.

        Args:
            filepath: Path to save state file.
        """
        state = {
            "timestamp": _utc_now().isoformat(),
            "total_volume": str(self._total_volume),
            "total_rebates": str(self._total_rebates),
            "rebate_counter": self._rebate_counter,
            "trades": [t.to_dict() for t in self.trades.values()],
            "rebates": [r.to_dict() for r in self.rebates],
            "market_stats": {m: s.to_dict() for m, s in self.market_stats.items()},
        }

        try:
            with open(filepath, "w") as f:
                json.dump(state, f, indent=2)
            logger.info(f"RebateTracker state saved to {filepath}")
        except Exception as e:
            logger.error(f"Failed to save rebate tracker state: {e}")
            raise RebateTrackerError(f"Failed to save state: {e}") from e

    def load_state(self, filepath: Path) -> bool:
        """
        Load tracker state from file.

        Args:
            filepath: Path to state file.

        Returns:
            True if successfully loaded, False otherwise.
        """
        try:
            with open(filepath) as f:
                state = json.load(f)

            # Load totals
            self._total_volume = Decimal(state["total_volume"])
            self._total_rebates = Decimal(state["total_rebates"])
            self._rebate_counter = state["rebate_counter"]

            # Load trades
            self.trades = {}
            for trade_data in state["trades"]:
                trade = RecordedTrade(
                    trade_id=trade_data["trade_id"],
                    market=trade_data["market"],
                    size=Decimal(trade_data["size"]),
                    timestamp=_parse_timestamp(trade_data["timestamp"]),
                    attributed_rebate=Decimal(trade_data["attributed_rebate"]),
                    rebate_rate=Decimal(trade_data["rebate_rate"]),
                )
                self.trades[trade.trade_id] = trade

            # Load rebates
            self.rebates = []
            for rebate_data in state["rebates"]:
                rebate = RebateEvent(
                    rebate_id=rebate_data["rebate_id"],
                    amount=Decimal(rebate_data["amount"]),
                    timestamp=_parse_timestamp(rebate_data["timestamp"]),
                    tx_hash=rebate_data.get("tx_hash"),
                    attributed_trades=rebate_data.get("attributed_trades", []),
                )
                self.rebates.append(rebate)

            # Load market stats
            self.market_stats = {}
            for market, stats_data in state.get("market_stats", {}).items():
                self.market_stats[market] = MarketStats(
                    market=market,
                    total_volume=Decimal(stats_data["total_volume"]),
                    total_rebates=Decimal(stats_data["total_rebates"]),
                    trade_count=stats_data["trade_count"],
                    avg_rebate_rate=Decimal(stats_data["avg_rebate_rate"]),
                )

            logger.info(f"RebateTracker state loaded from {filepath}")
            return True

        except FileNotFoundError:
            logger.warning(f"State file not found: {filepath}")
            return False
        except Exception as e:
            logger.error(f"Failed to load rebate tracker state: {e}")
            return False

    def reset(self) -> None:
        """Clear all tracked data."""
        self.trades.clear()
        self.rebates.clear()
        self.market_stats.clear()
        self._total_volume = Decimal("0")
        self._total_rebates = Decimal("0")
        self._rebate_counter = 0
        logger.info("RebateTracker reset: all data cleared")

    def __len__(self) -> int:
        """Return number of recorded trades."""
        return len(self.trades)

    def __repr__(self) -> str:
        """String representation of RebateTracker."""
        return (
            f"RebateTracker(trades={len(self.trades)}, "
            f"rebates={len(self.rebates)}, "
            f"total_volume=${self._total_volume:.2f}, "
            f"total_rebates=${self._total_rebates:.4f})"
        )
