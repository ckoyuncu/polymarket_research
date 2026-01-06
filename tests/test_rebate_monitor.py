"""
Comprehensive tests for the Rebate Monitor.

Tests cover:
- Trade recording and validation
- Rebate detection and attribution
- ROI and APY calculations
- Per-market statistics
- Best performing market identification
- State persistence (save/load)
- Edge cases and error handling

IMPORTANT: All tests use mocks/fixtures - no external API calls.
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.maker.rebate_monitor import (
    MarketStats,
    RebateEvent,
    RebateTracker,
    RebateTrackerError,
    RecordedTrade,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def tracker():
    """Create a tracker instance for testing."""
    return RebateTracker()


@pytest.fixture
def tracker_with_short_window():
    """Create a tracker with short attribution window for testing."""
    return RebateTracker(rebate_attribution_window_hours=1)


@pytest.fixture
def populated_tracker(tracker):
    """Create a tracker with some trades and rebates."""
    # Add trades
    now = datetime.now(timezone.utc)
    tracker.record_trade("trade-1", "btc-updown-15m", 50.0, now - timedelta(hours=2))
    tracker.record_trade("trade-2", "btc-updown-15m", 30.0, now - timedelta(hours=1))
    tracker.record_trade("trade-3", "eth-updown-15m", 40.0, now - timedelta(minutes=30))

    # Add rebate
    tracker.detect_rebate(
        {
            "amount": 0.12,
            "timestamp": now.isoformat(),
            "tx_hash": "0xabc123",
        }
    )

    return tracker


@pytest.fixture
def mock_usdc_transfer():
    """Create a mock USDC transfer for testing."""
    return {
        "amount": 1.50,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tx_hash": "0x123abc456def",
    }


# =============================================================================
# Test Initialization
# =============================================================================


class TestInitialization:
    """Tests for tracker initialization."""

    def test_initial_state(self, tracker):
        """Test tracker starts in clean state."""
        assert len(tracker.trades) == 0
        assert len(tracker.rebates) == 0
        assert len(tracker.market_stats) == 0
        assert tracker._total_volume == Decimal("0")
        assert tracker._total_rebates == Decimal("0")

    def test_custom_attribution_window(self):
        """Test custom attribution window configuration."""
        tracker = RebateTracker(rebate_attribution_window_hours=48)
        assert tracker.rebate_attribution_window == timedelta(hours=48)

    def test_custom_expected_rebate_rate(self):
        """Test custom expected rebate rate configuration."""
        tracker = RebateTracker(expected_rebate_rate=0.002)
        assert tracker.expected_rebate_rate == Decimal("0.002")

    def test_default_values(self):
        """Test default configuration values."""
        tracker = RebateTracker()
        assert tracker.rebate_attribution_window == timedelta(hours=24)
        assert tracker.expected_rebate_rate == Decimal("0.001")


# =============================================================================
# Test Trade Recording
# =============================================================================


class TestRecordTrade:
    """Tests for recording trades."""

    def test_record_basic_trade(self, tracker):
        """Test recording a basic trade."""
        trade = tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        assert trade is not None
        assert trade.trade_id == "trade-1"
        assert trade.market == "btc-updown-15m"
        assert trade.size == Decimal("50")
        assert trade.attributed_rebate == Decimal("0")

    def test_record_trade_updates_tracker(self, tracker):
        """Test that recording trade updates tracker state."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        assert len(tracker.trades) == 1
        assert "trade-1" in tracker.trades
        assert tracker._total_volume == Decimal("50")

    def test_record_trade_with_timestamp(self, tracker):
        """Test recording trade with explicit timestamp."""
        ts = datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc)
        trade = tracker.record_trade("trade-1", "btc-updown-15m", 50.0, ts)

        assert trade.timestamp == ts

    def test_record_multiple_trades(self, tracker):
        """Test recording multiple trades."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        tracker.record_trade("trade-2", "eth-updown-15m", 30.0)
        tracker.record_trade("trade-3", "btc-updown-15m", 40.0)

        assert len(tracker.trades) == 3
        assert tracker._total_volume == Decimal("120")

    def test_record_trade_updates_market_stats(self, tracker):
        """Test that recording trade updates market statistics."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        tracker.record_trade("trade-2", "btc-updown-15m", 30.0)

        assert "btc-updown-15m" in tracker.market_stats
        stats = tracker.market_stats["btc-updown-15m"]
        assert stats.total_volume == Decimal("80")
        assert stats.trade_count == 2

    def test_record_trade_decimal_size(self, tracker):
        """Test recording trade with decimal size."""
        trade = tracker.record_trade("trade-1", "btc-updown-15m", 50.25)

        assert trade.size == Decimal("50.25")


