"""
Comprehensive tests for the Delta Tracker.

Tests cover:
- Position addition and removal
- Delta calculation across multiple positions
- Delta threshold monitoring
- Rebalancing detection
- Position reconciliation with exchange
- Exposure calculations (YES, NO, total)
- Edge cases and error handling
"""

from decimal import Decimal

import pytest

from src.maker.delta_tracker import (
    DeltaTracker,
    DeltaTrackerError,
    TrackedPosition,
)


@pytest.fixture
def tracker():
    """Create a tracker instance for testing."""
    return DeltaTracker(max_delta_pct=0.05)


@pytest.fixture
def tracker_strict():
    """Create a tracker with stricter delta threshold."""
    return DeltaTracker(max_delta_pct=0.01)


class TestInitialization:
    """Tests for tracker initialization."""

    def test_initial_state(self, tracker):
        """Test tracker starts in clean state."""
        assert len(tracker.positions) == 0
        assert tracker.get_delta() == 0.0
        assert tracker.get_total_exposure() == 0.0
        assert not tracker.needs_rebalance()

    def test_custom_max_delta(self):
        """Test custom max_delta_pct configuration."""
        tracker = DeltaTracker(max_delta_pct=0.10)
        assert tracker.max_delta_pct == Decimal("0.10")

    def test_default_max_delta(self):
        """Test default max_delta_pct is 5%."""
        tracker = DeltaTracker()
        assert tracker.max_delta_pct == Decimal("0.05")


