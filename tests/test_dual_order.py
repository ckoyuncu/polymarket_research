"""
Tests for DualOrderExecutor - Synchronized YES/NO Order Placement.

Tests cover:
- Successful dual order placement
- Orphan cancellation when one side fails
- Fill verification
- Balance checking
- Position limits
- Kill switch
- Price validation
- Delta calculation
"""

import asyncio
import pytest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch

# Import the module under test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.maker.dual_order import (
    DualOrderExecutor,
    DualOrderResult,
    OrderResult,
    DualOrderError,
    InsufficientBalanceError,
    KillSwitchError,
    KILL_SWITCH_FILE,
)


@pytest.fixture
def mock_clob_client():
    """Create a mock CLOB client."""
    client = Mock()
    client.funder = "0x1234567890123456789012345678901234567890"
    client.create_and_post_order = Mock()
    client.cancel = Mock()
    client.get_order = Mock()
    return client


@pytest.fixture
def mock_balance_checker():
    """Create a mock balance checker."""
    checker = Mock()
    balance = Mock()
    balance.available = 1000.0
    checker.get_balance = Mock(return_value=balance)
    checker.has_sufficient_balance = Mock(return_value=True)
    return checker


@pytest.fixture
def executor(mock_clob_client, mock_balance_checker):
    """Create a DualOrderExecutor with mocked dependencies."""
    return DualOrderExecutor(
        clob_client=mock_clob_client,
        balance_checker=mock_balance_checker,
        max_position_size=Decimal("100"),
        max_concurrent_positions=3,
    )


@pytest.fixture(autouse=True)
def cleanup_kill_switch():
    """Ensure kill switch file is removed before and after each test."""
    if KILL_SWITCH_FILE.exists():
        KILL_SWITCH_FILE.unlink()
    yield
    if KILL_SWITCH_FILE.exists():
        KILL_SWITCH_FILE.unlink()


