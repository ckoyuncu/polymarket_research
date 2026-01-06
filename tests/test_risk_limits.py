"""
Comprehensive tests for Maker Rebates Risk Monitoring System.

Tests cover:
- Kill switch activation and deactivation
- Position size limits
- Concurrent position limits
- Total exposure limits
- Daily loss tracking and limits
- Balance tracking and alerts
- Delta monitoring
- Execution failure tracking
- Risk reporting
- Daily reset functionality
- State persistence
- Edge cases
"""

import json
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from src.maker.risk_limits import Alert, RiskMonitor


@pytest.fixture
def risk_monitor():
    """Create a risk monitor instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "max_daily_loss": 30.0,
            "max_position_size": 100.0,
            "max_concurrent": 3,
            "max_total_exposure": 300.0,
            "max_delta_pct": 0.05,
            "balance_alert_drop_pct": 0.10,
        }
        monitor = RiskMonitor(config=config, project_root=Path(tmpdir))
        yield monitor


@pytest.fixture
def risk_monitor_small():
    """Create a risk monitor with smaller limits for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {
            "max_daily_loss": 10.0,
            "max_position_size": 50.0,
            "max_concurrent": 2,
            "max_total_exposure": 100.0,
            "max_delta_pct": 0.03,
        }
        monitor = RiskMonitor(config=config, project_root=Path(tmpdir))
        yield monitor


class TestKillSwitch:
    """Tests for kill switch functionality."""

    def test_kill_switch_initially_inactive(self, risk_monitor):
        """Test that kill switch is initially inactive."""
        assert not risk_monitor.check_kill_switch()
        assert not risk_monitor.is_halted

    def test_activate_kill_switch(self, risk_monitor):
        """Test activating the kill switch."""
        risk_monitor.activate_kill_switch("Test activation")

        assert risk_monitor.check_kill_switch()
        assert risk_monitor.is_halted
        assert "Kill switch" in risk_monitor.halt_reason

        # Check file exists
        assert risk_monitor._kill_switch_path.exists()

    def test_kill_switch_file_content(self, risk_monitor):
        """Test that kill switch file contains correct information."""
        reason = "Emergency stop - test"
        risk_monitor.activate_kill_switch(reason)

        with open(risk_monitor._kill_switch_path) as f:
            content = f.read()

        assert "Kill switch activated" in content
        assert reason in content

    def test_deactivate_kill_switch(self, risk_monitor):
        """Test deactivating the kill switch."""
        risk_monitor.activate_kill_switch("Test")
        assert risk_monitor.check_kill_switch()

        success = risk_monitor.deactivate_kill_switch()

        assert success
        assert not risk_monitor.check_kill_switch()
        assert not risk_monitor._kill_switch_path.exists()

    def test_deactivate_when_not_active(self, risk_monitor):
        """Test deactivating when kill switch not active."""
        success = risk_monitor.deactivate_kill_switch()
        assert success

    def test_kill_switch_blocks_trading(self, risk_monitor):
        """Test that kill switch blocks position opening."""
        risk_monitor.activate_kill_switch("Test")

        can_open, reason = risk_monitor.can_open_position(size=50.0)

        assert not can_open
        assert "Kill switch is active" in reason

    def test_kill_switch_alert_generated(self, risk_monitor):
        """Test that kill switch activation generates alert."""
        risk_monitor.activate_kill_switch("Critical issue")

        alerts = risk_monitor.get_alerts(level="CRITICAL", category="KILL_SWITCH")
        assert len(alerts) > 0
        assert "ACTIVATED" in alerts[-1]["message"]


