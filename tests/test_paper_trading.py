"""
Comprehensive tests for the Paper Trading Exchange.

Tests cover:
- Connection and disconnection
- Order placement (market and limit)
- Position tracking (long and short)
- P&L calculation (realized and unrealized)
- Position flipping (long to short and vice versa)
- Weighted average entry price
- Trade logging
- Balance updates
- Reset functionality
- Edge cases
"""

import asyncio
import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from src.exchanges.base import (
    InsufficientBalanceError,
    OrderError,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from src.exchanges.paper import PaperExchange


@pytest.fixture
def paper_exchange():
    """Create a paper exchange instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_trades.jsonl"
        exchange = PaperExchange(
            initial_balance=Decimal("10000"),
            slippage_bps=Decimal("0"),
            log_trades=True,
            log_path=str(log_path),
        )
        yield exchange


@pytest.fixture
def paper_exchange_no_logging():
    """Create a paper exchange without trade logging."""
    return PaperExchange(
        initial_balance=Decimal("10000"),
        log_trades=False,
    )


class TestConnection:
    """Tests for connection and disconnection."""

    @pytest.mark.asyncio
    async def test_connect(self, paper_exchange):
        """Test connecting to paper exchange."""
        assert not paper_exchange.is_connected
        await paper_exchange.connect()
        assert paper_exchange.is_connected

    @pytest.mark.asyncio
    async def test_disconnect(self, paper_exchange):
        """Test disconnecting from paper exchange."""
        await paper_exchange.connect()
        assert paper_exchange.is_connected
        await paper_exchange.disconnect()
        assert not paper_exchange.is_connected

    @pytest.mark.asyncio
    async def test_exchange_name(self, paper_exchange):
        """Test exchange name property."""
        assert paper_exchange.name == "paper"

    @pytest.mark.asyncio
    async def test_repr(self, paper_exchange):
        """Test string representation."""
        repr_str = repr(paper_exchange)
        assert "PaperExchange" in repr_str
        assert "mock" in repr_str


class TestMarkets:
    """Tests for market information."""

    @pytest.mark.asyncio
    async def test_get_markets(self, paper_exchange):
        """Test getting available markets."""
        markets = await paper_exchange.get_markets()
        assert len(markets) >= 3
        symbols = [m.symbol for m in markets]
        assert "BTC-PERP" in symbols
        assert "ETH-PERP" in symbols

    @pytest.mark.asyncio
    async def test_get_market_exists(self, paper_exchange):
        """Test getting a specific market that exists."""
        market = await paper_exchange.get_market("BTC-PERP")
        assert market is not None
        assert market.symbol == "BTC-PERP"
        assert market.base_currency == "BTC"
        assert market.quote_currency == "USD"

    @pytest.mark.asyncio
    async def test_get_market_not_exists(self, paper_exchange):
        """Test getting a market that doesn't exist."""
        market = await paper_exchange.get_market("NONEXISTENT")
        assert market is None


class TestBalance:
    """Tests for balance tracking."""

    @pytest.mark.asyncio
    async def test_initial_balance(self, paper_exchange):
        """Test initial balance is set correctly."""
        balances = await paper_exchange.get_balance()
        assert len(balances) == 1
        assert balances[0].total == Decimal("10000")
        assert balances[0].available == Decimal("10000")
        assert balances[0].currency == "USD"

    @pytest.mark.asyncio
    async def test_balance_after_profitable_trade(self, paper_exchange):
        """Test balance updates after a profitable trade."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        # Buy 1 BTC
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Price rises
        paper_exchange.set_price("BTC-PERP", Decimal("51000"))

        # Sell 1 BTC
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        balances = await paper_exchange.get_balance()
        # Should have gained $1000
        assert balances[0].total == Decimal("11000")

    @pytest.mark.asyncio
    async def test_balance_filter_currency(self, paper_exchange):
        """Test balance filtering by currency."""
        balances = await paper_exchange.get_balance(currency="BTC")
        assert len(balances) == 0  # No BTC balance, only USD


class TestOrderPlacement:
    """Tests for order placement."""

    @pytest.mark.asyncio
    async def test_market_buy_order(self, paper_exchange):
        """Test placing a market buy order."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
        )

        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == Decimal("0.5")
        assert order.average_fill_price == Decimal("50000")
        assert order.symbol == "BTC-PERP"
        assert order.side == OrderSide.BUY

    @pytest.mark.asyncio
    async def test_market_sell_order(self, paper_exchange):
        """Test placing a market sell order."""
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        order = await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        assert order.status == OrderStatus.FILLED
        assert order.side == OrderSide.SELL

    @pytest.mark.asyncio
    async def test_limit_buy_order(self, paper_exchange):
        """Test placing a limit buy order."""
        order = await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1"),
            price=Decimal("49000"),
        )

        assert order.status == OrderStatus.FILLED
        assert order.average_fill_price == Decimal("49000")

    @pytest.mark.asyncio
    async def test_limit_order_without_price_raises(self, paper_exchange):
        """Test that limit order without price raises error."""
        with pytest.raises(OrderError, match="Limit orders require a price"):
            await paper_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal("1"),
            )

    @pytest.mark.asyncio
    async def test_invalid_quantity_raises(self, paper_exchange):
        """Test that zero/negative quantity raises error."""
        with pytest.raises(OrderError, match="quantity must be positive"):
            await paper_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("0"),
            )

    @pytest.mark.asyncio
    async def test_insufficient_balance_raises(self, paper_exchange):
        """Test that insufficient balance raises error."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        with pytest.raises(InsufficientBalanceError):
            await paper_exchange.place_order(
                symbol="BTC-PERP",
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                quantity=Decimal("1000"),  # Way more than balance
            )

    @pytest.mark.asyncio
    async def test_order_with_client_id(self, paper_exchange):
        """Test order with custom client order ID."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
            client_order_id="my-custom-id-123",
        )

        assert order.client_order_id == "my-custom-id-123"