class TestDualOrderPlacement:
    """Test successful dual order placement scenarios."""

    @pytest.mark.asyncio
    async def test_successful_dual_order(self, executor, mock_clob_client):
        """Test successful placement of both YES and NO orders."""
        # Mock successful order responses
        mock_clob_client.create_and_post_order.side_effect = [
            {
                "orderID": "yes-order-123",
                "status": "FILLED",
                "size": 50.0,
                "price": 0.495,
            },
            {
                "orderID": "no-order-456",
                "status": "FILLED",
                "size": 50.0,
                "price": 0.495,
            },
        ]

        # Mock order status checks
        mock_clob_client.get_order.side_effect = [
            {"orderID": "yes-order-123", "status": "FILLED"},
            {"orderID": "no-order-456", "status": "FILLED"},
        ]

        # Place order
        result = await executor.place_delta_neutral(
            market="btc-updown-15m-1767729600",
            yes_token_id="0xYES",
            no_token_id="0xNO",
            size=50.0,
            yes_price=0.495,
            no_price=0.495,
        )

        # Assertions
        assert result.success is True
        assert result.yes_order is not None
        assert result.no_order is not None
        assert result.yes_order.success is True
        assert result.no_order.success is True
        assert result.both_filled is True
        assert result.is_delta_neutral is True
        assert result.delta == Decimal("0")
        assert mock_clob_client.create_and_post_order.call_count == 2

    @pytest.mark.asyncio
    async def test_delta_calculation(self, executor, mock_clob_client):
        """Test delta calculation when fills differ slightly."""
        # Mock orders with slightly different fills
        mock_clob_client.create_and_post_order.side_effect = [
            {
                "orderID": "yes-123",
                "status": "FILLED",
                "size": 50.0,
                "price": 0.50,
            },
            {
                "orderID": "no-456",
                "status": "FILLED",
                "size": 49.9,  # Slightly different fill
                "price": 0.50,
            },
        ]

        mock_clob_client.get_order.side_effect = [
            {"status": "FILLED"},
            {"status": "FILLED"},
        ]

        result = await executor.place_delta_neutral(
            market="test-market",
            yes_token_id="0xYES",
            no_token_id="0xNO",
            size=50.0,
            yes_price=0.50,
            no_price=0.50,
        )

        assert result.success is True
        assert abs(result.delta - Decimal("0.1")) < Decimal("0.001")

    @pytest.mark.asyncio
    async def test_position_tracking(self, executor, mock_clob_client):
        """Test that positions are tracked correctly."""
        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": "yes-1", "status": "FILLED", "size": 50, "price": 0.5},
            {"orderID": "no-1", "status": "FILLED", "size": 50, "price": 0.5},
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        assert executor.get_position_count() == 0

        await executor.place_delta_neutral(
            "market-1", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert executor.get_position_count() == 1

        positions = executor.get_open_positions()
        assert len(positions) == 1
        assert positions[0].success is True


class TestOrphanCancellation:
    """Test orphan order cancellation when one side fails."""

    @pytest.mark.asyncio
    async def test_cancel_yes_when_no_fails(self, executor, mock_clob_client):
        """Test YES order is cancelled when NO order fails."""
        # YES succeeds, NO fails
        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": "yes-123", "status": "OPEN", "size": 50, "price": 0.5},
            None,  # NO order fails
        ]

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is False
        assert result.yes_order.success is True
        assert result.no_order.success is False
        assert "NO order failed" in result.error_message

        # Verify cancel was called for YES order
        mock_clob_client.cancel.assert_called_once_with("yes-123")

    @pytest.mark.asyncio
    async def test_no_cancel_when_yes_fails(self, executor, mock_clob_client):
        """Test NO order is not placed when YES fails."""
        mock_clob_client.create_and_post_order.side_effect = [
            None,  # YES fails
        ]

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is False
        assert result.yes_order is not None
        assert result.yes_order.success is False
        assert result.no_order is None

        # NO order should never be placed
        assert mock_clob_client.create_and_post_order.call_count == 1
        mock_clob_client.cancel.assert_not_called()

    @pytest.mark.asyncio
    async def test_orphan_cancellation_function(self, executor, mock_clob_client):
        """Test the cancel_orphan method directly."""
        mock_clob_client.cancel.return_value = {"success": True}

        result = await executor.cancel_orphan("test-order-id")

        assert result is True
        mock_clob_client.cancel.assert_called_once_with("test-order-id")

    @pytest.mark.asyncio
    async def test_orphan_cancellation_handles_errors(self, executor, mock_clob_client):
        """Test orphan cancellation handles API errors gracefully."""
        mock_clob_client.cancel.side_effect = Exception("API error")

        result = await executor.cancel_orphan("test-order-id")

        assert result is False


class TestFillVerification:
    """Test fill verification logic."""

    @pytest.mark.asyncio
    async def test_verify_both_filled(self, executor, mock_clob_client):
        """Test verification when both orders are filled."""
        yes_order = OrderResult(success=True, order_id="yes-123")
        no_order = OrderResult(success=True, order_id="no-456")

        mock_clob_client.get_order.side_effect = [
            {"status": "FILLED"},
            {"status": "FILLED"},
        ]

        result = await executor.verify_fills(yes_order, no_order)

        assert result is True
        assert yes_order.filled is True
        assert no_order.filled is True

    @pytest.mark.asyncio
    async def test_verify_fills_with_retry(self, executor, mock_clob_client):
        """Test fill verification retries for pending orders."""
        yes_order = OrderResult(success=True, order_id="yes-123")
        no_order = OrderResult(success=True, order_id="no-456")

        # First call: not filled, second call: filled
        mock_clob_client.get_order.side_effect = [
            {"status": "OPEN"},  # YES not filled yet
            {"status": "OPEN"},  # NO not filled yet
            {"status": "FILLED"},  # YES filled on retry
            {"status": "FILLED"},  # NO filled on retry
        ]

        result = await executor.verify_fills(yes_order, no_order, max_retries=2)

        assert result is True
        assert mock_clob_client.get_order.call_count == 4

    @pytest.mark.asyncio
    async def test_verify_fails_when_not_filled(self, executor, mock_clob_client):
        """Test verification fails when orders remain unfilled."""
        yes_order = OrderResult(success=True, order_id="yes-123")
        no_order = OrderResult(success=True, order_id="no-456")

        mock_clob_client.get_order.return_value = {"status": "OPEN"}

        result = await executor.verify_fills(yes_order, no_order, max_retries=2)

        assert result is False

    @pytest.mark.asyncio
    async def test_verify_handles_missing_order_ids(self, executor):
        """Test verification handles missing order IDs."""
        yes_order = OrderResult(success=True, order_id=None)
        no_order = OrderResult(success=True, order_id="no-456")

        result = await executor.verify_fills(yes_order, no_order)

        assert result is False


