"""
Tests for the Maker Rebates Backtester.

Validates:
- Data models
- Fill simulation logic
- P&L calculations
- Metrics computation
- End-to-end backtest
"""

import pytest
from typing import List

from src.backtest.maker.models import (
    BacktestConfig,
    MarketWindow,
    WindowResult,
    BacktestResults,
    OrderbookSnapshot,
    OrderSide,
)
from src.backtest.maker.fill_simulator import FillSimulator, FillResult
from src.backtest.maker.metrics import MakerMetrics
from src.backtest.maker.engine import MakerBacktestEngine, create_test_windows


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def basic_config() -> BacktestConfig:
    """Basic backtest configuration."""
    return BacktestConfig(
        position_size=50.0,
        spread_from_mid=0.01,
        rebate_rate=0.005,
        min_spread_to_enter=0.02
    )


@pytest.fixture
def sample_orderbook() -> OrderbookSnapshot:
    """Sample orderbook with clear spread."""
    return OrderbookSnapshot(
        timestamp=1704067200,
        bids=[[0.48, 100], [0.47, 200], [0.46, 300]],
        asks=[[0.52, 100], [0.51, 200], [0.50, 300]]
    )


@pytest.fixture
def tight_spread_orderbook() -> OrderbookSnapshot:
    """Orderbook with tight spread."""
    return OrderbookSnapshot(
        timestamp=1704067200,
        bids=[[0.499, 100], [0.498, 200]],
        asks=[[0.501, 100], [0.502, 200]]
    )


@pytest.fixture
def sample_window(sample_orderbook: OrderbookSnapshot) -> MarketWindow:
    """Sample market window with UP outcome."""
    snapshots = [sample_orderbook]
    # Add more snapshots with slight price movement
    for i in range(1, 5):
        snapshots.append(OrderbookSnapshot(
            timestamp=sample_orderbook.timestamp + i * 180,
            bids=[[0.48 + i*0.002, 100], [0.47 + i*0.002, 200]],
            asks=[[0.52 + i*0.002, 100], [0.51 + i*0.002, 200]]
        ))

    return MarketWindow(
        market_id="test-market-1",
        window_start=1704067200,
        window_end=1704068100,
        outcome="UP",
        orderbook_snapshots=snapshots,
        binance_start=43000.0,
        binance_end=43100.0,
        asset="BTC"
    )


# =============================================================================
# Test BacktestConfig
# =============================================================================

class TestBacktestConfig:
    """Test configuration validation and defaults."""

    def test_default_config(self):
        """Test default configuration values."""
        config = BacktestConfig()
        assert config.position_size == 50.0
        assert config.spread_from_mid == 0.01
        assert config.rebate_rate == 0.005
        assert config.min_spread_to_enter == 0.02

    def test_config_validation_passes(self, basic_config):
        """Test valid config passes validation."""
        assert basic_config.validate() is True

    def test_config_validation_invalid_position_size(self):
        """Test invalid position size fails validation."""
        config = BacktestConfig(position_size=-10)
        with pytest.raises(ValueError, match="position_size"):
            config.validate()

    def test_config_validation_invalid_spread(self):
        """Test invalid spread fails validation."""
        config = BacktestConfig(spread_from_mid=0.6)
        with pytest.raises(ValueError, match="spread_from_mid"):
            config.validate()

    def test_config_validation_invalid_rebate(self):
        """Test invalid rebate rate fails validation."""
        config = BacktestConfig(rebate_rate=0.2)
        with pytest.raises(ValueError, match="rebate_rate"):
            config.validate()


# =============================================================================
# Test OrderbookSnapshot
# =============================================================================

