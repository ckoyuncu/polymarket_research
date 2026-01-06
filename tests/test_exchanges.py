"""
Comprehensive tests for exchange infrastructure.

Tests cover:
- Base exchange dataclasses and enums
- Hyperliquid exchange implementation
- Mock mode functionality
- Error handling and retry logic
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
import os

import pytest

from src.exchanges.base import (
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
from src.exchanges.hyperliquid import HyperliquidExchange


# =============================================================================
# Test Base Dataclasses and Enums
# =============================================================================


class TestOrderSide:
    """Tests for OrderSide enum."""

    def test_buy_side(self):
        assert OrderSide.BUY.value == "buy"
        assert str(OrderSide.BUY) == "buy"

    def test_sell_side(self):
        assert OrderSide.SELL.value == "sell"
        assert str(OrderSide.SELL) == "sell"


class TestOrderType:
    """Tests for OrderType enum."""

    def test_market_type(self):
        assert OrderType.MARKET.value == "market"

    def test_limit_type(self):
        assert OrderType.LIMIT.value == "limit"

    def test_stop_types(self):
        assert OrderType.STOP_MARKET.value == "stop_market"
        assert OrderType.STOP_LIMIT.value == "stop_limit"


class TestOrderStatus:
    """Tests for OrderStatus enum."""

    def test_all_statuses(self):
        statuses = [
            OrderStatus.PENDING,
            OrderStatus.OPEN,
            OrderStatus.FILLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ]
        assert len(statuses) == 7


class TestPositionSide:
    """Tests for PositionSide enum."""

    def test_long_position(self):
        assert PositionSide.LONG.value == "long"

    def test_short_position(self):
        assert PositionSide.SHORT.value == "short"


class TestOrder:
    """Tests for Order dataclass."""

    def test_order_creation(self):
        order = Order(
            order_id="123",
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.5"),
            price=Decimal("50000"),
        )
        assert order.order_id == "123"
        assert order.symbol == "BTC-PERP"
        assert order.side == OrderSide.BUY
        assert order.quantity == Decimal("1.5")

    def test_order_is_open(self):
        open_order = Order(
            order_id="1",
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            status=OrderStatus.OPEN,
        )
        assert open_order.is_open is True

        filled_order = Order(
            order_id="2",
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            status=OrderStatus.FILLED,
        )
        assert filled_order.is_open is False

    def test_order_is_filled(self):
        order = Order(
            order_id="1",
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            status=OrderStatus.FILLED,
        )
        assert order.is_filled is True

    def test_remaining_quantity(self):
        order = Order(
            order_id="1",
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("10"),
            filled_quantity=Decimal("3"),
            status=OrderStatus.PARTIALLY_FILLED,
        )
        assert order.remaining_quantity == Decimal("7")


class TestPosition:
    """Tests for Position dataclass."""

    def test_position_creation(self):
        position = Position(
            symbol="BTC-PERP",
            side=PositionSide.LONG,
            quantity=Decimal("2"),
            entry_price=Decimal("50000"),
        )
        assert position.symbol == "BTC-PERP"
        assert position.is_long is True
        assert position.is_short is False

    def test_position_notional_value(self):
        position = Position(
            symbol="BTC-PERP",
            side=PositionSide.LONG,
            quantity=Decimal("2"),
            entry_price=Decimal("50000"),
            mark_price=Decimal("51000"),
        )
        assert position.notional_value == Decimal("102000")

    def test_position_notional_uses_entry_if_no_mark(self):
        position = Position(
            symbol="BTC-PERP",
            side=PositionSide.LONG,
            quantity=Decimal("2"),
            entry_price=Decimal("50000"),
        )
        assert position.notional_value == Decimal("100000")


class TestBalance:
    """Tests for Balance dataclass."""

    def test_balance_creation(self):
        balance = Balance(
            currency="USDC",
            total=Decimal("10000"),
            available=Decimal("8000"),
            locked=Decimal("2000"),
        )
        assert balance.currency == "USDC"
        assert balance.total == Decimal("10000")
        assert balance.available == Decimal("8000")


class TestMarket:
    """Tests for Market dataclass."""

    def test_market_creation(self):
        market = Market(
            symbol="BTC-PERP",
            base_currency="BTC",
            quote_currency="USDC",
            min_quantity=Decimal("0.001"),
            max_quantity=Decimal("100"),
            quantity_precision=4,
            price_precision=1,
            tick_size=Decimal("0.1"),
            lot_size=Decimal("0.001"),
        )
        assert market.symbol == "BTC-PERP"
        assert market.max_leverage == 50  # Default


# =============================================================================
# Test Exceptions
# =============================================================================


class TestExceptions:
    """Tests for exchange exceptions."""

    def test_exception_hierarchy(self):
        assert issubclass(ConnectionError, ExchangeError)
        assert issubclass(AuthenticationError, ExchangeError)
        assert issubclass(InsufficientBalanceError, ExchangeError)
        assert issubclass(OrderError, ExchangeError)
        assert issubclass(RateLimitError, ExchangeError)

    def test_exception_messages(self):
        ex = OrderError("Order failed: invalid price")
        assert str(ex) == "Order failed: invalid price"


# =============================================================================
# Test Hyperliquid Exchange - Mock Mode
# =============================================================================


class TestHyperliquidMockMode:
    """Tests for Hyperliquid exchange in mock mode."""

    @pytest.fixture
    def mock_exchange(self):
        """Create mock mode exchange."""
        # Ensure no private key is set
        with patch.dict(os.environ, {}, clear=True):
            exchange = HyperliquidExchange(testnet=True)
        return exchange

    def test_mock_mode_enabled_without_credentials(self, mock_exchange):
        assert mock_exchange.is_mock is True
        assert mock_exchange.is_testnet is True

    def test_exchange_name(self, mock_exchange):
        assert mock_exchange.name == "hyperliquid"

    def test_exchange_repr(self, mock_exchange):
        repr_str = repr(mock_exchange)
        assert "mock" in repr_str
        assert "disconnected" in repr_str

    @pytest.mark.asyncio
    async def test_connect_mock(self, mock_exchange):
        await mock_exchange.connect()
        assert mock_exchange.is_connected is True

    @pytest.mark.asyncio
    async def test_disconnect_mock(self, mock_exchange):
        await mock_exchange.connect()
        await mock_exchange.disconnect()
        assert mock_exchange.is_connected is False

    @pytest.mark.asyncio
    async def test_double_connect(self, mock_exchange):
        await mock_exchange.connect()
        await mock_exchange.connect()  # Should not raise
        assert mock_exchange.is_connected is True

    @pytest.mark.asyncio
    async def test_get_markets_mock(self, mock_exchange):
        await mock_exchange.connect()
        markets = await mock_exchange.get_markets()

        assert len(markets) == 3
        symbols = [m.symbol for m in markets]
        assert "BTC-PERP" in symbols
        assert "ETH-PERP" in symbols
        assert "SOL-PERP" in symbols

    @pytest.mark.asyncio
    async def test_get_market_mock(self, mock_exchange):
        await mock_exchange.connect()
        market = await mock_exchange.get_market("BTC-PERP")

        assert market is not None
        assert market.symbol == "BTC-PERP"
        assert market.base_currency == "BTC"

    @pytest.mark.asyncio
    async def test_get_market_not_found(self, mock_exchange):
        await mock_exchange.connect()
        market = await mock_exchange.get_market("NONEXISTENT-PERP")
        assert market is None

    @pytest.mark.asyncio
    async def test_get_balance_mock(self, mock_exchange):
        await mock_exchange.connect()
        balances = await mock_exchange.get_balance()

        assert len(balances) == 1
        assert balances[0].currency == "USDC"
        assert balances[0].total == Decimal("10000")

    @pytest.mark.asyncio
    async def test_get_balance_wrong_currency(self, mock_exchange):
        await mock_exchange.connect()
        balances = await mock_exchange.get_balance("BTC")
        assert len(balances) == 0

    @pytest.mark.asyncio
    async def test_get_positions_empty(self, mock_exchange):
        await mock_exchange.connect()
        positions = await mock_exchange.get_positions()
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_place_market_order_mock(self, mock_exchange):
        await mock_exchange.connect()
        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        assert order.symbol == "BTC-PERP"
        assert order.side == OrderSide.BUY
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == Decimal("0.1")

    @pytest.mark.asyncio
    async def test_place_limit_order_mock(self, mock_exchange):
        await mock_exchange.connect()
        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )

        assert order.status == OrderStatus.OPEN
        assert order.price == Decimal("45000")

    @pytest.mark.asyncio
    async def test_place_limit_order_no_price_raises(self, mock_exchange):
        await mock_exchange.connect()
        with pytest.raises(OrderError, match="Price required"):
            await mock_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.1"),
            )

    @pytest.mark.asyncio
    async def test_place_order_insufficient_balance(self, mock_exchange):
        await mock_exchange.connect()
        with pytest.raises(InsufficientBalanceError):
            await mock_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1000"),  # Would require millions in USDC
            )

    @pytest.mark.asyncio
    async def test_cancel_order_mock(self, mock_exchange):
        await mock_exchange.connect()

        # Place limit order
        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )

        # Cancel it
        cancelled = await mock_exchange.cancel_order(order.order_id)
        assert cancelled.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, mock_exchange):
        await mock_exchange.connect()
        with pytest.raises(OrderError, match="Order not found"):
            await mock_exchange.cancel_order("nonexistent-id")

    @pytest.mark.asyncio
    async def test_cancel_filled_order_raises(self, mock_exchange):
        await mock_exchange.connect()

        # Place market order (fills immediately)
        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Try to cancel filled order
        with pytest.raises(OrderError, match="not open"):
            await mock_exchange.cancel_order(order.order_id)

    @pytest.mark.asyncio
    async def test_get_order_mock(self, mock_exchange):
        await mock_exchange.connect()

        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )

        fetched = await mock_exchange.get_order(order.order_id)
        assert fetched is not None
        assert fetched.order_id == order.order_id

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, mock_exchange):
        await mock_exchange.connect()
        order = await mock_exchange.get_order("nonexistent")
        assert order is None

    @pytest.mark.asyncio
    async def test_get_open_orders_mock(self, mock_exchange):
        await mock_exchange.connect()

        # Place multiple limit orders
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )
        await mock_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            price=Decimal("3500"),
        )

        # Get all open orders
        open_orders = await mock_exchange.get_open_orders()
        assert len(open_orders) == 2

        # Filter by symbol
        btc_orders = await mock_exchange.get_open_orders("BTC-PERP")
        assert len(btc_orders) == 1
        assert btc_orders[0].symbol == "BTC-PERP"

    @pytest.mark.asyncio
    async def test_position_updates_on_fill(self, mock_exchange):
        await mock_exchange.connect()

        # Place market order
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Check position
        positions = await mock_exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTC-PERP"
        assert positions[0].side == PositionSide.LONG
        assert positions[0].quantity == Decimal("0.1")

    @pytest.mark.asyncio
    async def test_close_position(self, mock_exchange):
        await mock_exchange.connect()

        # Open position
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Close position
        close_order = await mock_exchange.close_position("BTC-PERP")
        assert close_order is not None
        assert close_order.side == OrderSide.SELL
        assert close_order.reduce_only is True

    @pytest.mark.asyncio
    async def test_close_no_position(self, mock_exchange):
        await mock_exchange.connect()
        result = await mock_exchange.close_position("BTC-PERP")
        assert result is None

    @pytest.mark.asyncio
    async def test_cancel_all_orders(self, mock_exchange):
        await mock_exchange.connect()

        # Place multiple orders
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
        )
        await mock_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            price=Decimal("2500"),
        )

        # Cancel all
        cancelled = await mock_exchange.cancel_all_orders()
        assert len(cancelled) == 2

        # Verify no open orders remain
        open_orders = await mock_exchange.get_open_orders()
        assert len(open_orders) == 0

    @pytest.mark.asyncio
    async def test_get_ticker_mock(self, mock_exchange):
        await mock_exchange.connect()
        ticker = await mock_exchange.get_ticker("BTC-PERP")

        assert "bid" in ticker
        assert "ask" in ticker
        assert "last" in ticker

    @pytest.mark.asyncio
    async def test_set_leverage_mock(self, mock_exchange):
        await mock_exchange.connect()
        result = await mock_exchange.set_leverage("BTC-PERP", 10)
        assert result is True


class TestHyperliquidNotConnected:
    """Test error handling when not connected."""

    @pytest.fixture
    def mock_exchange(self):
        with patch.dict(os.environ, {}, clear=True):
            return HyperliquidExchange(testnet=True)

    @pytest.mark.asyncio
    async def test_get_markets_not_connected(self, mock_exchange):
        with pytest.raises(ConnectionError, match="Not connected"):
            await mock_exchange.get_markets()

    @pytest.mark.asyncio
    async def test_get_balance_not_connected(self, mock_exchange):
        with pytest.raises(ConnectionError, match="Not connected"):
            await mock_exchange.get_balance()

    @pytest.mark.asyncio
    async def test_place_order_not_connected(self, mock_exchange):
        with pytest.raises(ConnectionError, match="Not connected"):
            await mock_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0.1"),
            )


# =============================================================================
# Test Hyperliquid Exchange - Live Mode (Mocked SDK)
# =============================================================================


# Check if hyperliquid SDK is installed
try:
    import hyperliquid
    HAS_HYPERLIQUID_SDK = True
except ImportError:
    HAS_HYPERLIQUID_SDK = False


class TestHyperliquidLiveMode:
    """Tests for Hyperliquid with mocked SDK calls."""

    @pytest.fixture
    def live_exchange(self):
        """Create exchange with credentials (mocked)."""
        with patch.dict(
            os.environ,
            {"HYPERLIQUID_PRIVATE_KEY": "0x1234", "HYPERLIQUID_WALLET_ADDRESS": "0xabcd"},
        ):
            exchange = HyperliquidExchange(testnet=True)
        return exchange

    def test_live_mode_enabled_with_credentials(self, live_exchange):
        assert live_exchange.is_mock is False
        assert live_exchange.is_testnet is True

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_HYPERLIQUID_SDK, reason="hyperliquid SDK not installed")
    async def test_connect_live_imports_sdk(self, live_exchange):
        """Test that connect attempts to import and initialize SDK."""
        import sys
        # Mock the SDK modules
        mock_info = MagicMock()
        mock_exchange = MagicMock()
        mock_constants = MagicMock()
        mock_constants.TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
        mock_constants.MAINNET_API_URL = "https://api.hyperliquid.xyz"

        with patch.dict(sys.modules, {
            'hyperliquid.info': MagicMock(Info=mock_info),
            'hyperliquid.exchange': MagicMock(Exchange=mock_exchange),
            'hyperliquid.utils': MagicMock(constants=mock_constants),
        }):
            await live_exchange.connect()
            assert live_exchange.is_connected is True

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_HYPERLIQUID_SDK, reason="hyperliquid SDK not installed")
    async def test_get_markets_live(self, live_exchange):
        """Test fetching markets with mocked SDK response."""
        import sys
        mock_meta = {
            "universe": [
                {"name": "BTC", "szDecimals": 4, "maxLeverage": 50},
                {"name": "ETH", "szDecimals": 3, "maxLeverage": 50},
            ]
        }

        mock_info_instance = MagicMock()
        mock_info_instance.meta.return_value = mock_meta
        mock_info_class = MagicMock(return_value=mock_info_instance)
        mock_exchange = MagicMock()
        mock_constants = MagicMock()
        mock_constants.TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
        mock_constants.MAINNET_API_URL = "https://api.hyperliquid.xyz"

        with patch.dict(sys.modules, {
            'hyperliquid.info': MagicMock(Info=mock_info_class),
            'hyperliquid.exchange': MagicMock(Exchange=mock_exchange),
            'hyperliquid.utils': MagicMock(constants=mock_constants),
        }):
            await live_exchange.connect()

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = mock_meta

            markets = await live_exchange.get_markets()

            assert len(markets) == 2
            assert markets[0].symbol == "BTC-PERP"
            assert markets[1].symbol == "ETH-PERP"

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_HYPERLIQUID_SDK, reason="hyperliquid SDK not installed")
    async def test_get_balance_live(self, live_exchange):
        """Test fetching balance with mocked SDK response."""
        import sys
        mock_user_state = {
            "marginSummary": {
                "accountValue": "10000.50",
                "totalMarginUsed": "2000.00",
                "totalUnrealizedPnl": "150.25",
            }
        }

        mock_info_instance = MagicMock()
        mock_info_class = MagicMock(return_value=mock_info_instance)
        mock_exchange = MagicMock()
        mock_constants = MagicMock()
        mock_constants.TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
        mock_constants.MAINNET_API_URL = "https://api.hyperliquid.xyz"

        with patch.dict(sys.modules, {
            'hyperliquid.info': MagicMock(Info=mock_info_class),
            'hyperliquid.exchange': MagicMock(Exchange=mock_exchange),
            'hyperliquid.utils': MagicMock(constants=mock_constants),
        }):
            await live_exchange.connect()

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = mock_user_state

            balances = await live_exchange.get_balance()

            assert len(balances) == 1
            assert balances[0].currency == "USDC"
            assert balances[0].total == Decimal("10000.50")
            assert balances[0].available == Decimal("8000.50")
            assert balances[0].locked == Decimal("2000.00")

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_HYPERLIQUID_SDK, reason="hyperliquid SDK not installed")
    async def test_get_positions_live(self, live_exchange):
        """Test fetching positions with mocked SDK response."""
        import sys
        mock_user_state = {
            "assetPositions": [
                {
                    "position": {
                        "coin": "BTC",
                        "szi": "0.5",
                        "entryPx": "45000",
                        "markPx": "46000",
                        "liquidationPx": "40000",
                        "unrealizedPnl": "500",
                        "returnOnEquity": "100",
                        "leverage": {"value": 5},
                        "marginUsed": "4500",
                    }
                }
            ]
        }

        mock_info_instance = MagicMock()
        mock_info_class = MagicMock(return_value=mock_info_instance)
        mock_exchange = MagicMock()
        mock_constants = MagicMock()
        mock_constants.TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
        mock_constants.MAINNET_API_URL = "https://api.hyperliquid.xyz"

        with patch.dict(sys.modules, {
            'hyperliquid.info': MagicMock(Info=mock_info_class),
            'hyperliquid.exchange': MagicMock(Exchange=mock_exchange),
            'hyperliquid.utils': MagicMock(constants=mock_constants),
        }):
            await live_exchange.connect()

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = mock_user_state

            positions = await live_exchange.get_positions()

            assert len(positions) == 1
            assert positions[0].symbol == "BTC-PERP"
            assert positions[0].side == PositionSide.LONG
            assert positions[0].quantity == Decimal("0.5")
            assert positions[0].entry_price == Decimal("45000")

    @pytest.mark.asyncio
    @pytest.mark.skipif(not HAS_HYPERLIQUID_SDK, reason="hyperliquid SDK not installed")
    async def test_get_open_orders_live(self, live_exchange):
        """Test fetching open orders with mocked SDK response."""
        import sys
        mock_orders = [
            {
                "oid": "12345",
                "coin": "BTC",
                "side": "B",
                "sz": "0.1",
                "limitPx": "45000",
            },
            {
                "oid": "12346",
                "coin": "ETH",
                "side": "A",
                "sz": "1.0",
                "limitPx": "3000",
            },
        ]

        mock_info_instance = MagicMock()
        mock_info_class = MagicMock(return_value=mock_info_instance)
        mock_exchange = MagicMock()
        mock_constants = MagicMock()
        mock_constants.TESTNET_API_URL = "https://api.hyperliquid-testnet.xyz"
        mock_constants.MAINNET_API_URL = "https://api.hyperliquid.xyz"

        with patch.dict(sys.modules, {
            'hyperliquid.info': MagicMock(Info=mock_info_class),
            'hyperliquid.exchange': MagicMock(Exchange=mock_exchange),
            'hyperliquid.utils': MagicMock(constants=mock_constants),
        }):
            await live_exchange.connect()

        with patch("asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
            mock_thread.return_value = mock_orders

            orders = await live_exchange.get_open_orders()

            assert len(orders) == 2
            assert orders[0].order_id == "12345"
            assert orders[0].side == OrderSide.BUY
            assert orders[1].side == OrderSide.SELL


# =============================================================================
# Test Retry Logic
# =============================================================================


class TestRetryLogic:
    """Tests for retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_decorator_logic(self):
        """Test the retry decorator behavior using mock mode exchange."""
        # Test via mock mode - verifies the decorator doesn't break normal operation
        with patch.dict(os.environ, {}, clear=True):
            exchange = HyperliquidExchange(testnet=True)

        await exchange.connect()
        # If retry logic is broken, this would fail
        markets = await exchange.get_markets()
        assert len(markets) == 3  # Mock returns 3 markets

    @pytest.mark.asyncio
    async def test_retry_preserves_exceptions(self):
        """Test that non-retryable exceptions propagate correctly."""
        with patch.dict(os.environ, {}, clear=True):
            exchange = HyperliquidExchange(testnet=True)

        # Connection errors should propagate after retries
        with pytest.raises(ConnectionError):
            await exchange.get_markets()  # Not connected


