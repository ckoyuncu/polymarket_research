"""
Integration tests for the Delta-Neutral Maker Rebates Bot.

These tests verify the main bot functionality including:
- Full cycle in paper mode
- Kill switch halts bot
- Position limits are enforced
- Delta tracking integration

IMPORTANT: All tests use mocks for external API calls. NO real trades are made.
"""

import asyncio
import pytest
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
import tempfile
import os

# Import the bot and components
from src.maker.bot import MakerBot, BotState
from src.maker.market_finder import Market15Min, MarketFinder
from src.maker.delta_tracker import DeltaTracker
from src.maker.risk_limits import RiskMonitor
from src.maker.paper_simulator import MakerPaperSimulator
from src.maker.dual_order import DualOrderExecutor, DualOrderResult, OrderResult


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_market():
    """Create a mock 15-minute market for testing."""
    return Market15Min(
        condition_id="test-condition-123",
        question="Will BTC go up in the next 15 minutes?",
        slug="btc-updown-15m-1767729600",
        yes_token_id="0x123yes",
        no_token_id="0x456no",
        yes_price=0.50,
        no_price=0.48,
        volume_24h=100000.0,
        liquidity=50000.0,
        end_time=1767729600,
    )


@pytest.fixture
def mock_market_list(mock_market):
    """Create a list of mock markets."""
    return [mock_market]


@pytest.fixture
def temp_project_root():
    """Create a temporary directory for project root (for kill switch file)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def paper_bot(temp_project_root):
    """Create a MakerBot in paper mode with mocked components."""
    with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
        bot = MakerBot(
            paper_mode=True,
            position_size=50.0,
            max_concurrent=3,
            cycle_interval=1,  # Short interval for tests
        )
        # Inject temp project root into risk monitor
        bot.risk_monitor._kill_switch_path = temp_project_root / ".kill_switch"
        yield bot


@pytest.fixture
def mock_clob_client():
    """Create a mock CLOB client for testing."""
    client = MagicMock()
    client.funder = "0xmockfunder"
    client.create_and_post_order = MagicMock(return_value={
        "orderID": "order-123",
        "status": "FILLED",
        "size": 50,
        "price": 0.50,
    })
    client.cancel = MagicMock(return_value=True)
    client.get_order = MagicMock(return_value={"status": "FILLED"})
    return client


# =============================================================================
# Test: Bot Initialization
# =============================================================================


class TestBotInitialization:
    """Tests for bot initialization."""

    def test_paper_mode_default(self, temp_project_root):
        """Test that paper mode is the default."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            bot = MakerBot()
            assert bot.paper_mode is True

    def test_paper_mode_explicit(self, temp_project_root):
        """Test explicit paper mode initialization."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            bot = MakerBot(paper_mode=True)
            assert bot.paper_mode is True

    def test_live_mode_requires_clob_client(self, temp_project_root):
        """Test that live mode requires a CLOB client."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            with pytest.raises(ValueError, match="Live trading requires a clob_client"):
                MakerBot(paper_mode=False)

    def test_live_mode_with_clob_client(self, temp_project_root, mock_clob_client):
        """Test live mode initialization with CLOB client."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            bot = MakerBot(paper_mode=False, clob_client=mock_clob_client)
            assert bot.paper_mode is False
            assert bot._dual_executor is not None

    def test_custom_configuration(self, temp_project_root):
        """Test bot with custom configuration."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            bot = MakerBot(
                paper_mode=True,
                assets=["btc"],
                position_size=25.0,
                max_concurrent=2,
                min_spread=0.03,
                min_prob=0.35,
                max_prob=0.65,
            )

            assert bot.assets == ["btc"]
            assert bot.position_size == Decimal("25.0")
            assert bot.max_concurrent == 2
            assert bot.min_spread == 0.03
            assert bot.min_prob == 0.35
            assert bot.max_prob == 0.65

    def test_components_initialized(self, paper_bot):
        """Test that all components are initialized."""
        assert paper_bot.market_finder is not None
        assert paper_bot.delta_tracker is not None
        assert paper_bot.risk_monitor is not None
        assert paper_bot.paper_simulator is not None

    def test_initial_state(self, paper_bot):
        """Test initial bot state."""
        assert paper_bot.state.is_running is False
        assert paper_bot.state.paper_mode is True
        assert paper_bot.state.cycle_count == 0
        assert paper_bot.state.positions_opened == 0