class TestPositionLimits:
    """Tests for position size and count limits."""

    def test_can_open_within_limit(self, risk_monitor):
        """Test that positions within limits are allowed."""
        can_open, reason = risk_monitor.can_open_position(size=50.0)

        assert can_open
        assert reason == "OK"

    def test_cannot_exceed_position_size(self, risk_monitor):
        """Test that positions exceeding size limit are blocked."""
        can_open, reason = risk_monitor.can_open_position(size=150.0)

        assert not can_open
        assert "exceeds limit" in reason
        assert "100" in reason

    def test_position_exactly_at_limit(self, risk_monitor):
        """Test position exactly at size limit."""
        can_open, reason = risk_monitor.can_open_position(size=100.0)

        assert can_open
        assert reason == "OK"

    def test_record_position_opened(self, risk_monitor):
        """Test recording a position opening."""
        risk_monitor.record_position_opened("market-1", size=50.0)

        assert "market-1" in risk_monitor._positions
        assert risk_monitor._positions["market-1"] == Decimal("50.0")

    def test_record_position_closed(self, risk_monitor):
        """Test recording a position closing."""
        risk_monitor.record_position_opened("market-1", size=50.0)
        risk_monitor.record_position_closed("market-1")

        assert "market-1" not in risk_monitor._positions

    def test_add_to_existing_position(self, risk_monitor):
        """Test adding to an existing position."""
        risk_monitor.record_position_opened("market-1", size=30.0)
        risk_monitor.record_position_opened("market-1", size=20.0)

        assert risk_monitor._positions["market-1"] == Decimal("50.0")

    def test_cannot_exceed_position_size_with_addition(self, risk_monitor):
        """Test that adding to position respects size limit."""
        risk_monitor.record_position_opened("market-1", size=60.0)

        can_open, reason = risk_monitor.can_open_position(size=50.0, market_id="market-1")

        assert not can_open
        assert "would exceed limit" in reason

    def test_concurrent_positions_limit(self, risk_monitor):
        """Test maximum concurrent positions limit."""
        risk_monitor.record_position_opened("market-1", size=50.0)
        risk_monitor.record_position_opened("market-2", size=50.0)
        risk_monitor.record_position_opened("market-3", size=50.0)

        # Try to open 4th position
        can_open, reason = risk_monitor.can_open_position(size=50.0, market_id="market-4")

        assert not can_open
        assert "Maximum concurrent positions" in reason
        assert "3" in reason

    def test_can_add_to_existing_when_at_limit(self, risk_monitor):
        """Test that adding to existing position is allowed when at concurrent limit."""
        risk_monitor.record_position_opened("market-1", size=30.0)
        risk_monitor.record_position_opened("market-2", size=30.0)
        risk_monitor.record_position_opened("market-3", size=30.0)

        # Should be able to add to existing position
        can_open, reason = risk_monitor.can_open_position(size=20.0, market_id="market-1")

        assert can_open
        assert reason == "OK"


class TestTotalExposure:
    """Tests for total exposure limits."""

    def test_total_exposure_within_limit(self, risk_monitor):
        """Test total exposure within limits."""
        risk_monitor.record_position_opened("market-1", size=100.0)
        risk_monitor.record_position_opened("market-2", size=100.0)

        can_open, reason = risk_monitor.can_open_position(size=50.0)

        assert can_open
        assert reason == "OK"

    def test_cannot_exceed_total_exposure(self, risk_monitor):
        """Test that total exposure limit is enforced."""
        risk_monitor.record_position_opened("market-1", size=100.0)
        risk_monitor.record_position_opened("market-2", size=100.0)
        risk_monitor.record_position_opened("market-3", size=100.0)

        # Total is 300, at limit - will hit either concurrent or exposure limit
        can_open, reason = risk_monitor.can_open_position(size=50.0)

        assert not can_open
        # May hit concurrent limit (3) or total exposure limit (300)
        assert "exceeded" in reason.lower() or "reached" in reason.lower()

    def test_exposure_exactly_at_limit(self, risk_monitor):
        """Test exposure exactly at limit."""
        risk_monitor.record_position_opened("market-1", size=100.0)
        risk_monitor.record_position_opened("market-2", size=100.0)

        can_open, reason = risk_monitor.can_open_position(size=100.0)

        assert can_open

    def test_exposure_after_closing_position(self, risk_monitor):
        """Test exposure calculation after closing positions."""
        risk_monitor.record_position_opened("market-1", size=100.0)
        risk_monitor.record_position_opened("market-2", size=100.0)
        risk_monitor.record_position_opened("market-3", size=100.0)

        # Close one position
        risk_monitor.record_position_closed("market-1")

        # Should be able to open new position
        can_open, reason = risk_monitor.can_open_position(size=100.0)

        assert can_open


