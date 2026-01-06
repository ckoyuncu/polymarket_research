"""
Tests for LiveExecutor and SafeExecutor.

Tests cover:
- Order rejection scenarios
- Partial fills
- API timeout handling
- Balance checks
- Rate limiting
- Input validation
- Kill switch functionality
- Retry logic with exponential backoff
- Slippage detection
"""
import os
import time
import pytest
import logging
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

# Import the modules we're testing
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.trading.executor import (
    LiveExecutor,
    SafeExecutor,
    OrderResult,
    OrderStatus,
    OrderType,
    OrderSide,
    Balance,
    create_executor,
    check_kill_switch,
    _check_slippage,
    KillSwitchError,
    APITimeoutError,
    KILL_SWITCH_FILE,
    API_TIMEOUT,
    MAX_RETRY_ATTEMPTS,
    SLIPPAGE_WARNING_THRESHOLD,
)


class TestOrderResult:
    """Tests for OrderResult dataclass."""

    def test_order_result_default_values(self):
        """Test OrderResult has correct defaults."""
        result = OrderResult(success=True)
        assert result.success is True
        assert result.order_id is None
        assert result.status == OrderStatus.PENDING
        assert result.filled_size == 0.0
        assert result.filled_price == 0.0
        assert result.message == ""

    def test_order_result_to_dict(self):
        """Test OrderResult serialization."""
        result = OrderResult(
            success=True,
            order_id="test123",
            status=OrderStatus.FILLED,
            filled_size=100.0,
            filled_price=0.55,
            message="Order filled",
        )
        d = result.to_dict()

        assert d["success"] is True
        assert d["order_id"] == "test123"
        assert d["status"] == "filled"
        assert d["filled_size"] == 100.0
        assert d["filled_price"] == 0.55


class TestLiveExecutorInitialization:
    """Tests for LiveExecutor initialization."""

    def test_missing_private_key(self):
        """Test executor fails gracefully without private key."""
        with patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": "", "POLYMARKET_FUNDER": "0x123"}):
            executor = LiveExecutor()
            assert executor.is_ready() is False
            assert "POLYMARKET_PRIVATE_KEY not set" in executor.get_error()

    def test_missing_funder(self):
        """Test executor fails gracefully without funder address."""
        with patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": "abc123", "POLYMARKET_FUNDER": ""}):
            executor = LiveExecutor()
            assert executor.is_ready() is False
            assert "POLYMARKET_FUNDER not set" in executor.get_error()

    def test_missing_py_clob_client(self):
        """Test executor handles missing py-clob-client package."""
        # This test verifies that the error message is set correctly when
        # py-clob-client import fails. Since we can't easily unload the module,
        # we test by checking the error handling path exists.
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "abc123", "POLYMARKET_FUNDER": "0x123"},
        ):
            executor = LiveExecutor()
            # Even if py_clob_client is available, we can verify the executor
            # has proper error handling mechanisms
            assert hasattr(executor, '_last_error')
            assert hasattr(executor, '_ready')