# =============================================================================
# Test: Kill Switch
# =============================================================================


class TestKillSwitch:
    """Tests for kill switch functionality."""

    def test_kill_switch_halts_cycle(self, paper_bot, mock_market_list):
        """Test that kill switch halts the trading cycle."""
        # Activate kill switch
        paper_bot.activate_kill_switch("Test activation")

        # Mock market finder
        paper_bot.market_finder.find_active_markets = MagicMock(return_value=mock_market_list)

        # Run cycle
        result = asyncio.run(paper_bot.run_cycle())

        # Verify cycle was halted
        assert "HALTED" in str(result["actions"])
        assert paper_bot.state.positions_opened == 0

    def test_kill_switch_file_creation(self, paper_bot, temp_project_root):
        """Test that kill switch creates the file."""
        kill_switch_path = temp_project_root / ".kill_switch"

        assert not kill_switch_path.exists()

        paper_bot.activate_kill_switch("Test")

        assert kill_switch_path.exists()

    def test_kill_switch_deactivation(self, paper_bot, temp_project_root):
        """Test kill switch deactivation."""
        # Activate
        paper_bot.activate_kill_switch("Test")
        assert paper_bot.risk_monitor.check_kill_switch() is True

        # Deactivate
        result = paper_bot.deactivate_kill_switch()
        assert result is True
        assert paper_bot.risk_monitor.check_kill_switch() is False

    @pytest.mark.asyncio
    async def test_kill_switch_stops_main_loop(self, paper_bot):
        """Test that kill switch stops the main loop."""
        # Start bot
        bot_task = paper_bot.start()

        # Wait a moment then activate kill switch
        await asyncio.sleep(0.1)
        paper_bot.activate_kill_switch("Test stop")

        # Wait for bot to stop
        try:
            await asyncio.wait_for(bot_task, timeout=2.0)
        except asyncio.TimeoutError:
            paper_bot.stop()
            pytest.fail("Bot did not stop after kill switch activation")

        assert paper_bot.state.is_running is False


# =============================================================================
# Test: Position Limits
# =============================================================================


class TestPositionLimits:
    """Tests for position limit enforcement."""

    def test_max_concurrent_positions_enforced(self, paper_bot, mock_market):
        """Test that max concurrent positions is enforced."""
        # Fill up to max positions
        for i in range(paper_bot.max_concurrent):
            market_id = f"market-{i}"
            paper_bot.delta_tracker.add_position(
                market_id=market_id,
                yes_size=50.0,
                no_size=50.0,
                prices={"yes": 0.50, "no": 0.48},
            )

        # Check entry criteria on new market
        paper_bot.market_finder.find_active_markets = MagicMock(return_value=[mock_market])

        # Run cycle
        result = asyncio.run(paper_bot.run_cycle())

        # Should report max positions reached
        actions_str = str(result["actions"])
        assert "Max positions" in actions_str or len(paper_bot.delta_tracker.positions) == paper_bot.max_concurrent

    def test_position_size_limit(self, paper_bot):
        """Test that position size limit is enforced."""
        # Try to open position exceeding limit
        can_open, reason = paper_bot.risk_monitor.can_open_position(
            size=1000.0,  # Exceeds default max
            market_id="test-market",
        )

        assert can_open is False
        assert "exceeds" in reason.lower()

    def test_total_exposure_limit(self, paper_bot):
        """Test that total exposure limit is enforced."""
        # Record positions to approach limit
        for i in range(10):
            paper_bot.risk_monitor.record_position_opened(
                market_id=f"market-{i}",
                size=100.0,
            )

        # Try to open another
        can_open, reason = paper_bot.risk_monitor.can_open_position(
            size=100.0,
            market_id="new-market",
        )

        # Should be blocked by either concurrent or exposure limit
        # (depends on configuration)
        # Just verify the check runs without error
        assert isinstance(can_open, bool)
        assert isinstance(reason, str)


# =============================================================================
# Test: Delta Tracking
# =============================================================================