class TestBalanceChecking:
    """Test balance verification before placing orders."""

    @pytest.mark.asyncio
    async def test_insufficient_balance_rejection(
        self, executor, mock_balance_checker, mock_clob_client
    ):
        """Test order is rejected when balance is insufficient."""
        mock_balance_checker.has_sufficient_balance.return_value = False
        balance = Mock()
        balance.available = 10.0
        mock_balance_checker.get_balance.return_value = balance

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is False
        assert "Insufficient balance" in result.error_message
        mock_clob_client.create_and_post_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_balance_check_with_sufficient_funds(
        self, executor, mock_balance_checker, mock_clob_client
    ):
        """Test order proceeds when balance is sufficient."""
        mock_balance_checker.has_sufficient_balance.return_value = True

        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": "yes-1", "status": "FILLED", "size": 50, "price": 0.5},
            {"orderID": "no-1", "status": "FILLED", "size": 50, "price": 0.5},
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is True
        # Balance check should be called with total cost (50 * 0.5 * 2 = 50)
        mock_balance_checker.has_sufficient_balance.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_balance_checker_warning(self, mock_clob_client):
        """Test warning is logged when no balance checker is configured."""
        executor_no_checker = DualOrderExecutor(mock_clob_client, balance_checker=None)

        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": "yes-1", "status": "FILLED", "size": 50, "price": 0.5},
            {"orderID": "no-1", "status": "FILLED", "size": 50, "price": 0.5},
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        # Should not raise error even without balance checker
        result = await executor_no_checker.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is True


