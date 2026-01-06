#!/usr/bin/env python3
"""
Hypothesis Backtester

Tests various trading hypotheses against Account88888's historical trades
to determine which strategies could explain their 97.9% win rate.

Hypotheses to test:
1. Pure momentum following
2. Momentum + hedging
3. Account88888's exact pattern (from ML model)
4. Contrarian to extreme momentum
5. Time-weighted momentum

Usage:
    python scripts/reverse_engineer/hypothesis_backtester.py

Output:
    Reports on win rate and profitability of each hypothesis
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Callable, Optional
from dataclasses import dataclass
from collections import defaultdict
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class TradeDecision:
    """A simulated trade decision."""
    market_slug: str
    asset: str
    timestamp: int
    window_end: int

    # Decision
    bet_up_ratio: float  # 0-1, how much to allocate to UP
    total_usdc: float

    # Context
    momentum: float  # Price momentum from window start
    binance_price: float


@dataclass
class MarketOutcome:
    """Outcome of a market."""
    slug: str
    asset: str
    window_end: int
    resolution: str  # "up" or "down"
    final_binance_price: float
    start_binance_price: float


@dataclass
class BacktestResult:
    """Results from backtesting a hypothesis."""
    hypothesis_name: str
    total_markets: int
    wins: int
    losses: int
    win_rate: float
    total_profit: float
    total_invested: float
    roi: float
    avg_profit_per_market: float


class HypothesisBacktester:
    """
    Backtests trading hypotheses against historical data.
    """

    def __init__(self):
        self.features_df: Optional[pd.DataFrame] = None
        self.market_outcomes: Dict[str, MarketOutcome] = {}

    def load_data(self, features_file: str):
        """Load feature data."""
        print(f"Loading features from {features_file}...")
        self.features_df = pd.read_parquet(features_file)
        print(f"  Loaded {len(self.features_df):,} trades")

        # Calculate market outcomes from the data
        self._calculate_market_outcomes()

    def _calculate_market_outcomes(self):
        """
        Calculate actual market outcomes.

        Since we have Account88888's trades with betting direction and we know
        they have 97.9% win rate, we can infer outcomes from their bets.
        """
        print("Calculating market outcomes...")

        df = self.features_df.copy()

        # Group by market (slug)
        markets = df.groupby('slug').agg({
            'asset': 'first',
            'timestamp': ['min', 'max'],
            'betting_up': 'mean',  # Average bet direction
            'usdc_amount': 'sum',
            'momentum_from_window_start': 'mean',
            'binance_price': 'mean',
        }).reset_index()

        markets.columns = ['slug', 'asset', 'first_trade', 'last_trade',
                          'avg_bet_up', 'total_usdc', 'avg_momentum', 'avg_binance']

        # Infer resolution: if they bet mostly UP and won 97.9%, resolution was likely UP
        # This is an approximation - we don't have actual resolution data
        for _, row in markets.iterrows():
            # Use their dominant bet as the likely resolution (they win 97.9%)
            resolution = "up" if row['avg_bet_up'] > 0.5 else "down"

            # Extract window_end from slug
            try:
                window_start = int(row['slug'].split('-')[-1])
                window_end = window_start + 900
            except:
                continue

            outcome = MarketOutcome(
                slug=row['slug'],
                asset=row['asset'],
                window_end=window_end,
                resolution=resolution,
                final_binance_price=row['avg_binance'],  # Approximation
                start_binance_price=row['avg_binance'],  # Would need start price
            )
            self.market_outcomes[row['slug']] = outcome

        print(f"  Calculated outcomes for {len(self.market_outcomes):,} markets")

    def hypothesis_momentum_follow(self, momentum: float, **kwargs) -> float:
        """
        Hypothesis 1: Simple momentum following.
        Bet UP if price is up from start, DOWN if down.

        Returns: bet_up_ratio (0-1)
        """
        if momentum > 0:
            return 0.7  # 70% to UP
        elif momentum < 0:
            return 0.3  # 30% to UP (70% to DOWN)
        else:
            return 0.5  # Even split

    def hypothesis_strong_momentum(self, momentum: float, **kwargs) -> float:
        """
        Hypothesis 2: Strong momentum following.
        More aggressive betting based on momentum magnitude.
        """
        if momentum > 0.002:  # Strong up
            return 0.9
        elif momentum > 0:  # Weak up
            return 0.65
        elif momentum < -0.002:  # Strong down
            return 0.1
        elif momentum < 0:  # Weak down
            return 0.35
        else:
            return 0.5

    def hypothesis_contrarian(self, momentum: float, **kwargs) -> float:
        """
        Hypothesis 3: Contrarian - bet against extreme momentum.
        Theory: Extreme moves revert.
        """
        if momentum > 0.003:  # Very strong up - bet DOWN
            return 0.3
        elif momentum < -0.003:  # Very strong down - bet UP
            return 0.7
        elif momentum > 0:
            return 0.6  # Slight momentum follow
        elif momentum < 0:
            return 0.4
        else:
            return 0.5

    def hypothesis_account88888_ml(self, momentum: float, price: float, window_fraction: float, **kwargs) -> float:
        """
        Hypothesis 4: Mimic Account88888 based on ML findings.
        - Follow momentum 61% of time
        - Buy undervalued tokens (price < 0.5)
        - Weight by timing
        """
        # Base: follow momentum 61%
        if momentum > 0:
            base = 0.61
        elif momentum < 0:
            base = 0.39
        else:
            base = 0.5

        # Adjust for price: prefer undervalued
        if price < 0.45:
            base += 0.1  # More likely to buy this side
        elif price > 0.55:
            base -= 0.1  # Less likely

        # Adjust for timing: more confident later in window
        if window_fraction > 0.7:
            # Amplify the bet
            if base > 0.5:
                base = min(0.8, base + 0.1)
            else:
                base = max(0.2, base - 0.1)

        return max(0.1, min(0.9, base))

    def hypothesis_hedge_momentum(self, momentum: float, **kwargs) -> float:
        """
        Hypothesis 5: Hedge with momentum bias.
        Always bet both sides but favor momentum direction.
        Similar to Account88888's actual behavior.
        """
        # 74% to dominant side (ratio ~2.8x)
        if momentum > 0:
            return 0.74
        elif momentum < 0:
            return 0.26
        else:
            return 0.5

    def simulate_market(self, hypothesis_fn: Callable, market_trades: pd.DataFrame) -> Tuple[bool, float]:
        """
        Simulate trading a single market with a hypothesis.

        Returns: (correctly_predicted_88888_direction, total_usdc)
        """
        if len(market_trades) == 0:
            return False, 0

        # Get 88888's actual dominant bet direction
        actual_bet_up_ratio = market_trades['betting_up'].mean()
        actual_favored_up = actual_bet_up_ratio > 0.5

        # Get market state at decision time (use median trade)
        mid_idx = len(market_trades) // 2
        row = market_trades.iloc[mid_idx]

        # Make decision using hypothesis
        momentum = row.get('momentum_from_window_start', 0) or 0
        price = row.get('price', 0.5) or 0.5
        window_fraction = row.get('window_fraction', 0.5) or 0.5

        predicted_up_ratio = hypothesis_fn(
            momentum=momentum,
            price=price,
            window_fraction=window_fraction
        )
        predicted_favored_up = predicted_up_ratio > 0.5

        # Did we predict 88888's direction correctly?
        correct = (predicted_favored_up == actual_favored_up)

        total_usdc = market_trades['usdc_amount'].sum()
        return correct, total_usdc

    def backtest_hypothesis(self, hypothesis_fn: Callable, hypothesis_name: str) -> BacktestResult:
        """
        Backtest a single hypothesis across all markets.
        Tests how well we can predict Account88888's betting DIRECTION.
        """
        print(f"\nBacktesting: {hypothesis_name}...")

        df = self.features_df[self.features_df['side'] == 'BUY'].copy()

        total_invested = 0
        correct_predictions = 0
        total_markets = 0

        # Group by market
        for slug, market_trades in df.groupby('slug'):
            # Skip markets where betting_up is all null
            if market_trades['betting_up'].isna().all():
                continue

            correct, invested = self.simulate_market(hypothesis_fn, market_trades)

            if invested > 0:
                total_invested += invested
                total_markets += 1

                if correct:
                    correct_predictions += 1

        win_rate = correct_predictions / total_markets if total_markets > 0 else 0

        result = BacktestResult(
            hypothesis_name=hypothesis_name,
            total_markets=total_markets,
            wins=correct_predictions,
            losses=total_markets - correct_predictions,
            win_rate=win_rate,
            total_profit=0,  # Not calculated this way
            total_invested=total_invested,
            roi=0,  # Not calculated this way
            avg_profit_per_market=0,
        )

        return result

    def run_all_hypotheses(self) -> List[BacktestResult]:
        """Run all hypothesis backtests."""
        hypotheses = [
            (self.hypothesis_momentum_follow, "Simple Momentum Follow (61/39)"),
            (self.hypothesis_strong_momentum, "Strong Momentum (90/10 at extremes)"),
            (self.hypothesis_contrarian, "Contrarian (bet against extremes)"),
            (self.hypothesis_account88888_ml, "Account88888 ML Pattern"),
            (self.hypothesis_hedge_momentum, "Hedge with Momentum (74/26)"),
        ]

        results = []
        for fn, name in hypotheses:
            result = self.backtest_hypothesis(fn, name)
            results.append(result)

        return results

    def print_results(self, results: List[BacktestResult]):
        """Print backtest results."""
        print("\n" + "=" * 80)
        print("HYPOTHESIS BACKTEST RESULTS")
        print("=" * 80)
        print()
        print("Note: Outcomes are INFERRED from Account88888's bets (they win 97.9%).")
        print("      This tests if we can replicate their DECISION PATTERN, not actual outcomes.")
        print()

        # Sort by win rate
        results_sorted = sorted(results, key=lambda x: -x.win_rate)

        print(f"{'Hypothesis':<40} {'Win Rate':>10} {'Markets':>10} {'ROI':>10}")
        print("-" * 80)

        for r in results_sorted:
            print(f"{r.hypothesis_name:<40} {r.win_rate:>9.1%} {r.total_markets:>10,} {r.roi:>9.1%}")

        # Best hypothesis
        best = results_sorted[0]
        print()
        print(f"Best Hypothesis: {best.hypothesis_name}")
        print(f"  Win Rate: {best.win_rate:.1%}")
        print(f"  ROI: {best.roi:.1%}")
        print(f"  Total Markets: {best.total_markets:,}")

        # Compare to ML model
        print()
        print("=" * 80)
        print("INTERPRETATION")
        print("=" * 80)
        print()
        print("These results show how well each hypothesis predicts Account88888's")
        print("betting DIRECTION (UP vs DOWN), not the actual market outcome.")
        print()
        print("For reference, our ML model achieved 74% accuracy predicting their direction.")
        print()

        if best.win_rate > 0.7:
            print(f"Best hypothesis achieves {best.win_rate:.1%} - GOOD match!")
            print("This simple rule captures most of their decision pattern.")
        elif best.win_rate > 0.6:
            print(f"Best hypothesis achieves {best.win_rate:.1%} - MODERATE match.")
            print("The rule captures part of their strategy.")
        else:
            print(f"Best hypothesis achieves {best.win_rate:.1%} - WEAK match.")
            print("Their decision-making is more complex than these simple rules.")


def main():
    """Run hypothesis backtester."""
    import argparse

    parser = argparse.ArgumentParser(description="Hypothesis Backtester")
    parser.add_argument(
        "--features",
        type=str,
        default="data/features/account88888_features_sample50000.parquet",
        help="Path to features parquet file"
    )

    args = parser.parse_args()

    print("=" * 80)
    print("HYPOTHESIS BACKTESTER")
    print("=" * 80)
    print()
    print("Testing trading hypotheses against Account88888's historical trades")
    print("to find strategies that could explain their 97.9% win rate.")
    print()

    backtester = HypothesisBacktester()

    # Load data
    features_file = PROJECT_ROOT / args.features
    backtester.load_data(features_file)

    # Run backtests
    results = backtester.run_all_hypotheses()

    # Print results
    backtester.print_results(results)


if __name__ == "__main__":
    main()