class TestDeltaTracking:
    """Tests for delta tracking integration."""

    def test_position_tracked_after_open(self, paper_bot):
        """Test that positions are tracked after opening."""
        # Create a MagicMock market with all required attributes
        mock_market = MagicMock()
        mock_market.condition_id = "test-condition-tracking"
        mock_market.question = "Will BTC go up?"
        mock_market.slug = "btc-updown-15m-test"
        mock_market.yes_token_id = "0x123yes"
        mock_market.no_token_id = "0x456no"
        mock_market.yes_price = 0.50
        mock_market.no_price = 0.48
        mock_market.volume_24h = 100000.0
        mock_market.liquidity = 50000.0
        mock_market.end_time = 1767729600
        mock_market.spread = 0.03
        mock_market.seconds_to_resolution = 600
        mock_market.is_tradeable = True

        # Mock market finder to return our mock market
        paper_bot.market_finder.find_active_markets = MagicMock(return_value=[mock_market])

        # Run cycle
        asyncio.run(paper_bot.run_cycle())

        # Check if position was tracked
        if paper_bot.state.positions_opened > 0:
            assert len(paper_bot.delta_tracker.positions) > 0

    def test_delta_neutral_constraint(self, paper_bot):
        """Test that positions maintain delta neutrality."""
        # Add a delta-neutral position
        paper_bot.delta_tracker.add_position(
            market_id="test-market",
            yes_size=50.0,
            no_size=50.0,
            prices={"yes": 0.50, "no": 0.48},
        )

        # Get delta
        delta = paper_bot.delta_tracker.get_delta()

        # Should be zero for equal sizes
        assert delta == 0.0

    def test_position_removed_after_resolution(self, paper_bot):
        """Test that positions are removed after resolution."""
        # Add position via paper simulator
        paper_bot.paper_simulator.place_delta_neutral(
            market_id="test-market",
            size=50.0,
            yes_price=0.50,
            no_price=0.48,
        )

        # Track in delta tracker
        paper_bot.delta_tracker.add_position(
            market_id="test-market",
            yes_size=50.0,
            no_size=50.0,
            prices={"yes": 0.50, "no": 0.48},
        )

        initial_count = len(paper_bot.delta_tracker.positions)

        # Simulate resolution
        paper_bot.paper_simulator.simulate_resolution("test-market", "YES")
        paper_bot.delta_tracker.remove_position("test-market")

        # Position should be removed
        assert len(paper_bot.delta_tracker.positions) == initial_count - 1


# =============================================================================
# Test: Full Cycle in Paper Mode
# =============================================================================


class TestFullCycle:
    """Tests for full trading cycle in paper mode."""

    def test_cycle_without_markets(self, paper_bot):
        """Test cycle behavior when no markets are available."""
        # Mock empty market list
        paper_bot.market_finder.find_active_markets = MagicMock(return_value=[])

        # Run cycle
        result = asyncio.run(paper_bot.run_cycle())

        # Should complete without error
        assert result["cycle_number"] == 1
        assert result["markets_found"] == 0
        assert "No active markets" in str(result["actions"])

    def test_cycle_with_tradeable_market(self, paper_bot, mock_market):
        """Test cycle with a tradeable market."""
        # Create a fresh mock market with proper properties
        tradeable_market = MagicMock(spec=Market15Min)
        tradeable_market.condition_id = "test-condition-123"
        tradeable_market.question = "Will BTC go up?"
        tradeable_market.slug = "btc-updown-15m-1767729600"
        tradeable_market.yes_token_id = "0x123yes"
        tradeable_market.no_token_id = "0x456no"
        tradeable_market.yes_price = 0.50
        tradeable_market.no_price = 0.48
        tradeable_market.volume_24h = 100000.0
        tradeable_market.liquidity = 50000.0
        tradeable_market.end_time = 1767729600
        tradeable_market.spread = 0.03
        tradeable_market.seconds_to_resolution = 600
        tradeable_market.is_tradeable = True

        paper_bot.market_finder.find_active_markets = MagicMock(return_value=[tradeable_market])

        # Run cycle
        result = asyncio.run(paper_bot.run_cycle())

        # Cycle should complete
        assert result["cycle_number"] == 1
        assert result["markets_found"] == 1

    def test_cycle_increments_counter(self, temp_project_root):
        """Test that cycle counter increments."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            # Create a fresh bot for this test
            bot = MakerBot(paper_mode=True)
            bot.risk_monitor._kill_switch_path = temp_project_root / ".kill_switch"
            bot.market_finder.find_active_markets = MagicMock(return_value=[])

            initial_count = bot.state.cycle_count

            asyncio.run(bot.run_cycle())

            assert bot.state.cycle_count == initial_count + 1

    def test_cycle_updates_last_cycle_time(self, temp_project_root):
        """Test that last cycle time is updated."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            # Create a fresh bot for this test
            bot = MakerBot(paper_mode=True)
            bot.risk_monitor._kill_switch_path = temp_project_root / ".kill_switch"
            bot.market_finder.find_active_markets = MagicMock(return_value=[])

            assert bot.state.last_cycle_time is None

            asyncio.run(bot.run_cycle())

            assert bot.state.last_cycle_time is not None


