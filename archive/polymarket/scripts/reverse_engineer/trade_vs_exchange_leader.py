#!/usr/bin/env python3
"""
Trade vs Exchange Leader Analyzer

Correlates Account88888's trades with which exchange showed price movement first.
This tests the hypothesis that they use a non-Binance exchange as their signal source.

Analysis:
1. For each trade, identify the price direction (UP or DOWN bet)
2. Check which exchange showed that direction first
3. Calculate correlation between trade timing and exchange leadership

Requires: Multi-exchange price data collected by multi_exchange_tracker.py

Usage:
    python scripts/reverse_engineer/trade_vs_exchange_leader.py

Output:
    Analysis of which exchanges correlate with Account88888's trading decisions
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import statistics
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class ExchangeLeadEvent:
    """An event where one exchange led a price move."""
    timestamp: float
    symbol: str
    direction: str  # "up" or "down"
    leader: str  # Exchange that moved first
    lag_ms: float  # How many ms before others followed
    magnitude_pct: float  # Size of the move


@dataclass
class TradeExchangeCorrelation:
    """Correlation between a trade and exchange leadership."""
    trade_timestamp: float
    slug: str
    asset: str
    betting_direction: str  # "up" or "down"
    usdc_amount: float

    # Which exchanges showed this direction in the prior window
    binance_showed_first: bool
    coinbase_showed_first: bool
    kraken_showed_first: bool

    # Timing
    seconds_after_leader: float  # How long after leader's signal


class TradeVsExchangeAnalyzer:
    """Analyzes correlation between trades and exchange price leadership."""

    def __init__(self):
        self.exchange_data: List[dict] = []
        self.trades: List[dict] = []
        self.correlations: List[TradeExchangeCorrelation] = []

    def load_exchange_data(self, data_dir: Path) -> bool:
        """Load multi-exchange tracker output."""
        print(f"Loading exchange data from {data_dir}...")

        files = list(data_dir.glob("multi_exchange_*.json"))
        if not files:
            print("  No multi-exchange data files found!")
            print("  Run multi_exchange_tracker.py first to collect data.")
            return False

        print(f"  Found {len(files)} data files")

        all_ticks = []
        all_lead_lag = []

        for f in sorted(files):
            with open(f) as fp:
                data = json.load(fp)

            ticks = data.get("sample_ticks", [])
            lead_lag = data.get("lead_lag_events", [])

            all_ticks.extend(ticks)
            all_lead_lag.extend(lead_lag)

        print(f"  Loaded {len(all_ticks):,} price ticks")
        print(f"  Loaded {len(all_lead_lag):,} lead-lag events")

        self.exchange_data = {
            "ticks": all_ticks,
            "lead_lag_events": all_lead_lag,
        }

        return True

    def load_trades(self, trades_file: Path, features_file: Optional[Path] = None) -> bool:
        """Load Account88888's trades with betting direction."""
        print(f"\nLoading trades...")

        # Prefer features file if available (has betting_up column)
        if features_file and features_file.exists():
            print(f"  Loading from features: {features_file}")
            df = pd.read_parquet(features_file)
            self.trades = df.to_dict('records')
            print(f"  Loaded {len(self.trades):,} trades with features")
            return True

        # Fallback to raw trades
        if trades_file.exists():
            print(f"  Loading from raw trades: {trades_file}")
            with open(trades_file) as f:
                data = json.load(f)

            if isinstance(data, dict) and "trades" in data:
                self.trades = data["trades"]
            else:
                self.trades = data

            print(f"  Loaded {len(self.trades):,} trades")
            return True

        print("  No trades file found!")
        return False

    def find_exchange_leader(self, timestamp: float, symbol: str, lookback_seconds: float = 60) -> Dict[str, bool]:
        """
        Find which exchange showed price movement first before a given timestamp.

        Returns dict of {exchange: was_leader}
        """
        ticks = self.exchange_data.get("ticks", [])

        # Filter to relevant ticks
        window_start = timestamp - lookback_seconds
        relevant_ticks = [
            t for t in ticks
            if window_start <= t.get("timestamp", 0) <= timestamp
            and t.get("symbol") == symbol
        ]

        if len(relevant_ticks) < 3:
            return {"binance": False, "coinbase": False, "kraken": False}

        # Group by exchange
        by_exchange = defaultdict(list)
        for t in relevant_ticks:
            by_exchange[t["exchange"]].append(t)

        # Find first significant move per exchange
        leaders = {"binance": False, "coinbase": False, "kraken": False}
        first_move_time = {}

        for exchange, ticks_list in by_exchange.items():
            if len(ticks_list) < 2:
                continue

            # Sort by time
            ticks_list.sort(key=lambda x: x["timestamp"])

            # Find first significant move (>0.05%)
            for i in range(1, len(ticks_list)):
                prev_price = ticks_list[i-1]["price"]
                curr_price = ticks_list[i]["price"]

                if prev_price > 0:
                    move_pct = abs(curr_price - prev_price) / prev_price
                    if move_pct > 0.0005:  # 0.05%
                        first_move_time[exchange] = ticks_list[i]["timestamp"]
                        break

        # Determine leader (earliest significant move)
        if first_move_time:
            earliest = min(first_move_time.items(), key=lambda x: x[1])
            leaders[earliest[0]] = True

        return leaders

    def analyze_trade(self, trade: dict) -> Optional[TradeExchangeCorrelation]:
        """Analyze a single trade's correlation with exchange leadership."""
        timestamp = trade.get("timestamp")
        asset = trade.get("asset")
        betting_up = trade.get("betting_up")

        if timestamp is None or asset is None or betting_up is None:
            return None

        symbol = asset  # BTC, ETH

        # Find which exchange led
        leaders = self.find_exchange_leader(timestamp, symbol)

        # Determine betting direction
        betting_direction = "up" if betting_up == 1 else "down"

        # Calculate timing relative to leader
        # (This is approximate - would need exact leader timestamp)
        seconds_after = 0  # Placeholder

        return TradeExchangeCorrelation(
            trade_timestamp=timestamp,
            slug=trade.get("slug", ""),
            asset=asset,
            betting_direction=betting_direction,
            usdc_amount=trade.get("usdc_amount", 0),
            binance_showed_first=leaders.get("binance", False),
            coinbase_showed_first=leaders.get("coinbase", False),
            kraken_showed_first=leaders.get("kraken", False),
            seconds_after_leader=seconds_after,
        )

    def analyze_lead_lag_correlation(self):
        """Analyze correlation between lead-lag events and trade direction."""
        lead_lag_events = self.exchange_data.get("lead_lag_events", [])

        if not lead_lag_events:
            print("\nNo lead-lag events to analyze.")
            return {}

        print(f"\nAnalyzing {len(lead_lag_events)} lead-lag events...")

        # Count by leader
        leader_counts = defaultdict(int)
        leader_by_symbol = defaultdict(lambda: defaultdict(int))

        for event in lead_lag_events:
            leader = event.get("leader", "unknown")
            symbol = event.get("symbol", "unknown")
            leader_counts[leader] += 1
            leader_by_symbol[symbol][leader] += 1

        results = {
            "total_events": len(lead_lag_events),
            "by_leader": dict(leader_counts),
            "by_symbol": {s: dict(leaders) for s, leaders in leader_by_symbol.items()},
        }

        return results

    def compute_statistics(self) -> Dict:
        """Compute correlation statistics."""
        if not self.correlations:
            return {}

        total = len(self.correlations)

        # Count how often each exchange was the leader when 88888 traded
        binance_led = sum(1 for c in self.correlations if c.binance_showed_first)
        coinbase_led = sum(1 for c in self.correlations if c.coinbase_showed_first)
        kraken_led = sum(1 for c in self.correlations if c.kraken_showed_first)

        stats = {
            "total_trades_analyzed": total,
            "binance_led_pct": binance_led / total * 100 if total else 0,
            "coinbase_led_pct": coinbase_led / total * 100 if total else 0,
            "kraken_led_pct": kraken_led / total * 100 if total else 0,
            "no_clear_leader_pct": (total - binance_led - coinbase_led - kraken_led) / total * 100 if total else 0,
        }

        # By asset
        for asset in ["BTC", "ETH"]:
            asset_trades = [c for c in self.correlations if c.asset == asset]
            if asset_trades:
                stats[f"{asset}_binance_led"] = sum(1 for c in asset_trades if c.binance_showed_first) / len(asset_trades) * 100
                stats[f"{asset}_coinbase_led"] = sum(1 for c in asset_trades if c.coinbase_showed_first) / len(asset_trades) * 100
                stats[f"{asset}_kraken_led"] = sum(1 for c in asset_trades if c.kraken_showed_first) / len(asset_trades) * 100

        return stats

    def print_analysis(self, stats: Dict, lead_lag_stats: Dict):
        """Print analysis results."""
        print("\n" + "=" * 70)
        print("TRADE VS EXCHANGE LEADER ANALYSIS")
        print("=" * 70)

        # Lead-lag events analysis
        if lead_lag_stats:
            print("\n--- Lead-Lag Events (from multi_exchange_tracker) ---")
            print(f"Total events: {lead_lag_stats.get('total_events', 0)}")

            by_leader = lead_lag_stats.get("by_leader", {})
            total_events = lead_lag_stats.get("total_events", 1)

            for leader, count in sorted(by_leader.items(), key=lambda x: -x[1]):
                pct = count / total_events * 100
                print(f"  {leader}: {count} times ({pct:.1f}%)")

        # Trade correlation analysis
        if stats:
            print(f"\n--- Trade Correlation (Account88888) ---")
            print(f"Trades analyzed: {stats.get('total_trades_analyzed', 0):,}")

            print("\nWhen Account88888 traded, which exchange had shown movement first?")
            print(f"  Binance: {stats.get('binance_led_pct', 0):.1f}%")
            print(f"  Coinbase: {stats.get('coinbase_led_pct', 0):.1f}%")
            print(f"  Kraken: {stats.get('kraken_led_pct', 0):.1f}%")
            print(f"  No clear leader: {stats.get('no_clear_leader_pct', 0):.1f}%")

        # Interpretation
        print("\n--- Interpretation ---")

        if lead_lag_stats:
            by_leader = lead_lag_stats.get("by_leader", {})
            if by_leader:
                top_leader = max(by_leader, key=by_leader.get)
                if top_leader != "binance":
                    print(f"! {top_leader.upper()} leads price moves most often")
                    print("  Account88888 might be watching this exchange for signals")
                else:
                    print("Binance typically leads - unlikely to be their edge source")

        if stats:
            if stats.get("coinbase_led_pct", 0) > stats.get("binance_led_pct", 0):
                print("! Coinbase leads when 88888 trades - possible signal source")
            if stats.get("kraken_led_pct", 0) > stats.get("binance_led_pct", 0):
                print("! Kraken leads when 88888 trades - possible signal source")

        print("\n" + "=" * 70)

    def run(self):
        """Run the full analysis."""
        print("=" * 70)
        print("TRADE VS EXCHANGE LEADER ANALYZER")
        print("=" * 70)
        print()
        print("Testing hypothesis: Does Account88888 use a non-Binance exchange")
        print("as their signal source?")
        print()

        # Load exchange data
        data_dir = PROJECT_ROOT / "data" / "research" / "multi_exchange"
        if not self.load_exchange_data(data_dir):
            print("\nPlease run multi_exchange_tracker.py first to collect data.")
            return

        # Load trades
        trades_file = PROJECT_ROOT / "data" / "account88888_trades_joined.json"
        features_file = PROJECT_ROOT / "data" / "features" / "account88888_features_sample50000.parquet"

        if not self.load_trades(trades_file, features_file):
            return

        # Analyze lead-lag events
        lead_lag_stats = self.analyze_lead_lag_correlation()

        # Analyze trade correlations (sample)
        print("\nAnalyzing trade correlations...")
        sample_size = min(1000, len(self.trades))

        import random
        random.seed(42)
        sampled_trades = random.sample(self.trades, sample_size)

        for trade in sampled_trades:
            correlation = self.analyze_trade(trade)
            if correlation:
                self.correlations.append(correlation)

        print(f"  Analyzed {len(self.correlations)} trades")

        # Compute stats
        stats = self.compute_statistics()

        # Print results
        self.print_analysis(stats, lead_lag_stats)


def main():
    """Run the analyzer."""
    analyzer = TradeVsExchangeAnalyzer()
    analyzer.run()


if __name__ == "__main__":
    main()