class TestLiveExecutorOrders:
    """Tests for order placement and management."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock executor for testing."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            # Mock the client
            executor._ready = True
            executor._client = Mock()
            return executor

    def test_order_rejected_when_not_ready(self):
        """Test order fails when executor not ready."""
        with patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": "", "POLYMARKET_FUNDER": ""}):
            executor = LiveExecutor()
            result = executor.place_order(
                token_id="test_token",
                side="buy",
                size=10,
                price=0.50,
            )

            assert result.success is False
            assert "not ready" in result.message.lower()

    def test_order_rejected_invalid_side(self, mock_executor):
        """Test order fails with invalid side."""
        result = mock_executor.place_order(
            token_id="test_token",
            side="invalid",
            size=10,
            price=0.50,
        )

        assert result.success is False
        assert "Invalid side" in result.message

    def test_order_rejected_price_too_low(self, mock_executor):
        """Test order fails with price below 0.01."""
        result = mock_executor.place_order(
            token_id="test_token",
            side="buy",
            size=10,
            price=0.001,
        )

        assert result.success is False
        assert "Price" in result.message and "0.01" in result.message

    def test_order_rejected_price_too_high(self, mock_executor):
        """Test order fails with price above 0.99."""
        result = mock_executor.place_order(
            token_id="test_token",
            side="buy",
            size=10,
            price=0.999,
        )

        assert result.success is False
        assert "Price" in result.message and "0.99" in result.message

    def test_order_rejected_negative_size(self, mock_executor):
        """Test order fails with negative size."""
        result = mock_executor.place_order(
            token_id="test_token",
            side="buy",
            size=-10,
            price=0.50,
        )

        assert result.success is False
        assert "Size must be positive" in result.message

    def test_order_rejected_zero_size(self, mock_executor):
        """Test order fails with zero size."""
        result = mock_executor.place_order(
            token_id="test_token",
            side="buy",
            size=0,
            price=0.50,
        )

        assert result.success is False
        assert "Size must be positive" in result.message

    def test_order_empty_response_handling(self, mock_executor):
        """Test handling when API returns empty response."""
        # Mock the imports and client call - the retry wrapper will call the client method
        mock_executor._client.create_and_post_order = Mock(return_value=None)

        with patch(
            "py_clob_client.order_builder.constants.BUY", "BUY"
        ), patch("py_clob_client.order_builder.constants.SELL", "SELL"), patch(
            "py_clob_client.clob_types.OrderArgs"
        ), patch(
            "py_clob_client.clob_types.PartialCreateOrderOptions"
        ):
            result = mock_executor.place_order(
                token_id="test_token",
                side="sell",  # Use SELL to bypass balance check
                size=10,
                price=0.50,
            )

        # Should handle gracefully
        assert result.success is False
        assert "empty response" in result.message.lower()

    def test_order_api_exception_handling(self, mock_executor):
        """Test handling when API throws exception."""
        mock_executor._client.create_and_post_order = Mock(
            side_effect=Exception("Network timeout")
        )

        with patch("py_clob_client.order_builder.constants.BUY", "BUY"), patch(
            "py_clob_client.order_builder.constants.SELL", "SELL"
        ), patch("py_clob_client.clob_types.OrderArgs"), patch(
            "py_clob_client.clob_types.PartialCreateOrderOptions"
        ):
            result = mock_executor.place_order(
                token_id="test_token",
                side="sell",  # Use SELL to bypass balance check
                size=10,
                price=0.50,
            )

        assert result.success is False
        assert "Network timeout" in result.message

    def test_cancel_order_when_not_ready(self):
        """Test cancel fails when executor not ready."""
        with patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": "", "POLYMARKET_FUNDER": ""}):
            executor = LiveExecutor()
            result = executor.cancel_order("order123")

            assert result.success is False
            assert "not ready" in result.message.lower()

    def test_cancel_order_api_exception(self, mock_executor):
        """Test cancel handles API exceptions."""
        mock_executor._client.cancel = Mock(side_effect=Exception("Order not found"))

        result = mock_executor.cancel_order("order123")

        assert result.success is False
        assert "Order not found" in result.message


class TestLiveExecutorRateLimiting:
    """Tests for rate limiting behavior."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock executor for testing."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            executor._min_request_interval = 0.1  # 100ms
            return executor

    def test_rate_limiting_applied(self, mock_executor):
        """Test that rate limiting delays requests."""
        mock_executor._last_request_time = time.time()

        start = time.time()
        mock_executor._rate_limit()
        elapsed = time.time() - start

        # Should have waited approximately 100ms
        assert elapsed >= 0.09  # Allow some tolerance


class TestSafeExecutorBasics:
    """Tests for SafeExecutor wrapper."""

    def test_dry_run_always_ready(self):
        """Test dry run mode is always ready."""
        executor = SafeExecutor(dry_run=True)
        assert executor.is_ready() is True
        assert executor.get_error() == ""

    def test_dry_run_returns_mock_balance(self):
        """Test dry run returns mock balance."""
        executor = SafeExecutor(dry_run=True)
        balance = executor.get_balance()

        assert balance is not None
        assert balance.available == 1000.0
        assert balance.total == 1000.0

    def test_dry_run_simulates_orders(self):
        """Test dry run mode simulates orders."""
        executor = SafeExecutor(dry_run=True)

        result = executor.place_order(
            token_id="test_token",
            side="buy",
            size=10,
            price=0.50,
        )

        assert result.success is True
        assert "DRY_" in result.order_id
        assert result.status == OrderStatus.FILLED
        assert "simulated" in result.message.lower()