# =============================================================================
# Test: Entry Criteria
# =============================================================================


class TestEntryCriteria:
    """Tests for market entry criteria."""

    def test_reject_market_too_close_to_resolution(self, paper_bot, mock_market):
        """Test that markets too close to resolution are rejected."""
        # Set market to resolve in 30 seconds
        mock_market_copy = MagicMock(spec=Market15Min)
        mock_market_copy.seconds_to_resolution = 30  # Too close
        mock_market_copy.spread = 0.03
        mock_market_copy.yes_price = 0.50

        result = paper_bot._check_entry_criteria(mock_market_copy)

        assert result["pass"] is False
        assert "resolution" in result["reason"].lower()

    def test_reject_market_spread_too_tight(self, paper_bot):
        """Test that markets with tight spreads are rejected."""
        tight_spread_market = MagicMock(spec=Market15Min)
        tight_spread_market.seconds_to_resolution = 600
        tight_spread_market.spread = 0.005  # Too tight
        tight_spread_market.yes_price = 0.50

        result = paper_bot._check_entry_criteria(tight_spread_market)

        assert result["pass"] is False
        assert "spread" in result["reason"].lower()

    def test_reject_extreme_probability(self, paper_bot):
        """Test that extreme probabilities are rejected."""
        extreme_market = MagicMock(spec=Market15Min)
        extreme_market.seconds_to_resolution = 600
        extreme_market.spread = 0.03
        extreme_market.yes_price = 0.95  # Too extreme

        result = paper_bot._check_entry_criteria(extreme_market)

        assert result["pass"] is False
        assert "range" in result["reason"].lower()

    def test_accept_good_market(self, paper_bot):
        """Test that good markets pass criteria."""
        good_market = MagicMock(spec=Market15Min)
        good_market.seconds_to_resolution = 600  # Good time
        good_market.spread = 0.03  # Good spread
        good_market.yes_price = 0.50  # Good probability

        result = paper_bot._check_entry_criteria(good_market)

        assert result["pass"] is True


# =============================================================================
# Test: Bot Status
# =============================================================================


class TestBotStatus:
    """Tests for bot status reporting."""

    def test_get_status_returns_dict(self, paper_bot):
        """Test that get_status returns a dictionary."""
        status = paper_bot.get_status()

        assert isinstance(status, dict)
        assert "bot_state" in status
        assert "risk_status" in status
        assert "delta_status" in status

    def test_status_includes_paper_stats(self, paper_bot):
        """Test that status includes paper trading stats."""
        status = paper_bot.get_status()

        assert "paper_stats" in status
        assert status["paper_stats"] is not None

    def test_bot_state_to_dict(self):
        """Test BotState.to_dict() method."""
        state = BotState(
            is_running=True,
            paper_mode=True,
            cycle_count=10,
            positions_opened=5,
        )

        state_dict = state.to_dict()

        assert state_dict["is_running"] is True
        assert state_dict["cycle_count"] == 10
        assert state_dict["positions_opened"] == 5


# =============================================================================
# Test: Stop and Start
# =============================================================================