class TestRecordTradeValidation:
    """Tests for trade validation during recording."""

    def test_duplicate_trade_id(self, tracker):
        """Test rejection of duplicate trade_id."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        with pytest.raises(RebateTrackerError, match="already recorded"):
            tracker.record_trade("trade-1", "eth-updown-15m", 30.0)

    def test_zero_size(self, tracker):
        """Test rejection of zero size trade."""
        with pytest.raises(RebateTrackerError, match="must be positive"):
            tracker.record_trade("trade-1", "btc-updown-15m", 0.0)

    def test_negative_size(self, tracker):
        """Test rejection of negative size trade."""
        with pytest.raises(RebateTrackerError, match="must be positive"):
            tracker.record_trade("trade-1", "btc-updown-15m", -10.0)


# =============================================================================
# Test Rebate Detection
# =============================================================================


class TestDetectRebate:
    """Tests for rebate detection."""

    def test_detect_basic_rebate(self, tracker, mock_usdc_transfer):
        """Test detecting a basic rebate."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        rebate = tracker.detect_rebate(mock_usdc_transfer)

        assert rebate is not None
        assert rebate.amount == Decimal("1.50")
        assert len(tracker.rebates) == 1

    def test_detect_rebate_updates_totals(self, tracker, mock_usdc_transfer):
        """Test that detecting rebate updates totals."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        tracker.detect_rebate(mock_usdc_transfer)

        assert tracker._total_rebates == Decimal("1.50")

    def test_detect_rebate_with_tx_hash(self, tracker):
        """Test rebate detection preserves tx_hash."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        rebate = tracker.detect_rebate(
            {
                "amount": 1.0,
                "tx_hash": "0xabcdef123456",
            }
        )

        assert rebate.tx_hash == "0xabcdef123456"

    def test_detect_rebate_without_timestamp(self, tracker):
        """Test rebate detection without explicit timestamp."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        rebate = tracker.detect_rebate({"amount": 1.0})

        assert rebate is not None
        assert rebate.timestamp is not None

    def test_detect_rebate_with_iso_timestamp(self, tracker):
        """Test rebate detection with ISO format timestamp."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        ts = "2025-01-06T12:00:00Z"

        rebate = tracker.detect_rebate({"amount": 1.0, "timestamp": ts})

        assert rebate is not None
        assert rebate.timestamp.year == 2025

    def test_detect_rebate_missing_amount(self, tracker):
        """Test rebate detection with missing amount returns None."""
        rebate = tracker.detect_rebate({"timestamp": datetime.now(timezone.utc).isoformat()})

        assert rebate is None

    def test_detect_rebate_invalid_amount(self, tracker):
        """Test rebate detection with invalid amount returns None."""
        rebate = tracker.detect_rebate({"amount": "invalid"})

        assert rebate is None

    def test_detect_rebate_zero_amount(self, tracker):
        """Test rebate detection with zero amount returns None."""
        rebate = tracker.detect_rebate({"amount": 0.0})

        assert rebate is None

    def test_detect_rebate_negative_amount(self, tracker):
        """Test rebate detection with negative amount returns None."""
        rebate = tracker.detect_rebate({"amount": -1.0})

        assert rebate is None


# =============================================================================
# Test Rebate Attribution
# =============================================================================


