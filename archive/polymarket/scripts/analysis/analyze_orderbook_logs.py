#!/usr/bin/env python3
"""
Order Book Log Analyzer

Parses and analyzes Polymarket order book logs captured from EC2 instances.
Used to understand order book patterns and correlate with Account88888's trades.

Usage:
    python scripts/analysis/analyze_orderbook_logs.py
    python scripts/analysis/analyze_orderbook_logs.py --market eth-updown-15m-1767648600
    python scripts/analysis/analyze_orderbook_logs.py --time-range 1767644000 1767645000
"""

import argparse
import gzip
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def load_orderbook_logs(log_dir: str, hours: Optional[List[int]] = None) -> List[dict]:
    """Load order book logs from directory."""
    records = []
    log_path = Path(log_dir)

    # Find all log files
    files = list(log_path.glob("polymarket_books_*.jsonl*"))
    files.sort()

    for file_path in files:
        # Filter by hour if specified
        if hours:
            hour_str = file_path.stem.split("_")[-1].replace(".jsonl", "")
            try:
                hour = int(hour_str)
                if hour not in hours:
                    continue
            except ValueError:
                pass

        print(f"Loading {file_path.name}...")

        opener = gzip.open if file_path.suffix == ".gz" else open
        mode = "rt" if file_path.suffix == ".gz" else "r"

        with opener(file_path, mode) as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    records.append(record)
                except json.JSONDecodeError:
                    continue

    return records


def analyze_market_coverage(records: List[dict]) -> Dict[str, dict]:
    """Analyze which markets are covered in the logs."""
    markets = defaultdict(lambda: {
        "count": 0,
        "first_ts": float("inf"),
        "last_ts": 0,
        "token_ids": set()
    })

    for r in records:
        slug = r.get("slug", "unknown")
        ts = r.get("ts_received", 0)
        token_id = r.get("token_id", "")

        markets[slug]["count"] += 1
        markets[slug]["first_ts"] = min(markets[slug]["first_ts"], ts)
        markets[slug]["last_ts"] = max(markets[slug]["last_ts"], ts)
        markets[slug]["token_ids"].add(token_id)

    # Convert sets to counts for JSON serialization
    for slug in markets:
        markets[slug]["token_ids"] = len(markets[slug]["token_ids"])
        if markets[slug]["first_ts"] < float("inf"):
            markets[slug]["first_dt"] = datetime.fromtimestamp(
                markets[slug]["first_ts"] / 1000, tz=timezone.utc
            ).isoformat()
            markets[slug]["last_dt"] = datetime.fromtimestamp(
                markets[slug]["last_ts"] / 1000, tz=timezone.utc
            ).isoformat()

    return dict(markets)


def analyze_time_coverage(records: List[dict]) -> dict:
    """Analyze time coverage of the logs."""
    if not records:
        return {}

    timestamps = [r.get("ts_received", 0) for r in records]
    min_ts = min(timestamps)
    max_ts = max(timestamps)

    # Calculate gaps (periods > 5 seconds without data)
    timestamps.sort()
    gaps = []
    for i in range(1, len(timestamps)):
        gap = timestamps[i] - timestamps[i-1]
        if gap > 5000:  # 5 second gap
            gaps.append({
                "start": timestamps[i-1],
                "end": timestamps[i],
                "duration_sec": gap / 1000
            })

    return {
        "total_records": len(records),
        "start_ts": min_ts,
        "end_ts": max_ts,
        "start_dt": datetime.fromtimestamp(min_ts / 1000, tz=timezone.utc).isoformat(),
        "end_dt": datetime.fromtimestamp(max_ts / 1000, tz=timezone.utc).isoformat(),
        "duration_sec": (max_ts - min_ts) / 1000,
        "avg_interval_ms": (max_ts - min_ts) / len(records) if records else 0,
        "gaps_over_5sec": len(gaps),
        "largest_gap_sec": max([g["duration_sec"] for g in gaps]) if gaps else 0
    }


