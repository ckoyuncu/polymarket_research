"""
Abstract base exchange interface for trading operations.

This module defines the core abstractions for exchange interactions including
order types, positions, balances, and the abstract exchange interface that
all concrete exchange implementations must inherit from.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Optional


class OrderSide(Enum):
    """Order side enumeration."""

    BUY = "buy"
    SELL = "sell"

    def __str__(self) -> str:
        return self.value


class OrderType(Enum):
    """Order type enumeration."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"
    TAKE_PROFIT_MARKET = "take_profit_market"
    TAKE_PROFIT_LIMIT = "take_profit_limit"

    def __str__(self) -> str:
        return self.value


class OrderStatus(Enum):
    """Order status enumeration."""

    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"

    def __str__(self) -> str:
        return self.value


class PositionSide(Enum):
    """Position side enumeration for futures."""

    LONG = "long"
    SHORT = "short"

    def __str__(self) -> str:
        return self.value


@dataclass
class Order:
    """
    Represents a trading order.

    Attributes:
        order_id: Unique identifier for the order.
        symbol: Trading pair symbol (e.g., 'BTC-PERP').
        side: Buy or sell side.
        order_type: Type of order (market, limit, etc.).
        quantity: Order quantity in base currency.
        price: Limit price (optional for market orders).
        status: Current order status.
        filled_quantity: Amount filled so far.
        average_fill_price: Average price of fills.
        created_at: Order creation timestamp.
        updated_at: Last update timestamp.
        client_order_id: Optional client-specified order ID.
        reduce_only: Whether this order only reduces position.
        time_in_force: Order time in force (GTC, IOC, FOK).
        stop_price: Stop trigger price (for stop orders).
        raw: Raw exchange response data.
    """

    order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = Decimal("0")
    average_fill_price: Optional[Decimal] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    client_order_id: Optional[str] = None
    reduce_only: bool = False
    time_in_force: str = "GTC"
    stop_price: Optional[Decimal] = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        """Check if order is still active."""
        return self.status in (OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIALLY_FILLED)

    @property
    def is_filled(self) -> bool:
        """Check if order is completely filled."""
        return self.status == OrderStatus.FILLED

    @property
    def remaining_quantity(self) -> Decimal:
        """Calculate remaining unfilled quantity."""
        return self.quantity - self.filled_quantity


@dataclass
class Position:
    """
    Represents an open position.

    Attributes:
        symbol: Trading pair symbol.
        side: Long or short position.
        quantity: Position size in base currency.
        entry_price: Average entry price.
        mark_price: Current mark price.
        liquidation_price: Estimated liquidation price.
        unrealized_pnl: Unrealized profit/loss.
        realized_pnl: Realized profit/loss.
        leverage: Current leverage multiplier.
        margin: Margin used for position.
        updated_at: Last update timestamp.
        raw: Raw exchange response data.
    """

    symbol: str
    side: PositionSide
    quantity: Decimal
    entry_price: Decimal
    mark_price: Optional[Decimal] = None
    liquidation_price: Optional[Decimal] = None
    unrealized_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    leverage: int = 1
    margin: Decimal = Decimal("0")
    updated_at: datetime = field(default_factory=datetime.utcnow)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def notional_value(self) -> Decimal:
        """Calculate notional value of position."""
        if self.mark_price:
            return self.quantity * self.mark_price
        return self.quantity * self.entry_price

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.side == PositionSide.SHORT


@dataclass
class Balance:
    """
    Represents account balance for a currency.

    Attributes:
        currency: Currency symbol (e.g., 'USDC').
        total: Total balance including locked.
        available: Available balance for trading.
        locked: Balance locked in open orders.
        unrealized_pnl: Unrealized PnL from positions.
        updated_at: Last update timestamp.
        raw: Raw exchange response data.
    """

    currency: str
    total: Decimal
    available: Decimal
    locked: Decimal = Decimal("0")
    unrealized_pnl: Decimal = Decimal("0")
    updated_at: datetime = field(default_factory=datetime.utcnow)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Market:
    """
    Represents a tradeable market/instrument.

    Attributes:
        symbol: Trading pair symbol (e.g., 'BTC-PERP').
        base_currency: Base currency (e.g., 'BTC').
        quote_currency: Quote currency (e.g., 'USDC').
        min_quantity: Minimum order quantity.
        max_quantity: Maximum order quantity.
        quantity_precision: Decimal places for quantity.
        price_precision: Decimal places for price.
        tick_size: Minimum price increment.
        lot_size: Minimum quantity increment.
        max_leverage: Maximum allowed leverage.
        is_active: Whether market is currently tradeable.
        raw: Raw exchange response data.
    """

    symbol: str
    base_currency: str
    quote_currency: str
    min_quantity: Decimal
    max_quantity: Decimal
    quantity_precision: int
    price_precision: int
    tick_size: Decimal
    lot_size: Decimal
    max_leverage: int = 50
    is_active: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


class ExchangeError(Exception):
    """Base exception for exchange-related errors."""

    pass


class ConnectionError(ExchangeError):
    """Raised when connection to exchange fails."""

    pass


class AuthenticationError(ExchangeError):
    """Raised when authentication fails."""

    pass


class InsufficientBalanceError(ExchangeError):
    """Raised when balance is insufficient for operation."""

    pass


class OrderError(ExchangeError):
    """Raised when order operation fails."""

    pass


class RateLimitError(ExchangeError):
    """Raised when rate limit is exceeded."""

    pass


