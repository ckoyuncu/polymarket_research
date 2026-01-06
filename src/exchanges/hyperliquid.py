"""
Hyperliquid exchange implementation.

This module provides a concrete implementation of the BaseExchange interface
for Hyperliquid perpetual futures trading. Supports both testnet and mainnet,
with automatic mock mode when credentials are not available.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from .base import (
    AuthenticationError,
    Balance,
    BaseExchange,
    ConnectionError,
    ExchangeError,
    InsufficientBalanceError,
    Market,
    Order,
    OrderError,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    RateLimitError,
)

logger = logging.getLogger(__name__)


def _with_retry(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator for retry logic with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds (doubles each retry).
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except RateLimitError as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            f"Rate limit hit, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                except (ConnectionError, ExchangeError) as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            f"Exchange error: {e}, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
            raise last_exception

        return wrapper

    return decorator


class HyperliquidExchange(BaseExchange):
    """
    Hyperliquid perpetual futures exchange implementation.

    Supports:
    - Testnet (default) and mainnet environments
    - Mock mode when HYPERLIQUID_PRIVATE_KEY is not set
    - Retry logic with exponential backoff
    - All standard exchange operations

    Environment Variables:
        HYPERLIQUID_PRIVATE_KEY: Private key for signing transactions.
        HYPERLIQUID_WALLET_ADDRESS: Wallet address (optional, derived from key).

    Example:
        >>> exchange = HyperliquidExchange(testnet=True)
        >>> await exchange.connect()
        >>> markets = await exchange.get_markets()
        >>> await exchange.disconnect()
    """

    # Hyperliquid API endpoints
    MAINNET_API_URL = "https://api.hyperliquid.xyz"
    TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"

    # Mock data for testing without credentials
    MOCK_MARKETS = [
        {
            "symbol": "BTC-PERP",
            "base_currency": "BTC",
            "quote_currency": "USDC",
            "min_quantity": Decimal("0.001"),
            "max_quantity": Decimal("100"),
            "quantity_precision": 4,
            "price_precision": 1,
            "tick_size": Decimal("0.1"),
            "lot_size": Decimal("0.001"),
            "max_leverage": 50,
        },
        {
            "symbol": "ETH-PERP",
            "base_currency": "ETH",
            "quote_currency": "USDC",
            "min_quantity": Decimal("0.01"),
            "max_quantity": Decimal("1000"),
            "quantity_precision": 3,
            "price_precision": 2,
            "tick_size": Decimal("0.01"),
            "lot_size": Decimal("0.01"),
            "max_leverage": 50,
        },
        {
            "symbol": "SOL-PERP",
            "base_currency": "SOL",
            "quote_currency": "USDC",
            "min_quantity": Decimal("0.1"),
            "max_quantity": Decimal("10000"),
            "quantity_precision": 2,
            "price_precision": 3,
            "tick_size": Decimal("0.001"),
            "lot_size": Decimal("0.1"),
            "max_leverage": 20,
        },
    ]

    def __init__(
        self,
        testnet: bool = True,
        private_key: Optional[str] = None,
        wallet_address: Optional[str] = None,
    ) -> None:
        """
        Initialize Hyperliquid exchange.

        Args:
            testnet: Use testnet environment (default True for safety).
            private_key: Private key for signing. Falls back to env var.
            wallet_address: Wallet address. Falls back to env var.
        """
        # Check for credentials
        self._private_key = private_key or os.environ.get("HYPERLIQUID_PRIVATE_KEY")
        self._wallet_address = wallet_address or os.environ.get("HYPERLIQUID_WALLET_ADDRESS")

        # Enable mock mode if no credentials
        mock_mode = not self._private_key
        super().__init__(testnet=testnet, mock_mode=mock_mode)

        self._name = "hyperliquid"
        self._api_url = self.TESTNET_API_URL if testnet else self.MAINNET_API_URL

        # SDK clients (lazy initialized)
        self._info_client = None
        self._exchange_client = None

        # Mock state for testing
        self._mock_orders: dict[str, Order] = {}
        self._mock_positions: dict[str, Position] = {}
        self._mock_balance = Balance(
            currency="USDC",
            total=Decimal("10000"),
            available=Decimal("10000"),
            locked=Decimal("0"),
        )

        if self.is_mock:
            logger.info(
                "Hyperliquid initialized in MOCK MODE - no real trades will be executed. "
                "Set HYPERLIQUID_PRIVATE_KEY environment variable for live trading."
            )
        else:
            logger.info(f"Hyperliquid initialized for {'testnet' if testnet else 'MAINNET'}")

    async def connect(self) -> None:
        """
        Establish connection to Hyperliquid.

        In mock mode, simulates a successful connection.
        In live mode, initializes the SDK clients.

        Raises:
            ConnectionError: If connection fails.
            AuthenticationError: If authentication fails.
        """
        if self.is_connected:
            logger.debug("Already connected to Hyperliquid")
            return

        if self.is_mock:
            logger.info("Mock connection established to Hyperliquid")
            self.is_connected = True
            return

        try:
            # Import SDK only when needed (not in mock mode)
            from hyperliquid.info import Info
            from hyperliquid.exchange import Exchange
            from hyperliquid.utils import constants

            # Select API URL based on network
            base_url = constants.TESTNET_API_URL if self.is_testnet else constants.MAINNET_API_URL

            # Initialize info client (read-only, no auth needed)
            self._info_client = Info(base_url=base_url, skip_ws=True)

            # Initialize exchange client (requires auth for trading)
            if self._private_key:
                self._exchange_client = Exchange(
                    wallet=None,  # Will use private key directly
                    base_url=base_url,
                    account_address=self._wallet_address,
                )
                # Set up auth with private key
                self._exchange_client.wallet = self._private_key

            self.is_connected = True
            logger.info(f"Connected to Hyperliquid {'testnet' if self.is_testnet else 'mainnet'}")

        except ImportError as e:
            raise ConnectionError(
                f"Failed to import hyperliquid SDK: {e}. "
                "Install with: pip install hyperliquid-python-sdk"
            )
        except Exception as e:
            raise ConnectionError(f"Failed to connect to Hyperliquid: {e}")

    async def disconnect(self) -> None:
        """
        Close connection to Hyperliquid.

        Cleans up SDK clients and resets connection state.
        """
        if not self.is_connected:
            return

        self._info_client = None
        self._exchange_client = None
        self.is_connected = False
        logger.info("Disconnected from Hyperliquid")

    def _ensure_connected(self) -> None:
        """Raise ConnectionError if not connected."""
        if not self.is_connected:
            raise ConnectionError("Not connected to Hyperliquid. Call connect() first.")

    @_with_retry(max_retries=3)
    async def get_markets(self) -> list[Market]:
        """
        Fetch all available perpetual markets.

        Returns:
            List of Market objects for all tradeable perpetuals.

        Raises:
            ConnectionError: If not connected.
        """
        self._ensure_connected()

        if self.is_mock:
            return [Market(**m) for m in self.MOCK_MARKETS]

        try:
            # Fetch meta info from Hyperliquid
            meta = await asyncio.to_thread(self._info_client.meta)
            markets = []

            for asset_info in meta.get("universe", []):
                symbol = f"{asset_info['name']}-PERP"
                sz_decimals = asset_info.get("szDecimals", 4)

                market = Market(
                    symbol=symbol,
                    base_currency=asset_info["name"],
                    quote_currency="USDC",
                    min_quantity=Decimal("10") ** (-sz_decimals),
                    max_quantity=Decimal("1000000"),
                    quantity_precision=sz_decimals,
                    price_precision=6,
                    tick_size=Decimal("0.000001"),
                    lot_size=Decimal("10") ** (-sz_decimals),
                    max_leverage=asset_info.get("maxLeverage", 50),
                    is_active=True,
                    raw=asset_info,
                )
                markets.append(market)

            return markets

        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            raise ConnectionError(f"Failed to fetch markets: {e}")

    @_with_retry(max_retries=3)
    async def get_market(self, symbol: str) -> Optional[Market]:
        """
        Fetch a specific market by symbol.

        Args:
            symbol: Market symbol (e.g., 'BTC-PERP').

        Returns:
            Market object if found, None otherwise.
        """
        markets = await self.get_markets()
        for market in markets:
            if market.symbol == symbol:
                return market
        return None

    @_with_retry(max_retries=3)
    async def get_balance(self, currency: Optional[str] = None) -> list[Balance]:
        """
        Fetch account balance.

        Args:
            currency: Currency to fetch (default 'USDC' for Hyperliquid).

        Returns:
            List of Balance objects (typically just USDC for Hyperliquid).

        Raises:
            ConnectionError: If not connected.
            AuthenticationError: If authentication fails.
        """
        self._ensure_connected()

        if self.is_mock:
            if currency and currency != "USDC":
                return []
            return [self._mock_balance]

        try:
            if not self._wallet_address:
                raise AuthenticationError("Wallet address required for balance check")

            # Fetch user state
            user_state = await asyncio.to_thread(
                self._info_client.user_state, self._wallet_address
            )

            margin_summary = user_state.get("marginSummary", {})
            account_value = Decimal(str(margin_summary.get("accountValue", "0")))
            total_margin = Decimal(str(margin_summary.get("totalMarginUsed", "0")))

            balance = Balance(
                currency="USDC",
                total=account_value,
                available=account_value - total_margin,
                locked=total_margin,
                unrealized_pnl=Decimal(str(margin_summary.get("totalUnrealizedPnl", "0"))),
                raw=user_state,
            )

            if currency and currency != "USDC":
                return []
            return [balance]

        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            raise ConnectionError(f"Failed to fetch balance: {e}")

    @_with_retry(max_retries=3)
    async def get_positions(self, symbol: Optional[str] = None) -> list[Position]:
        """
        Fetch open positions.

        Args:
            symbol: Filter by symbol, or None for all positions.

        Returns:
            List of Position objects.

        Raises:
            ConnectionError: If not connected.
        """
        self._ensure_connected()

        if self.is_mock:
            positions = list(self._mock_positions.values())
            if symbol:
                positions = [p for p in positions if p.symbol == symbol]
            return positions

        try:
            if not self._wallet_address:
                raise AuthenticationError("Wallet address required for position check")

            user_state = await asyncio.to_thread(
                self._info_client.user_state, self._wallet_address
            )

            positions = []
            for pos_data in user_state.get("assetPositions", []):
                pos = pos_data.get("position", {})
                if not pos:
                    continue

                coin = pos.get("coin", "")
                pos_symbol = f"{coin}-PERP"

                if symbol and pos_symbol != symbol:
                    continue

                size = Decimal(str(pos.get("szi", "0")))
                if size == 0:
                    continue

                position = Position(
                    symbol=pos_symbol,
                    side=PositionSide.LONG if size > 0 else PositionSide.SHORT,
                    quantity=abs(size),
                    entry_price=Decimal(str(pos.get("entryPx", "0"))),
                    mark_price=Decimal(str(pos.get("markPx", "0"))),
                    liquidation_price=Decimal(str(pos.get("liquidationPx", "0")))
                    if pos.get("liquidationPx")
                    else None,
                    unrealized_pnl=Decimal(str(pos.get("unrealizedPnl", "0"))),
                    realized_pnl=Decimal(str(pos.get("returnOnEquity", "0"))),
                    leverage=int(pos.get("leverage", {}).get("value", 1)),
                    margin=Decimal(str(pos.get("marginUsed", "0"))),
                    raw=pos_data,
                )
                positions.append(position)

            return positions

        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            raise ConnectionError(f"Failed to fetch positions: {e}")

    @_with_retry(max_retries=3)
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
            symbol: Trading pair (e.g., 'BTC-PERP').
            side: Buy or sell.
            order_type: Market, limit, etc.
            quantity: Order quantity.
            price: Limit price (required for limit orders).
            reduce_only: Only reduce existing position.
            client_order_id: Custom order ID.
            time_in_force: GTC, IOC, or FOK.
            stop_price: Trigger price for stop orders.

        Returns:
            Order object with order details.

        Raises:
            OrderError: If order placement fails.
            InsufficientBalanceError: If balance is insufficient.
        """
        self._ensure_connected()

        # Validate inputs
        if order_type == OrderType.LIMIT and price is None:
            raise OrderError("Price required for limit orders")

        if order_type in (OrderType.STOP_LIMIT, OrderType.STOP_MARKET) and stop_price is None:
            raise OrderError("Stop price required for stop orders")

        order_id = client_order_id or str(uuid.uuid4())

        if self.is_mock:
            return await self._mock_place_order(
                order_id=order_id,
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                reduce_only=reduce_only,
                time_in_force=time_in_force,
                stop_price=stop_price,
            )

        try:
            # Parse coin from symbol (e.g., 'BTC-PERP' -> 'BTC')
            coin = symbol.replace("-PERP", "")

            # Determine if buy or sell
            is_buy = side == OrderSide.BUY

            # Map order type to Hyperliquid format
            if order_type == OrderType.MARKET:
                # Market orders use aggressive limit
                order_result = await asyncio.to_thread(
                    self._exchange_client.market_open,
                    coin,
                    is_buy,
                    float(quantity),
                    reduce_only=reduce_only,
                )
            elif order_type == OrderType.LIMIT:
                # TIF mapping
                tif_map = {"GTC": "Gtc", "IOC": "Ioc", "FOK": "Fok"}
                tif = tif_map.get(time_in_force, "Gtc")

                order_result = await asyncio.to_thread(
                    self._exchange_client.order,
                    coin,
                    is_buy,
                    float(quantity),
                    float(price),
                    {"limit": {"tif": tif}},
                    reduce_only=reduce_only,
                )
            else:
                raise OrderError(f"Order type {order_type} not yet supported")

            # Parse response
            if order_result.get("status") == "err":
                raise OrderError(f"Order failed: {order_result.get('response', 'Unknown error')}")

            response = order_result.get("response", {})
            data = response.get("data", {})
            statuses = data.get("statuses", [{}])
            status_info = statuses[0] if statuses else {}

            # Determine order status
            if "filled" in status_info:
                filled_info = status_info["filled"]
                status = OrderStatus.FILLED
                filled_qty = Decimal(str(filled_info.get("totalSz", quantity)))
                avg_price = Decimal(str(filled_info.get("avgPx", price or 0)))
            elif "resting" in status_info:
                status = OrderStatus.OPEN
                filled_qty = Decimal("0")
                avg_price = None
            else:
                status = OrderStatus.PENDING
                filled_qty = Decimal("0")
                avg_price = None

            order = Order(
                order_id=str(status_info.get("oid", order_id)),
                symbol=symbol,
                side=side,
                order_type=order_type,
                quantity=quantity,
                price=price,
                status=status,
                filled_quantity=filled_qty,
                average_fill_price=avg_price,
                client_order_id=client_order_id,
                reduce_only=reduce_only,
                time_in_force=time_in_force,
                stop_price=stop_price,
                raw=order_result,
            )

            logger.info(f"Order placed: {order}")
            return order

        except OrderError:
            raise
        except Exception as e:
            logger.error(f"Failed to place order: {e}")
            raise OrderError(f"Failed to place order: {e}")

    async def _mock_place_order(
        self,
        order_id: str,
        symbol: str,
        side: OrderSide,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal],
        reduce_only: bool,
        time_in_force: str,
        stop_price: Optional[Decimal],
    ) -> Order:
        """Place order in mock mode."""
        # Simulate balance check
        if not reduce_only:
            notional = quantity * (price or Decimal("50000"))  # Use rough BTC price
            if notional > self._mock_balance.available:
                raise InsufficientBalanceError(
                    f"Insufficient balance: need {notional}, have {self._mock_balance.available}"
                )

        # Market orders fill immediately in mock
        if order_type == OrderType.MARKET:
            status = OrderStatus.FILLED
            filled_qty = quantity
            avg_price = price or Decimal("50000")  # Mock fill price
        else:
            status = OrderStatus.OPEN
            filled_qty = Decimal("0")
            avg_price = None

        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=status,
            filled_quantity=filled_qty,
            average_fill_price=avg_price,
            reduce_only=reduce_only,
            time_in_force=time_in_force,
            stop_price=stop_price,
        )

        self._mock_orders[order_id] = order

        # Update mock position if filled
        if status == OrderStatus.FILLED:
            await self._update_mock_position(order, reduce_only)

        logger.info(f"[MOCK] Order placed: {order}")
        return order

    async def _update_mock_position(self, order: Order, reduce_only: bool = False) -> None:
        """Update mock position after fill."""
        symbol = order.symbol
        existing = self._mock_positions.get(symbol)

        if reduce_only:
            # Reduce only orders only close positions
            if existing is not None:
                if order.filled_quantity >= existing.quantity:
                    del self._mock_positions[symbol]
                else:
                    existing.quantity -= order.filled_quantity
            return

        if existing is None:
            # New position
            self._mock_positions[symbol] = Position(
                symbol=symbol,
                side=PositionSide.LONG if order.side == OrderSide.BUY else PositionSide.SHORT,
                quantity=order.filled_quantity,
                entry_price=order.average_fill_price or Decimal("0"),
            )
        else:
            # Update existing position (simplified)
            if (
                order.side == OrderSide.BUY
                and existing.side == PositionSide.LONG
            ) or (
                order.side == OrderSide.SELL
                and existing.side == PositionSide.SHORT
            ):
                # Adding to position
                existing.quantity += order.filled_quantity
            else:
                # Reducing position
                if order.filled_quantity >= existing.quantity:
                    del self._mock_positions[symbol]
                else:
                    existing.quantity -= order.filled_quantity

    @_with_retry(max_retries=3)
    async def cancel_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Order:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel.
            symbol: Symbol (required for Hyperliquid).

        Returns:
            Updated Order with cancelled status.

        Raises:
            OrderError: If cancellation fails.
        """
        self._ensure_connected()

        if self.is_mock:
            return await self._mock_cancel_order(order_id)

        if not symbol:
            raise OrderError("Symbol required for cancellation on Hyperliquid")

        try:
            coin = symbol.replace("-PERP", "")

            result = await asyncio.to_thread(
                self._exchange_client.cancel, coin, int(order_id)
            )

            if result.get("status") == "err":
                raise OrderError(f"Cancel failed: {result.get('response', 'Unknown error')}")

            # Return updated order
            order = await self.get_order(order_id, symbol)
            if order:
                order.status = OrderStatus.CANCELLED
                return order

            # Order not found, return minimal cancelled order
            return Order(
                order_id=order_id,
                symbol=symbol,
                side=OrderSide.BUY,  # Unknown
                order_type=OrderType.LIMIT,  # Unknown
                quantity=Decimal("0"),
                status=OrderStatus.CANCELLED,
                raw=result,
            )

        except OrderError:
            raise
        except Exception as e:
            logger.error(f"Failed to cancel order: {e}")
            raise OrderError(f"Failed to cancel order: {e}")

    async def _mock_cancel_order(self, order_id: str) -> Order:
        """Cancel order in mock mode."""
        if order_id not in self._mock_orders:
            raise OrderError(f"Order not found: {order_id}")

        order = self._mock_orders[order_id]
        if not order.is_open:
            raise OrderError(f"Order {order_id} is not open (status: {order.status})")

        order.status = OrderStatus.CANCELLED
        order.updated_at = datetime.utcnow()

        logger.info(f"[MOCK] Order cancelled: {order_id}")
        return order

    @_with_retry(max_retries=3)
    async def get_order(
        self,
        order_id: str,
        symbol: Optional[str] = None,
    ) -> Optional[Order]:
        """
        Fetch a specific order by ID.

        Args:
            order_id: Order ID to fetch.
            symbol: Symbol (helps with lookup on Hyperliquid).

        Returns:
            Order object if found, None otherwise.
        """
        self._ensure_connected()

        if self.is_mock:
            return self._mock_orders.get(order_id)

        try:
            if not self._wallet_address:
                raise AuthenticationError("Wallet address required for order lookup")

            # Fetch all open orders and search
            open_orders = await asyncio.to_thread(
                self._info_client.open_orders, self._wallet_address
            )

            for order_data in open_orders:
                if str(order_data.get("oid")) == order_id:
                    return self._parse_order(order_data)

            # Check order history if not found in open orders
            order_history = await asyncio.to_thread(
                self._info_client.user_fills, self._wallet_address
            )

            for fill_data in order_history:
                if str(fill_data.get("oid")) == order_id:
                    return self._parse_fill_to_order(fill_data)

            return None

        except Exception as e:
            logger.error(f"Failed to fetch order: {e}")
            return None

    def _parse_order(self, data: dict[str, Any]) -> Order:
        """Parse order data from Hyperliquid API."""
        coin = data.get("coin", "")
        symbol = f"{coin}-PERP"

        return Order(
            order_id=str(data.get("oid", "")),
            symbol=symbol,
            side=OrderSide.BUY if data.get("side") == "B" else OrderSide.SELL,
            order_type=OrderType.LIMIT,  # Hyperliquid returns limit orders
            quantity=Decimal(str(data.get("sz", "0"))),
            price=Decimal(str(data.get("limitPx", "0"))),
            status=OrderStatus.OPEN,
            filled_quantity=Decimal("0"),
            raw=data,
        )

    def _parse_fill_to_order(self, data: dict[str, Any]) -> Order:
        """Parse fill data to Order (for historical orders)."""
        coin = data.get("coin", "")
        symbol = f"{coin}-PERP"

        return Order(
            order_id=str(data.get("oid", "")),
            symbol=symbol,
            side=OrderSide.BUY if data.get("side") == "B" else OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal(str(data.get("sz", "0"))),
            price=Decimal(str(data.get("px", "0"))),
            status=OrderStatus.FILLED,
            filled_quantity=Decimal(str(data.get("sz", "0"))),
            average_fill_price=Decimal(str(data.get("px", "0"))),
            raw=data,
        )

    @_with_retry(max_retries=3)
    async def get_open_orders(
        self,
        symbol: Optional[str] = None,
    ) -> list[Order]:
        """
        Fetch all open orders.

        Args:
            symbol: Filter by symbol, or None for all.

        Returns:
            List of open Order objects.
        """
        self._ensure_connected()

        if self.is_mock:
            orders = [o for o in self._mock_orders.values() if o.is_open]
            if symbol:
                orders = [o for o in orders if o.symbol == symbol]
            return orders

        try:
            if not self._wallet_address:
                raise AuthenticationError("Wallet address required for orders lookup")

            open_orders = await asyncio.to_thread(
                self._info_client.open_orders, self._wallet_address
            )

            orders = []
            for order_data in open_orders:
                order = self._parse_order(order_data)
                if symbol is None or order.symbol == symbol:
                    orders.append(order)

            return orders

        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            raise ConnectionError(f"Failed to fetch open orders: {e}")

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """
        Set leverage for a symbol.

        Args:
            symbol: Trading symbol.
            leverage: Desired leverage (1-50).

        Returns:
            True if successful.

        Raises:
            ExchangeError: If leverage change fails.
        """
        self._ensure_connected()

        if self.is_mock:
            logger.info(f"[MOCK] Leverage set to {leverage}x for {symbol}")
            return True

        try:
            coin = symbol.replace("-PERP", "")

            result = await asyncio.to_thread(
                self._exchange_client.update_leverage, leverage, coin
            )

            if result.get("status") == "err":
                raise ExchangeError(f"Failed to set leverage: {result}")

            logger.info(f"Leverage set to {leverage}x for {symbol}")
            return True

        except Exception as e:
            logger.error(f"Failed to set leverage: {e}")
            raise ExchangeError(f"Failed to set leverage: {e}")

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """
        Fetch current ticker/price data for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            Dictionary with price data (bid, ask, last, etc.).
        """
        self._ensure_connected()

        if self.is_mock:
            # Return mock ticker data
            mock_prices = {
                "BTC-PERP": {"bid": "49990", "ask": "50010", "last": "50000"},
                "ETH-PERP": {"bid": "2990", "ask": "3010", "last": "3000"},
                "SOL-PERP": {"bid": "99", "ask": "101", "last": "100"},
            }
            return mock_prices.get(symbol, {"bid": "100", "ask": "100", "last": "100"})

        try:
            all_mids = await asyncio.to_thread(self._info_client.all_mids)
            coin = symbol.replace("-PERP", "")

            mid_price = all_mids.get(coin)
            if mid_price:
                return {
                    "symbol": symbol,
                    "mid": mid_price,
                    "bid": str(float(mid_price) * 0.9999),
                    "ask": str(float(mid_price) * 1.0001),
                    "last": mid_price,
                }

            return {}

        except Exception as e:
            logger.error(f"Failed to fetch ticker: {e}")
            return {}