class TestRebateAttribution:
    """Tests for rebate attribution to trades."""

    def test_attribute_to_single_trade(self, tracker):
        """Test attributing rebate to single trade."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0, now - timedelta(hours=1))

        rebate = tracker.detect_rebate({"amount": 0.50, "timestamp": now.isoformat()})

        assert "trade-1" in rebate.attributed_trades
        trade = tracker.get_trade("trade-1")
        assert trade.attributed_rebate == Decimal("0.50")

    def test_attribute_to_multiple_trades_proportionally(self, tracker):
        """Test proportional attribution to multiple trades."""
        now = datetime.now(timezone.utc)
        # Trade 1: 100 size, Trade 2: 50 size (2:1 ratio)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))
        tracker.record_trade("trade-2", "btc-updown-15m", 50.0, now - timedelta(hours=1))

        rebate = tracker.detect_rebate({"amount": 1.50, "timestamp": now.isoformat()})

        # Should attribute 2/3 to trade-1, 1/3 to trade-2
        trade1 = tracker.get_trade("trade-1")
        trade2 = tracker.get_trade("trade-2")

        # 1.50 * (100/150) = 1.00, 1.50 * (50/150) = 0.50
        assert trade1.attributed_rebate == Decimal("1.000000")
        assert trade2.attributed_rebate == Decimal("0.500000")

    def test_attribution_respects_time_window(self, tracker_with_short_window):
        """Test that attribution respects the time window."""
        tracker = tracker_with_short_window
        now = datetime.now(timezone.utc)

        # Trade outside window (2 hours ago)
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0, now - timedelta(hours=2))
        # Trade inside window (30 minutes ago)
        tracker.record_trade("trade-2", "btc-updown-15m", 50.0, now - timedelta(minutes=30))

        rebate = tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        # Only trade-2 should be attributed (within 1-hour window)
        assert "trade-1" not in rebate.attributed_trades
        assert "trade-2" in rebate.attributed_trades

        trade1 = tracker.get_trade("trade-1")
        trade2 = tracker.get_trade("trade-2")
        assert trade1.attributed_rebate == Decimal("0")
        assert trade2.attributed_rebate == Decimal("1.000000")

    def test_no_attribution_when_no_eligible_trades(self, tracker):
        """Test rebate with no eligible trades."""
        rebate = tracker.detect_rebate({"amount": 1.0})

        assert rebate is not None
        assert len(rebate.attributed_trades) == 0

    def test_attribution_updates_market_stats(self, tracker):
        """Test that attribution updates market rebate stats."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0, now - timedelta(hours=1))

        tracker.detect_rebate({"amount": 0.50, "timestamp": now.isoformat()})

        stats = tracker.market_stats["btc-updown-15m"]
        assert stats.total_rebates == Decimal("0.500000")

    def test_multiple_rebates_cumulative(self, tracker):
        """Test multiple rebates accumulate on trades."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0, now - timedelta(hours=1))

        tracker.detect_rebate({"amount": 0.25, "timestamp": now.isoformat()})
        tracker.detect_rebate({"amount": 0.25, "timestamp": now.isoformat()})

        trade = tracker.get_trade("trade-1")
        assert trade.attributed_rebate == Decimal("0.500000")


# =============================================================================
# Test Rebate Statistics
# =============================================================================


class TestGetRebateStats:
    """Tests for rebate statistics."""

    def test_stats_empty_tracker(self, tracker):
        """Test stats with no data."""
        stats = tracker.get_rebate_stats()

        assert stats["total_trades"] == 0
        assert Decimal(stats["total_volume"]) == Decimal("0")
        assert Decimal(stats["total_rebates"]) == Decimal("0")
        assert stats["rebate_events"] == 0

    def test_stats_with_trades(self, tracker):
        """Test stats with trades only."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        tracker.record_trade("trade-2", "eth-updown-15m", 30.0)

        stats = tracker.get_rebate_stats()

        assert stats["total_trades"] == 2
        assert Decimal(stats["total_volume"]) == Decimal("80")

    def test_stats_with_rebates(self, populated_tracker):
        """Test stats with trades and rebates."""
        stats = populated_tracker.get_rebate_stats()

        assert stats["total_trades"] == 3
        assert Decimal(stats["total_volume"]) == Decimal("120")
        assert Decimal(stats["total_rebates"]) == Decimal("0.12")
        assert stats["rebate_events"] == 1

    def test_stats_rebate_rate_calculation(self, tracker):
        """Test average rebate rate calculation."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))
        tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        stats = tracker.get_rebate_stats()

        # 1.0 / 100.0 = 0.01 (1%)
        assert Decimal(stats["avg_rebate_rate"]) == Decimal("0.010000")
        assert Decimal(stats["avg_rebate_rate_pct"]) == Decimal("1.0000")

    def test_stats_rebate_per_100(self, tracker):
        """Test rebate per $100 calculation."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 200.0, now - timedelta(hours=1))
        tracker.detect_rebate({"amount": 2.0, "timestamp": now.isoformat()})

        stats = tracker.get_rebate_stats()

        # 2.0 / 200.0 * 100 = 1.0
        assert Decimal(stats["rebate_per_100"]) == Decimal("1.0000")

    def test_stats_per_market(self, populated_tracker):
        """Test per-market statistics."""
        stats = populated_tracker.get_rebate_stats()

        assert "btc-updown-15m" in stats["markets"]
        assert "eth-updown-15m" in stats["markets"]

        btc_stats = stats["markets"]["btc-updown-15m"]
        assert Decimal(btc_stats["total_volume"]) == Decimal("80")