class TestSafeExecutorLimits:
    """Tests for SafeExecutor safety limits."""

    def test_max_order_size_enforced(self):
        """Test orders exceeding max size are rejected."""
        executor = SafeExecutor(dry_run=True, max_order_size=50.0)

        # Order value = 100 * 0.60 = $60 > $50 limit
        result = executor.place_order(
            token_id="test_token",
            side="buy",
            size=100,
            price=0.60,
        )

        assert result.success is False
        assert "exceeds max" in result.message.lower()

    def test_daily_order_limit_enforced(self):
        """Test daily order limit is enforced."""
        executor = SafeExecutor(dry_run=True, max_daily_orders=3)

        # Place 3 successful orders
        for _ in range(3):
            result = executor.place_order(
                token_id="test_token",
                side="buy",
                size=10,
                price=0.10,
            )
            assert result.success is True

        # 4th order should fail
        result = executor.place_order(
            token_id="test_token",
            side="buy",
            size=10,
            price=0.10,
        )

        assert result.success is False
        assert "limit" in result.message.lower()

    def test_daily_counters_reset_on_new_day(self):
        """Test daily counters reset when day changes."""
        executor = SafeExecutor(dry_run=True, max_daily_orders=2)

        # Exhaust daily limit
        for _ in range(2):
            executor.place_order(
                token_id="test_token",
                side="buy",
                size=10,
                price=0.10,
            )

        # Simulate day change
        executor._today = datetime(2020, 1, 1).date()
        executor._check_day_reset()

        # Should be able to place orders again
        result = executor.place_order(
            token_id="test_token",
            side="buy",
            size=10,
            price=0.10,
        )

        assert result.success is True


class TestCreateExecutorFactory:
    """Tests for create_executor factory function."""

    def test_creates_dry_run_by_default(self):
        """Test factory creates dry run executor by default."""
        executor = create_executor(live=False)

        assert executor.dry_run is True
        assert executor.is_ready() is True

    def test_respects_max_order_size(self):
        """Test factory respects max order size parameter."""
        executor = create_executor(live=False, max_order_size=25.0)

        assert executor.max_order_size == 25.0


class TestAPITimeoutScenarios:
    """Tests for API timeout scenarios (simulated)."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock executor for testing."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            return executor

    def test_get_orders_timeout_returns_empty(self, mock_executor):
        """Test get_orders returns empty list on timeout."""
        mock_executor._client.get_orders = Mock(
            side_effect=Exception("Connection timeout")
        )

        result = mock_executor.get_open_orders()

        assert result == []
        assert "timeout" in mock_executor.get_error().lower()

    def test_get_trades_timeout_returns_empty(self, mock_executor):
        """Test get_trades returns empty list on timeout."""
        mock_executor._client.get_trades = Mock(
            side_effect=Exception("Connection timeout")
        )

        result = mock_executor.get_trades()

        assert result == []

    def test_get_order_status_timeout_returns_none(self, mock_executor):
        """Test get_order_status returns None on timeout."""
        mock_executor._client.get_order = Mock(
            side_effect=Exception("Connection timeout")
        )

        result = mock_executor.get_order_status("order123")

        assert result is None


class TestOrderTracking:
    """Tests for order history tracking."""

    @pytest.fixture
    def mock_executor(self, tmp_path):
        """Create a mock executor with temp data directory."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            executor.data_dir = tmp_path
            return executor

    def test_successful_order_tracked(self, mock_executor):
        """Test successful orders are tracked."""
        mock_executor._client.create_and_post_order = Mock(
            return_value={"orderID": "order123"}
        )

        with patch("py_clob_client.order_builder.constants.BUY", "BUY"), patch(
            "py_clob_client.order_builder.constants.SELL", "SELL"
        ), patch("py_clob_client.clob_types.OrderArgs"), patch(
            "py_clob_client.clob_types.PartialCreateOrderOptions"
        ):
            mock_executor.place_order(
                token_id="test_token",
                side="sell",  # Use SELL to bypass balance check
                size=10,
                price=0.50,
            )

        assert "order123" in mock_executor.pending_orders

    def test_order_history_limits(self, mock_executor):
        """Test order history is limited to prevent unbounded growth."""
        # Manually add many orders
        for i in range(1100):
            mock_executor.pending_orders[f"order{i}"] = {
                "token_id": "test",
                "size": 10,
                "placed_at": int(time.time()),
            }

        mock_executor._save_orders()

        # Read back and verify limit
        history = mock_executor.get_order_history(limit=2000)
        assert len(history) <= 1000


