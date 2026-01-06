"""
Comprehensive tests for the Maker Paper Simulator.

Tests cover:
- Delta-neutral position placement
- Resolution simulation (YES and NO outcomes)
- Delta calculation
- Rebate estimation
- Balance tracking
- Risk controls (daily loss limit, max positions)
- Edge cases and error handling
"""

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from src.maker.paper_simulator import (
    DeltaNeutralError,
    DeltaNeutralPosition,
    InsufficientBalanceError,
    MakerPaperSimulator,
)


@pytest.fixture
def simulator():
    """Create a simulator instance for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "test_trades.jsonl"
        sim = MakerPaperSimulator(
            initial_balance=300.0,
            max_position_size=100.0,
            max_concurrent_positions=3,
            max_daily_loss=30.0,
            maker_rebate_rate=0.001,
            log_trades=True,
            log_path=str(log_path),
        )
        yield sim


@pytest.fixture
def simulator_no_logging():
    """Create a simulator without trade logging."""
    return MakerPaperSimulator(
        initial_balance=300.0,
        log_trades=False,
    )


class TestInitialization:
    """Tests for simulator initialization."""

    def test_initial_balance(self, simulator):
        """Test initial balance is set correctly."""
        assert simulator.balance == Decimal("300")
        assert simulator.initial_balance == Decimal("300")

    def test_initial_pnl_zero(self, simulator):
        """Test initial P&L values are zero."""
        assert simulator.realized_pnl == Decimal("0")
        assert simulator.rebates_earned == Decimal("0")

    def test_initial_positions_empty(self, simulator):
        """Test positions list starts empty."""
        assert len(simulator.positions) == 0
        assert len(simulator.trades) == 0

    def test_configuration_values(self, simulator):
        """Test configuration values are set correctly."""
        assert simulator.max_position_size == Decimal("100")
        assert simulator.max_concurrent_positions == 3
        assert simulator.max_daily_loss == Decimal("30")
        assert simulator.maker_rebate_rate == Decimal("0.001")


class TestDeltaNeutralPlacement:
    """Tests for delta-neutral position placement."""

    def test_place_delta_neutral_basic(self, simulator):
        """Test basic delta-neutral placement."""
        position = simulator.place_delta_neutral(
            market_id="market-123",
            size=50,
            yes_price=0.50,
            no_price=0.50,
        )

        assert position is not None
        assert position.market_id == "market-123"
        assert position.yes_size == Decimal("50")
        assert position.no_size == Decimal("50")
        assert position.yes_price == Decimal("0.50")
        assert position.no_price == Decimal("0.50")

    def test_place_delta_neutral_cost_calculation(self, simulator):
        """Test cost calculation for delta-neutral position."""
        position = simulator.place_delta_neutral(
            market_id="market-123",
            size=50,
            yes_price=0.50,
            no_price=0.50,
        )

        # Cost = 50 * 0.50 + 50 * 0.50 = 50
        expected_cost = Decimal("50")
        assert position.total_cost == expected_cost

    def test_place_delta_neutral_balance_deduction(self, simulator):
        """Test balance is deducted correctly."""
        initial_balance = simulator.balance

        simulator.place_delta_neutral(
            market_id="market-123",
            size=50,
            yes_price=0.50,
            no_price=0.50,
        )

        # Cost = 50, rebates = 50 * 0.001 = 0.05
        expected_balance = initial_balance - Decimal("50") + Decimal("0.05")
        assert simulator.balance == expected_balance

    def test_place_delta_neutral_rebates_credited(self, simulator):
        """Test maker rebates are credited."""
        position = simulator.place_delta_neutral(
            market_id="market-123",
            size=50,
            yes_price=0.50,
            no_price=0.50,
        )

        # Rebates = 50 * 0.001 = 0.05
        expected_rebates = Decimal("0.05")
        assert position.rebates_earned == expected_rebates
        assert simulator.rebates_earned == expected_rebates

    def test_place_delta_neutral_asymmetric_prices(self, simulator):
        """Test placement with asymmetric but valid prices."""
        position = simulator.place_delta_neutral(
            market_id="market-123",
            size=50,
            yes_price=0.40,
            no_price=0.55,
        )

        # Total price = 0.95 < 1, so valid
        assert position.yes_price == Decimal("0.40")
        assert position.no_price == Decimal("0.55")
        assert position.implied_fair_price == Decimal("0.95")

    def test_place_delta_neutral_with_edge(self, simulator):
        """Test placement where yes_price + no_price < 1 (positive edge)."""
        position = simulator.place_delta_neutral(
            market_id="market-123",
            size=100,
            yes_price=0.45,
            no_price=0.45,
        )

        # Cost = 100 * 0.45 + 100 * 0.45 = 90
        # At resolution, payout is always 100 (size * 1)
        # Expected P&L before rebates = 100 - 90 = 10
        assert position.total_cost == Decimal("90")
        assert position.implied_fair_price == Decimal("0.90")

    def test_place_multiple_positions(self, simulator):
        """Test placing multiple delta-neutral positions."""
        pos1 = simulator.place_delta_neutral("market-1", 30, 0.50, 0.50)
        pos2 = simulator.place_delta_neutral("market-2", 30, 0.50, 0.50)
        pos3 = simulator.place_delta_neutral("market-3", 30, 0.50, 0.50)

        assert len(simulator.positions) == 3
        assert pos1.position_id != pos2.position_id
        assert pos2.position_id != pos3.position_id


class TestDeltaNeutralValidation:
    """Tests for validation of delta-neutral constraints."""

    def test_invalid_yes_price_too_high(self, simulator):
        """Test rejection of YES price >= 1."""
        with pytest.raises(DeltaNeutralError, match="YES price must be between 0 and 1"):
            simulator.place_delta_neutral("market-123", 50, 1.0, 0.50)

    def test_invalid_yes_price_too_low(self, simulator):
        """Test rejection of YES price <= 0."""
        with pytest.raises(DeltaNeutralError, match="YES price must be between 0 and 1"):
            simulator.place_delta_neutral("market-123", 50, 0.0, 0.50)

    def test_invalid_no_price_too_high(self, simulator):
        """Test rejection of NO price >= 1."""
        with pytest.raises(DeltaNeutralError, match="NO price must be between 0 and 1"):
            simulator.place_delta_neutral("market-123", 50, 0.50, 1.0)

    def test_invalid_no_price_too_low(self, simulator):
        """Test rejection of NO price <= 0."""
        with pytest.raises(DeltaNeutralError, match="NO price must be between 0 and 1"):
            simulator.place_delta_neutral("market-123", 50, 0.50, 0.0)

    def test_invalid_negative_yes_price(self, simulator):
        """Test rejection of negative YES price."""
        with pytest.raises(DeltaNeutralError, match="YES price must be between 0 and 1"):
            simulator.place_delta_neutral("market-123", 50, -0.1, 0.50)

    def test_delta_neutral_violation(self, simulator):
        """Test rejection when yes_price + no_price > 1."""
        with pytest.raises(DeltaNeutralError, match="Delta-neutral violation"):
            simulator.place_delta_neutral("market-123", 50, 0.60, 0.60)

    def test_invalid_size_zero(self, simulator):
        """Test rejection of zero size."""
        with pytest.raises(DeltaNeutralError, match="Size must be positive"):
            simulator.place_delta_neutral("market-123", 0, 0.50, 0.50)

    def test_invalid_size_negative(self, simulator):
        """Test rejection of negative size."""
        with pytest.raises(DeltaNeutralError, match="Size must be positive"):
            simulator.place_delta_neutral("market-123", -10, 0.50, 0.50)

    def test_size_exceeds_max(self, simulator):
        """Test rejection when size exceeds max position size."""
        with pytest.raises(DeltaNeutralError, match="exceeds max position size"):
            simulator.place_delta_neutral("market-123", 150, 0.50, 0.50)

    def test_max_concurrent_positions(self, simulator):
        """Test rejection when max concurrent positions reached."""
        simulator.place_delta_neutral("market-1", 30, 0.50, 0.50)
        simulator.place_delta_neutral("market-2", 30, 0.50, 0.50)
        simulator.place_delta_neutral("market-3", 30, 0.50, 0.50)

        with pytest.raises(DeltaNeutralError, match="Maximum concurrent positions"):
            simulator.place_delta_neutral("market-4", 30, 0.50, 0.50)

    def test_insufficient_balance(self, simulator):
        """Test rejection when balance is insufficient."""
        # Place one large position to consume most of the balance
        # Position 1: cost = 100 * 0.99 + 100 * 0.01 = 100
        # (asymmetric but valid: 0.99 + 0.01 = 1.0)
        simulator.place_delta_neutral("market-1", 100, 0.99, 0.01)  # cost=100
        # Balance now ~= 300 - 100 + 0.1 = 200.1

        # Position 2
        simulator.place_delta_neutral("market-2", 100, 0.99, 0.01)  # cost=100
        # Balance now ~= 200.1 - 100 + 0.1 = 100.2

        # Resolve one position to free up concurrent slot but keep balance low
        simulator.simulate_resolution("market-1", "YES")
        # Payout = 100, balance ~= 100.2 + 100 = 200.2

        # Now place position 3 - still within concurrent limit (only market-2 open)
        simulator.place_delta_neutral("market-3", 100, 0.99, 0.01)  # cost=100
        # Balance now ~= 200.2 - 100 + 0.1 = 100.3

        # Resolve position 2 to stay within concurrent limit
        simulator.simulate_resolution("market-2", "YES")
        # Payout = 100, balance ~= 100.3 + 100 = 200.3

        # Now place position 4
        simulator.place_delta_neutral("market-4", 100, 0.99, 0.01)  # cost=100
        # Balance now ~= 200.3 - 100 + 0.1 = 100.4

        # Resolve all open positions
        simulator.simulate_resolution("market-3", "YES")
        simulator.simulate_resolution("market-4", "YES")

        # Now balance should be ~= 300 (back to start with just rebates added)
        # Place three positions to drain balance
        simulator.place_delta_neutral("market-5", 100, 0.99, 0.01)  # cost=100
        simulator.place_delta_neutral("market-6", 100, 0.99, 0.01)  # cost=100
        simulator.place_delta_neutral("market-7", 100, 0.99, 0.01)  # cost=100
        # Balance now very low

        # Resolve 5 and 6 to free up concurrent slots, but keep balance low
        simulator.simulate_resolution("market-5", "YES")
        simulator.simulate_resolution("market-6", "YES")
        # Balance ~= rebates only + 200 from resolutions

        # Keep draining - this test is getting complex, let's simplify
        simulator.reset()

        # Use a simulator with lower max_concurrent to make testing easier
        sim2 = MakerPaperSimulator(
            initial_balance=100.0,  # Small balance
            max_position_size=100.0,
            max_concurrent_positions=5,  # More positions allowed
            log_trades=False,
        )

        # Try to place a position that costs more than our balance
        # Cost = 100 * 0.60 + 100 * 0.40 = 100, but we only have 100
        # After rebates, we'd have 100 - 100 + 0.1 = 0.1
        # So second position should fail
        sim2.place_delta_neutral("market-1", 100, 0.60, 0.40)

        with pytest.raises(InsufficientBalanceError, match="Insufficient balance"):
            sim2.place_delta_neutral("market-2", 100, 0.60, 0.40)


class TestResolution:
    """Tests for market resolution simulation."""

    def test_resolution_yes_wins_even_odds(self, simulator):
        """Test resolution when YES wins at 50/50 odds."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        pnl = simulator.simulate_resolution("market-123", "YES")

        # Cost = 50 (25 YES + 25 NO), Payout = 50 (YES wins)
        # P&L = 50 - 50 = 0
        assert pnl == Decimal("0")

    def test_resolution_no_wins_even_odds(self, simulator):
        """Test resolution when NO wins at 50/50 odds."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        pnl = simulator.simulate_resolution("market-123", "NO")

        # Cost = 50, Payout = 50 (NO wins)
        # P&L = 50 - 50 = 0
        assert pnl == Decimal("0")

    def test_resolution_yes_wins_with_edge(self, simulator):
        """Test resolution with positive edge when YES wins."""
        position = simulator.place_delta_neutral("market-123", 100, 0.45, 0.45)

        pnl = simulator.simulate_resolution("market-123", "YES")

        # Cost = 90 (45 + 45), Payout = 100
        # P&L = 100 - 90 = 10
        assert pnl == Decimal("10")
        assert position.pnl == Decimal("10")

    def test_resolution_no_wins_with_edge(self, simulator):
        """Test resolution with positive edge when NO wins."""
        position = simulator.place_delta_neutral("market-123", 100, 0.45, 0.45)

        pnl = simulator.simulate_resolution("market-123", "NO")

        # Cost = 90, Payout = 100
        # P&L = 100 - 90 = 10
        assert pnl == Decimal("10")
        assert position.pnl == Decimal("10")

    def test_resolution_marks_position_resolved(self, simulator):
        """Test that resolution marks position as resolved."""
        position = simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        assert not position.resolved
        assert position.resolution_outcome is None

        simulator.simulate_resolution("market-123", "YES")

        assert position.resolved
        assert position.resolution_outcome == "YES"

    def test_resolution_updates_balance(self, simulator):
        """Test that resolution updates balance correctly."""
        simulator.place_delta_neutral("market-123", 100, 0.45, 0.45)

        # Balance after open: 300 - 90 + 0.09 (rebates) = 210.09
        balance_after_open = simulator.balance

        simulator.simulate_resolution("market-123", "YES")

        # Balance after resolution: 210.09 + 100 (payout) = 310.09
        expected_balance = balance_after_open + Decimal("100")
        assert simulator.balance == expected_balance

    def test_resolution_updates_realized_pnl(self, simulator):
        """Test that resolution updates realized P&L."""
        simulator.place_delta_neutral("market-123", 100, 0.45, 0.45)

        assert simulator.realized_pnl == Decimal("0")

        simulator.simulate_resolution("market-123", "YES")

        # P&L = 100 - 90 = 10
        assert simulator.realized_pnl == Decimal("10")

    def test_resolution_invalid_outcome(self, simulator):
        """Test rejection of invalid outcome."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        with pytest.raises(ValueError, match="Outcome must be 'YES' or 'NO'"):
            simulator.simulate_resolution("market-123", "MAYBE")

    def test_resolution_no_positions(self, simulator):
        """Test resolution when no positions exist for market."""
        pnl = simulator.simulate_resolution("market-123", "YES")

        assert pnl == Decimal("0")

    def test_resolution_multiple_positions_same_market(self, simulator):
        """Test resolving multiple positions on the same market."""
        simulator.place_delta_neutral("market-123", 30, 0.45, 0.45)
        simulator.place_delta_neutral("market-123", 30, 0.45, 0.45)

        pnl = simulator.simulate_resolution("market-123", "YES")

        # Each position: P&L = 30 - 27 = 3
        # Total P&L = 3 + 3 = 6
        assert pnl == Decimal("6")

    def test_resolution_case_insensitive(self, simulator):
        """Test that outcome is case-insensitive."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        pnl = simulator.simulate_resolution("market-123", "yes")
        assert pnl == Decimal("0")


class TestDeltaCalculation:
    """Tests for delta exposure calculation."""

    def test_delta_zero_no_positions(self, simulator):
        """Test delta is zero with no positions."""
        assert simulator.get_delta() == Decimal("0")

    def test_delta_zero_delta_neutral(self, simulator):
        """Test delta is zero for delta-neutral positions."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        delta = simulator.get_delta()

        assert delta == Decimal("0")

    def test_delta_multiple_positions(self, simulator):
        """Test delta across multiple positions."""
        simulator.place_delta_neutral("market-1", 30, 0.50, 0.50)
        simulator.place_delta_neutral("market-2", 40, 0.50, 0.50)

        delta = simulator.get_delta()

        # Each position is delta-neutral (yes_size = no_size)
        assert delta == Decimal("0")

    def test_delta_excludes_resolved(self, simulator):
        """Test that resolved positions are excluded from delta."""
        simulator.place_delta_neutral("market-1", 50, 0.50, 0.50)
        simulator.place_delta_neutral("market-2", 50, 0.50, 0.50)

        simulator.simulate_resolution("market-1", "YES")

        # Only market-2 is open, delta should still be 0
        delta = simulator.get_delta()
        assert delta == Decimal("0")

    def test_position_is_delta_neutral(self, simulator):
        """Test DeltaNeutralPosition.is_delta_neutral property."""
        position = simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        assert position.is_delta_neutral
        assert position.delta == Decimal("0")