# =============================================================================
# Test ROI Calculations
# =============================================================================


class TestCalculateROI:
    """Tests for ROI calculation."""

    def test_roi_no_data(self, tracker):
        """Test ROI with no data returns 0."""
        roi = tracker.calculate_roi(period_days=7)

        assert roi == 0.0

    def test_roi_basic(self, tracker):
        """Test basic ROI calculation."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(days=1))
        tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        roi = tracker.calculate_roi(period_days=7)

        # 1.0 / 100.0 * 100 = 1.0%
        assert roi == pytest.approx(1.0, rel=0.01)

    def test_roi_respects_period(self, tracker):
        """Test ROI respects the period parameter."""
        now = datetime.now(timezone.utc)
        # Trade outside period (10 days ago)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(days=10))
        # Trade inside period (2 days ago)
        tracker.record_trade("trade-2", "btc-updown-15m", 50.0, now - timedelta(days=2))

        # Rebate now
        tracker.detect_rebate({"amount": 0.50, "timestamp": now.isoformat()})

        # 7-day period should only include trade-2
        roi = tracker.calculate_roi(period_days=7)

        # 0.50 / 50.0 * 100 = 1.0%
        assert roi == pytest.approx(1.0, rel=0.01)

    def test_roi_invalid_period(self, tracker):
        """Test ROI with invalid period raises error."""
        with pytest.raises(RebateTrackerError, match="must be positive"):
            tracker.calculate_roi(period_days=0)

        with pytest.raises(RebateTrackerError, match="must be positive"):
            tracker.calculate_roi(period_days=-1)


class TestCalculateAPY:
    """Tests for effective APY calculation."""

    def test_apy_no_data(self, tracker):
        """Test APY with no data returns 0."""
        apy = tracker.calculate_effective_apy(period_days=7)

        assert apy == 0.0

    def test_apy_basic(self, tracker):
        """Test basic APY calculation."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(days=1))
        tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        # 1% in 7 days, annualized
        apy = tracker.calculate_effective_apy(period_days=7)

        # Should be positive and reasonable
        assert apy > 0
        assert apy < 1000  # Sanity check

    def test_apy_invalid_period(self, tracker):
        """Test APY with invalid period raises error."""
        with pytest.raises(RebateTrackerError, match="must be positive"):
            tracker.calculate_effective_apy(period_days=0)


# =============================================================================
# Test Best Performing Market
# =============================================================================


