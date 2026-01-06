"""
Tests for risk controls and circuit breakers.

Tests cover:
- Max position size limits
- Daily loss limits
- Kill switch (min bankroll)
- Consecutive loss tracking
- Cooldown periods
- Circuit breaker triggers and resets
"""
import os
import time
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.arbitrage.bot import ArbitrageBot


class TestCircuitBreakerConfiguration:
    """Tests for circuit breaker configuration."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                max_daily_loss=100.0,
                max_consecutive_losses=10,
                min_bankroll=50.0,
                cooldown_after_loss=2,
                starting_capital=250.0,
            )
            return bot

    def test_circuit_breaker_defaults(self, mock_bot):
        """Test circuit breakers have correct initial state."""
        assert mock_bot.circuit_breaker_triggered is False
        assert mock_bot.circuit_breaker_reason == ""
        assert mock_bot.consecutive_losses == 0
        assert mock_bot.daily_loss == 0.0
        assert mock_bot.cooldown_windows_remaining == 0

    def test_max_daily_loss_configured(self, mock_bot):
        """Test max daily loss is configured."""
        assert mock_bot.max_daily_loss == 100.0

    def test_max_consecutive_losses_configured(self, mock_bot):
        """Test max consecutive losses is configured."""
        assert mock_bot.max_consecutive_losses == 10

    def test_min_bankroll_configured(self, mock_bot):
        """Test min bankroll (kill switch) is configured."""
        assert mock_bot.min_bankroll == 50.0


class TestDailyLossLimit:
    """Tests for daily loss limit circuit breaker."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                max_daily_loss=50.0,
                max_consecutive_losses=100,  # High so it doesn't trigger
                min_bankroll=10.0,  # Low so it doesn't trigger
                cooldown_after_loss=0,
                starting_capital=200.0,
            )
            return bot

    def test_daily_loss_accumulates(self, mock_bot):
        """Test daily loss accumulates with each loss."""
        mock_bot._record_trade_result(pnl=-10.0, won=False)
        assert mock_bot.daily_loss == 10.0

        mock_bot._record_trade_result(pnl=-15.0, won=False)
        assert mock_bot.daily_loss == 25.0

    def test_circuit_breaker_triggers_at_limit(self, mock_bot):
        """Test circuit breaker triggers when daily loss reaches limit."""
        # Record losses that reach the limit
        mock_bot._record_trade_result(pnl=-25.0, won=False)
        mock_bot._record_trade_result(pnl=-25.0, won=False)

        can_trade, reason = mock_bot._check_circuit_breakers()

        assert can_trade is False
        assert mock_bot.circuit_breaker_triggered is True
        assert "Daily loss" in reason

    def test_wins_dont_reduce_daily_loss(self, mock_bot):
        """Test winning trades don't reduce daily loss counter."""
        mock_bot._record_trade_result(pnl=-30.0, won=False)
        initial_loss = mock_bot.daily_loss

        mock_bot._record_trade_result(pnl=20.0, won=True)

        # Daily loss should not decrease from wins
        assert mock_bot.daily_loss == initial_loss


class TestConsecutiveLossLimit:
    """Tests for consecutive loss circuit breaker."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                max_daily_loss=1000.0,  # High so it doesn't trigger
                max_consecutive_losses=5,
                min_bankroll=10.0,  # Low so it doesn't trigger
                cooldown_after_loss=0,
                starting_capital=500.0,
            )
            return bot

    def test_consecutive_losses_increment(self, mock_bot):
        """Test consecutive losses increment correctly."""
        mock_bot._record_trade_result(pnl=-5.0, won=False)
        assert mock_bot.consecutive_losses == 1

        mock_bot._record_trade_result(pnl=-5.0, won=False)
        assert mock_bot.consecutive_losses == 2

    def test_consecutive_losses_reset_on_win(self, mock_bot):
        """Test consecutive losses reset to zero on win."""
        mock_bot._record_trade_result(pnl=-5.0, won=False)
        mock_bot._record_trade_result(pnl=-5.0, won=False)
        mock_bot._record_trade_result(pnl=-5.0, won=False)
        assert mock_bot.consecutive_losses == 3

        mock_bot._record_trade_result(pnl=10.0, won=True)
        assert mock_bot.consecutive_losses == 0

    def test_circuit_breaker_triggers_at_limit(self, mock_bot):
        """Test circuit breaker triggers at consecutive loss limit."""
        for _ in range(5):
            mock_bot._record_trade_result(pnl=-5.0, won=False)

        can_trade, reason = mock_bot._check_circuit_breakers()

        assert can_trade is False
        assert mock_bot.circuit_breaker_triggered is True
        assert "consecutive losses" in reason


class TestMinBankrollKillSwitch:
    """Tests for minimum bankroll (kill switch) circuit breaker."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                max_daily_loss=1000.0,  # High so it doesn't trigger
                max_consecutive_losses=100,  # High so it doesn't trigger
                min_bankroll=75.0,
                cooldown_after_loss=0,
                starting_capital=100.0,
            )
            return bot

    def test_bankroll_updates_with_pnl(self, mock_bot):
        """Test bankroll updates correctly with P&L."""
        initial = mock_bot.current_bankroll
        mock_bot._update_bankroll(-10.0)

        assert mock_bot.current_bankroll == initial - 10.0

    def test_circuit_breaker_triggers_below_minimum(self, mock_bot):
        """Test kill switch triggers when bankroll falls below minimum."""
        # Reduce bankroll below minimum (100 - 30 = 70 < 75)
        mock_bot._record_trade_result(pnl=-30.0, won=False)

        can_trade, reason = mock_bot._check_circuit_breakers()

        assert can_trade is False
        assert mock_bot.circuit_breaker_triggered is True
        assert "below minimum" in reason