class BaseExchange(ABC):
    """
    Abstract base class for exchange implementations.

    All exchange implementations must inherit from this class and implement
    all abstract methods. The interface supports both spot and futures trading.

    Attributes:
        name: Exchange name identifier.
        is_connected: Connection status flag.
        is_testnet: Whether using testnet environment.
        is_mock: Whether running in mock mode without real credentials.
    """

    def __init__(
        self,
        testnet: bool = True,
        mock_mode: bool = False,
    ) -> None:
        """
        Initialize base exchange.

        Args:
            testnet: Use testnet environment (default True for safety).
            mock_mode: Run in mock mode without real API calls.
        """
        self.is_testnet = testnet
        self.is_mock = mock_mode
        self.is_connected = False
        self._name = "base"

    @property
    def name(self) -> str:
        """Exchange name identifier."""
        return self._name

    @abstractmethod
    async def connect(self) -> None:
        """
        Establish connection to the exchange.

        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If authentication fails.
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """
        Close connection to the exchange.

        Should clean up any resources and websocket connections.
        """
        pass

    @abstractmethod
    async def get_markets(self) -> list[Market]:
        """
        Fetch all available trading markets.

        Returns:
            List of Market objects representing tradeable instruments.

        Raises:
            ConnectionError: If not connected or connection lost.
        """
        pass

    @abstractmethod
    async def get_market(self, symbol: str) -> Optional[Market]:
        """
        Fetch a specific market by symbol.

        Args:
            symbol: Market symbol to fetch.

        Returns:
            Market object if found, None otherwise.

        Raises:
            ConnectionError: If not connected.
        """
        pass

    @abstractmethod
    async def get_balance(self, currency: Optional[str] = None) -> list[Balance]:
        """
        Fetch account balance(s).

        Args:
            currency: Specific currency to fetch, or None for all.

        Returns:
            List of Balance objects.

        Raises:
            ConnectionError: If not connected.
            AuthenticationError: If authentication fails.
        """
        pass

    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> list[Position]:
        """
        Fetch open positions.

        Args:
            symbol: Specific symbol to fetch, or None for all positions.

        Returns:
            List of Position objects.

        Raises:
            ConnectionError: If not connected.
            AuthenticationError: If authentication fails.
        """
        pass

    @abstractmethod
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
        Place a new order.

        Args:
            symbol: Trading pair symbol.
            side: Buy or sell.
            order_type: Type of order.
            quantity: Order quantity.
            price: Limit price (required for limit orders).
            reduce_only: Only reduce existing position.
            client_order_id: Custom order identifier.
            time_in_force: GTC, IOC, or FOK.
            stop_price: Trigger price for stop orders.

        Returns:
            Order object with order details.

        Raises:
            OrderError: If order placement fails.
            InsufficientBalanceError: If balance is insufficient.
            ConnectionError: If not connected.
        """
        pass

    @abstractmethod
    async def cancel_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Order:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel.
            symbol: Symbol (required by some exchanges).

        Returns:
            Updated Order object with cancelled status.

        Raises:
            OrderError: If cancellation fails.
            ConnectionError: If not connected.
        """
        pass

    @abstractmethod
    async def get_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Optional[Order]:
        """
        Fetch a specific order by ID.

        Args:
            order_id: Order ID to fetch.
            symbol: Symbol (required by some exchanges).

        Returns:
            Order object if found, None otherwise.

        Raises:
            ConnectionError: If not connected.
        """
        pass

    @abstractmethod
    async def get_open_orders(
        self,
        symbol: Optional[str] = None,
    ) -> list[Order]:
        """
        Fetch all open orders.

        Args:
            symbol: Filter by symbol, or None for all symbols.

        Returns:
            List of open Order objects.

        Raises:
            ConnectionError: If not connected.
        """
        pass

    async def cancel_all_orders(
        self,
        symbol: Optional[str] = None,
    ) -> list[Order]:
        """
        Cancel all open orders.

        Default implementation fetches and cancels each order individually.
        Subclasses may override with more efficient batch cancellation.

        Args:
            symbol: Filter by symbol, or None for all symbols.

        Returns:
            List of cancelled Order objects.
        """
        open_orders = await self.get_open_orders(symbol)
        cancelled = []
        for order in open_orders:
            try:
                cancelled_order = await self.cancel_order(order.order_id, order.symbol)
                cancelled.append(cancelled_order)
            except OrderError:
                # Order may have been filled in the meantime
                pass
        return cancelled

    async def close_position(
        self,
        symbol: str,
        quantity: Optional[Decimal] = None,
    ) -> Optional[Order]:
        """
        Close an open position.

        Args:
            symbol: Symbol of position to close.
            quantity: Quantity to close (None for full position).

        Returns:
            Market order to close position, or None if no position.
        """
        positions = await self.get_positions(symbol)
        if not positions:
            return None

        position = positions[0]
        close_quantity = quantity if quantity else position.quantity
        close_side = OrderSide.SELL if position.is_long else OrderSide.BUY

        return await self.place_order(
            symbol=symbol,
            side=close_side,
            order_type=OrderType.MARKET,
            quantity=close_quantity,
            reduce_only=True,
        )

    def __repr__(self) -> str:
        mode = "mock" if self.is_mock else ("testnet" if self.is_testnet else "mainnet")
        status = "connected" if self.is_connected else "disconnected"
        return f"<{self.__class__.__name__} mode={mode} status={status}>"