class TestDailyLossTracking:
    """Tests for daily loss tracking and limits."""

    def test_initial_daily_pnl_zero(self, risk_monitor):
        """Test that daily P&L starts at zero."""
        assert risk_monitor._daily_pnl == Decimal("0")
        assert not risk_monitor.is_daily_limit_hit()

    def test_record_profit(self, risk_monitor):
        """Test recording profit."""
        risk_monitor.record_pnl(amount=5.0)

        assert risk_monitor._daily_pnl == Decimal("5.0")
        assert not risk_monitor.is_daily_limit_hit()

    def test_record_loss(self, risk_monitor):
        """Test recording loss."""
        risk_monitor.record_pnl(amount=-10.0)

        assert risk_monitor._daily_pnl == Decimal("-10.0")
        assert not risk_monitor.is_daily_limit_hit()

    def test_cumulative_pnl(self, risk_monitor):
        """Test cumulative P&L tracking."""
        risk_monitor.record_pnl(amount=5.0)
        risk_monitor.record_pnl(amount=-3.0)
        risk_monitor.record_pnl(amount=2.0)

        assert risk_monitor._daily_pnl == Decimal("4.0")

    def test_daily_loss_limit_hit(self, risk_monitor):
        """Test that daily loss limit is detected."""
        risk_monitor.record_pnl(amount=-30.0)

        assert risk_monitor.is_daily_limit_hit()
        assert risk_monitor.check_kill_switch()

    def test_daily_loss_exactly_at_limit(self, risk_monitor):
        """Test daily loss exactly at limit."""
        risk_monitor.record_pnl(amount=-30.0)

        assert risk_monitor.is_daily_limit_hit()

    def test_approaching_daily_loss_limit_alert(self, risk_monitor):
        """Test alert when approaching daily loss limit."""
        risk_monitor.record_pnl(amount=-28.0)  # 93% of limit

        alerts = risk_monitor.get_alerts(level="WARNING", category="LOSS")
        assert len(alerts) > 0
        assert "Approaching daily loss limit" in alerts[-1]["message"]

    def test_daily_loss_limit_activates_kill_switch(self, risk_monitor):
        """Test that exceeding daily loss activates kill switch."""
        risk_monitor.record_pnl(amount=-35.0)

        assert risk_monitor.check_kill_switch()
        assert risk_monitor.is_halted

    def test_position_close_records_pnl(self, risk_monitor):
        """Test that closing position records P&L."""
        risk_monitor.record_position_opened("market-1", size=50.0)
        risk_monitor.record_position_closed("market-1", pnl=2.5)

        assert risk_monitor._daily_pnl == Decimal("2.5")

    def test_daily_reset(self, risk_monitor):
        """Test that daily counters reset on new day."""
        risk_monitor.record_pnl(amount=-15.0)
        assert risk_monitor._daily_pnl == Decimal("-15.0")

        # Simulate next day
        future_date = date.today() + timedelta(days=1)
        with patch("src.maker.risk_limits._utc_today", return_value=future_date):
            risk_monitor._check_daily_reset()

        assert risk_monitor._daily_pnl == Decimal("0")
        assert len(risk_monitor._daily_pnl_history) == 1


class TestBalanceTracking:
    """Tests for balance tracking and alerts."""

    def test_initial_balance_set(self, risk_monitor):
        """Test setting initial balance."""
        risk_monitor.update_balance(300.0)

        assert risk_monitor._initial_balance == Decimal("300.0")
        assert risk_monitor._current_balance == Decimal("300.0")
        assert risk_monitor._peak_balance == Decimal("300.0")

    def test_balance_increase_updates_peak(self, risk_monitor):
        """Test that balance increases update peak."""
        risk_monitor.update_balance(300.0)
        risk_monitor.update_balance(320.0)

        assert risk_monitor._peak_balance == Decimal("320.0")

    def test_balance_drop_alert(self, risk_monitor):
        """Test alert on significant balance drop."""
        risk_monitor.update_balance(300.0)
        risk_monitor.update_balance(260.0)  # 13.3% drop

        alerts = risk_monitor.get_alerts(level="WARNING", category="BALANCE")
        assert len(alerts) > 0
        assert "dropped" in alerts[-1]["message"].lower()

    def test_balance_drop_below_threshold(self, risk_monitor):
        """Test balance drop exactly at alert threshold."""
        risk_monitor.update_balance(300.0)
        risk_monitor.update_balance(270.0)  # Exactly 10% drop

        alerts = risk_monitor.get_alerts(category="BALANCE")
        assert len(alerts) > 0