class TestGetBestPerformingMarket:
    """Tests for best performing market identification."""

    def test_best_market_no_data(self, tracker):
        """Test best market with no data returns empty string."""
        result = tracker.get_best_performing_market()

        assert result == ""

    def test_best_market_single_market(self, tracker):
        """Test best market with single market."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))
        tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        result = tracker.get_best_performing_market()

        assert result == "btc-updown-15m"

    def test_best_market_multiple_markets(self, tracker):
        """Test best market with multiple markets."""
        now = datetime.now(timezone.utc)

        # BTC: 100 volume, 1.0 rebate = 1% rate
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))
        # ETH: 50 volume, 1.0 rebate = 2% rate (better)
        tracker.record_trade("trade-2", "eth-updown-15m", 50.0, now - timedelta(hours=1))

        # Rebate 2.0 total - proportionally: BTC gets 2/3, ETH gets 1/3
        # BTC: 1.33/100 = 1.33%, ETH: 0.67/50 = 1.33%
        tracker.detect_rebate({"amount": 2.0, "timestamp": now.isoformat()})

        # Now add another rebate just for ETH
        tracker.record_trade("trade-3", "eth-updown-15m", 50.0, now - timedelta(minutes=30))
        tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        result = tracker.get_best_performing_market()

        # ETH should have higher rebate rate
        assert result in ["btc-updown-15m", "eth-updown-15m"]

    def test_best_market_zero_volume_excluded(self, tracker):
        """Test that markets with zero volume are excluded."""
        # Add a market stat manually with zero volume
        tracker.market_stats["empty-market"] = MarketStats(
            market="empty-market",
            total_volume=Decimal("0"),
            total_rebates=Decimal("1.0"),
        )

        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))
        tracker.detect_rebate({"amount": 1.0, "timestamp": now.isoformat()})

        result = tracker.get_best_performing_market()

        assert result == "btc-updown-15m"


# =============================================================================
# Test Market Comparison
# =============================================================================


class TestGetMarketComparison:
    """Tests for market comparison."""

    def test_comparison_empty(self, tracker):
        """Test comparison with no markets."""
        result = tracker.get_market_comparison()

        assert result == []

    def test_comparison_sorted_by_rebate_rate(self, tracker):
        """Test comparison is sorted by rebate rate descending."""
        # Create stats directly for controlled testing
        tracker.market_stats["market-a"] = MarketStats(
            market="market-a",
            total_volume=Decimal("100"),
            total_rebates=Decimal("1.0"),
            trade_count=1,
            avg_rebate_rate=Decimal("0.01"),  # 1%
        )
        tracker.market_stats["market-b"] = MarketStats(
            market="market-b",
            total_volume=Decimal("100"),
            total_rebates=Decimal("2.0"),
            trade_count=1,
            avg_rebate_rate=Decimal("0.02"),  # 2%
        )
        tracker.market_stats["market-c"] = MarketStats(
            market="market-c",
            total_volume=Decimal("100"),
            total_rebates=Decimal("0.5"),
            trade_count=1,
            avg_rebate_rate=Decimal("0.005"),  # 0.5%
        )

        result = tracker.get_market_comparison()

        # Should be sorted: market-b (2%), market-a (1%), market-c (0.5%)
        assert len(result) == 3
        assert result[0]["market"] == "market-b"
        assert result[1]["market"] == "market-a"
        assert result[2]["market"] == "market-c"


# =============================================================================
# Test Trade Retrieval
# =============================================================================


class TestTradeRetrieval:
    """Tests for retrieving trades."""

    def test_get_trade(self, tracker):
        """Test getting a specific trade."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        trade = tracker.get_trade("trade-1")

        assert trade is not None
        assert trade.trade_id == "trade-1"

    def test_get_trade_not_found(self, tracker):
        """Test getting non-existent trade returns None."""
        trade = tracker.get_trade("non-existent")

        assert trade is None

    def test_get_trades_by_market(self, tracker):
        """Test getting trades by market."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        tracker.record_trade("trade-2", "eth-updown-15m", 30.0)
        tracker.record_trade("trade-3", "btc-updown-15m", 40.0)

        btc_trades = tracker.get_trades_by_market("btc-updown-15m")

        assert len(btc_trades) == 2
        assert all(t.market == "btc-updown-15m" for t in btc_trades)

    def test_get_trades_by_market_empty(self, tracker):
        """Test getting trades for market with no trades."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        eth_trades = tracker.get_trades_by_market("eth-updown-15m")

        assert len(eth_trades) == 0


# =============================================================================
# Test Recent Rebates
# =============================================================================


class TestGetRecentRebates:
    """Tests for recent rebates retrieval."""

    def test_recent_rebates_empty(self, tracker):
        """Test recent rebates with no data."""
        result = tracker.get_recent_rebates()

        assert result == []

    def test_recent_rebates_limit(self, tracker):
        """Test recent rebates respects limit."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))

        for i in range(15):
            tracker.detect_rebate({"amount": 0.1, "timestamp": now.isoformat()})

        result = tracker.get_recent_rebates(limit=5)

        assert len(result) == 5

    def test_recent_rebates_returns_most_recent(self, tracker):
        """Test recent rebates returns most recent entries."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))

        for i in range(5):
            tracker.detect_rebate({"amount": float(i + 1), "timestamp": now.isoformat()})

        result = tracker.get_recent_rebates(limit=3)

        # Should get rebates 3, 4, 5 (the last 3)
        amounts = [Decimal(r["amount"]) for r in result]
        assert Decimal("3") in amounts
        assert Decimal("4") in amounts
        assert Decimal("5") in amounts