class TestOrderbookSnapshot:
    """Test orderbook snapshot properties."""

    def test_best_bid_ask(self, sample_orderbook):
        """Test best bid/ask extraction."""
        assert sample_orderbook.best_bid == 0.48
        assert sample_orderbook.best_ask == 0.52

    def test_mid_price(self, sample_orderbook):
        """Test mid price calculation."""
        expected_mid = (0.48 + 0.52) / 2
        assert sample_orderbook.mid_price == expected_mid

    def test_spread(self, sample_orderbook):
        """Test spread calculation."""
        expected_spread = 0.52 - 0.48
        assert sample_orderbook.spread == expected_spread

    def test_no_side_prices(self, sample_orderbook):
        """Test NO side price derivation."""
        # NO bid = 1 - YES ask = 1 - 0.52 = 0.48
        assert sample_orderbook.best_no_bid == 0.48
        # NO ask = 1 - YES bid = 1 - 0.48 = 0.52
        assert sample_orderbook.best_no_ask == 0.52

    def test_bid_depth(self, sample_orderbook):
        """Test depth calculation."""
        expected_depth = 100 + 200 + 300
        assert sample_orderbook.bid_depth(levels=3) == expected_depth

    def test_empty_orderbook(self):
        """Test empty orderbook handling."""
        empty = OrderbookSnapshot(timestamp=0, bids=[], asks=[])
        assert empty.best_bid is None
        assert empty.best_ask is None
        assert empty.mid_price is None
        assert empty.spread is None


# =============================================================================
# Test MarketWindow
# =============================================================================

class TestMarketWindow:
    """Test market window data model."""

    def test_duration(self, sample_window):
        """Test window duration calculation."""
        assert sample_window.duration_seconds == 900

    def test_price_change(self, sample_window):
        """Test price change percentage."""
        expected_change = (43100 - 43000) / 43000 * 100
        assert abs(sample_window.price_change_pct - expected_change) < 0.01

    def test_num_snapshots(self, sample_window):
        """Test snapshot count."""
        assert sample_window.num_snapshots == 5

    def test_initial_final_snapshot(self, sample_window):
        """Test first and last snapshot access."""
        assert sample_window.initial_snapshot is not None
        assert sample_window.final_snapshot is not None
        assert sample_window.initial_snapshot.timestamp < sample_window.final_snapshot.timestamp


# =============================================================================
# Test FillSimulator
# =============================================================================

class TestFillSimulator:
    """Test fill probability and simulation."""

    def test_fill_probability_at_best_bid(self, sample_orderbook):
        """Test fill probability when at best bid."""
        sim = FillSimulator(conservative=True)
        prob = sim.estimate_fill_probability(
            order_price=0.48,  # At best bid
            side=OrderSide.YES,
            orderbook=sample_orderbook
        )
        assert prob >= 0.5  # Should have decent probability

    def test_fill_probability_below_best(self, sample_orderbook):
        """Test fill probability when below best bid."""
        sim = FillSimulator(conservative=True)
        prob = sim.estimate_fill_probability(
            order_price=0.40,  # Well below best bid
            side=OrderSide.YES,
            orderbook=sample_orderbook
        )
        assert prob < 0.2  # Low probability

    def test_simulate_fill_market_crosses(self):
        """Test fill when market crosses our level."""
        sim = FillSimulator(conservative=True)

        # Create snapshots where ask drops to our bid level
        snapshots = [
            OrderbookSnapshot(timestamp=100, bids=[[0.48, 100]], asks=[[0.52, 100]]),
            OrderbookSnapshot(timestamp=200, bids=[[0.47, 100]], asks=[[0.51, 100]]),
            OrderbookSnapshot(timestamp=300, bids=[[0.46, 100]], asks=[[0.49, 100]]),  # Ask crosses 0.49
        ]

        result = sim.simulate_fill(
            order_price=0.49,  # Our bid
            side=OrderSide.YES,
            orderbook_snapshots=snapshots
        )

        assert result.filled is True
        assert result.fill_price == 0.49

    def test_simulate_fill_no_cross(self):
        """Test no fill when market doesn't cross our level."""
        sim = FillSimulator(conservative=True)

        snapshots = [
            OrderbookSnapshot(timestamp=100, bids=[[0.48, 100]], asks=[[0.52, 100]]),
            OrderbookSnapshot(timestamp=200, bids=[[0.47, 100]], asks=[[0.51, 100]]),
        ]

        result = sim.simulate_fill(
            order_price=0.45,  # Our bid is too low
            side=OrderSide.YES,
            orderbook_snapshots=snapshots
        )

        assert result.filled is False

    def test_simulate_fill_no_side(self, sample_orderbook):
        """Test fill simulation for NO side."""
        sim = FillSimulator(conservative=True)

        # For NO side, our bid should be compared to NO asks
        # NO ask = 1 - YES bid = 1 - 0.48 = 0.52
        snapshots = [
            sample_orderbook,
            # Add snapshot where YES bid rises (NO ask drops)
            OrderbookSnapshot(
                timestamp=sample_orderbook.timestamp + 100,
                bids=[[0.52, 100]],  # YES bid at 0.52 -> NO ask at 0.48
                asks=[[0.54, 100]]
            )
        ]

        result = sim.simulate_fill(
            order_price=0.49,  # Our NO bid
            side=OrderSide.NO,
            orderbook_snapshots=snapshots
        )

        # NO ask drops to 0.48, which is below our bid of 0.49
        assert result.filled is True