class TestDeltaMonitoring:
    """Tests for delta exposure monitoring."""

    def test_delta_within_limit(self, risk_monitor):
        """Test delta within acceptable limits."""
        within_limit, message = risk_monitor.check_delta(delta=2.0, total_exposure=100.0)

        assert within_limit
        assert message == "OK"

    def test_delta_exceeds_limit(self, risk_monitor):
        """Test delta exceeding limits."""
        within_limit, message = risk_monitor.check_delta(delta=8.0, total_exposure=100.0)

        assert not within_limit
        assert "exceeds" in message

    def test_delta_exactly_at_limit(self, risk_monitor):
        """Test delta exactly at limit."""
        within_limit, message = risk_monitor.check_delta(delta=5.0, total_exposure=100.0)

        assert within_limit

    def test_delta_no_exposure(self, risk_monitor):
        """Test delta check with no exposure."""
        within_limit, message = risk_monitor.check_delta(delta=0.0, total_exposure=0.0)

        assert within_limit
        assert "No exposure" in message

    def test_negative_delta_checked(self, risk_monitor):
        """Test that negative delta is checked (absolute value)."""
        within_limit, message = risk_monitor.check_delta(delta=-8.0, total_exposure=100.0)

        assert not within_limit

    def test_delta_alert_on_position_open(self, risk_monitor):
        """Test delta alert when opening position."""
        risk_monitor.record_position_opened("market-1", size=50.0, delta=8.0)

        alerts = risk_monitor.get_alerts(category="DELTA")
        assert len(alerts) > 0


class TestExecutionFailures:
    """Tests for execution failure tracking."""

    def test_record_execution_failure(self, risk_monitor):
        """Test recording execution failures."""
        risk_monitor.record_execution_failure("Order timeout")

        assert risk_monitor._execution_failures == 1

        alerts = risk_monitor.get_alerts(category="EXECUTION")
        assert len(alerts) > 0
        assert "failed" in alerts[-1]["message"].lower()

    def test_multiple_execution_failures(self, risk_monitor):
        """Test tracking multiple failures."""
        risk_monitor.record_execution_failure("Timeout")
        risk_monitor.record_execution_failure("Rejected")
        risk_monitor.record_execution_failure("Insufficient balance")

        assert risk_monitor._execution_failures == 3

    def test_reset_execution_failures(self, risk_monitor):
        """Test resetting execution failure counter."""
        risk_monitor.record_execution_failure("Test")
        risk_monitor.record_execution_failure("Test")

        risk_monitor.reset_execution_failures()

        assert risk_monitor._execution_failures == 0


class TestRiskReport:
    """Tests for risk reporting."""

    def test_basic_risk_report(self, risk_monitor):
        """Test basic risk report structure."""
        report = risk_monitor.get_risk_report()

        assert "is_halted" in report
        assert "kill_switch_active" in report
        assert "daily_pnl" in report
        assert "open_positions" in report
        assert "current_exposure" in report

    def test_risk_report_with_positions(self, risk_monitor):
        """Test risk report with open positions."""
        risk_monitor.record_position_opened("market-1", size=50.0)
        risk_monitor.record_position_opened("market-2", size=75.0)

        report = risk_monitor.get_risk_report()

        assert report["open_positions"] == 2
        assert report["current_exposure"] == 125.0
        assert report["positions_remaining"] == 1

    def test_risk_report_exposure_utilization(self, risk_monitor):
        """Test exposure utilization calculation."""
        risk_monitor.record_position_opened("market-1", size=150.0)

        report = risk_monitor.get_risk_report()

        assert report["exposure_utilization"] == 0.5  # 150/300

    def test_risk_report_with_balance(self, risk_monitor):
        """Test risk report with balance tracking."""
        risk_monitor.update_balance(300.0)
        risk_monitor.update_balance(285.0)

        report = risk_monitor.get_risk_report()

        assert report["initial_balance"] == 300.0
        assert report["current_balance"] == 285.0
        assert report["peak_balance"] == 300.0

    def test_risk_report_includes_alerts(self, risk_monitor):
        """Test that risk report includes recent alerts."""
        risk_monitor.record_execution_failure("Test")

        report = risk_monitor.get_risk_report()

        assert report["alert_count"] > 0
        assert len(report["recent_alerts"]) > 0