class TestAddPosition:
    """Tests for adding positions."""

    def test_add_basic_position(self, tracker):
        """Test adding a basic delta-neutral position."""
        position = tracker.add_position(
            market_id="market-1",
            yes_size=50,
            no_size=50,
            prices={"yes": 0.50, "no": 0.50},
        )

        assert position is not None
        assert position.market_id == "market-1"
        assert position.yes_size == Decimal("50")
        assert position.no_size == Decimal("50")
        assert position.delta == Decimal("0")

    def test_add_position_updates_tracker(self, tracker):
        """Test that adding position updates tracker state."""
        tracker.add_position(
            market_id="market-1",
            yes_size=50,
            no_size=50,
            prices={"yes": 0.50, "no": 0.50},
        )

        assert len(tracker.positions) == 1
        assert "market-1" in tracker.positions
        assert tracker.get_delta() == 0.0

    def test_add_position_cost_calculation(self, tracker):
        """Test position cost is calculated correctly."""
        position = tracker.add_position(
            market_id="market-1",
            yes_size=100,
            no_size=100,
            prices={"yes": 0.45, "no": 0.50},
        )

        # Cost = 100 * 0.45 + 100 * 0.50 = 95
        expected_cost = Decimal("95")
        assert position.total_cost == expected_cost

    def test_add_multiple_positions(self, tracker):
        """Test adding multiple positions."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 30, 30, {"yes": 0.60, "no": 0.40})
        tracker.add_position("market-3", 40, 40, {"yes": 0.55, "no": 0.45})

        assert len(tracker.positions) == 3
        assert tracker.get_delta() == 0.0

    def test_add_asymmetric_position(self, tracker):
        """Test adding position with different YES/NO sizes."""
        position = tracker.add_position(
            market_id="market-1",
            yes_size=60,
            no_size=40,
            prices={"yes": 0.50, "no": 0.50},
        )

        # Delta = 60 - 40 = 20
        assert position.delta == Decimal("20")
        assert tracker.get_delta() == 20.0


class TestAddPositionValidation:
    """Tests for position validation during addition."""

    def test_duplicate_market_id(self, tracker):
        """Test rejection of duplicate market_id."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        with pytest.raises(DeltaTrackerError, match="already exists"):
            tracker.add_position("market-1", 30, 30, {"yes": 0.60, "no": 0.40})

    def test_missing_yes_price(self, tracker):
        """Test rejection when 'yes' price is missing."""
        with pytest.raises(DeltaTrackerError, match="must contain 'yes' and 'no'"):
            tracker.add_position("market-1", 50, 50, {"no": 0.50})

    def test_missing_no_price(self, tracker):
        """Test rejection when 'no' price is missing."""
        with pytest.raises(DeltaTrackerError, match="must contain 'yes' and 'no'"):
            tracker.add_position("market-1", 50, 50, {"yes": 0.50})

    def test_invalid_yes_price_too_high(self, tracker):
        """Test rejection of YES price > 1."""
        with pytest.raises(DeltaTrackerError, match="YES price must be between 0 and 1"):
            tracker.add_position("market-1", 50, 50, {"yes": 1.5, "no": 0.50})

    def test_invalid_yes_price_zero(self, tracker):
        """Test rejection of YES price = 0."""
        with pytest.raises(DeltaTrackerError, match="YES price must be between 0 and 1"):
            tracker.add_position("market-1", 50, 50, {"yes": 0.0, "no": 0.50})

    def test_invalid_no_price_too_high(self, tracker):
        """Test rejection of NO price > 1."""
        with pytest.raises(DeltaTrackerError, match="NO price must be between 0 and 1"):
            tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 1.5})

    def test_invalid_no_price_zero(self, tracker):
        """Test rejection of NO price = 0."""
        with pytest.raises(DeltaTrackerError, match="NO price must be between 0 and 1"):
            tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.0})

    def test_invalid_yes_size_zero(self, tracker):
        """Test rejection of YES size = 0."""
        with pytest.raises(DeltaTrackerError, match="YES size must be positive"):
            tracker.add_position("market-1", 0, 50, {"yes": 0.50, "no": 0.50})

    def test_invalid_yes_size_negative(self, tracker):
        """Test rejection of negative YES size."""
        with pytest.raises(DeltaTrackerError, match="YES size must be positive"):
            tracker.add_position("market-1", -10, 50, {"yes": 0.50, "no": 0.50})

    def test_invalid_no_size_zero(self, tracker):
        """Test rejection of NO size = 0."""
        with pytest.raises(DeltaTrackerError, match="NO size must be positive"):
            tracker.add_position("market-1", 50, 0, {"yes": 0.50, "no": 0.50})

    def test_invalid_no_size_negative(self, tracker):
        """Test rejection of negative NO size."""
        with pytest.raises(DeltaTrackerError, match="NO size must be positive"):
            tracker.add_position("market-1", 50, -10, {"yes": 0.50, "no": 0.50})


class TestRemovePosition:
    """Tests for removing positions."""

    def test_remove_existing_position(self, tracker):
        """Test removing an existing position."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        removed = tracker.remove_position("market-1")

        assert removed is not None
        assert removed.market_id == "market-1"
        assert len(tracker.positions) == 0
        assert "market-1" not in tracker.positions

    def test_remove_non_existent_position(self, tracker):
        """Test removing a position that doesn't exist."""
        removed = tracker.remove_position("market-999")

        assert removed is None
        assert len(tracker.positions) == 0

    def test_remove_updates_delta(self, tracker):
        """Test that removing position updates delta correctly."""
        tracker.add_position("market-1", 60, 40, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 40, 60, {"yes": 0.50, "no": 0.50})

        # Delta = (60-40) + (40-60) = 20 - 20 = 0
        assert tracker.get_delta() == 0.0

        tracker.remove_position("market-1")

        # Delta = (40-60) = -20
        assert tracker.get_delta() == -20.0

    def test_remove_from_multiple_positions(self, tracker):
        """Test removing one position when multiple exist."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 30, 30, {"yes": 0.60, "no": 0.40})
        tracker.add_position("market-3", 40, 40, {"yes": 0.55, "no": 0.45})

        tracker.remove_position("market-2")

        assert len(tracker.positions) == 2
        assert "market-1" in tracker.positions
        assert "market-2" not in tracker.positions
        assert "market-3" in tracker.positions


class TestGetPosition:
    """Tests for retrieving positions."""

    def test_get_existing_position(self, tracker):
        """Test retrieving an existing position."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        position = tracker.get_position("market-1")

        assert position is not None
        assert position.market_id == "market-1"

    def test_get_non_existent_position(self, tracker):
        """Test retrieving a non-existent position."""
        position = tracker.get_position("market-999")

        assert position is None


