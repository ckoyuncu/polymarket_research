#!/usr/bin/env python3
"""
Parse final_minute JSON files into a format suitable for backtesting
a delta-neutral maker rebates strategy.

Reads all JSON files from the research_ec2_jan6/final_minute directory
and outputs consolidated backtest data.
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
import statistics


# Source data directory
SOURCE_DIR = Path("/Users/shem/Desktop/polymarket_starter/polymarket_starter/archive/polymarket/small_sample_data/research_ec2_jan6/final_minute")
OUTPUT_FILE = Path("/Users/shem/Desktop/polymarket_research/data/backtest_data.json")


def determine_outcome(start_price: float, end_price: float) -> str:
    """Determine the outcome based on price movement."""
    if end_price >= start_price:
        return "UP"
    return "DOWN"


def process_orderbook_snapshots(snapshots: list) -> dict:
    """
    Process orderbook snapshots to extract useful trading data.

    Returns:
        dict with processed orderbook info including:
        - combined_snapshots: list of combined up/down snapshots by timestamp
        - avg_spread: average spread when available
        - yes_prices: list of YES (UP) prices
        - no_prices: list of NO (DOWN) prices
    """
    # Group snapshots by timestamp
    by_timestamp = defaultdict(dict)

    for snap in snapshots:
        ts = snap["timestamp"]
        outcome = snap.get("outcome", "unknown")
        by_timestamp[ts][outcome] = snap

    combined_snapshots = []
    spreads = []
    yes_prices = []  # UP outcome prices
    no_prices = []   # DOWN outcome prices

    for ts, outcomes in sorted(by_timestamp.items()):
        up_snap = outcomes.get("up", {})
        down_snap = outcomes.get("down", {})

        # UP token: best_bid = price someone will buy UP at
        # DOWN token: best_bid = price someone will buy DOWN at
        up_bid = up_snap.get("best_bid")
        up_ask = up_snap.get("best_ask")
        down_bid = down_snap.get("best_bid")
        down_ask = down_snap.get("best_ask")

        # Calculate combined spread
        # In a delta-neutral strategy, we care about the spread on both sides
        up_spread = None
        down_spread = None

        if up_bid is not None and up_ask is not None:
            up_spread = up_ask - up_bid
        if down_bid is not None and down_ask is not None:
            down_spread = down_ask - down_bid

        # Track YES (UP) mid price
        if up_bid is not None and up_ask is not None:
            yes_mid = (up_bid + up_ask) / 2
            yes_prices.append(yes_mid)
        elif up_bid is not None:
            yes_prices.append(up_bid)
        elif up_ask is not None:
            yes_prices.append(up_ask)

        # Track NO (DOWN) mid price
        if down_bid is not None and down_ask is not None:
            no_mid = (down_bid + down_ask) / 2
            no_prices.append(no_mid)
        elif down_bid is not None:
            no_prices.append(down_bid)
        elif down_ask is not None:
            no_prices.append(down_ask)

        combined = {
            "timestamp": ts,
            "up_best_bid": up_bid,
            "up_best_ask": up_ask,
            "up_bid_depth": up_snap.get("bid_depth", 0),
            "up_ask_depth": up_snap.get("ask_depth", 0),
            "down_best_bid": down_bid,
            "down_best_ask": down_ask,
            "down_bid_depth": down_snap.get("bid_depth", 0),
            "down_ask_depth": down_snap.get("ask_depth", 0),
        }

        # Calculate effective spread for delta-neutral trading
        # We need to buy/sell both YES and NO tokens
        if up_spread is not None and down_spread is not None:
            combined["up_spread"] = up_spread
            combined["down_spread"] = down_spread
            combined["total_spread"] = up_spread + down_spread
            spreads.append(up_spread + down_spread)

        combined_snapshots.append(combined)

    return {
        "combined_snapshots": combined_snapshots,
        "avg_spread": statistics.mean(spreads) if spreads else None,
        "spreads": spreads,
        "yes_prices": yes_prices,
        "no_prices": no_prices,
    }


def parse_single_file(filepath: Path) -> dict:
    """Parse a single final_minute JSON file."""
    with open(filepath, "r") as f:
        data = json.load(f)

    # Extract basic info
    asset = data.get("asset", "UNKNOWN")
    slug = data.get("slug", "")
    window_start = data.get("window_start")
    window_end = data.get("window_end")
    start_price = data.get("start_price")
    end_price = data.get("end_price")

    # Determine outcome
    outcome = determine_outcome(start_price, end_price) if start_price and end_price else None

    # Process Binance prices
    binance_prices = data.get("binance_prices", [])
    binance_price_series = [
        {"timestamp": p["timestamp"], "price": p["price"]}
        for p in binance_prices
    ]

    # Process orderbook snapshots
    orderbook_data = process_orderbook_snapshots(data.get("orderbook_snapshots", []))

    # Get typical spread at entry (first few snapshots)
    early_spreads = orderbook_data["spreads"][:5] if orderbook_data["spreads"] else []
    spread_at_entry = statistics.mean(early_spreads) if early_spreads else None

    # Get typical YES/NO prices
    yes_price = statistics.mean(orderbook_data["yes_prices"]) if orderbook_data["yes_prices"] else None
    no_price = statistics.mean(orderbook_data["no_prices"]) if orderbook_data["no_prices"] else None

    return {
        "market_id": slug,
        "asset": asset,
        "window_start": window_start,
        "window_end": window_end,
        "binance_start_price": start_price,
        "binance_end_price": end_price,
        "outcome": outcome,
        "orderbook_snapshots": orderbook_data["combined_snapshots"],
        "spread_at_entry": spread_at_entry,
        "avg_spread": orderbook_data["avg_spread"],
        "yes_price": yes_price,
        "no_price": no_price,
        "binance_price_series": binance_price_series,
        "snapshot_count": len(orderbook_data["combined_snapshots"]),
        "binance_price_count": len(binance_prices),
    }


def parse_all_files() -> tuple:
    """
    Parse all final_minute JSON files.

    Returns:
        tuple: (list of parsed records, statistics dict)
    """
    json_files = sorted(SOURCE_DIR.glob("*.json"))

    print(f"Found {len(json_files)} JSON files to parse")
    print(f"Source directory: {SOURCE_DIR}")
    print()

    records = []
    stats = {
        "total_files": len(json_files),
        "btc_count": 0,
        "eth_count": 0,
        "up_outcomes": 0,
        "down_outcomes": 0,
        "spreads": [],
        "data_quality_issues": [],
        "windows_with_spread_data": 0,
        "windows_without_spread_data": 0,
    }

    for filepath in json_files:
        try:
            record = parse_single_file(filepath)
            records.append(record)

            # Update statistics
            if record["asset"] == "BTC":
                stats["btc_count"] += 1
            elif record["asset"] == "ETH":
                stats["eth_count"] += 1

            if record["outcome"] == "UP":
                stats["up_outcomes"] += 1
            elif record["outcome"] == "DOWN":
                stats["down_outcomes"] += 1

            if record["avg_spread"] is not None:
                stats["spreads"].append(record["avg_spread"])
                stats["windows_with_spread_data"] += 1
            else:
                stats["windows_without_spread_data"] += 1

            # Check for data quality issues
            if record["snapshot_count"] == 0:
                stats["data_quality_issues"].append(f"{filepath.name}: No orderbook snapshots")
            if record["binance_price_count"] == 0:
                stats["data_quality_issues"].append(f"{filepath.name}: No Binance prices")
            if record["spread_at_entry"] is None:
                stats["data_quality_issues"].append(f"{filepath.name}: Could not calculate spread at entry")

        except Exception as e:
            stats["data_quality_issues"].append(f"{filepath.name}: Parse error - {str(e)}")
            print(f"Error parsing {filepath.name}: {e}")

    # Compute spread statistics
    if stats["spreads"]:
        stats["avg_spread_overall"] = statistics.mean(stats["spreads"])
        stats["median_spread"] = statistics.median(stats["spreads"])
        stats["min_spread"] = min(stats["spreads"])
        stats["max_spread"] = max(stats["spreads"])

    return records, stats


def main():
    """Main entry point."""
    print("=" * 60)
    print("Final Minute Data Parser for Delta-Neutral Maker Strategy")
    print("=" * 60)
    print()

    # Parse all files
    records, stats = parse_all_files()

    # Save output
    output_data = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_directory": str(SOURCE_DIR),
            "total_windows": len(records),
        },
        "statistics": {
            "total_files_parsed": stats["total_files"],
            "btc_windows": stats["btc_count"],
            "eth_windows": stats["eth_count"],
            "up_outcomes": stats["up_outcomes"],
            "down_outcomes": stats["down_outcomes"],
            "avg_spread": stats.get("avg_spread_overall"),
            "median_spread": stats.get("median_spread"),
            "min_spread": stats.get("min_spread"),
            "max_spread": stats.get("max_spread"),
            "windows_with_spread_data": stats["windows_with_spread_data"],
            "windows_without_spread_data": stats["windows_without_spread_data"],
            "data_quality_issues_count": len(stats["data_quality_issues"]),
        },
        "windows": records,
    }

    # Ensure output directory exists
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"Output saved to: {OUTPUT_FILE}")
    print()

    # Print statistics report
    print("=" * 60)
    print("PARSING STATISTICS")
    print("=" * 60)
    print()
    print(f"Total markets parsed: {stats['total_files']}")
    print(f"Total 15-min windows: {len(records)}")
    print()
    print("ASSET BREAKDOWN:")
    print(f"  BTC windows: {stats['btc_count']}")
    print(f"  ETH windows: {stats['eth_count']}")
    print()
    print("OUTCOME DISTRIBUTION:")
    print(f"  UP outcomes:   {stats['up_outcomes']} ({stats['up_outcomes']/len(records)*100:.1f}%)")
    print(f"  DOWN outcomes: {stats['down_outcomes']} ({stats['down_outcomes']/len(records)*100:.1f}%)")
    print()
    print("ORDERBOOK DATA AVAILABILITY:")
    print(f"  Windows with spread data:    {stats['windows_with_spread_data']} ({stats['windows_with_spread_data']/len(records)*100:.1f}%)")
    print(f"  Windows without spread data: {stats['windows_without_spread_data']} ({stats['windows_without_spread_data']/len(records)*100:.1f}%)")
    print("  (Missing spread = one-sided orderbook, common in final minute before resolution)")
    print()
    print("SPREAD STATISTICS (when available):")
    if stats.get("avg_spread_overall"):
        print(f"  Average spread: {stats['avg_spread_overall']:.4f} (${stats['avg_spread_overall']*100:.2f} per $100 notional)")
        print(f"  Median spread:  {stats.get('median_spread'):.4f}")
        print(f"  Min spread:     {stats.get('min_spread'):.4f}")
        print(f"  Max spread:     {stats.get('max_spread'):.4f}")
        print("  NOTE: Spread ~0.98 means bid=0.01, ask=0.99 (very wide, typical for illiquid markets)")
    else:
        print("  No spread data available (all orderbooks were one-sided)")
    print()
    print("DATA QUALITY ISSUES:")
    if stats["data_quality_issues"]:
        print(f"  Total issues: {len(stats['data_quality_issues'])}")
        # Group by issue type
        issue_types = defaultdict(int)
        for issue in stats["data_quality_issues"]:
            if "No orderbook snapshots" in issue:
                issue_types["No orderbook snapshots"] += 1
            elif "No Binance prices" in issue:
                issue_types["No Binance prices"] += 1
            elif "Could not calculate spread" in issue:
                issue_types["Could not calculate spread at entry"] += 1
            elif "Parse error" in issue:
                issue_types["Parse errors"] += 1
        for issue_type, count in issue_types.items():
            print(f"    - {issue_type}: {count}")
    else:
        print("  No issues found!")
    print()
    print("=" * 60)

    return output_data


if __name__ == "__main__":
    main()