class TestAlerts:
    """Tests for alert system."""

    def test_get_all_alerts(self, risk_monitor):
        """Test getting all alerts."""
        risk_monitor.record_execution_failure("Test 1")
        risk_monitor.record_execution_failure("Test 2")

        alerts = risk_monitor.get_alerts()

        assert len(alerts) >= 2

    def test_filter_alerts_by_level(self, risk_monitor):
        """Test filtering alerts by level."""
        risk_monitor.activate_kill_switch("Critical")  # CRITICAL alert
        risk_monitor.record_execution_failure("Warning")  # WARNING alert

        critical_alerts = risk_monitor.get_alerts(level="CRITICAL")
        warning_alerts = risk_monitor.get_alerts(level="WARNING")

        assert len(critical_alerts) > 0
        assert len(warning_alerts) > 0

    def test_filter_alerts_by_category(self, risk_monitor):
        """Test filtering alerts by category."""
        risk_monitor.record_execution_failure("Test")

        execution_alerts = risk_monitor.get_alerts(category="EXECUTION")

        assert len(execution_alerts) > 0
        assert all(a["category"] == "EXECUTION" for a in execution_alerts)

    def test_alert_limit(self, risk_monitor):
        """Test alert list size limit."""
        # Generate many alerts
        for i in range(150):
            risk_monitor.record_execution_failure(f"Test {i}")

        # Should keep only last 100
        assert len(risk_monitor.alerts) == 100

    def test_clear_alerts(self, risk_monitor):
        """Test clearing all alerts."""
        risk_monitor.record_execution_failure("Test")
        risk_monitor.clear_alerts()

        alerts = risk_monitor.get_alerts()
        assert len(alerts) == 0


class TestStatePersistence:
    """Tests for state saving and loading."""

    def test_save_state(self, risk_monitor):
        """Test saving risk monitor state."""
        risk_monitor.record_position_opened("market-1", size=50.0)
        risk_monitor.record_pnl(amount=-5.0)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            filepath = Path(f.name)

        try:
            risk_monitor.save_state(filepath)

            assert filepath.exists()

            with open(filepath) as f:
                state = json.load(f)

            assert state["daily_pnl"] == -5.0
            assert "market-1" in state["positions"]
        finally:
            if filepath.exists():
                filepath.unlink()

    def test_load_state(self, risk_monitor):
        """Test loading risk monitor state."""
        # Create initial state
        risk_monitor.record_position_opened("market-1", size=50.0)
        risk_monitor.record_pnl(amount=-5.0)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            filepath = Path(f.name)

        try:
            risk_monitor.save_state(filepath)

            # Create new monitor and load state
            new_monitor = RiskMonitor(project_root=risk_monitor.project_root)
            success = new_monitor.load_state(filepath)

            assert success
            assert new_monitor._daily_pnl == Decimal("-5.0")
            assert "market-1" in new_monitor._positions
        finally:
            if filepath.exists():
                filepath.unlink()

    def test_load_nonexistent_state(self, risk_monitor):
        """Test loading from nonexistent file."""
        filepath = Path("/tmp/nonexistent_state.json")
        success = risk_monitor.load_state(filepath)

        assert not success


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_size_position(self, risk_monitor):
        """Test handling zero size position."""
        can_open, reason = risk_monitor.can_open_position(size=0.0)

        assert can_open

    def test_negative_pnl_multiple_times(self, risk_monitor):
        """Test multiple negative P&L entries."""
        for _ in range(5):
            risk_monitor.record_pnl(amount=-5.0)

        assert risk_monitor._daily_pnl == Decimal("-25.0")

    def test_very_small_position(self, risk_monitor):
        """Test very small position size."""
        can_open, reason = risk_monitor.can_open_position(size=0.01)

        assert can_open

    def test_decimal_precision(self, risk_monitor):
        """Test decimal precision in calculations."""
        risk_monitor.record_pnl(amount=1.23456789)
        risk_monitor.record_pnl(amount=2.34567890)

        # Should maintain precision
        assert risk_monitor._daily_pnl == Decimal("3.58024679")

    def test_close_nonexistent_position(self, risk_monitor):
        """Test closing position that doesn't exist."""
        risk_monitor.record_position_closed("nonexistent-market")

        # Should not raise error
        assert "nonexistent-market" not in risk_monitor._positions

    def test_repr_string(self, risk_monitor):
        """Test string representation."""
        repr_str = repr(risk_monitor)

        assert "RiskMonitor" in repr_str
        assert "ACTIVE" in repr_str or "HALTED" in repr_str

    def test_halt_resume_cycle(self, risk_monitor):
        """Test halting and resuming cycle."""
        risk_monitor.activate_kill_switch("Test halt")
        assert risk_monitor.is_halted

        risk_monitor.deactivate_kill_switch()
        # Note: Manual halt persists even after kill switch deactivation
        assert not risk_monitor.check_kill_switch()