class TestCooldownPeriods:
    """Tests for cooldown periods after losses."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                max_daily_loss=1000.0,
                max_consecutive_losses=100,
                min_bankroll=10.0,
                cooldown_after_loss=3,  # 3 window cooldown
                starting_capital=500.0,
            )
            return bot

    def test_cooldown_activates_after_loss(self, mock_bot):
        """Test cooldown activates after a loss."""
        mock_bot._record_trade_result(pnl=-5.0, won=False)

        assert mock_bot.cooldown_windows_remaining == 3

    def test_cooldown_blocks_trading(self, mock_bot):
        """Test cooldown prevents trading."""
        mock_bot._record_trade_result(pnl=-5.0, won=False)

        can_trade, reason = mock_bot._check_circuit_breakers()

        assert can_trade is False
        assert "Cooldown active" in reason

    def test_cooldown_decrements(self, mock_bot):
        """Test cooldown decrements after each window."""
        mock_bot._record_trade_result(pnl=-5.0, won=False)
        assert mock_bot.cooldown_windows_remaining == 3

        mock_bot._decrement_cooldown()
        assert mock_bot.cooldown_windows_remaining == 2

        mock_bot._decrement_cooldown()
        assert mock_bot.cooldown_windows_remaining == 1

        mock_bot._decrement_cooldown()
        assert mock_bot.cooldown_windows_remaining == 0

    def test_trading_resumes_after_cooldown(self, mock_bot):
        """Test trading resumes after cooldown expires."""
        mock_bot._record_trade_result(pnl=-5.0, won=False)

        # Exhaust cooldown
        for _ in range(3):
            mock_bot._decrement_cooldown()

        can_trade, reason = mock_bot._check_circuit_breakers()

        assert can_trade is True

    def test_win_does_not_trigger_cooldown(self, mock_bot):
        """Test winning trades don't trigger cooldown."""
        mock_bot._record_trade_result(pnl=10.0, won=True)

        assert mock_bot.cooldown_windows_remaining == 0


class TestCircuitBreakerReset:
    """Tests for circuit breaker manual reset."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                max_daily_loss=50.0,
                max_consecutive_losses=5,
                min_bankroll=50.0,
                cooldown_after_loss=2,
                starting_capital=200.0,
            )
            return bot

    def test_reset_clears_triggered_state(self, mock_bot):
        """Test reset clears circuit breaker triggered state."""
        # Trigger circuit breaker
        mock_bot.circuit_breaker_triggered = True
        mock_bot.circuit_breaker_reason = "Test reason"

        mock_bot.reset_circuit_breakers()

        assert mock_bot.circuit_breaker_triggered is False
        assert mock_bot.circuit_breaker_reason == ""

    def test_reset_clears_consecutive_losses(self, mock_bot):
        """Test reset clears consecutive loss counter."""
        mock_bot.consecutive_losses = 10

        mock_bot.reset_circuit_breakers()

        assert mock_bot.consecutive_losses == 0

    def test_reset_clears_cooldown(self, mock_bot):
        """Test reset clears cooldown."""
        mock_bot.cooldown_windows_remaining = 5

        mock_bot.reset_circuit_breakers()

        assert mock_bot.cooldown_windows_remaining == 0

    def test_reset_allows_trading(self, mock_bot):
        """Test reset allows trading to resume."""
        mock_bot.circuit_breaker_triggered = True
        mock_bot.circuit_breaker_reason = "Test"

        mock_bot.reset_circuit_breakers()

        can_trade, _ = mock_bot._check_circuit_breakers()
        assert can_trade is True


class TestDailyStatsReset:
    """Tests for daily statistics reset."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                starting_capital=200.0,
            )
            return bot

    def test_daily_reset_clears_loss(self, mock_bot):
        """Test daily reset clears daily loss."""
        mock_bot.daily_loss = 100.0

        mock_bot.reset_daily_stats()

        assert mock_bot.daily_loss == 0.0

    def test_daily_reset_clears_trades_today(self, mock_bot):
        """Test daily reset clears trades today counter."""
        mock_bot.trades_today = 50

        mock_bot.reset_daily_stats()

        assert mock_bot.trades_today == 0