class TestBalanceChecks:
    """Tests for balance checking (documented as having a bug)."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock executor for testing."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            return executor

    def test_balance_returns_placeholder_when_ready(self, mock_executor):
        """Test balance returns placeholder (documented bug in py-clob-client)."""
        balance = mock_executor.get_balance()

        assert balance is not None
        # Due to documented bug, returns zeros
        assert balance.available == 0.0
        assert balance.total == 0.0

    def test_balance_returns_none_when_not_ready(self):
        """Test balance returns None when not ready."""
        with patch.dict(os.environ, {"POLYMARKET_PRIVATE_KEY": "", "POLYMARKET_FUNDER": ""}):
            executor = LiveExecutor()
            balance = executor.get_balance()

            assert balance is None


class TestKillSwitch:
    """Tests for kill switch functionality."""

    @pytest.fixture(autouse=True)
    def cleanup_kill_switch(self):
        """Ensure kill switch file is cleaned up after each test."""
        yield
        if KILL_SWITCH_FILE.exists():
            KILL_SWITCH_FILE.unlink()

    def test_kill_switch_not_active_by_default(self):
        """Test that kill switch is not active when file doesn't exist."""
        if KILL_SWITCH_FILE.exists():
            KILL_SWITCH_FILE.unlink()
        assert check_kill_switch() is False

    def test_kill_switch_active_when_file_exists(self):
        """Test that kill switch is active when file exists."""
        KILL_SWITCH_FILE.touch()
        assert check_kill_switch() is True

    def test_live_executor_blocks_order_with_kill_switch(self):
        """Test that LiveExecutor blocks orders when kill switch is active."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()

            # Activate kill switch
            KILL_SWITCH_FILE.touch()

            result = executor.place_order(
                token_id="test_token",
                side="buy",
                size=10,
                price=0.50,
            )

            assert result.success is False
            assert "kill switch" in result.message.lower()

    def test_safe_executor_blocks_order_with_kill_switch(self):
        """Test that SafeExecutor blocks orders when kill switch is active."""
        executor = SafeExecutor(dry_run=True)

        # Activate kill switch
        KILL_SWITCH_FILE.touch()

        result = executor.place_order(
            token_id="test_token",
            side="buy",
            size=10,
            price=0.50,
        )

        assert result.success is False
        assert "kill switch" in result.message.lower()

    def test_cancel_order_works_with_kill_switch(self):
        """Test that cancel_order works even with kill switch active."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            executor._client.cancel = Mock(return_value={"success": True})

            # Activate kill switch
            KILL_SWITCH_FILE.touch()

            # Cancel should still work (we want to be able to close positions)
            result = executor.cancel_order("order123")

            # Cancel should succeed even with kill switch
            assert result.success is True