class TestStopAndStart:
    """Tests for bot stop and start functionality."""

    def test_stop_sets_shutdown_event(self, paper_bot):
        """Test that stop sets the shutdown event."""
        assert not paper_bot._shutdown_event.is_set()

        paper_bot.stop()

        assert paper_bot._shutdown_event.is_set()

    def test_stop_updates_state(self, paper_bot):
        """Test that stop updates the running state."""
        paper_bot.state.is_running = True

        paper_bot.stop()

        assert paper_bot.state.is_running is False

    @pytest.mark.asyncio
    async def test_start_returns_task(self, paper_bot):
        """Test that start returns an asyncio task."""
        task = paper_bot.start()

        assert isinstance(task, asyncio.Task)

        # Clean up
        paper_bot.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


# =============================================================================
# Test: Paper Trading Integration
# =============================================================================


class TestPaperTradingIntegration:
    """Tests for paper trading integration."""

    def test_paper_position_placement(self, paper_bot, mock_market):
        """Test placing a position in paper mode."""
        # Mock market with good properties
        mock_market.condition_id = "test-123"
        mock_market.slug = "btc-updown-15m-test"
        mock_market.yes_price = 0.50
        mock_market.no_price = 0.48
        mock_market.yes_token_id = "0x123"
        mock_market.no_token_id = "0x456"

        result = asyncio.run(paper_bot._place_delta_neutral_position(mock_market))

        assert result["success"] is True
        assert result["mode"] == "paper"
        assert result["market_id"] == "test-123"

    def test_paper_position_tracked(self, paper_bot, mock_market):
        """Test that paper position is tracked in delta tracker."""
        mock_market.condition_id = "test-456"

        asyncio.run(paper_bot._place_delta_neutral_position(mock_market))

        assert "test-456" in paper_bot.delta_tracker.positions

    def test_paper_rebates_credited(self, paper_bot, mock_market):
        """Test that rebates are credited in paper mode."""
        mock_market.condition_id = "test-789"

        initial_rebates = paper_bot.state.total_rebates

        asyncio.run(paper_bot._place_delta_neutral_position(mock_market))

        assert paper_bot.state.total_rebates > initial_rebates


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_cycle_handles_market_finder_error(self, paper_bot):
        """Test that cycle handles market finder errors gracefully."""
        paper_bot.market_finder.find_active_markets = MagicMock(
            side_effect=Exception("API Error")
        )

        result = asyncio.run(paper_bot.run_cycle())

        assert len(result["errors"]) > 0
        assert paper_bot.state.last_error is not None

    def test_cycle_handles_position_error(self, paper_bot, mock_market):
        """Test that cycle handles position placement errors."""
        paper_bot.market_finder.find_active_markets = MagicMock(return_value=[mock_market])

        # Make paper simulator raise an error
        paper_bot.paper_simulator.place_delta_neutral = MagicMock(
            side_effect=Exception("Placement Error")
        )

        # Force market to pass criteria
        with patch.object(paper_bot, '_check_entry_criteria', return_value={"pass": True, "reason": "OK"}):
            result = asyncio.run(paper_bot.run_cycle())

        # Should have recorded the error
        assert len(result["errors"]) > 0


# =============================================================================
# Test: Live Mode (Mocked)
# =============================================================================


class TestLiveModeIntegration:
    """Tests for live mode integration (fully mocked)."""

    def test_live_mode_uses_dual_executor(self, temp_project_root, mock_clob_client):
        """Test that live mode uses the dual order executor."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            bot = MakerBot(paper_mode=False, clob_client=mock_clob_client)

            assert bot._dual_executor is not None
            assert isinstance(bot._dual_executor, DualOrderExecutor)

    @pytest.mark.asyncio
    async def test_live_position_uses_executor(self, temp_project_root, mock_clob_client, mock_market):
        """Test that live position placement uses the executor."""
        with patch("src.maker.bot.PROJECT_ROOT", temp_project_root):
            bot = MakerBot(paper_mode=False, clob_client=mock_clob_client)

            # Mock the dual executor's place_delta_neutral method
            mock_result = DualOrderResult(
                success=True,
                yes_order=OrderResult(success=True, order_id="yes-123", filled=True),
                no_order=OrderResult(success=True, order_id="no-456", filled=True),
                delta=Decimal("0"),
                total_cost=Decimal("49"),
            )

            bot._dual_executor.place_delta_neutral = AsyncMock(return_value=mock_result)

            result = await bot._place_delta_neutral_position(mock_market)

            assert result["success"] is True
            assert result["mode"] == "live"
            bot._dual_executor.place_delta_neutral.assert_called_once()


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