class TestRebateEstimation:
    """Tests for maker rebate estimation."""

    def test_rebates_calculated_correctly(self, simulator):
        """Test rebates are calculated based on total cost."""
        position = simulator.place_delta_neutral("market-123", 100, 0.50, 0.50)

        # Cost = 100, rebate rate = 0.1%
        # Rebates = 100 * 0.001 = 0.1
        expected_rebates = Decimal("0.1")
        assert position.rebates_earned == expected_rebates
        assert simulator.rebates_earned == expected_rebates

    def test_rebates_accumulate(self, simulator):
        """Test rebates accumulate across positions."""
        simulator.place_delta_neutral("market-1", 50, 0.50, 0.50)
        simulator.place_delta_neutral("market-2", 50, 0.50, 0.50)

        # Each position: rebates = 50 * 0.001 = 0.05
        # Total = 0.10
        expected_total_rebates = Decimal("0.10")
        assert simulator.rebates_earned == expected_total_rebates

    def test_rebates_in_stats(self, simulator):
        """Test rebates are included in stats."""
        simulator.place_delta_neutral("market-123", 100, 0.50, 0.50)

        stats = simulator.get_stats()

        # Rebates = 100 * 0.001 = 0.1
        assert Decimal(stats["rebates_earned"]) == Decimal("0.1")