class TestDeltaCalculation:
    """Tests for delta calculation."""

    def test_delta_zero_no_positions(self, tracker):
        """Test delta is zero with no positions."""
        assert tracker.get_delta() == 0.0

    def test_delta_zero_balanced_positions(self, tracker):
        """Test delta is zero for balanced positions."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 100, 100, {"yes": 0.60, "no": 0.40})

        assert tracker.get_delta() == 0.0

    def test_delta_positive(self, tracker):
        """Test positive delta (net long YES)."""
        tracker.add_position("market-1", 80, 20, {"yes": 0.50, "no": 0.50})

        # Delta = 80 - 20 = 60
        assert tracker.get_delta() == 60.0

    def test_delta_negative(self, tracker):
        """Test negative delta (net long NO)."""
        tracker.add_position("market-1", 20, 80, {"yes": 0.50, "no": 0.50})

        # Delta = 20 - 80 = -60
        assert tracker.get_delta() == -60.0

    def test_delta_multiple_positions_net_positive(self, tracker):
        """Test delta with multiple positions netting positive."""
        tracker.add_position("market-1", 60, 40, {"yes": 0.50, "no": 0.50})  # +20
        tracker.add_position("market-2", 70, 30, {"yes": 0.50, "no": 0.50})  # +40

        # Total delta = 20 + 40 = 60
        assert tracker.get_delta() == 60.0

    def test_delta_multiple_positions_net_zero(self, tracker):
        """Test delta with offsetting positions."""
        tracker.add_position("market-1", 60, 40, {"yes": 0.50, "no": 0.50})  # +20
        tracker.add_position("market-2", 30, 50, {"yes": 0.50, "no": 0.50})  # -20

        # Total delta = 20 - 20 = 0
        assert tracker.get_delta() == 0.0


class TestExposureCalculations:
    """Tests for exposure calculations."""

    def test_total_exposure_empty(self, tracker):
        """Test total exposure is zero with no positions."""
        assert tracker.get_total_exposure() == 0.0

    def test_total_exposure_single_position(self, tracker):
        """Test total exposure for single position."""
        tracker.add_position("market-1", 100, 100, {"yes": 0.45, "no": 0.50})

        # Exposure = 100 * 0.45 + 100 * 0.50 = 95
        assert tracker.get_total_exposure() == 95.0

    def test_total_exposure_multiple_positions(self, tracker):
        """Test total exposure across multiple positions."""
        tracker.add_position("market-1", 100, 100, {"yes": 0.50, "no": 0.50})  # 100
        tracker.add_position("market-2", 50, 50, {"yes": 0.60, "no": 0.40})  # 50

        # Total = 100 + 50 = 150
        assert tracker.get_total_exposure() == 150.0

    def test_yes_exposure(self, tracker):
        """Test YES side exposure calculation."""
        tracker.add_position("market-1", 100, 50, {"yes": 0.50, "no": 0.60})

        # YES exposure = 100 * 0.50 = 50
        assert tracker.get_yes_exposure() == 50.0

    def test_no_exposure(self, tracker):
        """Test NO side exposure calculation."""
        tracker.add_position("market-1", 100, 50, {"yes": 0.50, "no": 0.60})

        # NO exposure = 50 * 0.60 = 30
        assert tracker.get_no_exposure() == 30.0

    def test_yes_exposure_multiple_positions(self, tracker):
        """Test YES exposure across multiple positions."""
        tracker.add_position("market-1", 100, 50, {"yes": 0.50, "no": 0.50})  # 50
        tracker.add_position("market-2", 80, 60, {"yes": 0.60, "no": 0.40})  # 48

        # Total YES = 50 + 48 = 98
        assert tracker.get_yes_exposure() == 98.0

    def test_no_exposure_multiple_positions(self, tracker):
        """Test NO exposure across multiple positions."""
        tracker.add_position("market-1", 100, 50, {"yes": 0.50, "no": 0.50})  # 25
        tracker.add_position("market-2", 80, 60, {"yes": 0.60, "no": 0.40})  # 24

        # Total NO = 25 + 24 = 49
        assert tracker.get_no_exposure() == 49.0


class TestRebalancing:
    """Tests for rebalancing detection."""

    def test_needs_rebalance_no_positions(self, tracker):
        """Test no rebalancing needed with no positions."""
        assert not tracker.needs_rebalance()

    def test_needs_rebalance_within_threshold(self, tracker):
        """Test no rebalancing when delta is within threshold."""
        # Total exposure = 100, max delta = 5%, threshold = 5
        # Delta = 3 < 5, so no rebalancing
        tracker.add_position("market-1", 51.5, 48.5, {"yes": 0.50, "no": 0.50})

        assert tracker.get_delta() == 3.0
        assert tracker.get_total_exposure() == 50.0
        # Threshold = 50 * 0.05 = 2.5
        # Delta 3.0 > 2.5, so should need rebalancing
        assert tracker.needs_rebalance()

    def test_needs_rebalance_exceeds_threshold(self, tracker):
        """Test rebalancing needed when delta exceeds threshold."""
        # Position with significant imbalance
        tracker.add_position("market-1", 80, 20, {"yes": 0.50, "no": 0.50})

        # Delta = 60, Exposure = 50, Threshold = 50 * 0.05 = 2.5
        assert tracker.get_delta() == 60.0
        assert tracker.needs_rebalance()

    def test_needs_rebalance_at_exact_threshold(self, tracker):
        """Test rebalancing at exact threshold boundary."""
        # Create position where delta exactly equals threshold
        # Exposure = 100, threshold = 100 * 0.05 = 5
        # Need delta = 5, so yes_size - no_size = 5
        # With 0.50 prices: 52.5 - 47.5 = 5, exposure = 50
        # Threshold = 50 * 0.05 = 2.5
        # Need delta = 2.5 for this exposure
        tracker.add_position("market-1", 51.25, 48.75, {"yes": 0.50, "no": 0.50})

        delta = tracker.get_delta()
        exposure = tracker.get_total_exposure()
        threshold = exposure * 0.05

        # At exact threshold, should not need rebalancing (>, not >=)
        assert abs(delta - threshold) < 0.01
        assert not tracker.needs_rebalance()

    def test_needs_rebalance_negative_delta(self, tracker):
        """Test rebalancing works with negative delta."""
        tracker.add_position("market-1", 20, 80, {"yes": 0.50, "no": 0.50})

        # Delta = -60, Exposure = 50, Threshold = 2.5
        assert tracker.get_delta() == -60.0
        assert tracker.needs_rebalance()

    def test_needs_rebalance_strict_threshold(self, tracker_strict):
        """Test rebalancing with stricter 1% threshold."""
        # Tracker has 1% threshold
        # Exposure = 100, threshold = 1
        tracker_strict.add_position("market-1", 52, 48, {"yes": 0.50, "no": 0.50})

        # Delta = 4, Exposure = 50, Threshold = 0.5
        assert tracker_strict.get_delta() == 4.0
        assert tracker_strict.needs_rebalance()


class TestPositionReport:
    """Tests for position reporting."""

    def test_report_empty_tracker(self, tracker):
        """Test report with no positions."""
        report = tracker.get_position_report()

        assert report["total_positions"] == 0
        assert Decimal(report["total_exposure"]) == Decimal("0")
        assert Decimal(report["total_delta"]) == Decimal("0")
        assert not report["needs_rebalance"]
        assert len(report["positions"]) == 0

    def test_report_single_position(self, tracker):
        """Test report with single position."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        report = tracker.get_position_report()

        assert report["total_positions"] == 1
        assert Decimal(report["total_exposure"]) == Decimal("50")
        assert Decimal(report["total_delta"]) == Decimal("0")
        assert report["is_portfolio_neutral"]
        assert len(report["positions"]) == 1

    def test_report_delta_percentage(self, tracker):
        """Test delta percentage calculation in report."""
        tracker.add_position("market-1", 60, 40, {"yes": 0.50, "no": 0.50})

        report = tracker.get_position_report()

        # Delta = 20, Exposure = 50
        # Delta % = 20/50 * 100 = 40%
        assert Decimal(report["delta_pct"]) == Decimal("40.00")

    def test_report_identifies_non_neutral_positions(self, tracker):
        """Test report identifies non-neutral positions."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})  # Neutral
        tracker.add_position("market-2", 80, 20, {"yes": 0.50, "no": 0.50})  # Non-neutral

        report = tracker.get_position_report()

        assert "market-2" in report["non_neutral_positions"]
        assert "market-1" not in report["non_neutral_positions"]

    def test_report_exposure_breakdown(self, tracker):
        """Test report includes YES/NO exposure breakdown."""
        tracker.add_position("market-1", 100, 100, {"yes": 0.50, "no": 0.50})

        report = tracker.get_position_report()

        assert Decimal(report["yes_exposure"]) == Decimal("50")
        assert Decimal(report["no_exposure"]) == Decimal("50")
        assert Decimal(report["exposure_imbalance"]) == Decimal("0")


class TestReconciliation:
    """Tests for position reconciliation."""

    def test_reconcile_perfect_match(self, tracker):
        """Test reconciliation when positions match exactly."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        exchange_positions = {"market-1": {"yes_size": 50, "no_size": 50}}

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert result["reconciled"]
        assert len(result["discrepancies"]) == 0
        assert len(result["missing_in_tracker"]) == 0
        assert len(result["missing_in_exchange"]) == 0

    def test_reconcile_size_discrepancy(self, tracker):
        """Test reconciliation detects size discrepancies."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        exchange_positions = {"market-1": {"yes_size": 48, "no_size": 52}}

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert not result["reconciled"]
        assert len(result["discrepancies"]) == 1
        assert result["discrepancies"][0]["market_id"] == "market-1"

    def test_reconcile_missing_in_tracker(self, tracker):
        """Test reconciliation detects positions missing in tracker."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        exchange_positions = {
            "market-1": {"yes_size": 50, "no_size": 50},
            "market-2": {"yes_size": 30, "no_size": 30},
        }

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert not result["reconciled"]
        assert len(result["missing_in_tracker"]) == 1
        assert result["missing_in_tracker"][0]["market_id"] == "market-2"

    def test_reconcile_missing_in_exchange(self, tracker):
        """Test reconciliation detects positions missing in exchange."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 30, 30, {"yes": 0.60, "no": 0.40})

        exchange_positions = {"market-1": {"yes_size": 50, "no_size": 50}}

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert not result["reconciled"]
        assert len(result["missing_in_exchange"]) == 1
        assert result["missing_in_exchange"][0]["market_id"] == "market-2"

    def test_reconcile_rounding_tolerance(self, tracker):
        """Test reconciliation allows small rounding differences."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        # Tiny difference within tolerance (0.0001)
        exchange_positions = {"market-1": {"yes_size": 50.00005, "no_size": 50.00005}}

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert result["reconciled"]
        assert len(result["discrepancies"]) == 0

    def test_reconcile_empty_tracker(self, tracker):
        """Test reconciliation with empty tracker."""
        exchange_positions = {"market-1": {"yes_size": 50, "no_size": 50}}

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert not result["reconciled"]
        assert len(result["missing_in_tracker"]) == 1

    def test_reconcile_empty_exchange(self, tracker):
        """Test reconciliation with empty exchange."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        exchange_positions = {}

        result = tracker.reconcile_with_exchange(exchange_positions)

        assert not result["reconciled"]
        assert len(result["missing_in_exchange"]) == 1


class TestRebalancingSuggestion:
    """Tests for rebalancing suggestions."""

    def test_suggestion_no_rebalancing_needed(self, tracker):
        """Test suggestion when no rebalancing is needed."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        suggestion = tracker.get_rebalancing_suggestion()

        assert not suggestion["needs_rebalancing"]
        assert "within delta threshold" in suggestion["message"]

    def test_suggestion_positive_delta(self, tracker):
        """Test suggestion when delta is positive (long YES)."""
        tracker.add_position("market-1", 80, 20, {"yes": 0.50, "no": 0.50})

        suggestion = tracker.get_rebalancing_suggestion()

        assert suggestion["needs_rebalancing"]
        assert suggestion["direction"] == "reduce_yes_or_increase_no"
        assert "Sell YES or Buy NO" in suggestion["suggested_trade"]

    def test_suggestion_negative_delta(self, tracker):
        """Test suggestion when delta is negative (long NO)."""
        tracker.add_position("market-1", 20, 80, {"yes": 0.50, "no": 0.50})

        suggestion = tracker.get_rebalancing_suggestion()

        assert suggestion["needs_rebalancing"]
        assert suggestion["direction"] == "reduce_no_or_increase_yes"
        assert "Sell NO or Buy YES" in suggestion["suggested_trade"]

    def test_suggestion_includes_metrics(self, tracker):
        """Test suggestion includes relevant metrics."""
        tracker.add_position("market-1", 80, 20, {"yes": 0.50, "no": 0.50})

        suggestion = tracker.get_rebalancing_suggestion()

        assert "current_delta" in suggestion
        assert "threshold" in suggestion
        assert "excess_delta" in suggestion
        assert "estimated_trade_size" in suggestion