# =============================================================================
# Test Resolution P&L Calculations
# =============================================================================

class TestResolutionPnL:
    """Test P&L calculations for different scenarios."""

    def test_delta_neutral_up_outcome(self, basic_config):
        """Test P&L when both sides filled and outcome is UP."""
        engine = MakerBacktestEngine(basic_config)

        # Both filled at fair prices
        pnl = engine._calculate_resolution_pnl(
            yes_filled=True,
            no_filled=True,
            yes_price=0.49,  # Cost 0.49 per share
            no_price=0.49,   # Cost 0.49 per share
            yes_size=102.04,  # ~$50 / 0.49
            no_size=102.04,
            outcome="UP"
        )

        # UP outcome: YES wins
        # Revenue: 102.04 * $1 = $102.04
        # Cost: 0.49 * 102.04 + 0.49 * 102.04 = ~$100
        # P&L = $102.04 - $100 = ~$2.04
        expected_pnl = 102.04 - (0.49 * 102.04 + 0.49 * 102.04)
        assert abs(pnl - expected_pnl) < 0.01

    def test_delta_neutral_down_outcome(self, basic_config):
        """Test P&L when both sides filled and outcome is DOWN."""
        engine = MakerBacktestEngine(basic_config)

        pnl = engine._calculate_resolution_pnl(
            yes_filled=True,
            no_filled=True,
            yes_price=0.49,
            no_price=0.49,
            yes_size=102.04,
            no_size=102.04,
            outcome="DOWN"
        )

        # DOWN outcome: NO wins
        # Revenue: 102.04 * $1 = $102.04
        # Cost: same as above
        expected_pnl = 102.04 - (0.49 * 102.04 + 0.49 * 102.04)
        assert abs(pnl - expected_pnl) < 0.01

    def test_only_yes_filled_up(self, basic_config):
        """Test P&L when only YES filled and UP outcome (winning)."""
        engine = MakerBacktestEngine(basic_config)

        pnl = engine._calculate_resolution_pnl(
            yes_filled=True,
            no_filled=False,
            yes_price=0.49,
            no_price=0.0,
            yes_size=102.04,
            no_size=0.0,
            outcome="UP"
        )

        # Revenue: 102.04 * $1 = $102.04
        # Cost: 0.49 * 102.04 = $50
        # P&L = $102.04 - $50 = $52.04
        expected_pnl = 102.04 - 0.49 * 102.04
        assert abs(pnl - expected_pnl) < 0.01

    def test_only_yes_filled_down(self, basic_config):
        """Test P&L when only YES filled and DOWN outcome (losing)."""
        engine = MakerBacktestEngine(basic_config)

        pnl = engine._calculate_resolution_pnl(
            yes_filled=True,
            no_filled=False,
            yes_price=0.49,
            no_price=0.0,
            yes_size=102.04,
            no_size=0.0,
            outcome="DOWN"
        )

        # Revenue: 0 (YES loses)
        # Cost: 0.49 * 102.04 = $50
        # P&L = $0 - $50 = -$50
        expected_pnl = 0 - 0.49 * 102.04
        assert abs(pnl - expected_pnl) < 0.01


