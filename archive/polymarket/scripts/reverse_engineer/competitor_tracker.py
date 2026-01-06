#!/usr/bin/env python3
"""
Competitor Tracker

Tracks other large traders in the same Polymarket 15-minute markets to:
1. Identify top 10 most active wallets
2. Correlate Account88888's trades with competitor activity
3. Detect if 88888 trades AFTER seeing others (follower pattern)
4. Find copy-trade or front-run patterns

Usage:
    python scripts/reverse_engineer/competitor_tracker.py

Uses existing ERC1155 transfer data to identify other traders.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict
import statistics
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


ACCOUNT_88888 = "0x7f69983eb28245bba0d5083502a78744a8f66162"


@dataclass
class TraderProfile:
    """Profile of a trader."""
    address: str
    total_trades: int
    total_volume: float  # In token amounts
    markets_traded: int
    first_seen: int
    last_seen: int

    # Relationship with 88888
    shared_markets: int = 0
    trades_before_88888: int = 0
    trades_after_88888: int = 0
    avg_seconds_diff: float = 0


@dataclass
class MarketActivity:
    """Activity in a single market."""
    slug: str
    token_id: str
    traders: Dict[str, List[dict]]  # address -> list of trades


class CompetitorTracker:
    """Tracks competitor activity."""

    def __init__(self):
        self.traders: Dict[str, TraderProfile] = {}
        self.market_activity: Dict[str, MarketActivity] = {}
        self.account88888_trades: Dict[str, List[dict]] = {}  # slug -> trades

    def load_erc1155_transfers(self, transfers_file: str, limit: int = 500000) -> List[dict]:
        """Load ERC1155 transfers (trades)."""
        print(f"Loading ERC1155 transfers from {transfers_file}...")

        transfers = []
        count = 0

        with open(transfers_file) as f:
            for line in f:
                if count >= limit:
                    break
                try:
                    transfer = json.loads(line.strip())
                    transfers.append(transfer)
                    count += 1
                except:
                    continue

        print(f"  Loaded {len(transfers):,} transfers")
        return transfers

    def load_token_mapping(self, mapping_file: str) -> Dict:
        """Load token to market mapping."""
        print(f"Loading token mapping...")
        try:
            with open(mapping_file) as f:
                data = json.load(f)
            mapping = data.get("token_to_market", data)
            print(f"  Loaded {len(mapping):,} mappings")
            return mapping
        except Exception as e:
            print(f"  Error: {e}")
            return {}

    def process_transfers(self, transfers: List[dict], token_mapping: Dict):
        """Process transfers to identify traders."""
        print("\nProcessing transfers...")

        trader_stats = defaultdict(lambda: {
            "trades": 0,
            "volume": 0,
            "markets": set(),
            "first": float('inf'),
            "last": 0,
        })

        for transfer in transfers:
            from_addr = transfer.get("from_address", "").lower()
            to_addr = transfer.get("to_address", "").lower()
            token_id = str(transfer.get("token_id", ""))
            value = float(transfer.get("value", 0))
            timestamp = int(transfer.get("block_timestamp", 0))

            market_info = token_mapping.get(token_id, {})
            slug = market_info.get("slug", "")

            # Skip non-market transfers
            if not slug or "updown" not in slug:
                continue

            # Identify traders (exclude null address and contracts)
            for addr in [from_addr, to_addr]:
                if addr and addr != "0x0000000000000000000000000000000000000000":
                    stats = trader_stats[addr]
                    stats["trades"] += 1
                    stats["volume"] += value
                    stats["markets"].add(slug)
                    stats["first"] = min(stats["first"], timestamp)
                    stats["last"] = max(stats["last"], timestamp)

            # Track market activity
            if slug not in self.market_activity:
                self.market_activity[slug] = MarketActivity(
                    slug=slug,
                    token_id=token_id,
                    traders=defaultdict(list)
                )

            trade_info = {
                "timestamp": timestamp,
                "from": from_addr,
                "to": to_addr,
                "value": value,
                "token_id": token_id,
            }

            # Track by to_address (buyer)
            if to_addr:
                self.market_activity[slug].traders[to_addr].append(trade_info)

                # Track 88888 specifically
                if to_addr == ACCOUNT_88888:
                    if slug not in self.account88888_trades:
                        self.account88888_trades[slug] = []
                    self.account88888_trades[slug].append(trade_info)

        # Convert to profiles
        for addr, stats in trader_stats.items():
            if stats["trades"] >= 5:  # Only track active traders
                self.traders[addr] = TraderProfile(
                    address=addr,
                    total_trades=stats["trades"],
                    total_volume=stats["volume"],
                    markets_traded=len(stats["markets"]),
                    first_seen=stats["first"] if stats["first"] != float('inf') else 0,
                    last_seen=stats["last"],
                )

        print(f"  Identified {len(self.traders):,} active traders")
        print(f"  Markets with activity: {len(self.market_activity):,}")

    def analyze_competitor_timing(self):
        """Analyze timing relationship with Account88888."""
        print("\nAnalyzing competitor timing vs Account88888...")

        for addr, profile in self.traders.items():
            if addr == ACCOUNT_88888:
                continue

            shared_markets = 0
            before_count = 0
            after_count = 0
            time_diffs = []

            for slug, activity in self.market_activity.items():
                if addr not in activity.traders:
                    continue

                if slug not in self.account88888_trades:
                    continue

                shared_markets += 1

                # Get 88888's first trade in this market
                t88888_trades = self.account88888_trades[slug]
                t88888_first = min(t["timestamp"] for t in t88888_trades)

                # Get competitor's trades
                competitor_trades = activity.traders[addr]

                for trade in competitor_trades:
                    diff = trade["timestamp"] - t88888_first
                    time_diffs.append(diff)

                    if diff < -10:  # Traded >10s before 88888
                        before_count += 1
                    elif diff > 10:  # Traded >10s after 88888
                        after_count += 1

            if shared_markets > 0:
                profile.shared_markets = shared_markets
                profile.trades_before_88888 = before_count
                profile.trades_after_88888 = after_count
                if time_diffs:
                    profile.avg_seconds_diff = statistics.mean(time_diffs)

    def get_top_competitors(self, n: int = 10) -> List[TraderProfile]:
        """Get top N competitors by volume."""
        competitors = [p for addr, p in self.traders.items() if addr != ACCOUNT_88888]
        return sorted(competitors, key=lambda x: x.total_volume, reverse=True)[:n]

    def get_related_traders(self, n: int = 10) -> List[TraderProfile]:
        """Get traders most related to Account88888 (shared markets)."""
        competitors = [p for addr, p in self.traders.items() if addr != ACCOUNT_88888 and p.shared_markets > 0]
        return sorted(competitors, key=lambda x: x.shared_markets, reverse=True)[:n]

    def print_analysis(self):
        """Print analysis results."""
        print("\n" + "=" * 70)
        print("COMPETITOR ANALYSIS")
        print("=" * 70)

        # Account88888 stats
        if ACCOUNT_88888 in self.traders:
            t88888 = self.traders[ACCOUNT_88888]
            print(f"\nAccount88888:")
            print(f"  Total trades: {t88888.total_trades:,}")
            print(f"  Markets traded: {t88888.markets_traded:,}")
            print(f"  Total volume: {t88888.total_volume:,.0f} tokens")

        # Top competitors by volume
        print("\n--- Top 10 Competitors by Volume ---")
        print(f"{'Rank':<5} {'Address':<44} {'Trades':>8} {'Markets':>8} {'Volume':>12}")
        print("-" * 80)

        for i, trader in enumerate(self.get_top_competitors(10), 1):
            addr_short = trader.address[:6] + "..." + trader.address[-4:]
            print(f"{i:<5} {addr_short:<44} {trader.total_trades:>8,} {trader.markets_traded:>8,} {trader.total_volume:>12,.0f}")

        # Related traders (shared markets with 88888)
        print("\n--- Traders Related to Account88888 (Shared Markets) ---")
        related = self.get_related_traders(10)

        if related:
            print(f"{'Address':<44} {'Shared':>8} {'Before':>8} {'After':>8} {'Avg Diff':>10}")
            print("-" * 80)

            for trader in related:
                addr_short = trader.address[:6] + "..." + trader.address[-4:]
                print(f"{addr_short:<44} {trader.shared_markets:>8} {trader.trades_before_88888:>8} {trader.trades_after_88888:>8} {trader.avg_seconds_diff:>10.1f}s")
        else:
            print("No traders with shared markets found.")

        # Interpretation
        print("\n--- Interpretation ---")

        if related:
            total_before = sum(t.trades_before_88888 for t in related)
            total_after = sum(t.trades_after_88888 for t in related)

            if total_before > total_after * 2:
                print("! Other traders typically trade BEFORE Account88888")
                print("  → 88888 may be watching/following other traders")
            elif total_after > total_before * 2:
                print("Other traders typically trade AFTER Account88888")
                print("  → 88888 is a leader, others may be following them")
            else:
                print("Mixed timing - no clear leader/follower pattern")

        print("\n" + "=" * 70)

    def save_results(self):
        """Save results to file."""
        output_dir = PROJECT_ROOT / "data" / "analysis"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save trader profiles
        traders_data = {}
        for addr, profile in self.traders.items():
            traders_data[addr] = {
                "address": profile.address,
                "total_trades": profile.total_trades,
                "total_volume": profile.total_volume,
                "markets_traded": profile.markets_traded,
                "shared_markets_with_88888": profile.shared_markets,
                "trades_before_88888": profile.trades_before_88888,
                "trades_after_88888": profile.trades_after_88888,
                "avg_seconds_diff": profile.avg_seconds_diff,
            }

        import time
        timestamp = int(time.time())
        filepath = output_dir / f"competitor_analysis_{timestamp}.json"

        with open(filepath, 'w') as f:
            json.dump(traders_data, f, indent=2)

        print(f"\nSaved results to: {filepath}")

    def run(self, transfers_file: str, mapping_file: str, limit: int = 500000):
        """Run competitor analysis."""
        print("=" * 70)
        print("COMPETITOR TRACKER")
        print("=" * 70)
        print()
        print("Analyzing other traders in the same markets as Account88888")
        print()

        # Load data
        transfers = self.load_erc1155_transfers(transfers_file, limit)
        token_mapping = self.load_token_mapping(mapping_file)

        # Process
        self.process_transfers(transfers, token_mapping)
        self.analyze_competitor_timing()

        # Output
        self.print_analysis()
        self.save_results()


def main():
    """Run competitor tracker."""
    import argparse

    parser = argparse.ArgumentParser(description="Competitor Tracker")
    parser.add_argument(
        "--transfers",
        default="data/ec2_transfers/transfers_0x7f69983e_erc1155.jsonl",
        help="ERC1155 transfers file"
    )
    parser.add_argument(
        "--mapping",
        default="data/token_to_market.json",
        help="Token mapping file"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500000,
        help="Max transfers to process"
    )

    args = parser.parse_args()

    tracker = CompetitorTracker()
    tracker.run(
        str(PROJECT_ROOT / args.transfers),
        str(PROJECT_ROOT / args.mapping),
        args.limit
    )


if __name__ == "__main__":
    main()