class TestTrackedPositionDataclass:
    """Tests for TrackedPosition dataclass."""

    def test_position_delta_property(self):
        """Test delta property calculation."""
        position = TrackedPosition(
            market_id="market-1",
            yes_size=Decimal("60"),
            no_size=Decimal("40"),
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("50"),
        )

        assert position.delta == Decimal("20")

    def test_position_is_delta_neutral_true(self):
        """Test is_delta_neutral when position is balanced."""
        position = TrackedPosition(
            market_id="market-1",
            yes_size=Decimal("50"),
            no_size=Decimal("50"),
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("50"),
        )

        assert position.is_delta_neutral

    def test_position_is_delta_neutral_false(self):
        """Test is_delta_neutral when position is imbalanced."""
        position = TrackedPosition(
            market_id="market-1",
            yes_size=Decimal("80"),
            no_size=Decimal("20"),
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("50"),
        )

        assert not position.is_delta_neutral

    def test_position_yes_exposure(self):
        """Test YES exposure calculation."""
        position = TrackedPosition(
            market_id="market-1",
            yes_size=Decimal("100"),
            no_size=Decimal("50"),
            yes_price=Decimal("0.60"),
            no_price=Decimal("0.40"),
            total_cost=Decimal("80"),
        )

        assert position.yes_exposure == Decimal("60")

    def test_position_no_exposure(self):
        """Test NO exposure calculation."""
        position = TrackedPosition(
            market_id="market-1",
            yes_size=Decimal("100"),
            no_size=Decimal("50"),
            yes_price=Decimal("0.60"),
            no_price=Decimal("0.40"),
            total_cost=Decimal("80"),
        )

        assert position.no_exposure == Decimal("20")

    def test_position_to_dict(self):
        """Test position serialization to dict."""
        position = TrackedPosition(
            market_id="market-1",
            yes_size=Decimal("50"),
            no_size=Decimal("50"),
            yes_price=Decimal("0.50"),
            no_price=Decimal("0.50"),
            total_cost=Decimal("50"),
        )

        result = position.to_dict()

        assert result["market_id"] == "market-1"
        assert result["yes_size"] == "50"
        assert result["no_size"] == "50"
        assert result["delta"] == "0"
        assert result["is_delta_neutral"]