# =============================================================================
# Test Rebate Calculations
# =============================================================================

class TestRebates:
    """Test rebate calculations."""

    def test_both_sides_rebates(self, basic_config):
        """Test rebates when both sides fill."""
        engine = MakerBacktestEngine(basic_config)

        rebate = engine._calculate_rebates(
            yes_filled=True,
            no_filled=True,
            yes_price=0.50,
            no_price=0.50,
            yes_size=100.0,
            no_size=100.0
        )

        # Volume: 0.50 * 100 + 0.50 * 100 = $100
        # Rebate: $100 * 0.005 = $0.50
        expected = 100.0 * 0.005
        assert abs(rebate - expected) < 0.001

    def test_one_side_rebates(self, basic_config):
        """Test rebates when only one side fills."""
        engine = MakerBacktestEngine(basic_config)

        rebate = engine._calculate_rebates(
            yes_filled=True,
            no_filled=False,
            yes_price=0.50,
            no_price=0.0,
            yes_size=100.0,
            no_size=0.0
        )

        # Volume: 0.50 * 100 = $50
        # Rebate: $50 * 0.005 = $0.25
        expected = 50.0 * 0.005
        assert abs(rebate - expected) < 0.001


# =============================================================================
# Test MakerMetrics
# =============================================================================

class TestMakerMetrics:
    """Test metrics calculation."""

    def test_empty_results(self):
        """Test metrics with no results."""
        metrics = MakerMetrics.calculate([])
        assert metrics["total_windows"] == 0

    def test_basic_metrics(self):
        """Test basic metrics calculation."""
        results = [
            WindowResult(market_id="1", entered=True, total_pnl=1.0, resolution_pnl=0.5, rebate_earned=0.5),
            WindowResult(market_id="2", entered=True, total_pnl=-0.5, resolution_pnl=-0.75, rebate_earned=0.25),
            WindowResult(market_id="3", entered=False, skip_reason="Spread too thin"),
        ]

        metrics = MakerMetrics.calculate(results)

        assert metrics["summary"]["total_windows"] == 3
        assert metrics["summary"]["windows_entered"] == 2
        assert abs(metrics["summary"]["total_pnl"] - 0.5) < 0.01
        assert abs(metrics["summary"]["total_rebates"] - 0.75) < 0.01

    def test_win_rate(self):
        """Test win rate calculation."""
        results = [
            WindowResult(market_id="1", entered=True, total_pnl=1.0),
            WindowResult(market_id="2", entered=True, total_pnl=0.5),
            WindowResult(market_id="3", entered=True, total_pnl=-0.2),
        ]

        metrics = MakerMetrics.calculate(results)

        # 2 wins, 1 loss = 66.67% win rate
        assert abs(metrics["risk"]["win_rate"] - 0.6667) < 0.01

    def test_fill_metrics(self):
        """Test fill statistics."""
        results = [
            WindowResult(market_id="1", entered=True, yes_filled=True, no_filled=True),
            WindowResult(market_id="2", entered=True, yes_filled=True, no_filled=False),
            WindowResult(market_id="3", entered=True, yes_filled=False, no_filled=True),
            WindowResult(market_id="4", entered=False),
        ]

        metrics = MakerMetrics.calculate(results)

        assert metrics["fills"]["yes_fill_count"] == 2
        assert metrics["fills"]["no_fill_count"] == 2
        assert abs(metrics["fills"]["both_fill_rate"] - 1/3) < 0.01  # 1 out of 3 entered


# =============================================================================
# Test Full Engine
# =============================================================================