class TestStats:
    """Tests for statistics reporting."""

    def test_stats_initial(self, simulator):
        """Test stats for fresh simulator."""
        stats = simulator.get_stats()

        assert Decimal(stats["initial_balance"]) == Decimal("300")
        assert Decimal(stats["current_balance"]) == Decimal("300")
        assert Decimal(stats["realized_pnl"]) == Decimal("0")
        assert Decimal(stats["rebates_earned"]) == Decimal("0")
        assert stats["total_trades"] == 0
        assert stats["open_positions"] == 0
        assert stats["closed_positions"] == 0
        assert stats["is_delta_neutral"] is True

    def test_stats_after_open_position(self, simulator):
        """Test stats after opening a position."""
        simulator.place_delta_neutral("market-123", 100, 0.50, 0.50)

        stats = simulator.get_stats()

        assert stats["total_trades"] == 1
        assert stats["open_positions"] == 1
        assert stats["closed_positions"] == 0
        assert Decimal(stats["locked_in_positions"]) == Decimal("100")

    def test_stats_after_resolution(self, simulator):
        """Test stats after resolving a position."""
        simulator.place_delta_neutral("market-123", 100, 0.45, 0.45)
        simulator.simulate_resolution("market-123", "YES")

        stats = simulator.get_stats()

        assert stats["open_positions"] == 0
        assert stats["closed_positions"] == 1
        assert Decimal(stats["realized_pnl"]) == Decimal("10")
        assert stats["win_rate"] == "100.0%"

    def test_stats_win_rate_calculation(self, simulator):
        """Test win rate calculation."""
        # Position 1: Win (positive edge: 0.45 + 0.45 = 0.90)
        simulator.place_delta_neutral("market-1", 30, 0.45, 0.45)
        simulator.simulate_resolution("market-1", "YES")

        # Position 2: Also a win (0.50 + 0.50 = 1.0, break-even)
        simulator.place_delta_neutral("market-2", 30, 0.50, 0.50)
        simulator.simulate_resolution("market-2", "YES")

        stats = simulator.get_stats()

        # 2 wins (P&L >= 0), 0 losses = 100% win rate
        assert stats["closed_positions"] == 2
        assert stats["win_rate"] == "100.0%"


