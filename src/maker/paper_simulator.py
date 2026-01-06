"""
Delta-Neutral Paper Trading Simulator for Maker Rebates Strategy.

This simulator implements a delta-neutral strategy where mirror YES and NO positions
are placed on the same market. The strategy aims to:
- Break even on market outcome (YES @ p + NO @ (1-p) = 1)
- Earn maker rebates when orders are filled as liquidity provider
- Maintain zero directional risk (delta-neutral)

Example:
    >>> simulator = MakerPaperSimulator(initial_balance=300.0)
    >>> simulator.place_delta_neutral("market-123", size=50, yes_price=0.50, no_price=0.50)
    >>> simulator.simulate_resolution("market-123", outcome="YES")
    >>> print(simulator.get_stats())

Note:
    Polymarket maker rebates are earned when providing liquidity (limit orders that
    rest on the book). This simulator estimates rebates based on typical rebate rates.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Default configuration values (can be overridden)
DEFAULT_MAKER_POSITION_SIZE = Decimal("50")
DEFAULT_MAKER_MAX_CONCURRENT = 3
DEFAULT_MAX_POSITION_SIZE = Decimal("100")
DEFAULT_MAX_DAILY_LOSS = Decimal("30")
DEFAULT_MAKER_REBATE_RATE = Decimal("0.001")  # 0.1% maker rebate estimate


def _utc_now() -> datetime:
    """Get current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


@dataclass
class DeltaNeutralPosition:
    """
    Represents a delta-neutral position pair (YES + NO on same market).

    Attributes:
        position_id: Unique identifier for this position pair.
        market_id: The market this position is in.
        yes_size: Size of the YES position.
        yes_price: Price paid for YES position (0-1).
        no_size: Size of the NO position.
        no_price: Price paid for NO position (0-1).
        total_cost: Total cost to open both positions.
        rebates_earned: Estimated maker rebates earned on this position.
        created_at: When the position was opened.
        resolved: Whether the market has been resolved.
        resolution_outcome: The outcome when resolved (YES or NO).
        pnl: Profit/loss after resolution (excluding rebates).
    """

    position_id: str
    market_id: str
    yes_size: Decimal
    yes_price: Decimal
    no_size: Decimal
    no_price: Decimal
    total_cost: Decimal
    rebates_earned: Decimal = Decimal("0")
    created_at: datetime = field(default_factory=_utc_now)
    resolved: bool = False
    resolution_outcome: Optional[str] = None
    pnl: Decimal = Decimal("0")

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
        """Check if position is delta-neutral (within tolerance)."""
        return abs(self.delta) < Decimal("0.01")

    @property
    def implied_fair_price(self) -> Decimal:
        """
        Calculate the implied fair price based on position prices.

        For delta-neutral: yes_price + no_price should equal 1.
        If < 1, there's a theoretical arbitrage opportunity.
        """
        return self.yes_price + self.no_price


class DeltaNeutralError(Exception):
    """Raised when delta-neutral constraints are violated."""

    pass


class InsufficientBalanceError(Exception):
    """Raised when balance is insufficient for operation."""

    pass


