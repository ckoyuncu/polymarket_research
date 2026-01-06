#!/usr/bin/env python3
"""
Correlate Account88888 Trades with Order Book State

This script correlates Account88888's trades from the tracker database
with order book snapshots captured at the same time.

Goal: Understand what order book signals might be driving trade decisions.

Usage:
    python scripts/analysis/correlate_trades_orderbook.py
    python scripts/analysis/correlate_trades_orderbook.py --output reports/trade_orderbook_correlation.json
"""

import argparse
import gzip
import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_trades_from_tracker(db_path: str) -> List[dict]:
    """Load trades from the tracker SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM trades
        WHERE slug IS NOT NULL
        ORDER BY timestamp DESC
    """)

    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return trades


def load_orderbook_logs(log_dir: str) -> Dict[str, List[dict]]:
    """Load order book logs indexed by market slug."""
    records_by_slug = defaultdict(list)
    log_path = Path(log_dir)

    for subdir in ["tokyo", "us_east"]:
        dir_path = log_path / subdir
        if not dir_path.exists():
            continue

        for file_path in dir_path.glob("polymarket_books_*.jsonl*"):
            opener = gzip.open if file_path.suffix == ".gz" else open
            mode = "rt" if file_path.suffix == ".gz" else "r"

            with opener(file_path, mode) as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        slug = record.get("slug", "")
                        if slug:
                            records_by_slug[slug].append(record)
                    except json.JSONDecodeError:
                        continue

    # Sort each market's records by timestamp
    for slug in records_by_slug:
        records_by_slug[slug].sort(key=lambda r: r.get("ts_received", 0))

    return dict(records_by_slug)


def find_orderbook_at_trade(
    trade_ts_ms: int,
    orderbook_records: List[dict],
    window_ms: int = 5000
) -> Optional[dict]:
    """Find the order book snapshot closest to trade time."""
    if not orderbook_records:
        return None

    # Binary search for closest record
    target = trade_ts_ms
    left, right = 0, len(orderbook_records) - 1

    while left < right:
        mid = (left + right) // 2
        if orderbook_records[mid].get("ts_received", 0) < target:
            left = mid + 1
        else:
            right = mid

    # Check if within window
    closest = orderbook_records[left]
    if abs(closest.get("ts_received", 0) - target) <= window_ms:
        return closest

    # Check neighbor
    if left > 0:
        prev = orderbook_records[left - 1]
        if abs(prev.get("ts_received", 0) - target) < abs(closest.get("ts_received", 0) - target):
            closest = prev

    if abs(closest.get("ts_received", 0) - target) <= window_ms:
        return closest

    return None


def calculate_imbalance(orderbook: dict) -> float:
    """Calculate bid/ask depth imbalance."""
    bid_depth = orderbook.get("bid_depth", 0)
    ask_depth = orderbook.get("ask_depth", 0)
    total = bid_depth + ask_depth
    if total == 0:
        return 0.0
    return (bid_depth - ask_depth) / total


def correlate_trade_with_orderbook(
    trade: dict,
    orderbook_records: List[dict]
) -> Optional[dict]:
    """Correlate a single trade with order book state."""
    trade_ts_ms = trade["timestamp"] * 1000  # Convert to ms

    # Find order book at trade time
    ob_at_trade = find_orderbook_at_trade(trade_ts_ms, orderbook_records)

    if not ob_at_trade:
        return None

    # Calculate metrics
    imbalance = calculate_imbalance(ob_at_trade)

    # Determine if trade aligned with imbalance
    # Positive imbalance = more bids = bullish pressure
    # If trading UP and imbalance negative = mean reversion (contrarian)
    # If trading UP and imbalance positive = momentum (following)
    is_up_trade = trade.get("outcome") == "UP"
    is_mean_reversion = (is_up_trade and imbalance < -0.1) or (not is_up_trade and imbalance > 0.1)
    is_momentum = (is_up_trade and imbalance > 0.1) or (not is_up_trade and imbalance < -0.1)

    return {
        "trade_ts": trade["timestamp"],
        "trade_time": datetime.fromtimestamp(trade["timestamp"], tz=timezone.utc).isoformat(),
        "slug": trade["slug"],
        "asset": trade.get("asset"),
        "outcome": trade.get("outcome"),
        "side": trade.get("side"),
        "price": trade.get("price"),
        "size": trade.get("size"),
        "seconds_until_close": trade.get("seconds_until_close"),
        "binance_btc": trade.get("binance_btc"),
        "binance_eth": trade.get("binance_eth"),

        # Order book state
        "ob_ts": ob_at_trade.get("ts_received"),
        "ob_latency_ms": ob_at_trade.get("ts_received", 0) - trade_ts_ms,
        "best_bid": ob_at_trade.get("best_bid"),
        "best_ask": ob_at_trade.get("best_ask"),
        "spread": ob_at_trade.get("spread"),
        "bid_depth": ob_at_trade.get("bid_depth"),
        "ask_depth": ob_at_trade.get("ask_depth"),

        # Derived metrics
        "imbalance": imbalance,
        "is_mean_reversion": is_mean_reversion,
        "is_momentum": is_momentum,
    }