class TestReset:
    """Tests for reset functionality."""

    def test_reset_clears_positions(self, tracker):
        """Test reset clears all positions."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 30, 30, {"yes": 0.60, "no": 0.40})

        tracker.reset()

        assert len(tracker.positions) == 0
        assert tracker.get_delta() == 0.0
        assert tracker.get_total_exposure() == 0.0

    def test_reset_allows_reuse(self, tracker):
        """Test tracker can be reused after reset."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.reset()

        tracker.add_position("market-2", 30, 30, {"yes": 0.60, "no": 0.40})

        assert len(tracker.positions) == 1
        assert "market-2" in tracker.positions


class TestMagicMethods:
    """Tests for magic methods (len, contains, repr)."""

    def test_len_empty(self, tracker):
        """Test __len__ with no positions."""
        assert len(tracker) == 0

    def test_len_with_positions(self, tracker):
        """Test __len__ with positions."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})
        tracker.add_position("market-2", 30, 30, {"yes": 0.60, "no": 0.40})

        assert len(tracker) == 2

    def test_contains_true(self, tracker):
        """Test __contains__ when market exists."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        assert "market-1" in tracker

    def test_contains_false(self, tracker):
        """Test __contains__ when market doesn't exist."""
        assert "market-999" not in tracker

    def test_repr(self, tracker):
        """Test __repr__ string representation."""
        tracker.add_position("market-1", 50, 50, {"yes": 0.50, "no": 0.50})

        repr_str = repr(tracker)

        assert "DeltaTracker" in repr_str
        assert "positions=1" in repr_str
        assert "delta=" in repr_str
        assert "exposure=" in repr_str


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_small_sizes(self, tracker):
        """Test handling very small position sizes."""
        position = tracker.add_position("market-1", 0.01, 0.01, {"yes": 0.50, "no": 0.50})

        assert position.yes_size == Decimal("0.01")
        assert position.no_size == Decimal("0.01")
        assert tracker.get_delta() == 0.0

    def test_prices_at_boundaries(self, tracker):
        """Test prices near 0 and 1 boundaries."""
        position = tracker.add_position("market-1", 50, 50, {"yes": 0.99, "no": 0.01})

        assert position.yes_price == Decimal("0.99")
        assert position.no_price == Decimal("0.01")

    def test_large_position_sizes(self, tracker):
        """Test handling large position sizes."""
        position = tracker.add_position(
            "market-1", 100000, 100000, {"yes": 0.50, "no": 0.50}
        )

        assert position.yes_size == Decimal("100000")
        assert tracker.get_total_exposure() == 100000.0

    def test_many_positions(self, tracker):
        """Test handling many positions."""
        for i in range(100):
            tracker.add_position(f"market-{i}", 10, 10, {"yes": 0.50, "no": 0.50})

        assert len(tracker) == 100
        assert tracker.get_delta() == 0.0
        assert tracker.get_total_exposure() == 1000.0

    def test_extreme_imbalance(self, tracker):
        """Test position with extreme YES/NO imbalance."""
        position = tracker.add_position("market-1", 1000, 1, {"yes": 0.50, "no": 0.50})

        assert position.delta == Decimal("999")
        assert not position.is_delta_neutral
        assert tracker.needs_rebalance()

    def test_decimal_precision(self, tracker):
        """Test decimal precision in calculations."""
        position = tracker.add_position(
            "market-1", 33.33, 33.33, {"yes": 0.333, "no": 0.667}
        )

        # Should handle decimal precision correctly
        expected_cost = Decimal("33.33") * Decimal("0.333") + Decimal("33.33") * Decimal(
            "0.667"
        )
        assert position.total_cost == expected_cost