class TestDrawdownCalculation:
    """Tests for drawdown calculation."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                starting_capital=100.0,
            )
            return bot

    def test_no_drawdown_at_start(self, mock_bot):
        """Test drawdown is zero at start."""
        assert mock_bot.get_drawdown() == 0.0

    def test_drawdown_calculated_from_peak(self, mock_bot):
        """Test drawdown is calculated from peak."""
        # Set peak to 150
        mock_bot.stats["peak_bankroll"] = 150.0
        # Current at 120 = 20% drawdown
        mock_bot.current_bankroll = 120.0

        drawdown = mock_bot.get_drawdown()

        assert drawdown == 0.2  # 20%

    def test_peak_updates_on_new_high(self, mock_bot):
        """Test peak updates when bankroll reaches new high."""
        initial_peak = mock_bot.stats["peak_bankroll"]

        # Win that takes us above peak
        mock_bot._update_bankroll(50.0)

        assert mock_bot.stats["peak_bankroll"] > initial_peak


class TestPositionSizing:
    """Tests for dynamic position sizing with compounding."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=None,
                dry_run=True,
                starting_capital=250.0,
                max_position_size=100.0,
                enable_compounding=True,
                max_risk_per_trade_pct=0.04,
            )
            return bot

    def test_position_size_scales_with_bankroll(self, mock_bot):
        """Test position size scales with bankroll when compounding enabled."""
        initial_max = mock_bot._calculate_max_position()

        # Double the bankroll
        mock_bot.current_bankroll = 500.0

        new_max = mock_bot._calculate_max_position()

        # Should be larger but capped
        assert new_max >= initial_max

    def test_position_size_capped(self, mock_bot):
        """Test position size is capped at base_max_position."""
        # Set very high bankroll
        mock_bot.current_bankroll = 10000.0

        max_pos = mock_bot._calculate_max_position()

        assert max_pos <= mock_bot.base_max_position

    def test_compounding_disabled_uses_fixed_size(self, mock_bot):
        """Test fixed position size when compounding disabled."""
        mock_bot.enable_compounding = False

        initial_max = mock_bot._calculate_max_position()

        mock_bot.current_bankroll = 1000.0

        new_max = mock_bot._calculate_max_position()

        assert new_max == initial_max == mock_bot.base_max_position


class TestTradeBlockingByCircuitBreaker:
    """Tests for trade execution blocked by circuit breakers."""

    @pytest.fixture
    def mock_bot(self):
        """Create a bot with mocked dependencies."""
        with patch("src.arbitrage.bot.BinanceFeed") as mock_binance, patch(
            "src.arbitrage.bot.MarketCalendar"
        ) as mock_calendar, patch(
            "src.arbitrage.bot.MarketScanner"
        ) as mock_scanner, patch(
            "src.arbitrage.bot.DecisionEngine"
        ) as mock_decision:
            mock_binance.return_value = Mock()
            mock_calendar.return_value = Mock()
            mock_scanner.return_value = Mock()
            mock_decision.return_value = Mock()

            bot = ArbitrageBot(
                data_api=Mock(),
                executor=Mock(),
                dry_run=False,
                starting_capital=200.0,
                max_daily_loss=50.0,
            )
            return bot

    def test_signal_blocked_when_circuit_breaker_triggered(self, mock_bot):
        """Test _execute_signal doesn't trade when circuit breaker active."""
        mock_bot.circuit_breaker_triggered = True
        mock_bot.circuit_breaker_reason = "Test"

        # Create mock signal and market
        mock_signal = Mock()
        mock_signal.should_trade = True
        mock_market = Mock()

        # This should not execute any trade
        mock_bot._execute_signal(mock_signal, mock_market)

        # Executor should not have been called
        mock_bot.executor.place_order.assert_not_called()


# Run tests with: pytest tests/test_risk_controls.py -v
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