class MakerPaperSimulator:
    """
    Delta-neutral paper trading simulator for maker rebates strategy.

    This simulator allows testing of a market-making strategy that places
    synchronized YES and NO orders to maintain delta-neutral exposure while
    earning maker rebates.

    Attributes:
        initial_balance: Starting balance for paper trading.
        balance: Current available balance.
        positions: List of delta-neutral position pairs.
        trades: History of all trades executed.
        rebates_earned: Total maker rebates earned.
        realized_pnl: Total realized P&L from resolutions.
        max_position_size: Maximum size per position.
        max_concurrent_positions: Maximum number of open positions.
        max_daily_loss: Maximum allowed daily loss (kill switch).
        maker_rebate_rate: Estimated maker rebate rate.

    Example:
        >>> sim = MakerPaperSimulator(initial_balance=300.0)
        >>> sim.place_delta_neutral("market-1", 50, 0.50, 0.50)
        >>> print(f"Balance: {sim.balance}, Delta: {sim.get_delta()}")
    """

    def __init__(
        self,
        initial_balance: float = 300.0,
        max_position_size: float = 100.0,
        max_concurrent_positions: int = 3,
        max_daily_loss: float = 30.0,
        maker_rebate_rate: float = 0.001,
        log_trades: bool = True,
        log_path: str = "data/maker_paper_trades.jsonl",
    ) -> None:
        """
        Initialize the maker paper simulator.

        Args:
            initial_balance: Starting balance (default $300).
            max_position_size: Maximum size per position (default $100).
            max_concurrent_positions: Maximum concurrent positions (default 3).
            max_daily_loss: Daily loss limit for kill switch (default $30).
            maker_rebate_rate: Estimated maker rebate rate (default 0.1%).
            log_trades: Whether to log trades to file.
            log_path: Path to trade log file.
        """
        # Balance tracking
        self.initial_balance = Decimal(str(initial_balance))
        self.balance = self.initial_balance
        self.realized_pnl = Decimal("0")
        self.rebates_earned = Decimal("0")

        # Position tracking
        self.positions: list[DeltaNeutralPosition] = []
        self.trades: list[dict[str, Any]] = []

        # Configuration
        self.max_position_size = Decimal(str(max_position_size))
        self.max_concurrent_positions = max_concurrent_positions
        self.max_daily_loss = Decimal(str(max_daily_loss))
        self.maker_rebate_rate = Decimal(str(maker_rebate_rate))

        # Daily tracking for kill switch
        self._daily_loss = Decimal("0")
        self._daily_reset_date: Optional[datetime] = None

        # Logging
        self.log_trades = log_trades
        self.log_path = Path(log_path)

        logger.info(
            f"MakerPaperSimulator initialized with balance={initial_balance}, "
            f"max_position={max_position_size}, max_concurrent={max_concurrent_positions}"
        )

    def place_delta_neutral(
        self,
        market_id: str,
        size: float,
        yes_price: float,
        no_price: float,
    ) -> DeltaNeutralPosition:
        """
        Place synchronized YES and NO orders for delta-neutral position.

        This method places equal-sized YES and NO positions at the given prices.
        The total cost is: size * yes_price + size * no_price.

        For delta-neutral: yes_price + no_price should be <= 1 to avoid
        guaranteed loss. If yes_price + no_price < 1, there's a theoretical
        profit opportunity at resolution.

        Args:
            market_id: The market identifier.
            size: Position size for both YES and NO (in contracts/shares).
            yes_price: Price for YES position (0-1).
            no_price: Price for NO position (0-1).

        Returns:
            The created DeltaNeutralPosition.

        Raises:
            DeltaNeutralError: If prices are invalid or constraints violated.
            InsufficientBalanceError: If balance is insufficient.
        """
        size_decimal = Decimal(str(size))
        yes_price_decimal = Decimal(str(yes_price))
        no_price_decimal = Decimal(str(no_price))

        # Validate prices
        if not (Decimal("0") < yes_price_decimal < Decimal("1")):
            raise DeltaNeutralError(f"YES price must be between 0 and 1, got {yes_price}")

        if not (Decimal("0") < no_price_decimal < Decimal("1")):
            raise DeltaNeutralError(f"NO price must be between 0 and 1, got {no_price}")

        # Check delta-neutral constraint: yes_price + no_price <= 1
        total_price = yes_price_decimal + no_price_decimal
        if total_price > Decimal("1"):
            raise DeltaNeutralError(
                f"Delta-neutral violation: yes_price + no_price = {total_price} > 1. "
                f"This guarantees a loss on resolution."
            )

        # Validate size
        if size_decimal <= Decimal("0"):
            raise DeltaNeutralError(f"Size must be positive, got {size}")

        if size_decimal > self.max_position_size:
            raise DeltaNeutralError(
                f"Size {size} exceeds max position size {self.max_position_size}"
            )

        # Check concurrent positions limit
        open_positions = [p for p in self.positions if not p.resolved]
        if len(open_positions) >= self.max_concurrent_positions:
            raise DeltaNeutralError(
                f"Maximum concurrent positions ({self.max_concurrent_positions}) reached"
            )

        # Calculate total cost
        yes_cost = size_decimal * yes_price_decimal
        no_cost = size_decimal * no_price_decimal
        total_cost = yes_cost + no_cost

        # Check balance
        if total_cost > self.balance:
            raise InsufficientBalanceError(
                f"Insufficient balance: need {total_cost}, have {self.balance}"
            )

        # Check daily loss limit
        self._check_daily_loss_limit()

        # Create position
        position_id = str(uuid.uuid4())[:8]
        position = DeltaNeutralPosition(
            position_id=position_id,
            market_id=market_id,
            yes_size=size_decimal,
            yes_price=yes_price_decimal,
            no_size=size_decimal,
            no_price=no_price_decimal,
            total_cost=total_cost,
        )

        # Deduct cost from balance
        self.balance -= total_cost

        # Estimate and credit maker rebates
        # Rebates are earned on the notional value of maker orders
        estimated_rebates = total_cost * self.maker_rebate_rate
        position.rebates_earned = estimated_rebates
        self.rebates_earned += estimated_rebates
        self.balance += estimated_rebates

        # Store position
        self.positions.append(position)

        # Log trade
        self._log_trade(
            event="OPEN_DELTA_NEUTRAL",
            position_id=position_id,
            market_id=market_id,
            yes_size=str(size_decimal),
            yes_price=str(yes_price_decimal),
            no_size=str(size_decimal),
            no_price=str(no_price_decimal),
            total_cost=str(total_cost),
            rebates=str(estimated_rebates),
            balance_after=str(self.balance),
        )

        logger.info(
            f"Opened delta-neutral position {position_id} on {market_id}: "
            f"YES={size}@{yes_price}, NO={size}@{no_price}, cost={total_cost}, "
            f"rebates={estimated_rebates}"
        )

        return position

    def simulate_resolution(self, market_id: str, outcome: str) -> Decimal:
        """
        Simulate market resolution and calculate P&L.

        When a market resolves:
        - If YES wins: YES positions pay out $1 per share, NO positions pay $0
        - If NO wins: NO positions pay out $1 per share, YES positions pay $0

        For a delta-neutral position with equal YES and NO sizes:
        - Payout = size * 1 (winning side)
        - P&L = Payout - Total Cost = size - (size * yes_price + size * no_price)
        - If yes_price + no_price < 1: P&L = size * (1 - yes_price - no_price) > 0

        Args:
            market_id: The market that resolved.
            outcome: The outcome ("YES" or "NO").

        Returns:
            The P&L from resolution (excluding rebates already credited).

        Raises:
            ValueError: If outcome is invalid or market not found.
        """
        outcome = outcome.upper()
        if outcome not in ("YES", "NO"):
            raise ValueError(f"Outcome must be 'YES' or 'NO', got {outcome}")

        # Find all unresolved positions for this market
        market_positions = [
            p for p in self.positions if p.market_id == market_id and not p.resolved
        ]

        if not market_positions:
            logger.warning(f"No open positions found for market {market_id}")
            return Decimal("0")

        total_pnl = Decimal("0")

        for position in market_positions:
            # Calculate payout based on outcome
            if outcome == "YES":
                # YES side pays out $1 per share, NO side pays $0
                payout = position.yes_size * Decimal("1")
            else:
                # NO side pays out $1 per share, YES side pays $0
                payout = position.no_size * Decimal("1")

            # P&L = Payout - Cost
            position_pnl = payout - position.total_cost
            position.pnl = position_pnl
            position.resolved = True
            position.resolution_outcome = outcome

            # Update balances
            self.balance += payout
            self.realized_pnl += position_pnl
            total_pnl += position_pnl

            # Track daily loss
            if position_pnl < Decimal("0"):
                self._daily_loss += abs(position_pnl)

            # Log resolution
            self._log_trade(
                event="RESOLUTION",
                position_id=position.position_id,
                market_id=market_id,
                outcome=outcome,
                payout=str(payout),
                pnl=str(position_pnl),
                balance_after=str(self.balance),
            )

            logger.info(
                f"Resolved position {position.position_id} on {market_id}: "
                f"outcome={outcome}, payout={payout}, pnl={position_pnl}"
            )

        return total_pnl

    def get_delta(self) -> Decimal:
        """
        Calculate current total delta exposure across all open positions.

        A perfectly delta-neutral portfolio should have delta = 0.

        Returns:
            Total delta: sum of (yes_size - no_size) for all open positions.
        """
        total_delta = Decimal("0")
        for position in self.positions:
            if not position.resolved:
                total_delta += position.delta
        return total_delta

    def get_open_positions(self) -> list[DeltaNeutralPosition]:
        """Get all open (unresolved) positions."""
        return [p for p in self.positions if not p.resolved]

    def get_stats(self) -> dict[str, Any]:
        """
        Return comprehensive trading statistics.

        Returns:
            Dictionary with trading statistics including:
            - Balance info (initial, current, available)
            - P&L breakdown (realized, unrealized, rebates)
            - Position stats (open, closed, delta)
            - Risk metrics (daily loss, remaining capacity)
        """
        open_positions = [p for p in self.positions if not p.resolved]
        closed_positions = [p for p in self.positions if p.resolved]

        # Calculate open position value (locked capital)
        locked_capital = sum(p.total_cost for p in open_positions)

        # Calculate win rate
        if closed_positions:
            wins = sum(1 for p in closed_positions if p.pnl >= Decimal("0"))
            win_rate = wins / len(closed_positions)
        else:
            win_rate = 0.0

        # Total P&L including rebates
        total_pnl = self.realized_pnl + self.rebates_earned

        return {
            # Balance
            "initial_balance": str(self.initial_balance),
            "current_balance": str(self.balance),
            "locked_in_positions": str(locked_capital),
            # P&L
            "realized_pnl": str(self.realized_pnl),
            "rebates_earned": str(self.rebates_earned),
            "total_pnl": str(total_pnl),
            "return_pct": str(
                (total_pnl / self.initial_balance * Decimal("100")).quantize(Decimal("0.01"))
            ),
            # Positions
            "total_trades": len(self.positions),
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "win_rate": f"{win_rate:.1%}",
            # Risk
            "current_delta": str(self.get_delta()),
            "is_delta_neutral": abs(self.get_delta()) < Decimal("0.01"),
            "daily_loss": str(self._daily_loss),
            "daily_loss_remaining": str(self.max_daily_loss - self._daily_loss),
            "positions_remaining": self.max_concurrent_positions - len(open_positions),
        }

    def reset(self) -> None:
        """
        Reset simulator to initial state.

        Useful for running multiple simulations or backtests.
        """
        self.balance = self.initial_balance
        self.realized_pnl = Decimal("0")
        self.rebates_earned = Decimal("0")
        self.positions.clear()
        self.trades.clear()
        self._daily_loss = Decimal("0")
        self._daily_reset_date = None

        logger.info("MakerPaperSimulator reset to initial state")

    def get_trade_history(self) -> list[dict[str, Any]]:
        """Get complete trade history."""
        return self.trades.copy()

    def _check_daily_loss_limit(self) -> None:
        """Check and potentially reset daily loss tracking."""
        now = _utc_now()

        # Reset daily tracking if it's a new day
        if self._daily_reset_date is None or now.date() > self._daily_reset_date.date():
            self._daily_loss = Decimal("0")
            self._daily_reset_date = now

        # Check if we've exceeded daily loss limit
        if self._daily_loss >= self.max_daily_loss:
            raise DeltaNeutralError(
                f"Daily loss limit reached: {self._daily_loss} >= {self.max_daily_loss}. "
                f"Trading suspended until tomorrow."
            )

    def _log_trade(self, event: str, **kwargs: Any) -> None:
        """Log a trade event."""
        trade = {
            "timestamp": _utc_now().isoformat(),
            "event": event,
            **kwargs,
        }
        self.trades.append(trade)

        if self.log_trades:
            try:
                self.log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log_path, "a") as f:
                    f.write(json.dumps(trade) + "\n")
            except Exception as e:
                logger.warning(f"Failed to write to trade log: {e}")