# =============================================================================
# Test Configuration Options
# =============================================================================


class TestConfiguration:
    """Tests for exchange configuration."""

    def test_testnet_url(self):
        with patch.dict(os.environ, {}, clear=True):
            exchange = HyperliquidExchange(testnet=True)
        assert exchange._api_url == HyperliquidExchange.TESTNET_API_URL

    def test_mainnet_url(self):
        with patch.dict(os.environ, {}, clear=True):
            exchange = HyperliquidExchange(testnet=False)
        assert exchange._api_url == HyperliquidExchange.MAINNET_API_URL

    def test_custom_credentials(self):
        exchange = HyperliquidExchange(
            testnet=True,
            private_key="0xcustom",
            wallet_address="0xwallet",
        )
        assert exchange._private_key == "0xcustom"
        assert exchange._wallet_address == "0xwallet"
        assert exchange.is_mock is False


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.fixture
    def mock_exchange(self):
        with patch.dict(os.environ, {}, clear=True):
            exchange = HyperliquidExchange(testnet=True)
        return exchange

    @pytest.mark.asyncio
    async def test_order_with_client_id(self, mock_exchange):
        await mock_exchange.connect()
        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.1"),
            price=Decimal("45000"),
            client_order_id="my-custom-id-123",
        )
        assert order.order_id == "my-custom-id-123"

    @pytest.mark.asyncio
    async def test_reduce_only_order(self, mock_exchange):
        await mock_exchange.connect()

        # First create a position (use small quantity to fit balance)
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Place reduce only order
        order = await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal("0.05"),
            price=Decimal("55000"),
            reduce_only=True,
        )
        assert order.reduce_only is True

    @pytest.mark.asyncio
    async def test_stop_order_requires_stop_price(self, mock_exchange):
        await mock_exchange.connect()
        with pytest.raises(OrderError, match="Stop price required"):
            await mock_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.SELL,
                order_type=OrderType.STOP_MARKET,
                quantity=Decimal("0.1"),
            )

    @pytest.mark.asyncio
    async def test_filter_positions_by_symbol(self, mock_exchange):
        await mock_exchange.connect()

        # Create positions in different symbols (use small quantities to fit balance)
        # Mock uses 50000 as default price, so 0.05 BTC = 2500 USDC, 0.1 ETH = 5000 USDC
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.05"),
        )
        await mock_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),  # 0.1 * 50000 = 5000 USDC (within 10000 balance)
        )

        # Filter by symbol
        btc_positions = await mock_exchange.get_positions("BTC-PERP")
        assert len(btc_positions) == 1
        assert btc_positions[0].symbol == "BTC-PERP"

    @pytest.mark.asyncio
    async def test_time_in_force_options(self, mock_exchange):
        await mock_exchange.connect()

        for tif in ["GTC", "IOC", "FOK"]:
            order = await mock_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("0.1"),
                price=Decimal("45000"),
                time_in_force=tif,
            )
            assert order.time_in_force == tif

    @pytest.mark.asyncio
    async def test_zero_quantity_position_removed(self, mock_exchange):
        await mock_exchange.connect()

        # Open position
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Close exact same quantity
        await mock_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
            reduce_only=True,
        )

        # Position should be removed
        positions = await mock_exchange.get_positions()
        btc_positions = [p for p in positions if p.symbol == "BTC-PERP"]
        assert len(btc_positions) == 0


# =============================================================================
# Run tests
# =============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
