"""
Maker Rebates Backtest Engine.

Main backtesting engine for delta-neutral maker strategy on 15-minute markets.
Simulates placing maker orders on both YES and NO sides, earning rebates,
and tracking resolution P&L.
"""

import logging
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
import time

from .models import (
    BacktestConfig,
    MarketWindow,
    WindowResult,
    BacktestResults,
    OrderbookSnapshot,
    OrderSide,
)
from .fill_simulator import FillSimulator, FillResult
from .metrics import MakerMetrics


logger = logging.getLogger(__name__)


@dataclass
class MakerOrder:
    """Represents a maker order placed in the market."""
    side: OrderSide
    price: float
    size_usd: float
    size_shares: float = 0.0


class MakerBacktestEngine:
    """
    Backtest engine for maker rebates strategy.

    The strategy:
    1. At window start, check if spread is wide enough
    2. Place maker orders on BOTH sides (YES bid, NO bid)
    3. Simulate fills based on orderbook activity
    4. At resolution: one side wins ($1), one loses ($0)
    5. Calculate P&L = rebates + (resolution value - cost)

    Key assumptions:
    - Maker fee: 0%
    - Maker rebate: configurable (default 0.5% of filled volume)
    - Resolution: YES wins if outcome="UP", NO wins if outcome="DOWN"
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        """
        Initialize the backtest engine.

        Args:
            config: Backtest configuration. Uses defaults if not provided.
        """
        self.config = config or BacktestConfig()
        self.config.validate()

        self.fill_simulator = FillSimulator(conservative=True)
        self.results: List[WindowResult] = []
        self._start_time: Optional[int] = None
        self._end_time: Optional[int] = None

    def run(self, data: List[MarketWindow]) -> BacktestResults:
        """
        Run backtest on a list of 15-minute market windows.

        Args:
            data: List of MarketWindow objects to backtest

        Returns:
            BacktestResults with all window results and metrics
        """
        self._start_time = int(time.time())
        self.results = []

        logger.info(f"Starting backtest on {len(data)} windows")
        logger.info(f"Config: position_size=${self.config.position_size}, "
                   f"spread_from_mid={self.config.spread_from_mid}, "
                   f"rebate_rate={self.config.rebate_rate:.2%}")

        for i, window in enumerate(data):
            try:
                result = self.simulate_window(window)
                self.results.append(result)

                if (i + 1) % 100 == 0:
                    logger.info(f"Processed {i + 1}/{len(data)} windows")

            except Exception as e:
                logger.error(f"Error processing window {window.market_id}: {e}")
                # Add a skipped result
                self.results.append(WindowResult(
                    market_id=window.market_id,
                    window_start=window.window_start,
                    entered=False,
                    skip_reason=f"Error: {str(e)}"
                ))

        self._end_time = int(time.time())

        # Calculate metrics
        metrics = MakerMetrics.calculate(self.results)

        return BacktestResults(
            config=self.config,
            window_results=self.results,
            metrics=metrics,
            start_time=self._start_time,
            end_time=self._end_time
        )

    def simulate_window(self, window: MarketWindow) -> WindowResult:
        """
        Simulate one 15-minute market window.

        Steps:
        1. Check entry conditions (spread wide enough)
        2. Determine entry prices (offset from mid)
        3. Simulate fills for YES and NO orders
        4. Calculate resolution P&L based on outcome
        5. Add rebate revenue

        Args:
            window: MarketWindow with orderbook data

        Returns:
            WindowResult with P&L and fill details
        """
        result = WindowResult(
            market_id=window.market_id,
            window_start=window.window_start,
            outcome=window.outcome
        )

        # Check if we have orderbook data
        if not window.orderbook_snapshots:
            result.skip_reason = "No orderbook data"
            return result

        initial_book = window.initial_snapshot
        if initial_book is None:
            result.skip_reason = "No initial orderbook"
            return result

        # Step 1: Check entry conditions
        spread = initial_book.spread
        mid_price = initial_book.mid_price

        if spread is None or mid_price is None:
            result.skip_reason = "Invalid orderbook state"
            return result

        result.initial_spread = spread
        result.initial_mid = mid_price

        if spread < self.config.min_spread_to_enter:
            result.skip_reason = f"Spread too thin: {spread:.4f} < {self.config.min_spread_to_enter}"
            return result

        # Step 2: Determine entry prices
        # YES order: bid below mid
        yes_order_price = mid_price - self.config.spread_from_mid
        # NO order: bid for NO below NO mid (which is 1 - YES mid)
        no_mid = 1.0 - mid_price
        no_order_price = no_mid - self.config.spread_from_mid

        # Ensure prices are valid (between 0 and 1)
        yes_order_price = max(0.01, min(0.99, yes_order_price))
        no_order_price = max(0.01, min(0.99, no_order_price))

        # Step 3: Simulate fills
        yes_fill = self.fill_simulator.simulate_fill(
            order_price=yes_order_price,
            side=OrderSide.YES,
            orderbook_snapshots=window.orderbook_snapshots,
            position_size=self.config.position_size
        )

        no_fill = self.fill_simulator.simulate_fill(
            order_price=no_order_price,
            side=OrderSide.NO,
            orderbook_snapshots=window.orderbook_snapshots,
            position_size=self.config.position_size
        )

        # Record fill results
        result.yes_filled = yes_fill.filled
        result.no_filled = no_fill.filled
        result.yes_fill_price = yes_fill.fill_price if yes_fill.filled else 0
        result.no_fill_price = no_fill.fill_price if no_fill.filled else 0
        result.yes_size = yes_fill.fill_size if yes_fill.filled else 0
        result.no_size = no_fill.fill_size if no_fill.filled else 0

        # If neither side filled, no entry
        if not yes_fill.filled and not no_fill.filled:
            result.skip_reason = "No fills"
            return result

        result.entered = True

        # Step 4: Calculate resolution P&L
        result.resolution_pnl = self._calculate_resolution_pnl(
            yes_filled=yes_fill.filled,
            no_filled=no_fill.filled,
            yes_price=yes_fill.fill_price,
            no_price=no_fill.fill_price,
            yes_size=yes_fill.fill_size,
            no_size=no_fill.fill_size,
            outcome=window.outcome
        )

        # Step 5: Calculate rebates
        result.rebate_earned = self._calculate_rebates(
            yes_filled=yes_fill.filled,
            no_filled=no_fill.filled,
            yes_price=yes_fill.fill_price,
            no_price=no_fill.fill_price,
            yes_size=yes_fill.fill_size,
            no_size=no_fill.fill_size
        )

        # Total P&L
        result.total_pnl = result.resolution_pnl + result.rebate_earned

        return result

    def _calculate_resolution_pnl(
        self,
        yes_filled: bool,
        no_filled: bool,
        yes_price: float,
        no_price: float,
        yes_size: float,
        no_size: float,
        outcome: str
    ) -> float:
        """
        Calculate P&L from position resolution.

        At resolution:
        - If outcome = "UP": YES pays $1 per share, NO pays $0
        - If outcome = "DOWN": YES pays $0, NO pays $1 per share

        P&L = (winning side value) - (cost of both positions)

        For delta-neutral (both filled):
        - Cost = yes_price * yes_size + no_price * no_size
        - If UP: revenue = yes_size * 1.0
        - If DOWN: revenue = no_size * 1.0
        """
        # Calculate costs
        yes_cost = yes_price * yes_size if yes_filled else 0
        no_cost = no_price * no_size if no_filled else 0
        total_cost = yes_cost + no_cost

        # Calculate resolution revenue
        if outcome == "UP":
            # YES wins - pays $1 per share
            revenue = yes_size if yes_filled else 0
        else:  # outcome == "DOWN"
            # NO wins - pays $1 per share
            revenue = no_size if no_filled else 0

        resolution_pnl = revenue - total_cost

        return resolution_pnl

    def _calculate_rebates(
        self,
        yes_filled: bool,
        no_filled: bool,
        yes_price: float,
        no_price: float,
        yes_size: float,
        no_size: float
    ) -> float:
        """
        Calculate maker rebates earned.

        Rebate = filled_volume_usd * rebate_rate

        Volume is calculated as price * shares for each side.
        """
        yes_volume = yes_price * yes_size if yes_filled else 0
        no_volume = no_price * no_size if no_filled else 0
        total_volume = yes_volume + no_volume

        rebate = total_volume * self.config.rebate_rate

        return rebate

    def run_monte_carlo(
        self,
        data: List[MarketWindow],
        num_simulations: int = 100,
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Run Monte Carlo simulation with probabilistic fills.

        Instead of deterministic fill rules, samples from fill probability
        distributions for more realistic variance estimation.

        Args:
            data: List of market windows
            num_simulations: Number of MC iterations
            seed: Random seed for reproducibility

        Returns:
            Dictionary with distribution of results
        """
        from .fill_simulator import ProbabilisticFillSimulator
        import random

        if seed is not None:
            random.seed(seed)

        all_results = []

        for sim in range(num_simulations):
            # Use a different seed for each simulation
            sim_seed = seed + sim if seed else None
            self.fill_simulator = ProbabilisticFillSimulator(seed=sim_seed)

            sim_results = []
            for window in data:
                result = self.simulate_window(window)
                sim_results.append(result)

            total_pnl = sum(r.total_pnl for r in sim_results if r.entered)
            all_results.append(total_pnl)

        # Reset to deterministic simulator
        self.fill_simulator = FillSimulator(conservative=True)

        # Calculate distribution statistics
        all_results.sort()
        n = len(all_results)

        return {
            "num_simulations": num_simulations,
            "mean_pnl": sum(all_results) / n,
            "median_pnl": all_results[n // 2],
            "std_dev": (sum((x - sum(all_results)/n)**2 for x in all_results) / n) ** 0.5,
            "min_pnl": min(all_results),
            "max_pnl": max(all_results),
            "percentile_5": all_results[int(n * 0.05)],
            "percentile_95": all_results[int(n * 0.95)],
            "positive_rate": sum(1 for x in all_results if x > 0) / n,
        }

    def sensitivity_analysis(
        self,
        data: List[MarketWindow],
        param_name: str,
        param_values: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Run sensitivity analysis on a single parameter.

        Args:
            data: Market windows to test
            param_name: Name of config parameter to vary
            param_values: List of values to test

        Returns:
            List of results for each parameter value
        """
        results = []
        original_value = getattr(self.config, param_name)

        for value in param_values:
            setattr(self.config, param_name, value)

            backtest_result = self.run(data)
            metrics = backtest_result.metrics

            results.append({
                "param_value": value,
                "total_pnl": backtest_result.total_pnl,
                "entry_rate": metrics["summary"]["entry_rate"],
                "win_rate": metrics["risk"]["win_rate"],
                "sharpe_ratio": metrics["risk"]["sharpe_ratio"],
            })

        # Restore original value
        setattr(self.config, param_name, original_value)

        return results


def create_test_windows(num_windows: int = 10) -> List[MarketWindow]:
    """
    Create test market windows for validation.

    Generates synthetic but realistic market windows for testing
    the backtest engine without real data.

    Args:
        num_windows: Number of test windows to create

    Returns:
        List of MarketWindow objects
    """
    import random

    windows = []
    base_time = 1704067200  # 2024-01-01 00:00:00 UTC

    for i in range(num_windows):
        window_start = base_time + i * 900  # 15-min intervals
        window_end = window_start + 900

        # Random outcome
        outcome = random.choice(["UP", "DOWN"])

        # Generate orderbook snapshots
        snapshots = []
        mid_price = random.uniform(0.45, 0.55)
        spread = random.uniform(0.02, 0.08)

        for j in range(10):  # 10 snapshots per window
            timestamp = window_start + j * 90

            # Add some price drift
            mid_drift = random.uniform(-0.02, 0.02)
            current_mid = mid_price + mid_drift

            # Create bids and asks
            best_bid = current_mid - spread / 2
            best_ask = current_mid + spread / 2

            bids = [
                [best_bid, random.uniform(100, 500)],
                [best_bid - 0.01, random.uniform(50, 200)],
                [best_bid - 0.02, random.uniform(50, 150)],
            ]
            asks = [
                [best_ask, random.uniform(100, 500)],
                [best_ask + 0.01, random.uniform(50, 200)],
                [best_ask + 0.02, random.uniform(50, 150)],
            ]

            snapshots.append(OrderbookSnapshot(
                timestamp=timestamp,
                bids=bids,
                asks=asks
            ))

        # Binance prices
        btc_start = random.uniform(42000, 44000)
        if outcome == "UP":
            btc_end = btc_start * (1 + random.uniform(0.001, 0.01))
        else:
            btc_end = btc_start * (1 - random.uniform(0.001, 0.01))

        windows.append(MarketWindow(
            market_id=f"test-window-{i}",
            window_start=window_start,
            window_end=window_end,
            outcome=outcome,
            orderbook_snapshots=snapshots,
            binance_start=btc_start,
            binance_end=btc_end,
            asset="BTC"
        ))

    return windows


if __name__ == "__main__":
    # Quick test
    logging.basicConfig(level=logging.INFO)

    print("Creating test data...")
    test_windows = create_test_windows(100)

    print("Running backtest...")
    config = BacktestConfig(
        position_size=50.0,
        spread_from_mid=0.01,
        rebate_rate=0.005,
        min_spread_to_enter=0.02
    )

    engine = MakerBacktestEngine(config)
    results = engine.run(test_windows)

    print("\n" + MakerMetrics.format_report(results.metrics))