def analyze_spread_distribution(records: List[dict]) -> dict:
    """Analyze bid-ask spread distribution."""
    spreads = [r.get("spread", 0) for r in records if "spread" in r]

    if not spreads:
        return {}

    spreads.sort()
    n = len(spreads)

    return {
        "count": n,
        "min": spreads[0],
        "max": spreads[-1],
        "median": spreads[n // 2],
        "p10": spreads[n // 10],
        "p90": spreads[9 * n // 10],
        "avg": sum(spreads) / n
    }


def analyze_imbalance_distribution(records: List[dict]) -> dict:
    """Analyze bid/ask depth imbalance distribution."""
    imbalances = []

    for r in records:
        bid_depth = r.get("bid_depth", 0)
        ask_depth = r.get("ask_depth", 0)
        total = bid_depth + ask_depth
        if total > 0:
            # Positive = more bids, negative = more asks
            imbalance = (bid_depth - ask_depth) / total
            imbalances.append(imbalance)

    if not imbalances:
        return {}

    imbalances.sort()
    n = len(imbalances)

    # Count strongly imbalanced snapshots
    strong_bid = sum(1 for i in imbalances if i > 0.3)
    strong_ask = sum(1 for i in imbalances if i < -0.3)

    return {
        "count": n,
        "min": imbalances[0],
        "max": imbalances[-1],
        "median": imbalances[n // 2],
        "p10": imbalances[n // 10],
        "p90": imbalances[9 * n // 10],
        "avg": sum(imbalances) / n,
        "strong_bid_side": strong_bid,
        "strong_ask_side": strong_ask,
        "strong_imbalance_pct": (strong_bid + strong_ask) / n * 100
    }


def get_orderbook_at_time(records: List[dict], target_ts: int, market_slug: Optional[str] = None) -> List[dict]:
    """Get order book snapshots closest to a specific timestamp."""
    # Filter by market if specified
    if market_slug:
        records = [r for r in records if r.get("slug") == market_slug]

    # Find records within 5 seconds of target
    window_ms = 5000
    nearby = [r for r in records if abs(r.get("ts_received", 0) - target_ts) <= window_ms]

    # Sort by proximity to target
    nearby.sort(key=lambda r: abs(r.get("ts_received", 0) - target_ts))

    return nearby[:10]  # Return up to 10 closest


def analyze_final_30_seconds(records: List[dict]) -> dict:
    """Analyze order book patterns in the final 30 seconds before market close."""
    # Group by market slug (which contains resolution timestamp)
    markets = defaultdict(list)
    for r in records:
        slug = r.get("slug", "")
        if slug:
            markets[slug].append(r)

    results = []

    for slug, market_records in markets.items():
        # Extract resolution timestamp from slug (format: xxx-15m-{timestamp})
        try:
            resolution_ts = int(slug.split("-")[-1]) * 1000  # Convert to ms
        except (ValueError, IndexError):
            continue

        # Find records in final 30 seconds
        final_30s = [
            r for r in market_records
            if resolution_ts - 30000 <= r.get("ts_received", 0) <= resolution_ts
        ]

        if len(final_30s) < 5:
            continue

        # Analyze imbalance trend in final 30 seconds
        final_30s.sort(key=lambda r: r.get("ts_received", 0))

        imbalances = []
        for r in final_30s:
            bid_depth = r.get("bid_depth", 0)
            ask_depth = r.get("ask_depth", 0)
            total = bid_depth + ask_depth
            if total > 0:
                imbalances.append((bid_depth - ask_depth) / total)

        if imbalances:
            first_half = imbalances[:len(imbalances)//2]
            second_half = imbalances[len(imbalances)//2:]

            results.append({
                "slug": slug,
                "resolution_ts": resolution_ts,
                "records_in_final_30s": len(final_30s),
                "avg_imbalance_first_15s": sum(first_half) / len(first_half) if first_half else 0,
                "avg_imbalance_last_15s": sum(second_half) / len(second_half) if second_half else 0,
                "imbalance_trend": (sum(second_half) / len(second_half) - sum(first_half) / len(first_half)) if first_half and second_half else 0
            })

    return {
        "markets_analyzed": len(results),
        "details": results
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze Order Book Logs")
    parser.add_argument(
        "--log-dir",
        type=str,
        default="data/orderbook_logs",
        help="Directory containing order book logs"
    )
    parser.add_argument(
        "--region",
        type=str,
        choices=["tokyo", "us_east", "all"],
        default="all",
        help="Region to analyze"
    )
    parser.add_argument(
        "--market",
        type=str,
        help="Filter to specific market slug"
    )
    parser.add_argument(
        "--time",
        type=int,
        help="Get order book at specific Unix timestamp (ms)"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for analysis results (JSON)"
    )

    args = parser.parse_args()

    # Determine directories to load
    base_dir = Path(args.log_dir)
    if args.region == "all":
        dirs = [base_dir / "tokyo", base_dir / "us_east"]
    else:
        dirs = [base_dir / args.region]

    # Load all records
    all_records = []
    for d in dirs:
        if d.exists():
            print(f"\n=== Loading from {d} ===")
            records = load_orderbook_logs(str(d))
            print(f"Loaded {len(records):,} records")
            all_records.extend(records)

    if not all_records:
        print("No records found!")
        return

    print(f"\nTotal records: {len(all_records):,}")

    # If specific time requested, show order book at that time
    if args.time:
        print(f"\n=== Order Book at {args.time} ===")
        nearby = get_orderbook_at_time(all_records, args.time, args.market)
        for r in nearby:
            dt = datetime.fromtimestamp(r["ts_received"] / 1000, tz=timezone.utc)
            print(f"  {dt.strftime('%H:%M:%S.%f')[:-3]} | "
                  f"bid={r.get('best_bid', 0):.2f} ask={r.get('best_ask', 0):.2f} | "
                  f"depth: {r.get('bid_depth', 0)}/{r.get('ask_depth', 0)} | "
                  f"{r.get('slug', 'unknown')}")
        return

    # Run full analysis
    results = {}

    print("\n=== Time Coverage ===")
    time_cov = analyze_time_coverage(all_records)
    results["time_coverage"] = time_cov
    print(f"  Duration: {time_cov.get('duration_sec', 0):.0f} seconds")
    print(f"  Records: {time_cov.get('total_records', 0):,}")
    print(f"  Avg interval: {time_cov.get('avg_interval_ms', 0):.1f}ms")
    print(f"  Gaps > 5s: {time_cov.get('gaps_over_5sec', 0)}")

    print("\n=== Market Coverage ===")
    market_cov = analyze_market_coverage(all_records)
    results["market_coverage"] = market_cov
    for slug, info in sorted(market_cov.items(), key=lambda x: -x[1]["count"])[:10]:
        print(f"  {slug}: {info['count']:,} records, {info['token_ids']} tokens")

    print("\n=== Spread Distribution ===")
    spread_dist = analyze_spread_distribution(all_records)
    results["spread_distribution"] = spread_dist
    print(f"  Median: {spread_dist.get('median', 0):.4f}")
    print(f"  P10-P90: {spread_dist.get('p10', 0):.4f} - {spread_dist.get('p90', 0):.4f}")

    print("\n=== Imbalance Distribution ===")
    imbalance_dist = analyze_imbalance_distribution(all_records)
    results["imbalance_distribution"] = imbalance_dist
    print(f"  Median: {imbalance_dist.get('median', 0):.3f}")
    print(f"  P10-P90: {imbalance_dist.get('p10', 0):.3f} - {imbalance_dist.get('p90', 0):.3f}")
    print(f"  Strong imbalance: {imbalance_dist.get('strong_imbalance_pct', 0):.1f}%")

    print("\n=== Final 30 Seconds Analysis ===")
    final_30s = analyze_final_30_seconds(all_records)
    results["final_30_seconds"] = final_30s
    print(f"  Markets analyzed: {final_30s.get('markets_analyzed', 0)}")

    for detail in final_30s.get("details", [])[:5]:
        print(f"    {detail['slug']}: "
              f"trend={detail['imbalance_trend']:.3f} "
              f"({detail['records_in_final_30s']} records)")

    # Save results if output specified
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