class TestConfiguration:
    """Tests for configuration handling."""

    def test_default_configuration(self):
        """Test default configuration values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monitor = RiskMonitor(project_root=Path(tmpdir))

            assert monitor._max_daily_loss == Decimal("30.0")
            assert monitor._max_position_size == Decimal("100.0")
            assert monitor._max_concurrent == 3

    def test_custom_configuration(self):
        """Test custom configuration values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {
                "max_daily_loss": 50.0,
                "max_position_size": 200.0,
                "max_concurrent": 5,
            }
            monitor = RiskMonitor(config=config, project_root=Path(tmpdir))

            assert monitor._max_daily_loss == Decimal("50.0")
            assert monitor._max_position_size == Decimal("200.0")
            assert monitor._max_concurrent == 5

    def test_partial_configuration(self):
        """Test partial configuration (should use defaults for missing values)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"max_daily_loss": 20.0}
            monitor = RiskMonitor(config=config, project_root=Path(tmpdir))

            assert monitor._max_daily_loss == Decimal("20.0")
            assert monitor._max_position_size == Decimal("100.0")  # Default


class TestIntegration:
    """Integration tests for realistic scenarios."""

    def test_complete_trading_cycle(self, risk_monitor):
        """Test complete trading cycle."""
        # Open position
        can_open, _ = risk_monitor.can_open_position(size=50.0, market_id="market-1")
        assert can_open

        risk_monitor.record_position_opened("market-1", size=50.0, delta=1.0)

        # Record some P&L
        risk_monitor.record_pnl(amount=2.5)

        # Close position
        risk_monitor.record_position_closed("market-1", pnl=1.5)

        # Check state
        assert "market-1" not in risk_monitor._positions
        assert risk_monitor._daily_pnl == Decimal("4.0")

    def test_multiple_positions_scenario(self, risk_monitor):
        """Test managing multiple positions."""
        # Open 3 positions
        for i in range(1, 4):
            can_open, _ = risk_monitor.can_open_position(
                size=80.0, market_id=f"market-{i}"
            )
            assert can_open
            risk_monitor.record_position_opened(f"market-{i}", size=80.0)

        # Should be at limit
        can_open, reason = risk_monitor.can_open_position(size=50.0, market_id="market-4")
        assert not can_open

        # Close one position
        risk_monitor.record_position_closed("market-1")

        # Should be able to open new position
        can_open, _ = risk_monitor.can_open_position(size=50.0, market_id="market-4")
        assert can_open

    def test_loss_limit_scenario(self, risk_monitor_small):
        """Test reaching daily loss limit."""
        # Small losses
        risk_monitor_small.record_pnl(amount=-3.0)
        risk_monitor_small.record_pnl(amount=-4.0)

        # Should still be able to trade
        can_open, _ = risk_monitor_small.can_open_position(size=30.0)
        assert can_open

        # Push over limit
        risk_monitor_small.record_pnl(amount=-5.0)

        # Should be blocked
        assert risk_monitor_small.is_daily_limit_hit()
        assert risk_monitor_small.check_kill_switch()
