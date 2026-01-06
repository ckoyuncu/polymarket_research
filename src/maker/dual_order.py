"""
Dual Order Executor for Delta-Neutral Maker Strategy.

This module implements synchronized YES and NO order placement to maintain
delta-neutral exposure while earning maker rebates on Polymarket.

Key Features:
- Atomic placement of mirror YES and NO limit orders
- Automatic orphan cancellation if one side fails
- Balance verification before placing orders
- Fill verification after placement
- Kill switch integration
- Position size limits

Example:
    >>> from py_clob_client.client import ClobClient
    >>> from src.maker.dual_order import DualOrderExecutor
    >>>
    >>> clob = ClobClient(...)
    >>> executor = DualOrderExecutor(clob)
    >>>
    >>> # Place delta-neutral order pair
    >>> yes_order, no_order = await executor.place_delta_neutral(
    ...     market="btc-updown-15m-1767729600",
    ...     yes_token_id="0x123...",
    ...     no_token_id="0x456...",
    ...     size=50.0,
    ...     yes_price=0.495,
    ...     no_price=0.495
    ... )
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# Kill switch file location
KILL_SWITCH_FILE = Path(".kill_switch")

# Default position limits
DEFAULT_MAX_POSITION_SIZE = Decimal("100")
DEFAULT_MAX_CONCURRENT_POSITIONS = 3
DEFAULT_MIN_TIME_TO_RESOLUTION = 60  # seconds


@dataclass
class OrderResult:
    """Result of an individual order placement."""

    success: bool
    order_id: Optional[str] = None
    filled: bool = False
    filled_size: Decimal = Decimal("0")
    filled_price: Decimal = Decimal("0")
    error_message: str = ""
    raw_response: dict = None

    def __post_init__(self):
        if self.raw_response is None:
            self.raw_response = {}


@dataclass
class DualOrderResult:
    """Result of synchronized dual order placement."""

    success: bool
    yes_order: Optional[OrderResult] = None
    no_order: Optional[OrderResult] = None
    delta: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    error_message: str = ""

    @property
    def is_delta_neutral(self) -> bool:
        """Check if the position is delta-neutral (within tolerance)."""
        return abs(self.delta) < Decimal("0.01")

    @property
    def both_filled(self) -> bool:
        """Check if both orders were filled."""
        return (
            self.yes_order is not None
            and self.no_order is not None
            and self.yes_order.filled
            and self.no_order.filled
        )


class DualOrderError(Exception):
    """Raised when dual order placement fails."""

    pass


class InsufficientBalanceError(DualOrderError):
    """Raised when balance is insufficient for dual order."""

    pass


class KillSwitchError(DualOrderError):
    """Raised when kill switch is active."""

    pass


class DualOrderExecutor:
    """
    Executor for placing synchronized YES and NO orders.

    This class handles the complexity of placing delta-neutral positions by
    ensuring both YES and NO orders are placed together, or neither is placed.

    Attributes:
        clob_client: py-clob-client instance for order placement
        balance_checker: Balance checker for pre-order validation (optional)
        max_position_size: Maximum size per position pair
        max_concurrent_positions: Maximum number of open position pairs
        min_time_to_resolution: Minimum seconds before market resolution

    Safety Features:
        - Pre-order balance checks
        - Kill switch monitoring
        - Orphan order cancellation
        - Fill verification
        - Delta validation
    """

    def __init__(
        self,
        clob_client,
        balance_checker=None,
        max_position_size: Decimal = DEFAULT_MAX_POSITION_SIZE,
        max_concurrent_positions: int = DEFAULT_MAX_CONCURRENT_POSITIONS,
        min_time_to_resolution: int = DEFAULT_MIN_TIME_TO_RESOLUTION,
    ):
        """
        Initialize the dual order executor.

        Args:
            clob_client: py-clob-client instance for API calls
            balance_checker: Optional balance checker for pre-order validation
            max_position_size: Maximum size per position (default $100)
            max_concurrent_positions: Maximum concurrent positions (default 3)
            min_time_to_resolution: Minimum time before resolution (default 60s)
        """
        self.clob = clob_client
        self.balance_checker = balance_checker
        self.max_position_size = Decimal(str(max_position_size))
        self.max_concurrent_positions = max_concurrent_positions
        self.min_time_to_resolution = min_time_to_resolution

        # Track open positions
        self.open_positions: dict[str, DualOrderResult] = {}

        logger.info(
            f"DualOrderExecutor initialized: max_size={max_position_size}, "
            f"max_concurrent={max_concurrent_positions}"
        )

    def _check_kill_switch(self) -> None:
        """
        Check if kill switch is active.

        Raises:
            KillSwitchError: If kill switch file exists
        """
        if KILL_SWITCH_FILE.exists():
            raise KillSwitchError("Kill switch activated - trading halted")

    def _validate_prices(self, yes_price: Decimal, no_price: Decimal) -> None:
        """
        Validate that prices are suitable for delta-neutral position.

        Args:
            yes_price: Price for YES position
            no_price: Price for NO position

        Raises:
            DualOrderError: If prices are invalid
        """
        # Check price bounds
        if not (Decimal("0.01") <= yes_price <= Decimal("0.99")):
            raise DualOrderError(f"YES price {yes_price} must be between 0.01 and 0.99")

        if not (Decimal("0.01") <= no_price <= Decimal("0.99")):
            raise DualOrderError(f"NO price {no_price} must be between 0.01 and 0.99")

        # Check delta-neutral constraint: yes_price + no_price should be <= 1
        total_price = yes_price + no_price
        if total_price > Decimal("1.0"):
            raise DualOrderError(
                f"Price sum {total_price} > 1.0. This guarantees a loss. "
                f"YES={yes_price}, NO={no_price}"
            )

        # Warn if spread is too tight (potential for slippage issues)
        if total_price > Decimal("0.99"):
            logger.warning(
                f"Very tight spread: YES={yes_price} + NO={no_price} = {total_price}. "
                f"Consider wider spread for maker orders."
            )

    def _check_balance(self, required_amount: Decimal) -> None:
        """
        Check if sufficient balance is available.

        Args:
            required_amount: Required balance in USDC

        Raises:
            InsufficientBalanceError: If balance is insufficient
        """
        if self.balance_checker is None:
            logger.warning("No balance checker configured - skipping balance check")
            return

        # Get funder address from clob client
        funder_address = getattr(self.clob, "funder", None)
        if not funder_address:
            logger.warning("No funder address found - skipping balance check")
            return

        # Check balance
        if not self.balance_checker.has_sufficient_balance(funder_address, float(required_amount)):
            balance = self.balance_checker.get_balance(funder_address)
            available = balance.available if balance else 0.0
            raise InsufficientBalanceError(
                f"Insufficient balance: need ${required_amount:.2f}, "
                f"have ${available:.2f}"
            )

    async def place_delta_neutral(
        self,
        market: str,
        yes_token_id: str,
        no_token_id: str,
        size: float,
        yes_price: float,
        no_price: float,
    ) -> DualOrderResult:
        """
        Place synchronized YES and NO limit orders for delta-neutral position.

        This method:
        1. Validates inputs and checks safety constraints
        2. Places YES order
        3. Places NO order
        4. If either fails, cancels the successful one
        5. Verifies both fills
        6. Returns result

        Args:
            market: Market identifier (e.g., "btc-updown-15m-1767729600")
            yes_token_id: Token ID for YES outcome
            no_token_id: Token ID for NO outcome
            size: Position size in shares (same for both sides)
            yes_price: Limit price for YES order (0-1)
            no_price: Limit price for NO order (0-1)

        Returns:
            DualOrderResult with status and order details

        Raises:
            KillSwitchError: If kill switch is active
            DualOrderError: If validation fails or orders cannot be placed
            InsufficientBalanceError: If balance is insufficient
        """
        # Convert to Decimal for precision
        size_decimal = Decimal(str(size))
        yes_price_decimal = Decimal(str(yes_price))
        no_price_decimal = Decimal(str(no_price))

        try:
            # Safety checks
            self._check_kill_switch()
            self._validate_prices(yes_price_decimal, no_price_decimal)

            # Check position size limit
            if size_decimal > self.max_position_size:
                raise DualOrderError(
                    f"Size {size_decimal} exceeds max position size {self.max_position_size}"
                )

            # Check concurrent positions limit
            if len(self.open_positions) >= self.max_concurrent_positions:
                raise DualOrderError(
                    f"Max concurrent positions ({self.max_concurrent_positions}) reached"
                )

            # Calculate total cost
            yes_cost = size_decimal * yes_price_decimal
            no_cost = size_decimal * no_price_decimal
            total_cost = yes_cost + no_cost

            # Check balance
            self._check_balance(total_cost)

            logger.info(
                f"Placing delta-neutral order on {market}: "
                f"size={size}, YES@{yes_price}, NO@{no_price}, cost=${total_cost:.2f}"
            )

            # Place YES order first
            yes_result = await self._place_order(
                token_id=yes_token_id, side="BUY", size=size, price=yes_price
            )

            if not yes_result.success:
                return DualOrderResult(
                    success=False,
                    yes_order=yes_result,
                    error_message=f"YES order failed: {yes_result.error_message}",
                )

            # Place NO order
            no_result = await self._place_order(
                token_id=no_token_id, side="BUY", size=size, price=no_price
            )

            if not no_result.success:
                # NO order failed - cancel YES order
                logger.warning(
                    f"NO order failed, cancelling orphan YES order {yes_result.order_id}"
                )
                await self.cancel_orphan(yes_result.order_id)

                return DualOrderResult(
                    success=False,
                    yes_order=yes_result,
                    no_order=no_result,
                    error_message=f"NO order failed: {no_result.error_message}. "
                    f"YES order cancelled.",
                )

            # Both orders placed - verify fills
            fills_verified = await self.verify_fills(yes_result, no_result)

            if not fills_verified:
                # Fill verification failed - cancel both
                logger.warning("Fill verification failed - cancelling both orders")
                await self.cancel_orphan(yes_result.order_id)
                await self.cancel_orphan(no_result.order_id)

                return DualOrderResult(
                    success=False,
                    yes_order=yes_result,
                    no_order=no_result,
                    error_message="Fill verification failed. Both orders cancelled.",
                )

            # Calculate delta (should be ~0 for delta-neutral)
            delta = yes_result.filled_size - no_result.filled_size

            # Success!
            result = DualOrderResult(
                success=True,
                yes_order=yes_result,
                no_order=no_result,
                delta=delta,
                total_cost=total_cost,
            )

            # Track position
            position_id = f"{market}_{yes_result.order_id}"
            self.open_positions[position_id] = result

            logger.info(
                f"Delta-neutral position opened: "
                f"YES={yes_result.filled_size}@{yes_result.filled_price}, "
                f"NO={no_result.filled_size}@{no_result.filled_price}, "
                f"delta={delta}"
            )

            return result

        except Exception as e:
            logger.error(f"Failed to place delta-neutral order: {e}", exc_info=True)
            return DualOrderResult(success=False, error_message=str(e))

    async def _place_order(
        self, token_id: str, side: str, size: float, price: float
    ) -> OrderResult:
        """
        Place a single limit order via CLOB client.

        Args:
            token_id: Token ID to trade
            side: "BUY" or "SELL"
            size: Order size
            price: Limit price

        Returns:
            OrderResult with placement status
        """
        try:
            from py_clob_client.order_builder.constants import BUY, SELL
            from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

            # Map side
            order_side = BUY if side.upper() == "BUY" else SELL

            # Create order args
            order_args = OrderArgs(
                token_id=token_id, price=price, size=size, side=order_side
            )

            # Create options with tick size
            options = PartialCreateOrderOptions(tick_size="0.01")

            # Place order
            response = self.clob.create_and_post_order(order_args, options)

            if response:
                order_id = response.get("orderID") or response.get("id")
                if not order_id:
                    order_id = str(int(time.time() * 1000))

                # Extract fill info
                status = response.get("status", "OPEN")
                filled = status in ("FILLED", "MATCHED")
                filled_size = Decimal(str(response.get("size", size)))
                filled_price = Decimal(str(response.get("price", price)))

                return OrderResult(
                    success=True,
                    order_id=order_id,
                    filled=filled,
                    filled_size=filled_size,
                    filled_price=filled_price,
                    raw_response=response,
                )
            else:
                return OrderResult(
                    success=False, error_message="Empty response from CLOB API"
                )

        except Exception as e:
            logger.error(f"Order placement failed: {e}", exc_info=True)
            return OrderResult(success=False, error_message=str(e))

    async def cancel_orphan(self, order_id: str) -> bool:
        """
        Cancel an orphaned order (one whose pair failed).

        Args:
            order_id: Order ID to cancel

        Returns:
            True if cancellation succeeded, False otherwise
        """
        try:
            logger.info(f"Cancelling orphan order {order_id}")
            result = self.clob.cancel(order_id)
            logger.info(f"Successfully cancelled order {order_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cancel orphan order {order_id}: {e}")
            return False

    async def verify_fills(
        self, yes_order: OrderResult, no_order: OrderResult, max_retries: int = 3
    ) -> bool:
        """
        Verify that both orders were filled correctly.

        This method queries the CLOB API to confirm fill status.
        For maker orders, fills may not be immediate, so we retry.

        Args:
            yes_order: YES order result
            no_order: NO order result
            max_retries: Maximum number of verification attempts

        Returns:
            True if both orders are filled, False otherwise
        """
        if not yes_order.order_id or not no_order.order_id:
            logger.warning("Cannot verify fills - missing order IDs")
            return False

        for attempt in range(max_retries):
            try:
                # Query YES order status
                yes_status = self.clob.get_order(yes_order.order_id)
                no_status = self.clob.get_order(no_order.order_id)

                # Check if both are filled
                yes_filled = (
                    yes_status and yes_status.get("status") in ("FILLED", "MATCHED")
                )
                no_filled = (
                    no_status and no_status.get("status") in ("FILLED", "MATCHED")
                )

                if yes_filled and no_filled:
                    logger.info("Both orders filled successfully")

                    # Update filled info
                    yes_order.filled = True
                    no_order.filled = True

                    return True

                # If not filled yet, wait before retry
                if attempt < max_retries - 1:
                    logger.debug(
                        f"Orders not filled yet (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in 1s..."
                    )
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Fill verification attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)

        logger.warning(f"Fill verification failed after {max_retries} attempts")
        return False

    def get_open_positions(self) -> list[DualOrderResult]:
        """Get all open delta-neutral positions."""
        return list(self.open_positions.values())

    def get_total_delta(self) -> Decimal:
        """
        Calculate total delta across all open positions.

        For a fully delta-neutral portfolio, this should be near zero.

        Returns:
            Total delta exposure
        """
        return sum(pos.delta for pos in self.open_positions.values())

    def close_position(self, position_id: str) -> None:
        """
        Mark a position as closed.

        Args:
            position_id: Position identifier
        """
        if position_id in self.open_positions:
            del self.open_positions[position_id]
            logger.info(f"Position {position_id} marked as closed")

    def get_position_count(self) -> int:
        """Get number of open positions."""
        return len(self.open_positions)