class TestOrderManagement:
    """Tests for order retrieval and cancellation."""

    @pytest.mark.asyncio
    async def test_get_order(self, paper_exchange):
        """Test getting an order by ID."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
        )

        retrieved = await paper_exchange.get_order(order.order_id)
        assert retrieved is not None
        assert retrieved.order_id == order.order_id

    @pytest.mark.asyncio
    async def test_get_order_not_found(self, paper_exchange):
        """Test getting a non-existent order."""
        retrieved = await paper_exchange.get_order("nonexistent-id")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_get_open_orders_empty(self, paper_exchange):
        """Test that open orders is empty (all orders fill instantly)."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
        )

        open_orders = await paper_exchange.get_open_orders()
        assert len(open_orders) == 0  # All orders fill instantly

    @pytest.mark.asyncio
    async def test_cancel_filled_order_raises(self, paper_exchange):
        """Test that cancelling a filled order raises error."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
        )

        with pytest.raises(OrderError, match="Cannot cancel filled order"):
            await paper_exchange.cancel_order(order.order_id)

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order_raises(self, paper_exchange):
        """Test that cancelling non-existent order raises error."""
        with pytest.raises(OrderError, match="Order not found"):
            await paper_exchange.cancel_order("nonexistent-id")


class TestPositionTracking:
    """Tests for position tracking."""

    @pytest.mark.asyncio
    async def test_long_position_created(self, paper_exchange):
        """Test that buying creates a long position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "BTC-PERP"
        assert positions[0].side == PositionSide.LONG
        assert positions[0].quantity == Decimal("1")
        assert positions[0].entry_price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_short_position_created(self, paper_exchange):
        """Test that selling creates a short position."""
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].side == PositionSide.SHORT
        assert positions[0].quantity == Decimal("5")

    @pytest.mark.asyncio
    async def test_position_filter_by_symbol(self, paper_exchange):
        """Test filtering positions by symbol."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        btc_positions = await paper_exchange.get_positions("BTC-PERP")
        assert len(btc_positions) == 1
        assert btc_positions[0].symbol == "BTC-PERP"

        nonexistent = await paper_exchange.get_positions("SOL-PERP")
        assert len(nonexistent) == 0

    @pytest.mark.asyncio
    async def test_weighted_average_entry_price(self, paper_exchange):
        """Test that adding to position uses weighted average entry."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        # Buy 1 BTC at $50,000
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Buy 1 more BTC at $52,000
        paper_exchange.set_price("BTC-PERP", Decimal("52000"))
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].quantity == Decimal("2")
        # Weighted average: (1 * 50000 + 1 * 52000) / 2 = 51000
        assert positions[0].entry_price == Decimal("51000")

    @pytest.mark.asyncio
    async def test_position_closed_when_fully_sold(self, paper_exchange):
        """Test that position is removed when fully closed."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 0


class TestPositionFlipping:
    """Tests for flipping positions from long to short and vice versa."""

    @pytest.mark.asyncio
    async def test_flip_long_to_short(self, paper_exchange):
        """Test flipping from long to short position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        # Open long position: 1 BTC
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Sell 2 BTC (close long, open short)
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].side == PositionSide.SHORT
        assert positions[0].quantity == Decimal("1")
        assert positions[0].entry_price == Decimal("50000")

    @pytest.mark.asyncio
    async def test_flip_short_to_long(self, paper_exchange):
        """Test flipping from short to long position."""
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        # Open short position: 5 ETH
        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
        )

        # Buy 8 ETH (close short, open long 3)
        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("8"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 1
        assert positions[0].side == PositionSide.LONG
        assert positions[0].quantity == Decimal("3")


class TestPnLCalculation:
    """Tests for P&L calculation."""

    @pytest.mark.asyncio
    async def test_unrealized_pnl_long_profit(self, paper_exchange):
        """Test unrealized P&L for profitable long position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Price rises by $1000
        paper_exchange.set_price("BTC-PERP", Decimal("51000"))

        positions = await paper_exchange.get_positions()
        assert positions[0].unrealized_pnl == Decimal("1000")

    @pytest.mark.asyncio
    async def test_unrealized_pnl_long_loss(self, paper_exchange):
        """Test unrealized P&L for losing long position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Price drops by $2000
        paper_exchange.set_price("BTC-PERP", Decimal("48000"))

        positions = await paper_exchange.get_positions()
        assert positions[0].unrealized_pnl == Decimal("-2000")

    @pytest.mark.asyncio
    async def test_unrealized_pnl_short_profit(self, paper_exchange):
        """Test unrealized P&L for profitable short position."""
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )

        # Price drops by $100 (profit for short)
        paper_exchange.set_price("ETH-PERP", Decimal("2900"))

        positions = await paper_exchange.get_positions()
        # P&L = (3000 - 2900) * 10 = 1000
        assert positions[0].unrealized_pnl == Decimal("1000")

    @pytest.mark.asyncio
    async def test_unrealized_pnl_short_loss(self, paper_exchange):
        """Test unrealized P&L for losing short position."""
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )

        # Price rises by $200 (loss for short)
        paper_exchange.set_price("ETH-PERP", Decimal("3200"))

        positions = await paper_exchange.get_positions()
        # P&L = (3000 - 3200) * 10 = -2000
        assert positions[0].unrealized_pnl == Decimal("-2000")

    @pytest.mark.asyncio
    async def test_realized_pnl_on_close(self, paper_exchange):
        """Test realized P&L when closing position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.set_price("BTC-PERP", Decimal("51000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        assert paper_exchange.realized_pnl == Decimal("1000")
        assert paper_exchange.balance == Decimal("11000")

    @pytest.mark.asyncio
    async def test_realized_pnl_partial_close(self, paper_exchange):
        """Test realized P&L when partially closing position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        paper_exchange.set_price("BTC-PERP", Decimal("51000"))

        # Sell only 0.5 BTC
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
        )

        # Realized P&L = (51000 - 50000) * 0.5 = 500
        assert paper_exchange.realized_pnl == Decimal("500")

        # Still have 1.5 BTC position
        positions = await paper_exchange.get_positions()
        assert positions[0].quantity == Decimal("1.5")

    @pytest.mark.asyncio
    async def test_pnl_summary(self, paper_exchange):
        """Test P&L summary report."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.set_price("BTC-PERP", Decimal("51000"))

        summary = paper_exchange.get_pnl_summary()

        assert summary["initial_balance"] == "10000"
        assert summary["unrealized_pnl"] == "1000"
        assert summary["total_trades"] == 1
        assert summary["open_positions"] == 1


class TestSlippage:
    """Tests for slippage simulation."""

    @pytest.mark.asyncio
    async def test_slippage_on_buy(self):
        """Test slippage is applied to buy orders."""
        exchange = PaperExchange(
            initial_balance=Decimal("10000"),
            slippage_bps=Decimal("10"),  # 0.1% slippage
            log_trades=False,
        )
        exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Slippage = 50000 * 10 / 10000 = 50
        # Fill price = 50000 + 50 = 50050
        assert order.average_fill_price == Decimal("50050")

    @pytest.mark.asyncio
    async def test_slippage_on_sell(self):
        """Test slippage is applied to sell orders."""
        exchange = PaperExchange(
            initial_balance=Decimal("10000"),
            slippage_bps=Decimal("10"),  # 0.1% slippage
            log_trades=False,
        )
        exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        # Slippage = 50000 * 10 / 10000 = 50
        # Fill price = 50000 - 50 = 49950
        assert order.average_fill_price == Decimal("49950")


class TestTradeLogging:
    """Tests for trade logging to JSONL file."""

    @pytest.mark.asyncio
    async def test_trade_logged_to_file(self, paper_exchange):
        """Test that trades are logged to JSONL file."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        # Read log file
        with open(paper_exchange.log_path) as f:
            lines = f.readlines()

        assert len(lines) >= 1
        trade = json.loads(lines[-1])
        assert trade["symbol"] == "BTC-PERP"
        assert trade["side"] == "buy"
        assert trade["quantity"] == "1"
        assert trade["price"] == "50000"

    @pytest.mark.asyncio
    async def test_trade_history_in_memory(self, paper_exchange):
        """Test trade history is maintained in memory."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.5"),
        )

        history = paper_exchange.get_trade_history()
        assert len(history) == 2
        assert history[0]["side"] == "buy"
        assert history[1]["side"] == "sell"

    @pytest.mark.asyncio
    async def test_connect_disconnect_logged(self, paper_exchange):
        """Test that connect/disconnect events are logged."""
        await paper_exchange.connect()
        await paper_exchange.disconnect()

        with open(paper_exchange.log_path) as f:
            lines = f.readlines()

        events = [json.loads(line) for line in lines]
        event_types = [e.get("event") for e in events]
        assert "CONNECTED" in event_types
        assert "DISCONNECTED" in event_types


class TestReset:
    """Tests for reset functionality."""

    @pytest.mark.asyncio
    async def test_reset_clears_positions(self, paper_exchange):
        """Test that reset clears all positions."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.reset()

        positions = await paper_exchange.get_positions()
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_reset_restores_balance(self, paper_exchange):
        """Test that reset restores initial balance."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.set_price("BTC-PERP", Decimal("51000"))
        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.reset()

        balances = await paper_exchange.get_balance()
        assert balances[0].total == Decimal("10000")
        assert paper_exchange.realized_pnl == Decimal("0")

    @pytest.mark.asyncio
    async def test_reset_clears_orders(self, paper_exchange):
        """Test that reset clears order history."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        order = await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.reset()

        retrieved = await paper_exchange.get_order(order.order_id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_reset_clears_trade_history(self, paper_exchange):
        """Test that reset clears trade history."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        paper_exchange.reset()

        history = paper_exchange.get_trade_history()
        assert len(history) == 0


class TestClosePosition:
    """Tests for close_position helper method."""

    @pytest.mark.asyncio
    async def test_close_long_position(self, paper_exchange):
        """Test closing a long position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        order = await paper_exchange.close_position("BTC-PERP")

        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == Decimal("1")

        positions = await paper_exchange.get_positions()
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_close_short_position(self, paper_exchange):
        """Test closing a short position."""
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))

        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("5"),
        )

        order = await paper_exchange.close_position("ETH-PERP")

        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.quantity == Decimal("5")

    @pytest.mark.asyncio
    async def test_close_position_partial(self, paper_exchange):
        """Test partially closing a position."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        order = await paper_exchange.close_position("BTC-PERP", quantity=Decimal("1"))

        assert order is not None
        assert order.quantity == Decimal("1")

        positions = await paper_exchange.get_positions()
        assert positions[0].quantity == Decimal("1")

    @pytest.mark.asyncio
    async def test_close_position_no_position(self, paper_exchange):
        """Test closing when no position exists."""
        order = await paper_exchange.close_position("BTC-PERP")
        assert order is None


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_multiple_symbols(self, paper_exchange):
        """Test managing positions across multiple symbols."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))
        paper_exchange.set_price("ETH-PERP", Decimal("3000"))
        paper_exchange.set_price("SOL-PERP", Decimal("100"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.1"),
        )

        await paper_exchange.place_order(
            symbol="ETH-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("2"),
        )

        await paper_exchange.place_order(
            symbol="SOL-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("10"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 3

    @pytest.mark.asyncio
    async def test_very_small_quantities(self, paper_exchange):
        """Test handling very small quantities."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("0.00001"),
        )

        positions = await paper_exchange.get_positions()
        assert positions[0].quantity == Decimal("0.00001")

    @pytest.mark.asyncio
    async def test_exact_position_close(self, paper_exchange):
        """Test that exact close removes position completely."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.23456789"),
        )

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal("1.23456789"),
        )

        positions = await paper_exchange.get_positions()
        assert len(positions) == 0

    @pytest.mark.asyncio
    async def test_default_price_when_not_set(self, paper_exchange):
        """Test that orders work even when price not set."""
        # Don't set price - should use default of 100
        order = await paper_exchange.place_order(
            symbol="NEW-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        assert order.average_fill_price == Decimal("100")

    @pytest.mark.asyncio
    async def test_add_custom_market(self, paper_exchange):
        """Test adding a custom market."""
        from src.exchanges.base import Market

        custom_market = Market(
            symbol="DOGE-PERP",
            base_currency="DOGE",
            quote_currency="USD",
            min_quantity=Decimal("100"),
            max_quantity=Decimal("10000000"),
            quantity_precision=0,
            price_precision=5,
            tick_size=Decimal("0.00001"),
            lot_size=Decimal("1"),
            max_leverage=5,
        )

        paper_exchange.add_market(custom_market)

        market = await paper_exchange.get_market("DOGE-PERP")
        assert market is not None
        assert market.base_currency == "DOGE"


class TestCancelAllOrders:
    """Tests for cancel_all_orders method."""

    @pytest.mark.asyncio
    async def test_cancel_all_orders_empty(self, paper_exchange):
        """Test cancel_all_orders when no orders exist."""
        cancelled = await paper_exchange.cancel_all_orders()
        assert len(cancelled) == 0

    @pytest.mark.asyncio
    async def test_cancel_all_orders_filled(self, paper_exchange):
        """Test cancel_all_orders with filled orders (should cancel nothing)."""
        paper_exchange.set_price("BTC-PERP", Decimal("50000"))

        await paper_exchange.place_order(
            symbol="BTC-PERP",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal("1"),
        )

        cancelled = await paper_exchange.cancel_all_orders()
        assert len(cancelled) == 0  # All orders are filled, nothing to cancel
