"""
Paper Trading Exchange Simulator.

Implements BaseExchange interface but executes trades virtually.
Useful for:
- Strategy development and testing
- Risk-free experimentation
- Backtesting with live-like execution

Features:
- Simulated order matching with instant fills
- Position tracking with weighted average entry price
- Realized and unrealized P&L calculation
- Trade history logging to JSONL file
- Configurable initial balance and slippage
- reset() method for backtesting iterations
- set_price() method for external price updates
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from .base import (
    Balance,
    BaseExchange,
    InsufficientBalanceError,
    Market,
    Order,
    OrderError,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
)

logger = logging.getLogger(__name__)


class PaperExchange(BaseExchange):
    """
    Paper trading exchange simulator.

    Simulates order execution without real funds. Orders fill instantly
    at the current price (or specified limit price). Tracks positions
    and calculates P&L in real-time.

    Attributes:
        initial_balance: Starting balance for paper trading.
        balance: Current available balance.
        realized_pnl: Total realized profit/loss.
        positions: Dictionary of open positions by symbol.
        orders: Dictionary of all orders by order_id.
        trade_history: List of all executed trades.
        current_prices: Dictionary of current prices by symbol.
        slippage_bps: Slippage in basis points (100 bps = 1%).
        log_trades: Whether to log trades to file.
        log_path: Path to trade log file.
    """

    def __init__(
        self,
        initial_balance: Decimal = Decimal("10000"),
        slippage_bps: Decimal = Decimal("0"),
        log_trades: bool = True,
        log_path: str = "data/paper_trades.jsonl",
        testnet: bool = True,
        mock_mode: bool = True,
    ) -> None:
        """
        Initialize paper trading exchange.

        Args:
            initial_balance: Starting balance (default 10,000).
            slippage_bps: Slippage in basis points (default 0).
            log_trades: Whether to log trades to JSONL file.
            log_path: Path to trade log file.
            testnet: Ignored for paper trading (always simulated).
            mock_mode: Ignored for paper trading (always mock).
        """
        super().__init__(testnet=True, mock_mode=True)
        self._name = "paper"

        # Balance tracking
        self.initial_balance = Decimal(str(initial_balance))
        self.balance = self.initial_balance
        self.realized_pnl = Decimal("0")

        # Position tracking: symbol -> Position
        self.positions: dict[str, Position] = {}

        # Order tracking: order_id -> Order
        self.orders: dict[str, Order] = {}

        # Trade history for analysis
        self.trade_history: list[dict[str, Any]] = []

        # Current prices for P&L calculation
        self.current_prices: dict[str, Decimal] = {}

        # Configuration
        self.slippage_bps = Decimal(str(slippage_bps))
        self.log_trades = log_trades
        self.log_path = Path(log_path)

        # Default markets
        self._markets: list[Market] = [
            Market(
                symbol="BTC-PERP",
                base_currency="BTC",
                quote_currency="USD",
                min_quantity=Decimal("0.001"),
                max_quantity=Decimal("1000"),
                quantity_precision=3,
                price_precision=2,
                tick_size=Decimal("0.01"),
                lot_size=Decimal("0.001"),
                max_leverage=50,
            ),
            Market(
                symbol="ETH-PERP",
                base_currency="ETH",
                quote_currency="USD",
                min_quantity=Decimal("0.01"),
                max_quantity=Decimal("10000"),
                quantity_precision=2,
                price_precision=2,
                tick_size=Decimal("0.01"),
                lot_size=Decimal("0.01"),
                max_leverage=50,
            ),
            Market(
                symbol="SOL-PERP",
                base_currency="SOL",
                quote_currency="USD",
                min_quantity=Decimal("0.1"),
                max_quantity=Decimal("100000"),
                quantity_precision=1,
                price_precision=3,
                tick_size=Decimal("0.001"),
                lot_size=Decimal("0.1"),
                max_leverage=20,
            ),
        ]

    # =========================================================================
    # BaseExchange Abstract Method Implementations
    # =========================================================================

    async def connect(self) -> None:
        """Simulate connection to exchange."""
        self.is_connected = True
        self._log_event("CONNECTED", {"initial_balance": str(self.initial_balance)})
        logger.info(f"Paper exchange connected with balance: {self.initial_balance}")

    async def disconnect(self) -> None:
        """Simulate disconnection from exchange."""
        self.is_connected = False
        summary = self.get_pnl_summary()
        self._log_event("DISCONNECTED", summary)
        logger.info(f"Paper exchange disconnected. Final P&L: {summary['total_pnl']}")

    async def get_markets(self) -> list[Market]:
        """Return available markets."""
        return self._markets

    async def get_market(self, symbol: str) -> Optional[Market]:
        """Get a specific market by symbol."""
        for market in self._markets:
            if market.symbol == symbol:
                return market
        return None

    async def get_balance(self, currency: Optional[str] = None) -> list[Balance]:
        """
        Get account balance.

        Returns balance including unrealized P&L from open positions.
        """
        unrealized = self._calculate_total_unrealized_pnl()
        in_positions = sum(
            pos.quantity * pos.entry_price for pos in self.positions.values()
        )

        balance = Balance(
            currency="USD",
            total=self.balance + unrealized,
            available=self.balance,
            locked=Decimal("0"),
            unrealized_pnl=unrealized,
        )

        if currency and currency != "USD":
            return []
        return [balance]

    async def get_positions(self, symbol: Optional[str] = None) -> list[Position]:
        """
        Get open positions with updated unrealized P&L.

        Args:
            symbol: Optional filter by symbol.

        Returns:
            List of open positions.
        """
        # Update unrealized P&L for all positions
        for sym, pos in self.positions.items():
            if sym in self.current_prices:
                current_price = self.current_prices[sym]
                pos.mark_price = current_price
                if pos.is_long:
                    pos.unrealized_pnl = (current_price - pos.entry_price) * pos.quantity
                else:
                    pos.unrealized_pnl = (pos.entry_price - current_price) * pos.quantity
                pos.updated_at = datetime.now(timezone.utc)

        if symbol:
            if symbol in self.positions:
                return [self.positions[symbol]]
            return []

        return list(self.positions.values())

    async def place_order(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        reduce_only: bool = False,
        client_order_id: Optional[str] = None,
        time_in_force: str = "GTC",
        stop_price: Optional[Decimal] = None,
    ) -> Order:
        """
        Place and immediately fill a simulated order.

        For paper trading, market orders fill instantly at current price
        (with optional slippage). Limit orders also fill instantly at
        the specified price.

        Args:
            symbol: Trading symbol.
            side: Buy or sell.
            order_type: Market or limit.
            quantity: Order quantity.
            price: Limit price (required for limit orders).
            reduce_only: Only reduce existing position.
            client_order_id: Optional client order ID.
            time_in_force: Time in force (ignored for paper).
            stop_price: Stop price (ignored for paper).

        Returns:
            Filled Order object.

        Raises:
            OrderError: If order is invalid.
            InsufficientBalanceError: If balance is insufficient.
        """
        quantity = Decimal(str(quantity))

        # Validate order
        if quantity <= 0:
            raise OrderError("Order quantity must be positive")

        if order_type == OrderType.LIMIT and price is None:
            raise OrderError("Limit orders require a price")

        # Determine fill price
        fill_price = self._determine_fill_price(symbol, side, order_type, price)

        # Check balance for opening/increasing position
        # For perpetual futures, we use margin (leverage). Default to 10x leverage.
        # This means we only need 10% of notional as margin.
        leverage = Decimal("10")
        required_margin = (quantity * fill_price) / leverage
        if not reduce_only:
            # Check if this increases position or opens new one
            existing_pos = self.positions.get(symbol)
            if existing_pos is None or (
                (side == OrderSide.BUY and existing_pos.is_long)
                or (side == OrderSide.SELL and existing_pos.is_short)
            ):
                if self.balance < required_margin:
                    raise InsufficientBalanceError(
                        f"Insufficient balance: {self.balance} < {required_margin}"
                    )

        # Generate order ID
        order_id = str(uuid.uuid4())[:8]

        # Create order
        now = datetime.now(timezone.utc)
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=fill_price,
            status=OrderStatus.FILLED,
            filled_quantity=quantity,
            average_fill_price=fill_price,
            created_at=now,
            updated_at=now,
            client_order_id=client_order_id,
            reduce_only=reduce_only,
            time_in_force=time_in_force,
        )

        # Update position
        self._update_position(symbol, side, quantity, fill_price)

        # Store order
        self.orders[order_id] = order

        # Log trade
        self._log_trade(order)

        logger.info(
            f"Paper order filled: {side.value} {quantity} {symbol} @ {fill_price}"
        )

        return order

    async def cancel_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Order:
        """
        Cancel an order.

        Since paper orders fill instantly, this is rarely used.
        Provided for interface compatibility.
        """
        if order_id not in self.orders:
            raise OrderError(f"Order not found: {order_id}")

        order = self.orders[order_id]
        if order.status == OrderStatus.FILLED:
            raise OrderError("Cannot cancel filled order")

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.now(timezone.utc)

        return order

    async def get_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Optional[Order]:
        """Get order by ID."""
        return self.orders.get(order_id)

    async def get_open_orders(
        self,
        symbol: Optional[str] = None,
    ) -> list[Order]:
        """
        Get open orders.

        Since paper orders fill instantly, this usually returns empty.
        """
        open_orders = [o for o in self.orders.values() if o.is_open]
        if symbol:
            open_orders = [o for o in open_orders if o.symbol == symbol]
        return open_orders

    # =========================================================================
    # Paper Trading Specific Methods
    # =========================================================================

    def set_price(self, symbol: str, price: Decimal | float | str) -> None:
        """
        Set current price for a symbol.

        Used to update prices for P&L calculation.

        Args:
            symbol: Trading symbol.
            price: Current price.
        """
        self.current_prices[symbol] = Decimal(str(price))

        # Update position P&L if exists
        if symbol in self.positions:
            pos = self.positions[symbol]
            pos.mark_price = self.current_prices[symbol]
            if pos.is_long:
                pos.unrealized_pnl = (
                    self.current_prices[symbol] - pos.entry_price
                ) * pos.quantity
            else:
                pos.unrealized_pnl = (
                    pos.entry_price - self.current_prices[symbol]
                ) * pos.quantity

    def get_trade_history(self) -> list[dict[str, Any]]:
        """Get complete trade history."""
        return self.trade_history.copy()

    def get_pnl_summary(self) -> dict[str, Any]:
        """
        Get comprehensive P&L summary.

        Returns:
            Dictionary with P&L breakdown.
        """
        unrealized = self._calculate_total_unrealized_pnl()
        return {
            "initial_balance": str(self.initial_balance),
            "current_balance": str(self.balance),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(unrealized),
            "total_pnl": str(self.realized_pnl + unrealized),
            "total_trades": len(self.trade_history),
            "open_positions": len(self.positions),
            "return_pct": str(
                ((self.balance + unrealized) / self.initial_balance - 1) * 100
            ),
        }

    def reset(self) -> None:
        """
        Reset exchange to initial state.

        Useful for backtesting iterations.
        """
        self.balance = self.initial_balance
        self.realized_pnl = Decimal("0")
        self.positions.clear()
        self.orders.clear()
        self.trade_history.clear()
        self.current_prices.clear()
        self.is_connected = False

        logger.info("Paper exchange reset to initial state")

    def add_market(self, market: Market) -> None:
        """
        Add a custom market.

        Args:
            market: Market to add.
        """
        # Remove existing market with same symbol
        self._markets = [m for m in self._markets if m.symbol != market.symbol]
        self._markets.append(market)

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _determine_fill_price(
        self,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        price: Optional[Decimal],
    ) -> Decimal:
        """
        Determine the fill price for an order.

        For market orders, uses current price with slippage.
        For limit orders, uses the specified price.
        """
        if order_type == OrderType.LIMIT and price is not None:
            return Decimal(str(price))

        # Market order - use current price
        if symbol not in self.current_prices:
            if price is not None:
                # Use provided price as reference
                self.current_prices[symbol] = Decimal(str(price))
            else:
                # Default price for testing
                self.current_prices[symbol] = Decimal("100")

        base_price = self.current_prices[symbol]

        # Apply slippage
        if self.slippage_bps > 0:
            slippage = base_price * self.slippage_bps / Decimal("10000")
            if side == OrderSide.BUY:
                return base_price + slippage
            else:
                return base_price - slippage

        return base_price

    def _update_position(
        self,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        fill_price: Decimal,
    ) -> None:
        """
        Update position after a trade.

        Handles:
        - Opening new positions
        - Adding to existing positions (weighted average entry)
        - Reducing positions (realizes P&L)
        - Flipping positions (close then open opposite)
        """
        # Convert side to position change (positive = long, negative = short)
        size_change = quantity if side == OrderSide.BUY else -quantity

        if symbol not in self.positions:
            # New position
            if size_change != 0:
                new_side = PositionSide.LONG if size_change > 0 else PositionSide.SHORT
                self.positions[symbol] = Position(
                    symbol=symbol,
                    side=new_side,
                    quantity=abs(size_change),
                    entry_price=fill_price,
                    mark_price=fill_price,
                    unrealized_pnl=Decimal("0"),
                )
            return

        pos = self.positions[symbol]
        current_size = pos.quantity if pos.is_long else -pos.quantity
        new_size = current_size + size_change

        # Same direction - increase position with weighted average
        if (current_size > 0 and size_change > 0) or (
            current_size < 0 and size_change < 0
        ):
            # Weighted average entry price
            total_cost = abs(current_size) * pos.entry_price + abs(
                size_change
            ) * fill_price
            pos.entry_price = total_cost / abs(new_size)
            pos.quantity = abs(new_size)
            pos.updated_at = datetime.now(timezone.utc)
            return

        # Opposite direction - reduce or flip position
        close_size = min(abs(current_size), abs(size_change))

        # Calculate realized P&L for the closing portion
        if pos.is_long:
            pnl = (fill_price - pos.entry_price) * close_size
        else:
            pnl = (pos.entry_price - fill_price) * close_size

        self.realized_pnl += pnl
        self.balance += pnl

        logger.debug(f"Realized P&L for {symbol}: {pnl}")

        # Update or remove position
        if abs(new_size) < Decimal("0.0000001"):
            # Position fully closed
            del self.positions[symbol]
        else:
            # Position reduced or flipped
            new_side = PositionSide.LONG if new_size > 0 else PositionSide.SHORT

            if (pos.is_long and new_size > 0) or (pos.is_short and new_size < 0):
                # Same side, just reduced
                pos.quantity = abs(new_size)
            else:
                # Flipped to opposite side - new entry price
                pos.side = new_side
                pos.quantity = abs(new_size)
                pos.entry_price = fill_price

            pos.updated_at = datetime.now(timezone.utc)

    def _calculate_total_unrealized_pnl(self) -> Decimal:
        """Calculate total unrealized P&L across all positions."""
        total = Decimal("0")
        for symbol, pos in self.positions.items():
            if symbol in self.current_prices:
                current = self.current_prices[symbol]
                if pos.is_long:
                    total += (current - pos.entry_price) * pos.quantity
                else:
                    total += (pos.entry_price - current) * pos.quantity
        return total

    def _log_trade(self, order: Order) -> None:
        """Log a trade to history and optionally to file."""
        trade = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "quantity": str(order.quantity),
            "price": str(order.average_fill_price),
            "balance_after": str(self.balance),
            "realized_pnl": str(self.realized_pnl),
        }
        self.trade_history.append(trade)

        if self.log_trades:
            self._write_to_log(trade)

    def _log_event(self, event: str, data: dict[str, Any]) -> None:
        """Log an event to file."""
        if self.log_trades:
            entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": event,
                **data,
            }
            self._write_to_log(entry)

    def _write_to_log(self, data: dict[str, Any]) -> None:
        """Write data to log file."""
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a") as f:
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.warning(f"Failed to write to trade log: {e}")