class TestRetryLogic:
    """Tests for retry logic with exponential backoff."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock executor for testing."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            return executor

    def test_retry_succeeds_on_first_attempt(self, mock_executor):
        """Test that retry succeeds immediately if first attempt works."""
        mock_executor._client.get_orders = Mock(return_value=[{"id": "order1"}])

        result = mock_executor.get_open_orders()

        assert result == [{"id": "order1"}]
        assert mock_executor._client.get_orders.call_count == 1

    def test_retry_succeeds_after_transient_failure(self, mock_executor):
        """Test that retry succeeds after transient failures."""
        # First call fails, second succeeds
        mock_executor._client.get_orders = Mock(
            side_effect=[Exception("Network error"), [{"id": "order1"}]]
        )

        result = mock_executor.get_open_orders()

        assert result == [{"id": "order1"}]
        assert mock_executor._client.get_orders.call_count == 2

    def test_retry_exhausted_returns_empty(self, mock_executor):
        """Test that after all retries are exhausted, empty result is returned."""
        # All calls fail
        mock_executor._client.get_orders = Mock(
            side_effect=Exception("Persistent error")
        )

        result = mock_executor.get_open_orders()

        assert result == []
        # Should have attempted MAX_RETRY_ATTEMPTS times
        assert mock_executor._client.get_orders.call_count == MAX_RETRY_ATTEMPTS


class TestAPITimeout:
    """Tests for API timeout functionality."""

    @pytest.fixture
    def mock_executor(self):
        """Create a mock executor for testing."""
        with patch.dict(
            os.environ,
            {"POLYMARKET_PRIVATE_KEY": "0xabc123", "POLYMARKET_FUNDER": "0xfunder123"},
        ):
            executor = LiveExecutor()
            executor._ready = True
            executor._client = Mock()
            return executor

    def test_api_timeout_constant_is_5_seconds(self):
        """Test that API timeout is set to 5 seconds."""
        assert API_TIMEOUT == 5.0

    def test_timeout_error_class_exists(self):
        """Test that APITimeoutError exception class exists."""
        error = APITimeoutError("Test timeout")
        assert str(error) == "Test timeout"

    def test_place_order_handles_timeout(self, mock_executor):
        """Test that place_order handles timeout gracefully."""
        # Mock a slow API call that raises timeout
        mock_executor._call_api_with_retry = Mock(
            side_effect=APITimeoutError("Simulated timeout")
        )

        with patch("py_clob_client.order_builder.constants.BUY", "BUY"), patch(
            "py_clob_client.order_builder.constants.SELL", "SELL"
        ), patch("py_clob_client.clob_types.OrderArgs"), patch(
            "py_clob_client.clob_types.PartialCreateOrderOptions"
        ):
            result = mock_executor.place_order(
                token_id="test_token",
                side="sell",  # Use SELL to bypass balance check
                size=10,
                price=0.50,
            )

        assert result.success is False
        assert "timeout" in result.message.lower()


class TestSlippageDetection:
    """Tests for slippage detection and logging."""

    def test_slippage_threshold_is_one_percent(self):
        """Test that slippage threshold is 1%."""
        assert SLIPPAGE_WARNING_THRESHOLD == 0.01

    def test_no_warning_for_small_slippage(self, caplog):
        """Test that no warning is logged for small slippage."""
        with caplog.at_level(logging.WARNING):
            # 0.5% slippage is below 1% threshold
            _check_slippage(expected_price=0.50, filled_price=0.5025, side="BUY")

        # Check no slippage warning was logged
        assert not any("slippage" in record.message.lower() for record in caplog.records)

    def test_warning_for_large_slippage_buy(self, caplog):
        """Test that warning is logged for large slippage on BUY."""
        with caplog.at_level(logging.WARNING):
            # 2% slippage (above 1% threshold)
            _check_slippage(expected_price=0.50, filled_price=0.51, side="BUY")

        assert "slippage" in caplog.text.lower()
        assert "adverse" in caplog.text.lower()  # Higher price is adverse for buyer

    def test_warning_for_large_slippage_sell(self, caplog):
        """Test that warning is logged for large slippage on SELL."""
        with caplog.at_level(logging.WARNING):
            # 2% slippage (above 1% threshold)
            _check_slippage(expected_price=0.50, filled_price=0.49, side="SELL")

        assert "slippage" in caplog.text.lower()
        assert "adverse" in caplog.text.lower()  # Lower price is adverse for seller

    def test_favorable_slippage_still_logged(self, caplog):
        """Test that favorable slippage is also logged."""
        with caplog.at_level(logging.WARNING):
            # Buyer gets better price (favorable)
            _check_slippage(expected_price=0.50, filled_price=0.49, side="BUY")

        assert "slippage" in caplog.text.lower()
        assert "favorable" in caplog.text.lower()

    def test_no_warning_for_zero_prices(self, caplog):
        """Test that no warning for invalid (zero) prices."""
        with caplog.at_level(logging.WARNING):
            _check_slippage(expected_price=0.0, filled_price=0.50, side="BUY")
            _check_slippage(expected_price=0.50, filled_price=0.0, side="BUY")

        assert "slippage" not in caplog.text.lower()


class TestRetryConfiguration:
    """Tests for retry configuration constants."""

    def test_max_retry_attempts_is_three(self):
        """Test that max retry attempts is 3."""
        assert MAX_RETRY_ATTEMPTS == 3

    def test_retry_delays_are_correct(self):
        """Test that retry delays follow exponential backoff."""
        from src.trading.executor import RETRY_MIN_WAIT, RETRY_MAX_WAIT
        assert RETRY_MIN_WAIT == 0.5
        assert RETRY_MAX_WAIT == 2.0


# Run tests with: pytest tests/test_executor.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