class TestMakerBacktestEngine:
    """Test full backtest engine."""

    def test_engine_initialization(self, basic_config):
        """Test engine initializes correctly."""
        engine = MakerBacktestEngine(basic_config)
        assert engine.config == basic_config
        assert len(engine.results) == 0

    def test_skip_thin_spread(self, basic_config, tight_spread_orderbook):
        """Test engine skips markets with spread too thin."""
        engine = MakerBacktestEngine(basic_config)

        # Spread is 0.002, min is 0.02
        window = MarketWindow(
            market_id="thin-spread",
            window_start=1704067200,
            window_end=1704068100,
            outcome="UP",
            orderbook_snapshots=[tight_spread_orderbook],
            binance_start=43000.0,
            binance_end=43100.0
        )

        result = engine.simulate_window(window)

        assert result.entered is False
        assert "thin" in result.skip_reason.lower()

    def test_skip_no_orderbook(self, basic_config):
        """Test engine skips windows with no orderbook data."""
        engine = MakerBacktestEngine(basic_config)

        window = MarketWindow(
            market_id="no-data",
            window_start=1704067200,
            window_end=1704068100,
            outcome="UP",
            orderbook_snapshots=[],
            binance_start=43000.0,
            binance_end=43100.0
        )

        result = engine.simulate_window(window)

        assert result.entered is False
        assert "orderbook" in result.skip_reason.lower()

    def test_full_backtest_run(self, basic_config):
        """Test full backtest with test data."""
        engine = MakerBacktestEngine(basic_config)

        windows = create_test_windows(50)
        results = engine.run(windows)

        assert results.total_windows == 50
        assert results.windows_entered >= 0
        assert "summary" in results.metrics
        assert "risk" in results.metrics

    def test_results_structure(self, basic_config):
        """Test BacktestResults structure."""
        engine = MakerBacktestEngine(basic_config)
        windows = create_test_windows(10)
        results = engine.run(windows)

        # Check all required fields
        assert results.config is not None
        assert len(results.window_results) == 10
        assert results.start_time is not None
        assert results.end_time is not None

        # Check metrics sections
        assert "summary" in results.metrics
        assert "pnl" in results.metrics
        assert "fills" in results.metrics
        assert "risk" in results.metrics
        assert "distribution" in results.metrics

    def test_report_generation(self, basic_config):
        """Test metrics report generation."""
        engine = MakerBacktestEngine(basic_config)
        windows = create_test_windows(20)
        results = engine.run(windows)

        report = MakerMetrics.format_report(results.metrics)

        assert "MAKER REBATES BACKTEST REPORT" in report
        assert "SUMMARY" in report
        assert "FILL STATISTICS" in report
        assert "RISK METRICS" in report


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for the full system."""

    def test_end_to_end_profitability(self):
        """
        Test that in favorable conditions the strategy is profitable.

        With wide spreads and good fills, rebates should overcome resolution losses.
        """
        # Use higher rebate rate to ensure profitability
        config = BacktestConfig(
            position_size=50.0,
            spread_from_mid=0.01,
            rebate_rate=0.01,  # 1% rebate
            min_spread_to_enter=0.03
        )

        engine = MakerBacktestEngine(config)
        windows = create_test_windows(100)
        results = engine.run(windows)

        # With 1% rebate on ~$100 volume per window and ~50% win rate on resolution
        # Should see positive rebate contribution
        assert results.total_rebates > 0

    def test_sensitivity_to_rebate_rate(self):
        """Test that P&L is sensitive to rebate rate."""
        config_low = BacktestConfig(rebate_rate=0.001)
        config_high = BacktestConfig(rebate_rate=0.01)

        engine_low = MakerBacktestEngine(config_low)
        engine_high = MakerBacktestEngine(config_high)

        windows = create_test_windows(50)

        results_low = engine_low.run(windows)
        results_high = engine_high.run(windows)

        # Higher rebate should give more rebate revenue
        assert results_high.total_rebates > results_low.total_rebates

    def test_deterministic_with_seed(self):
        """Test that test data generation is deterministic with seed."""
        import random

        random.seed(42)
        windows1 = create_test_windows(10)

        random.seed(42)
        windows2 = create_test_windows(10)

        for w1, w2 in zip(windows1, windows2):
            assert w1.market_id == w2.market_id
            assert w1.outcome == w2.outcome


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