def analyze_correlations(correlations: List[dict]) -> dict:
    """Analyze patterns in trade-orderbook correlations."""
    if not correlations:
        return {}

    # Count mean reversion vs momentum
    mean_reversion = sum(1 for c in correlations if c.get("is_mean_reversion"))
    momentum = sum(1 for c in correlations if c.get("is_momentum"))
    neutral = len(correlations) - mean_reversion - momentum

    # Imbalance distribution at trade time
    imbalances = [c.get("imbalance", 0) for c in correlations]
    imbalances.sort()
    n = len(imbalances)

    # Timing distribution
    seconds_to_close = [c.get("seconds_until_close", 0) for c in correlations if c.get("seconds_until_close")]
    seconds_to_close.sort()
    timing_n = len(seconds_to_close)

    # By asset
    by_asset = defaultdict(lambda: {"count": 0, "mean_reversion": 0, "momentum": 0})
    for c in correlations:
        asset = c.get("asset", "UNKNOWN")
        by_asset[asset]["count"] += 1
        if c.get("is_mean_reversion"):
            by_asset[asset]["mean_reversion"] += 1
        if c.get("is_momentum"):
            by_asset[asset]["momentum"] += 1

    return {
        "total_correlations": len(correlations),
        "mean_reversion_trades": mean_reversion,
        "momentum_trades": momentum,
        "neutral_trades": neutral,
        "mean_reversion_pct": mean_reversion / len(correlations) * 100 if correlations else 0,
        "momentum_pct": momentum / len(correlations) * 100 if correlations else 0,

        "imbalance_stats": {
            "min": imbalances[0] if imbalances else 0,
            "max": imbalances[-1] if imbalances else 0,
            "median": imbalances[n // 2] if imbalances else 0,
            "p10": imbalances[n // 10] if n >= 10 else (imbalances[0] if imbalances else 0),
            "p90": imbalances[9 * n // 10] if n >= 10 else (imbalances[-1] if imbalances else 0),
        },

        "timing_stats": {
            "min_seconds": seconds_to_close[0] if seconds_to_close else 0,
            "max_seconds": seconds_to_close[-1] if seconds_to_close else 0,
            "median_seconds": seconds_to_close[timing_n // 2] if seconds_to_close else 0,
        },

        "by_asset": dict(by_asset),
    }


def main():
    parser = argparse.ArgumentParser(description="Correlate Trades with Order Book")
    parser.add_argument(
        "--trades-db",
        type=str,
        default="data/tracker/trades.db",
        help="Path to tracker database"
    )
    parser.add_argument(
        "--orderbook-dir",
        type=str,
        default="data/orderbook_logs",
        help="Directory containing order book logs"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for correlation results (JSON)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max trades to correlate"
    )

    args = parser.parse_args()

    # Load data
    print("Loading trades from tracker database...")
    trades = load_trades_from_tracker(args.trades_db)
    print(f"  Loaded {len(trades):,} trades")

    print("\nLoading order book logs...")
    orderbooks = load_orderbook_logs(args.orderbook_dir)
    total_records = sum(len(v) for v in orderbooks.values())
    print(f"  Loaded {total_records:,} records across {len(orderbooks)} markets")

    # Find overlapping data
    trade_slugs = set(t.get("slug") for t in trades if t.get("slug"))
    ob_slugs = set(orderbooks.keys())
    overlap = trade_slugs & ob_slugs
    print(f"\n  Trade markets: {len(trade_slugs)}")
    print(f"  Order book markets: {len(ob_slugs)}")
    print(f"  Overlapping markets: {len(overlap)}")

    # Correlate trades with order books
    print("\nCorrelating trades with order book state...")
    correlations = []

    for i, trade in enumerate(trades[:args.limit]):
        slug = trade.get("slug")
        if not slug or slug not in orderbooks:
            continue

        correlation = correlate_trade_with_orderbook(trade, orderbooks[slug])
        if correlation:
            correlations.append(correlation)

        if (i + 1) % 100 == 0:
            print(f"  Processed {i + 1} trades, {len(correlations)} correlated")

    print(f"\nSuccessfully correlated {len(correlations)} trades")

    # Analyze patterns
    print("\n=== Correlation Analysis ===")
    analysis = analyze_correlations(correlations)

    print(f"\nStrategy Pattern:")
    print(f"  Mean Reversion: {analysis.get('mean_reversion_trades', 0)} "
          f"({analysis.get('mean_reversion_pct', 0):.1f}%)")
    print(f"  Momentum: {analysis.get('momentum_trades', 0)} "
          f"({analysis.get('momentum_pct', 0):.1f}%)")
    print(f"  Neutral: {analysis.get('neutral_trades', 0)}")

    print(f"\nImbalance at Trade Time:")
    imb = analysis.get("imbalance_stats", {})
    print(f"  Median: {imb.get('median', 0):.3f}")
    print(f"  P10-P90: {imb.get('p10', 0):.3f} to {imb.get('p90', 0):.3f}")

    print(f"\nTiming (seconds before close):")
    timing = analysis.get("timing_stats", {})
    print(f"  Range: {timing.get('min_seconds', 0)} - {timing.get('max_seconds', 0)}")
    print(f"  Median: {timing.get('median_seconds', 0)}")

    print(f"\nBy Asset:")
    for asset, stats in analysis.get("by_asset", {}).items():
        mr_pct = stats["mean_reversion"] / stats["count"] * 100 if stats["count"] else 0
        print(f"  {asset}: {stats['count']} trades, {mr_pct:.1f}% mean reversion")

    # Save results
    if args.output:
        results = {
            "analysis": analysis,
            "correlations": correlations[:100],  # Save first 100 for review
            "summary": {
                "total_trades": len(trades),
                "correlated": len(correlations),
                "markets_with_overlap": len(overlap),
            }
        }
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