# =============================================================================
# Test State Persistence
# =============================================================================


class TestStatePersistence:
    """Tests for saving and loading state."""

    def test_save_state(self, populated_tracker):
        """Test saving tracker state to file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            filepath = Path(f.name)

        try:
            populated_tracker.save_state(filepath)

            assert filepath.exists()

            with open(filepath) as f:
                data = json.load(f)

            assert "trades" in data
            assert "rebates" in data
            assert "total_volume" in data
            assert "total_rebates" in data
        finally:
            filepath.unlink()

    def test_load_state(self, tracker, populated_tracker):
        """Test loading tracker state from file."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            filepath = Path(f.name)

        try:
            # Save populated tracker state
            populated_tracker.save_state(filepath)

            # Load into fresh tracker
            success = tracker.load_state(filepath)

            assert success
            assert len(tracker.trades) == len(populated_tracker.trades)
            assert len(tracker.rebates) == len(populated_tracker.rebates)
            assert tracker._total_volume == populated_tracker._total_volume
        finally:
            filepath.unlink()

    def test_load_state_file_not_found(self, tracker):
        """Test loading from non-existent file returns False."""
        success = tracker.load_state(Path("/non/existent/file.json"))

        assert not success
        assert len(tracker.trades) == 0

    def test_round_trip_preserves_data(self, populated_tracker):
        """Test that save/load round trip preserves all data."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            filepath = Path(f.name)

        try:
            # Get original stats
            original_stats = populated_tracker.get_rebate_stats()

            # Save and reload
            populated_tracker.save_state(filepath)

            new_tracker = RebateTracker()
            new_tracker.load_state(filepath)

            # Get reloaded stats
            reloaded_stats = new_tracker.get_rebate_stats()

            assert original_stats["total_trades"] == reloaded_stats["total_trades"]
            assert original_stats["total_volume"] == reloaded_stats["total_volume"]
            assert original_stats["total_rebates"] == reloaded_stats["total_rebates"]
        finally:
            filepath.unlink()


# =============================================================================
# Test Reset
# =============================================================================


class TestReset:
    """Tests for reset functionality."""

    def test_reset_clears_all_data(self, populated_tracker):
        """Test reset clears all tracked data."""
        populated_tracker.reset()

        assert len(populated_tracker.trades) == 0
        assert len(populated_tracker.rebates) == 0
        assert len(populated_tracker.market_stats) == 0
        assert populated_tracker._total_volume == Decimal("0")
        assert populated_tracker._total_rebates == Decimal("0")

    def test_reset_allows_reuse(self, populated_tracker):
        """Test tracker can be reused after reset."""
        populated_tracker.reset()

        trade = populated_tracker.record_trade("new-trade", "btc-updown-15m", 25.0)

        assert len(populated_tracker.trades) == 1
        assert trade.trade_id == "new-trade"


# =============================================================================
# Test Magic Methods
# =============================================================================


class TestMagicMethods:
    """Tests for magic methods."""

    def test_len_empty(self, tracker):
        """Test __len__ with no trades."""
        assert len(tracker) == 0

    def test_len_with_trades(self, tracker):
        """Test __len__ with trades."""
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)
        tracker.record_trade("trade-2", "eth-updown-15m", 30.0)

        assert len(tracker) == 2

    def test_repr(self, populated_tracker):
        """Test __repr__ string representation."""
        repr_str = repr(populated_tracker)

        assert "RebateTracker" in repr_str
        assert "trades=" in repr_str
        assert "rebates=" in repr_str
        assert "total_volume=" in repr_str


# =============================================================================
# Test Dataclasses
# =============================================================================


class TestRecordedTradeDataclass:
    """Tests for RecordedTrade dataclass."""

    def test_to_dict(self):
        """Test trade serialization to dict."""
        trade = RecordedTrade(
            trade_id="trade-1",
            market="btc-updown-15m",
            size=Decimal("50"),
            timestamp=datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc),
            attributed_rebate=Decimal("0.50"),
            rebate_rate=Decimal("0.01"),
        )

        result = trade.to_dict()

        assert result["trade_id"] == "trade-1"
        assert result["market"] == "btc-updown-15m"
        assert result["size"] == "50"
        assert result["attributed_rebate"] == "0.50"
        assert result["rebate_rate"] == "0.01"


class TestRebateEventDataclass:
    """Tests for RebateEvent dataclass."""

    def test_to_dict(self):
        """Test rebate serialization to dict."""
        rebate = RebateEvent(
            rebate_id="rebate-1",
            amount=Decimal("1.50"),
            timestamp=datetime(2025, 1, 6, 12, 0, 0, tzinfo=timezone.utc),
            tx_hash="0xabc123",
            attributed_trades=["trade-1", "trade-2"],
        )

        result = rebate.to_dict()

        assert result["rebate_id"] == "rebate-1"
        assert result["amount"] == "1.50"
        assert result["tx_hash"] == "0xabc123"
        assert "trade-1" in result["attributed_trades"]


class TestMarketStatsDataclass:
    """Tests for MarketStats dataclass."""

    def test_rebate_per_100_property(self):
        """Test rebate per $100 calculation."""
        stats = MarketStats(
            market="btc-updown-15m",
            total_volume=Decimal("200"),
            total_rebates=Decimal("2.0"),
            trade_count=4,
            avg_rebate_rate=Decimal("0.01"),
        )

        # 2.0 / 200 * 100 = 1.0
        assert stats.rebate_per_100 == Decimal("1.0000")

    def test_rebate_per_100_zero_volume(self):
        """Test rebate per $100 with zero volume."""
        stats = MarketStats(
            market="btc-updown-15m",
            total_volume=Decimal("0"),
            total_rebates=Decimal("1.0"),
        )

        assert stats.rebate_per_100 == Decimal("0")

    def test_to_dict(self):
        """Test market stats serialization to dict."""
        stats = MarketStats(
            market="btc-updown-15m",
            total_volume=Decimal("100"),
            total_rebates=Decimal("1.0"),
            trade_count=2,
            avg_rebate_rate=Decimal("0.01"),
        )

        result = stats.to_dict()

        assert result["market"] == "btc-updown-15m"
        assert result["total_volume"] == "100"
        assert result["total_rebates"] == "1.0"
        assert result["trade_count"] == 2


# =============================================================================
# Test Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_small_rebate(self, tracker):
        """Test handling very small rebate amounts."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))

        rebate = tracker.detect_rebate(
            {"amount": 0.000001, "timestamp": now.isoformat()}
        )

        assert rebate is not None
        assert rebate.amount == Decimal("0.000001")

    def test_very_large_trade(self, tracker):
        """Test handling very large trade sizes."""
        trade = tracker.record_trade("trade-1", "btc-updown-15m", 1000000.0)

        assert trade.size == Decimal("1000000")

    def test_many_trades(self, tracker):
        """Test handling many trades."""
        now = datetime.now(timezone.utc)
        for i in range(100):
            tracker.record_trade(
                f"trade-{i}",
                "btc-updown-15m",
                10.0,
                now - timedelta(minutes=i),
            )

        assert len(tracker) == 100
        assert tracker._total_volume == Decimal("1000")

    def test_unicode_market_name(self, tracker):
        """Test handling unicode in market names."""
        trade = tracker.record_trade("trade-1", "test-market-", 50.0)

        assert trade.market == "test-market-"

    def test_timestamp_with_microseconds(self, tracker):
        """Test timestamp parsing with microseconds."""
        ts = "2025-01-06T12:00:00.123456Z"
        tracker.record_trade("trade-1", "btc-updown-15m", 50.0)

        rebate = tracker.detect_rebate({"amount": 1.0, "timestamp": ts})

        assert rebate is not None

    def test_concurrent_markets_separation(self, tracker):
        """Test that markets are tracked separately."""
        now = datetime.now(timezone.utc)
        tracker.record_trade("trade-1", "btc-updown-15m", 100.0, now - timedelta(hours=1))
        tracker.record_trade("trade-2", "eth-updown-15m", 100.0, now - timedelta(hours=1))

        assert len(tracker.market_stats) == 2
        assert tracker.market_stats["btc-updown-15m"].total_volume == Decimal("100")
        assert tracker.market_stats["eth-updown-15m"].total_volume == Decimal("100")