class TestReset:
    """Tests for reset functionality."""

    def test_reset_restores_balance(self, simulator):
        """Test reset restores initial balance."""
        simulator.place_delta_neutral("market-123", 100, 0.50, 0.50)

        simulator.reset()

        assert simulator.balance == Decimal("300")

    def test_reset_clears_positions(self, simulator):
        """Test reset clears all positions."""
        simulator.place_delta_neutral("market-1", 50, 0.50, 0.50)
        simulator.place_delta_neutral("market-2", 50, 0.50, 0.50)

        simulator.reset()

        assert len(simulator.positions) == 0
        assert len(simulator.get_open_positions()) == 0

    def test_reset_clears_pnl(self, simulator):
        """Test reset clears P&L values."""
        simulator.place_delta_neutral("market-123", 100, 0.45, 0.45)
        simulator.simulate_resolution("market-123", "YES")

        simulator.reset()

        assert simulator.realized_pnl == Decimal("0")
        assert simulator.rebates_earned == Decimal("0")

    def test_reset_clears_trades(self, simulator):
        """Test reset clears trade history."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        simulator.reset()

        assert len(simulator.trades) == 0


class TestDailyLossLimit:
    """Tests for daily loss limit (kill switch)."""

    def test_daily_loss_tracking_no_loss_on_delta_neutral(self, simulator):
        """Test that delta-neutral positions don't generate losses."""
        # With yes_price + no_price <= 1, we always break even or profit
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)
        simulator.simulate_resolution("market-123", "YES")

        stats = simulator.get_stats()
        # No loss because payout (50) >= cost (50)
        assert Decimal(stats["daily_loss"]) == Decimal("0")

    def test_daily_loss_remaining_full(self, simulator):
        """Test daily loss remaining when no losses incurred."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)
        simulator.simulate_resolution("market-123", "YES")

        stats = simulator.get_stats()
        # Max daily loss = 30, No losses, Remaining = 30
        assert Decimal(stats["daily_loss_remaining"]) == Decimal("30")


class TestTradeLogging:
    """Tests for trade logging."""

    def test_trade_logged_on_open(self, simulator):
        """Test trade is logged when opening position."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        trades = simulator.get_trade_history()

        assert len(trades) == 1
        assert trades[0]["event"] == "OPEN_DELTA_NEUTRAL"
        assert trades[0]["market_id"] == "market-123"

    def test_trade_logged_on_resolution(self, simulator):
        """Test trade is logged on resolution."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)
        simulator.simulate_resolution("market-123", "YES")

        trades = simulator.get_trade_history()

        assert len(trades) == 2
        assert trades[1]["event"] == "RESOLUTION"
        assert trades[1]["outcome"] == "YES"


class TestDeltaNeutralPositionDataclass:
    """Tests for DeltaNeutralPosition dataclass."""

    def test_delta_property(self):
        """Test delta property calculation."""
        position = DeltaNeutralPosition(
            position_id="test",
            market_id="market-123",
            yes_size=Decimal("50"),
            yes_price=Decimal("0.50"),
            no_size=Decimal("50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("50"),
        )

        assert position.delta == Decimal("0")

    def test_is_delta_neutral_property(self):
        """Test is_delta_neutral property."""
        position = DeltaNeutralPosition(
            position_id="test",
            market_id="market-123",
            yes_size=Decimal("50"),
            yes_price=Decimal("0.50"),
            no_size=Decimal("50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("50"),
        )

        assert position.is_delta_neutral is True

    def test_implied_fair_price_property(self):
        """Test implied_fair_price property."""
        position = DeltaNeutralPosition(
            position_id="test",
            market_id="market-123",
            yes_size=Decimal("50"),
            yes_price=Decimal("0.45"),
            no_size=Decimal("50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("47.5"),
        )

        assert position.implied_fair_price == Decimal("0.95")


class TestOpenPositions:
    """Tests for get_open_positions method."""

    def test_get_open_positions_empty(self, simulator):
        """Test get_open_positions with no positions."""
        positions = simulator.get_open_positions()
        assert len(positions) == 0

    def test_get_open_positions_filters_resolved(self, simulator):
        """Test get_open_positions filters out resolved positions."""
        simulator.place_delta_neutral("market-1", 30, 0.50, 0.50)
        simulator.place_delta_neutral("market-2", 30, 0.50, 0.50)

        simulator.simulate_resolution("market-1", "YES")

        open_positions = simulator.get_open_positions()

        assert len(open_positions) == 1
        assert open_positions[0].market_id == "market-2"


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_small_sizes(self, simulator):
        """Test handling very small position sizes."""
        position = simulator.place_delta_neutral("market-123", 0.01, 0.50, 0.50)

        assert position.yes_size == Decimal("0.01")
        assert position.no_size == Decimal("0.01")

    def test_prices_near_boundaries(self, simulator):
        """Test prices near 0 and 1 boundaries."""
        position = simulator.place_delta_neutral("market-123", 50, 0.01, 0.01)

        assert position.yes_price == Decimal("0.01")
        assert position.no_price == Decimal("0.01")
        # Total price = 0.02, well under 1

    def test_exactly_sum_to_one(self, simulator):
        """Test prices that exactly sum to 1 (break-even, no edge)."""
        position = simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        assert position.implied_fair_price == Decimal("1.00")

    def test_resolution_pnl_zero_at_fair_price(self, simulator):
        """Test P&L is zero when prices sum to 1."""
        simulator.place_delta_neutral("market-123", 100, 0.50, 0.50)

        pnl_yes = simulator.simulate_resolution("market-123", "YES")

        # Cost = 100, Payout = 100
        assert pnl_yes == Decimal("0")

    def test_same_market_id_multiple_times(self, simulator):
        """Test opening multiple positions on same market."""
        pos1 = simulator.place_delta_neutral("market-123", 30, 0.50, 0.50)
        pos2 = simulator.place_delta_neutral("market-123", 30, 0.50, 0.50)

        assert pos1.market_id == pos2.market_id
        assert pos1.position_id != pos2.position_id
        assert len(simulator.positions) == 2

    def test_resolution_only_affects_unresolved(self, simulator):
        """Test resolution only affects unresolved positions."""
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)
        simulator.simulate_resolution("market-123", "YES")

        # Open new position on same market
        simulator.place_delta_neutral("market-123", 50, 0.50, 0.50)

        # Only 1 open position
        assert len(simulator.get_open_positions()) == 1
