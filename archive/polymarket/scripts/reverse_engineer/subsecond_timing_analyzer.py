#!/usr/bin/env python3
"""
Subsecond Timing Analyzer for Account88888

Analyzes trade timing at sub-second granularity to identify timing patterns
that might explain Account88888's 97.9% win rate.

Key Questions:
1. When exactly do they trade relative to market resolution?
2. Are there clusters of trades at specific times?
3. Do trades in the final seconds have higher win rates?
4. Is there evidence of last-second information advantage?

Usage:
    python scripts/reverse_engineer/subsecond_timing_analyzer.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import Dict, List, Tuple
import statistics

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def load_trades(trades_file: str) -> Tuple[Dict, List[dict]]:
    """Load the full trades dataset."""
    print(f"Loading trades from {trades_file}...")
    with open(trades_file) as f:
        data = json.load(f)

    metadata = data.get("metadata", {})
    trades = data.get("trades", [])

    print(f"Loaded {len(trades):,} trades")
    print(f"Time range: {metadata.get('time_range_start')} to {metadata.get('time_range_end')}")
    print(f"Total volume: ${metadata.get('total_volume_usdc', 0):,.2f}")

    return metadata, trades


def load_token_mapping(mapping_file: str) -> Dict[str, dict]:
    """Load token to market mapping."""
    print(f"Loading token mapping from {mapping_file}...")
    with open(mapping_file) as f:
        data = json.load(f)

    # Handle nested structure
    if "token_to_market" in data:
        mapping = data["token_to_market"]
    else:
        mapping = data

    print(f"Loaded {len(mapping):,} token mappings")
    return mapping


def extract_window_times_from_slug(slug: str) -> Tuple[int, int]:
    """
    Extract window start and end times from market slug like 'btc-updown-15m-1764933300'.

    The slug timestamp is the WINDOW START. Window END (resolution) is +900 seconds.

    Returns: (window_start, window_end) or (None, None)
    """
    try:
        parts = slug.split("-")
        window_start = int(parts[-1])
        window_end = window_start + 900  # 15 minute window
        return window_start, window_end
    except:
        return None, None


def analyze_timing(trades: List[dict], token_mapping: Dict[str, dict]) -> Dict:
    """
    Analyze trade timing patterns.

    Returns comprehensive timing analysis.
    """
    print("\n" + "="*70)
    print("TIMING ANALYSIS")
    print("="*70)

    # Track timing metrics
    timing_data = []
    trades_by_second_before_close = defaultdict(list)
    trades_by_minute_into_window = defaultdict(list)
    block_clusters = defaultdict(list)

    # Track which trades we can analyze
    analyzed = 0
    skipped_no_mapping = 0
    skipped_no_slug = 0

    for trade in trades:
        token_id = trade.get("token_id")
        timestamp = trade.get("timestamp")
        block_number = trade.get("block_number")

        if not token_id or not timestamp:
            continue

        # Look up market info
        market_info = token_mapping.get(token_id)
        if not market_info:
            skipped_no_mapping += 1
            continue

        slug = market_info.get("slug")
        if not slug:
            skipped_no_slug += 1
            continue

        # Extract window times (slug = window start, +900 = window end/resolution)
        window_start, window_end = extract_window_times_from_slug(slug)
        if not window_start:
            continue

        # Time into window (0-900 seconds during window)
        time_into_window = timestamp - window_start

        # Time to close/resolution (positive = before end, negative = after end)
        time_to_close = window_end - timestamp

        # Only analyze trades within reasonable bounds
        # -300 to 1200 allows for some trades before window starts and after window ends
        if time_into_window < -300 or time_into_window > 1200:
            continue

        timing_entry = {
            "timestamp": timestamp,
            "block_number": block_number,
            "window_start": window_start,
            "window_end": window_end,
            "time_into_window": time_into_window,
            "time_to_close": time_to_close,
            "price": trade.get("price"),
            "usdc_amount": trade.get("usdc_amount"),
            "side": trade.get("side"),
            "token_id": token_id,
            "slug": slug,
        }

        timing_data.append(timing_entry)
        analyzed += 1

        # Group by seconds before close (only for trades during window)
        if 0 <= time_to_close <= 900:
            second_bucket = int(time_to_close)
            trades_by_second_before_close[second_bucket].append(timing_entry)

        # Group by minute into window (only for trades during window)
        if 0 <= time_into_window <= 900:
            minute_bucket = int(time_into_window // 60)
            trades_by_minute_into_window[minute_bucket].append(timing_entry)

        # Group by block
        if block_number:
            block_clusters[block_number].append(timing_entry)

    print(f"\nAnalyzed: {analyzed:,} trades")
    print(f"Skipped (no mapping): {skipped_no_mapping:,}")
    print(f"Skipped (no slug): {skipped_no_slug:,}")

    return {
        "timing_data": timing_data,
        "trades_by_second_before_close": dict(trades_by_second_before_close),
        "trades_by_minute_into_window": dict(trades_by_minute_into_window),
        "block_clusters": dict(block_clusters),
        "stats": {
            "analyzed": analyzed,
            "skipped_no_mapping": skipped_no_mapping,
            "skipped_no_slug": skipped_no_slug,
        }
    }


def print_timing_distribution(analysis: Dict):
    """Print timing distribution analysis."""
    timing_data = analysis["timing_data"]

    if not timing_data:
        print("No timing data to analyze")
        return

    print("\n" + "="*70)
    print("TIME TO CLOSE DISTRIBUTION")
    print("="*70)

    time_to_close_values = [t["time_to_close"] for t in timing_data if t["time_to_close"] is not None]

    if time_to_close_values:
        # Basic stats
        avg_time = statistics.mean(time_to_close_values)
        median_time = statistics.median(time_to_close_values)

        print(f"\nAll trades:")
        print(f"  Average time to close: {avg_time:.1f}s ({avg_time/60:.1f} min)")
        print(f"  Median time to close: {median_time:.1f}s ({median_time/60:.1f} min)")
        print(f"  Min: {min(time_to_close_values):.1f}s")
        print(f"  Max: {max(time_to_close_values):.1f}s")

        # Distribution by time buckets
        print(f"\nDistribution by time to close:")

        buckets = [
            ("After close (< 0s)", lambda x: x < 0),
            ("Last 10 seconds", lambda x: 0 <= x < 10),
            ("10-30 seconds", lambda x: 10 <= x < 30),
            ("30-60 seconds", lambda x: 30 <= x < 60),
            ("1-2 minutes", lambda x: 60 <= x < 120),
            ("2-5 minutes", lambda x: 120 <= x < 300),
            ("5-10 minutes", lambda x: 300 <= x < 600),
            ("10-15 minutes", lambda x: 600 <= x <= 900),
            (">15 minutes", lambda x: x > 900),
        ]

        total = len(time_to_close_values)
        for name, condition in buckets:
            count = sum(1 for x in time_to_close_values if condition(x))
            if count > 0:
                pct = 100 * count / total
                print(f"  {name}: {count:,} ({pct:.1f}%)")


def print_minute_distribution(analysis: Dict):
    """Print distribution by minute into window."""
    trades_by_minute = analysis["trades_by_minute_into_window"]

    print("\n" + "="*70)
    print("TRADES BY MINUTE INTO WINDOW")
    print("="*70)

    total_trades = sum(len(v) for v in trades_by_minute.values())
    total_usdc = sum(
        sum(t.get("usdc_amount", 0) for t in trades)
        for trades in trades_by_minute.values()
    )

    print(f"\nMinute | Trades | % of Total | USDC Volume | Avg USDC/Trade")
    print("-" * 70)

    for minute in range(16):  # 0-15 minutes
        trades = trades_by_minute.get(minute, [])
        count = len(trades)
        usdc = sum(t.get("usdc_amount", 0) for t in trades)

        if count > 0:
            pct = 100 * count / total_trades if total_trades > 0 else 0
            avg_usdc = usdc / count
            print(f"  {minute:2d}   | {count:7,} | {pct:5.1f}%     | ${usdc:12,.2f} | ${avg_usdc:8.2f}")


def analyze_final_seconds(analysis: Dict):
    """Deep dive into the final 60 seconds before close."""
    trades_by_second = analysis["trades_by_second_before_close"]

    print("\n" + "="*70)
    print("FINAL 60 SECONDS ANALYSIS")
    print("="*70)

    # Aggregate by 5-second buckets for final minute
    buckets_5s = defaultdict(list)

    for second, trades in trades_by_second.items():
        if 0 <= second <= 60:
            bucket = second // 5 * 5  # 0, 5, 10, 15, ...
            buckets_5s[bucket].extend(trades)

    print(f"\nTrades in 5-second buckets (final 60 seconds):")
    print(f"Seconds to Close | Trades | USDC Volume | Avg Price")
    print("-" * 60)

    for bucket in sorted(buckets_5s.keys()):
        trades = buckets_5s[bucket]
        count = len(trades)
        usdc = sum(t.get("usdc_amount", 0) for t in trades)
        avg_price = statistics.mean([t["price"] for t in trades if t.get("price")]) if trades else 0

        print(f"  {bucket:2d}-{bucket+5:2d}s           | {count:6,} | ${usdc:12,.2f} | ${avg_price:.3f}")

    # Count trades in final 10 seconds
    final_10s = sum(len(trades_by_second.get(s, [])) for s in range(11))
    final_30s = sum(len(trades_by_second.get(s, [])) for s in range(31))
    final_60s = sum(len(trades_by_second.get(s, [])) for s in range(61))

    print(f"\nFinal second counts:")
    print(f"  Final 10 seconds: {final_10s:,} trades")
    print(f"  Final 30 seconds: {final_30s:,} trades")
    print(f"  Final 60 seconds: {final_60s:,} trades")


def analyze_block_clusters(analysis: Dict):
    """Analyze trade clustering by block."""
    block_clusters = analysis["block_clusters"]

    print("\n" + "="*70)
    print("BLOCK CLUSTERING ANALYSIS")
    print("="*70)

    # Count trades per block
    trades_per_block = [(block, len(trades)) for block, trades in block_clusters.items()]

    if not trades_per_block:
        print("No block data available")
        return

    counts = [c for _, c in trades_per_block]

    print(f"\nTrades per block:")
    print(f"  Total blocks with trades: {len(trades_per_block):,}")
    print(f"  Average trades per block: {statistics.mean(counts):.1f}")
    print(f"  Max trades in single block: {max(counts)}")
    print(f"  Median trades per block: {statistics.median(counts):.1f}")

    # Distribution of cluster sizes
    cluster_sizes = defaultdict(int)
    for _, count in trades_per_block:
        if count == 1:
            cluster_sizes["1 trade"] += 1
        elif count <= 5:
            cluster_sizes["2-5 trades"] += 1
        elif count <= 10:
            cluster_sizes["6-10 trades"] += 1
        elif count <= 50:
            cluster_sizes["11-50 trades"] += 1
        else:
            cluster_sizes["50+ trades"] += 1

    print(f"\nCluster size distribution:")
    for size, count in sorted(cluster_sizes.items()):
        pct = 100 * count / len(trades_per_block)
        print(f"  {size}: {count:,} blocks ({pct:.1f}%)")

    # Top 10 largest clusters
    top_clusters = sorted(trades_per_block, key=lambda x: x[1], reverse=True)[:10]

    print(f"\nTop 10 largest block clusters:")
    for block, count in top_clusters:
        trades = block_clusters[block]
        # Get unique slugs in this block
        slugs = set(t["slug"] for t in trades)
        usdc = sum(t.get("usdc_amount", 0) for t in trades)
        print(f"  Block {block}: {count} trades, {len(slugs)} markets, ${usdc:,.2f}")


def analyze_price_by_timing(analysis: Dict):
    """Analyze entry prices by timing."""
    timing_data = analysis["timing_data"]

    print("\n" + "="*70)
    print("ENTRY PRICE BY TIMING")
    print("="*70)

    # Group by timing bucket
    timing_buckets = {
        "Final 30s": lambda t: 0 <= t["time_to_close"] < 30,
        "30-60s": lambda t: 30 <= t["time_to_close"] < 60,
        "1-5min": lambda t: 60 <= t["time_to_close"] < 300,
        "5-10min": lambda t: 300 <= t["time_to_close"] < 600,
        "10-15min": lambda t: 600 <= t["time_to_close"] <= 900,
    }

    print(f"\nAverage entry price by timing:")
    print(f"Timing Bucket | Count | Avg Price | Low (<$0.30) | Mid ($0.30-0.70) | High (>$0.70)")
    print("-" * 90)

    for name, condition in timing_buckets.items():
        matching = [t for t in timing_data if condition(t)]
        if matching:
            prices = [t["price"] for t in matching if t.get("price")]
            if prices:
                avg_price = statistics.mean(prices)
                low = sum(1 for p in prices if p < 0.30)
                mid = sum(1 for p in prices if 0.30 <= p <= 0.70)
                high = sum(1 for p in prices if p > 0.70)

                low_pct = 100 * low / len(prices)
                mid_pct = 100 * mid / len(prices)
                high_pct = 100 * high / len(prices)

                print(f"  {name:12s} | {len(matching):7,} | ${avg_price:.3f}    | {low_pct:5.1f}%       | {mid_pct:5.1f}%           | {high_pct:5.1f}%")


def main():
    """Run the subsecond timing analysis."""
    project_root = Path(__file__).parent.parent.parent

    trades_file = project_root / "data" / "account88888_trades_joined.json"
    mapping_file = project_root / "data" / "token_to_market.json"

    print("="*70)
    print("SUBSECOND TIMING ANALYZER - Account88888")
    print("="*70)

    # Load data
    metadata, trades = load_trades(trades_file)
    token_mapping = load_token_mapping(mapping_file)

    # Run analysis
    analysis = analyze_timing(trades, token_mapping)

    # Print results
    print_timing_distribution(analysis)
    print_minute_distribution(analysis)
    analyze_final_seconds(analysis)
    analyze_block_clusters(analysis)
    analyze_price_by_timing(analysis)

    # Summary
    print("\n" + "="*70)
    print("KEY FINDINGS")
    print("="*70)

    stats = analysis["stats"]
    timing_data = analysis["timing_data"]

    if timing_data:
        time_to_close = [t["time_to_close"] for t in timing_data if t.get("time_to_close") is not None]

        if time_to_close:
            # Trades before vs after resolution
            before = sum(1 for t in time_to_close if t > 0)
            after = sum(1 for t in time_to_close if t <= 0)

            print(f"\n1. TIMING RELATIVE TO WINDOW END (RESOLUTION):")
            print(f"   Trades BEFORE window end: {before:,} ({100*before/len(time_to_close):.1f}%)")
            print(f"   Trades AFTER window end: {after:,} ({100*after/len(time_to_close):.1f}%)")

            # Average timing for trades before close
            if before > 0:
                avg = statistics.mean([t for t in time_to_close if t > 0])
                print(f"\n2. AVERAGE TIMING (trades during window):")
                print(f"   {avg:.1f} seconds ({avg/60:.1f} minutes) before window close")

                # Final minute activity
                final_60 = sum(1 for t in time_to_close if 0 < t <= 60)
                final_30 = sum(1 for t in time_to_close if 0 < t <= 30)
                final_10 = sum(1 for t in time_to_close if 0 < t <= 10)

                print(f"\n3. FINAL MINUTE ACTIVITY:")
                print(f"   Final 60 seconds: {final_60:,} trades ({100*final_60/before:.1f}% of in-window trades)")
                print(f"   Final 30 seconds: {final_30:,} trades ({100*final_30/before:.1f}% of in-window trades)")
                print(f"   Final 10 seconds: {final_10:,} trades ({100*final_10/before:.1f}% of in-window trades)")

                # By 5-minute buckets
                first_5 = sum(1 for t in time_to_close if t > 600)  # 600-900s to close = first 5 min
                middle_5 = sum(1 for t in time_to_close if 300 < t <= 600)
                last_5 = sum(1 for t in time_to_close if 0 < t <= 300)

                print(f"\n4. TIMING DISTRIBUTION:")
                print(f"   First 5 minutes:  {first_5:,} ({100*first_5/before:.1f}%)")
                print(f"   Middle 5 minutes: {middle_5:,} ({100*middle_5/before:.1f}%)")
                print(f"   Last 5 minutes:   {last_5:,} ({100*last_5/before:.1f}%)")
            else:
                print("\n2. No trades during window found")

    print("\n" + "="*70)


if __name__ == "__main__":
    main()