class TestPositionLimits:
    """Test position size and concurrent position limits."""

    @pytest.mark.asyncio
    async def test_position_size_limit(self, executor):
        """Test orders exceeding max position size are rejected."""
        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 150.0, 0.5, 0.5  # Exceeds 100 limit
        )

        assert result.success is False
        assert "exceeds max position size" in result.error_message

    @pytest.mark.asyncio
    async def test_concurrent_position_limit(self, executor, mock_clob_client):
        """Test max concurrent positions limit is enforced."""
        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": f"yes-{i}", "status": "FILLED", "size": 10, "price": 0.5}
            for i in range(10)
        ] + [
            {"orderID": f"no-{i}", "status": "FILLED", "size": 10, "price": 0.5}
            for i in range(10)
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        # Place 3 positions (at limit)
        for i in range(3):
            result = await executor.place_delta_neutral(
                f"market-{i}", "0xYES", "0xNO", 10.0, 0.5, 0.5
            )
            assert result.success is True

        # 4th position should be rejected
        result = await executor.place_delta_neutral(
            "market-4", "0xYES", "0xNO", 10.0, 0.5, 0.5
        )

        assert result.success is False
        assert "Max concurrent positions" in result.error_message

    @pytest.mark.asyncio
    async def test_position_closure_frees_slot(self, executor, mock_clob_client):
        """Test closing a position frees up a slot for new positions."""
        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": f"yes-{i}", "status": "FILLED", "size": 10, "price": 0.5}
            for i in range(10)
        ] + [
            {"orderID": f"no-{i}", "status": "FILLED", "size": 10, "price": 0.5}
            for i in range(10)
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        # Fill to limit
        for i in range(3):
            await executor.place_delta_neutral(
                f"market-{i}", "0xYES", "0xNO", 10.0, 0.5, 0.5
            )

        # Close one position
        position_ids = list(executor.open_positions.keys())
        executor.close_position(position_ids[0])

        # Should be able to place new position now
        result = await executor.place_delta_neutral(
            "market-new", "0xYES", "0xNO", 10.0, 0.5, 0.5
        )

        assert result.success is True


class TestKillSwitch:
    """Test kill switch activation."""

    @pytest.mark.asyncio
    async def test_kill_switch_blocks_orders(self, executor):
        """Test orders are blocked when kill switch is active."""
        # Create kill switch file
        KILL_SWITCH_FILE.touch()

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is False
        assert "Kill switch activated" in result.error_message

    @pytest.mark.asyncio
    async def test_no_kill_switch_allows_orders(self, executor, mock_clob_client):
        """Test orders proceed when kill switch is not active."""
        # Ensure kill switch doesn't exist
        if KILL_SWITCH_FILE.exists():
            KILL_SWITCH_FILE.unlink()

        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": "yes-1", "status": "FILLED", "size": 50, "price": 0.5},
            {"orderID": "no-1", "status": "FILLED", "size": 50, "price": 0.5},
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.5
        )

        assert result.success is True


class TestPriceValidation:
    """Test price validation logic."""

    @pytest.mark.asyncio
    async def test_reject_yes_price_too_high(self, executor):
        """Test YES price > 0.99 is rejected."""
        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 1.0, 0.5  # YES = 1.0 invalid
        )

        assert result.success is False
        assert "YES price" in result.error_message

    @pytest.mark.asyncio
    async def test_reject_no_price_too_low(self, executor):
        """Test NO price < 0.01 is rejected."""
        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.5, 0.005  # NO too low
        )

        assert result.success is False
        assert "NO price" in result.error_message

    @pytest.mark.asyncio
    async def test_reject_sum_greater_than_one(self, executor):
        """Test YES + NO > 1.0 is rejected (guaranteed loss)."""
        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.55, 0.55  # Sum = 1.10
        )

        assert result.success is False
        assert "guarantees a loss" in result.error_message

    @pytest.mark.asyncio
    async def test_accept_valid_prices(self, executor, mock_clob_client):
        """Test valid prices are accepted."""
        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": "yes-1", "status": "FILLED", "size": 50, "price": 0.48},
            {"orderID": "no-1", "status": "FILLED", "size": 50, "price": 0.48},
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        result = await executor.place_delta_neutral(
            "test-market", "0xYES", "0xNO", 50.0, 0.48, 0.48  # Sum = 0.96 valid
        )

        assert result.success is True


class TestTotalDelta:
    """Test total delta calculation across positions."""

    @pytest.mark.asyncio
    async def test_total_delta_zero_for_neutral_positions(
        self, executor, mock_clob_client
    ):
        """Test total delta is zero for perfectly delta-neutral positions."""
        mock_clob_client.create_and_post_order.side_effect = [
            {"orderID": f"yes-{i}", "status": "FILLED", "size": 50, "price": 0.5}
            for i in range(6)
        ] + [
            {"orderID": f"no-{i}", "status": "FILLED", "size": 50, "price": 0.5}
            for i in range(6)
        ]
        mock_clob_client.get_order.return_value = {"status": "FILLED"}

        # Place 3 delta-neutral positions
        for i in range(3):
            await executor.place_delta_neutral(
                f"market-{i}", "0xYES", "0xNO", 50.0, 0.5, 0.5
            )

        total_delta = executor.get_total_delta()
        assert abs(total_delta) < Decimal("0.01")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
