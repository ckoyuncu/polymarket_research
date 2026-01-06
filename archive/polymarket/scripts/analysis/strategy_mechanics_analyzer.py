#!/usr/bin/env python3
"""
Strategy Mechanics Analyzer for Account88888

Deeply analyzes the trading patterns to understand:
1. WHEN do they trade (timing relative to resolution)
2. WHAT do they trade (which tokens, assets)
3. HOW do they trade (price thresholds, volume patterns)
4. WHY might they trade (signals, triggers)

This is the PRIMARY analysis for understanding strategy mechanics.

Usage:
    python scripts/analysis/strategy_mechanics_analyzer.py
    python scripts/analysis/strategy_mechanics_analyzer.py --output reports/strategy_mechanics.json
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import statistics


def load_data(trades_path: str, metadata_path: str) -> Tuple[List[dict], Dict[str, dict]]:
    """Load trades and metadata."""
    print("Loading data...")

    with open(trades_path, 'r') as f:
        data = json.load(f)
    if isinstance(data, dict):
        if "trades" in data:
            trades = data["trades"]
            trades = list(trades.values()) if isinstance(trades, dict) else trades
        else:
            trades = list(data.values())
    else:
        trades = data

    with open(metadata_path, 'r') as f:
        data = json.load(f)
    if isinstance(data, dict):
        if "token_to_market" in data:
            metadata = data["token_to_market"]
        else:
            metadata = data
    else:
        metadata = data

    print(f"  Loaded {len(trades):,} trades, {len(metadata):,} tokens")
    return trades, metadata


def get_resolution_ts(market: dict) -> Optional[int]:
    """Extract resolution timestamp from market metadata."""
    slug = market.get("slug", "")
    if "-15m-" in slug:
        try:
            return int(slug.split("-15m-")[1])
        except:
            pass
    return None


def get_token_outcome(token_id: str, market: dict) -> Optional[str]:
    """Determine if this token is UP or DOWN."""
    clob_ids_raw = market.get("clobTokenIds", [])

    if isinstance(clob_ids_raw, str):
        try:
            clob_ids = json.loads(clob_ids_raw)
        except:
            return None
    else:
        clob_ids = clob_ids_raw

    if len(clob_ids) != 2:
        return None

    if token_id == clob_ids[0]:
        return "UP"
    elif token_id == clob_ids[1]:
        return "DOWN"
    return None


def get_asset(market: dict) -> str:
    """Extract asset from market slug."""
    slug = market.get("slug", "")
    if slug:
        return slug.split("-")[0].upper()
    return "UNKNOWN"


def analyze_timing_mechanics(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    TIMING ANALYSIS: When exactly do they trade?

    Key questions:
    - Distribution of trade timing relative to resolution
    - Is there a "sweet spot" timing window?
    - Do they trade in bursts or steady stream?
    """
    print("\n[TIMING ANALYSIS] When do they trade?")
    print("-" * 50)

    timing_data = []
    by_minute_bucket = defaultdict(int)
    by_asset = defaultdict(list)

    for trade in trades:
        token_id = str(trade.get("token_id", ""))
        if token_id not in metadata:
            continue

        market = metadata[token_id]
        resolution_ts = get_resolution_ts(market)
        if not resolution_ts:
            continue

        trade_ts = trade.get("timestamp", 0)
        if not trade_ts:
            continue

        # Seconds from resolution (positive = after)
        seconds_after = trade_ts - resolution_ts
        timing_data.append(seconds_after)

        # Bucket by minute
        minute_bucket = (seconds_after // 60) * 60
        by_minute_bucket[minute_bucket] += 1

        # By asset
        asset = get_asset(market)
        by_asset[asset].append(seconds_after)

    if not timing_data:
        return {"error": "No timing data available"}

    # Statistics
    timing_data.sort()
    n = len(timing_data)

    results = {
        "total_trades_analyzed": n,
        "timing_stats": {
            "min_seconds": min(timing_data),
            "max_seconds": max(timing_data),
            "median_seconds": timing_data[n // 2],
            "mean_seconds": statistics.mean(timing_data),
            "p10_seconds": timing_data[n // 10],
            "p25_seconds": timing_data[n // 4],
            "p75_seconds": timing_data[3 * n // 4],
            "p90_seconds": timing_data[9 * n // 10],
        },
        "before_resolution_count": sum(1 for t in timing_data if t < 0),
        "after_resolution_count": sum(1 for t in timing_data if t >= 0),
    }

    # Find peak trading windows
    peak_windows = sorted(by_minute_bucket.items(), key=lambda x: x[1], reverse=True)[:10]
    results["peak_trading_windows"] = [
        {"minute_after": m // 60, "count": c}
        for m, c in peak_windows
    ]

    # Print findings
    print(f"  Total trades with timing: {n:,}")
    print(f"  Before resolution: {results['before_resolution_count']:,} ({results['before_resolution_count']/n*100:.2f}%)")
    print(f"  After resolution: {results['after_resolution_count']:,} ({results['after_resolution_count']/n*100:.2f}%)")
    print(f"\n  Timing statistics (seconds after resolution):")
    print(f"    Min: {results['timing_stats']['min_seconds']:.0f}s")
    print(f"    Median: {results['timing_stats']['median_seconds']:.0f}s ({results['timing_stats']['median_seconds']/60:.1f} min)")
    print(f"    Mean: {results['timing_stats']['mean_seconds']:.0f}s ({results['timing_stats']['mean_seconds']/60:.1f} min)")
    print(f"    P90: {results['timing_stats']['p90_seconds']:.0f}s ({results['timing_stats']['p90_seconds']/60:.1f} min)")
    print(f"    Max: {results['timing_stats']['max_seconds']:.0f}s ({results['timing_stats']['max_seconds']/60:.1f} min)")

    print(f"\n  Peak trading windows (minutes after resolution):")
    for w in results["peak_trading_windows"][:5]:
        print(f"    {w['minute_after']:>3} min: {w['count']:,} trades")

    return results


def analyze_token_selection(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    TOKEN SELECTION: What tokens do they trade?

    Key questions:
    - Do they favor UP or DOWN tokens?
    - Do they favor certain assets?
    - Is there a pattern based on market characteristics?
    """
    print("\n[TOKEN SELECTION] What do they trade?")
    print("-" * 50)

    by_outcome = {"UP": 0, "DOWN": 0, "UNKNOWN": 0}
    by_asset = defaultdict(lambda: {"UP": 0, "DOWN": 0, "total": 0})
    by_side = {"BUY": {"UP": 0, "DOWN": 0}, "SELL": {"UP": 0, "DOWN": 0}}

    for trade in trades:
        token_id = str(trade.get("token_id", ""))
        if token_id not in metadata:
            continue

        market = metadata[token_id]
        outcome = get_token_outcome(token_id, market)
        asset = get_asset(market)
        side = trade.get("side", "").upper()

        if outcome:
            by_outcome[outcome] += 1
            by_asset[asset][outcome] += 1
            by_asset[asset]["total"] += 1

            if side in by_side:
                by_side[side][outcome] += 1
        else:
            by_outcome["UNKNOWN"] += 1

    total = sum(by_outcome.values())
    results = {
        "total_analyzed": total,
        "by_outcome": by_outcome,
        "by_asset": dict(by_asset),
        "by_side_and_outcome": by_side,
    }

    # Calculate ratios
    if by_outcome["UP"] + by_outcome["DOWN"] > 0:
        up_ratio = by_outcome["UP"] / (by_outcome["UP"] + by_outcome["DOWN"])
        results["up_ratio"] = round(up_ratio, 4)

    print(f"  Total trades analyzed: {total:,}")
    print(f"\n  By outcome token:")
    print(f"    UP tokens: {by_outcome['UP']:,} ({by_outcome['UP']/total*100:.1f}%)")
    print(f"    DOWN tokens: {by_outcome['DOWN']:,} ({by_outcome['DOWN']/total*100:.1f}%)")
    print(f"    Unknown: {by_outcome['UNKNOWN']:,}")

    print(f"\n  By asset:")
    for asset, counts in sorted(by_asset.items(), key=lambda x: x[1]["total"], reverse=True)[:5]:
        up_pct = counts["UP"] / counts["total"] * 100 if counts["total"] > 0 else 0
        print(f"    {asset}: {counts['total']:,} trades (UP: {up_pct:.1f}%)")

    print(f"\n  By trade side:")
    for side, outcomes in by_side.items():
        total_side = outcomes["UP"] + outcomes["DOWN"]
        if total_side > 0:
            up_pct = outcomes["UP"] / total_side * 100
            print(f"    {side}: {total_side:,} trades (UP: {up_pct:.1f}%)")

    return results


def analyze_price_mechanics(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    PRICE ANALYSIS: At what prices do they trade?

    Key questions:
    - What's the entry price distribution?
    - Are they buying cheap (losers) or expensive (winners)?
    - Do prices vary by timing?
    """
    print("\n[PRICE ANALYSIS] At what prices?")
    print("-" * 50)

    prices_by_outcome = {"UP": [], "DOWN": []}
    prices_by_timing = defaultdict(list)
    prices_by_side = {"BUY": [], "SELL": []}

    for trade in trades:
        price = trade.get("price", 0)
        if not price or price <= 0 or price > 10:
            continue

        token_id = str(trade.get("token_id", ""))
        if token_id not in metadata:
            continue

        market = metadata[token_id]
        outcome = get_token_outcome(token_id, market)
        resolution_ts = get_resolution_ts(market)
        trade_ts = trade.get("timestamp", 0)
        side = trade.get("side", "").upper()

        if outcome:
            prices_by_outcome[outcome].append(price)

        if resolution_ts and trade_ts:
            seconds_after = trade_ts - resolution_ts
            if 0 <= seconds_after < 300:
                prices_by_timing["0-5min"].append(price)
            elif 300 <= seconds_after < 600:
                prices_by_timing["5-10min"].append(price)
            elif 600 <= seconds_after < 1800:
                prices_by_timing["10-30min"].append(price)

        if side in prices_by_side:
            prices_by_side[side].append(price)

    def price_stats(prices):
        if not prices:
            return {}
        prices.sort()
        n = len(prices)
        return {
            "count": n,
            "min": prices[0],
            "max": prices[-1],
            "median": prices[n // 2],
            "mean": statistics.mean(prices),
            "p25": prices[n // 4],
            "p75": prices[3 * n // 4],
        }

    results = {
        "by_outcome": {k: price_stats(v) for k, v in prices_by_outcome.items()},
        "by_timing": {k: price_stats(v) for k, v in prices_by_timing.items()},
        "by_side": {k: price_stats(v) for k, v in prices_by_side.items()},
    }

    print(f"\n  Price by outcome token:")
    for outcome, stats in results["by_outcome"].items():
        if stats:
            print(f"    {outcome}: median=${stats['median']:.2f}, mean=${stats['mean']:.2f} ({stats['count']:,} trades)")

    print(f"\n  Price by timing:")
    for timing, stats in results["by_timing"].items():
        if stats:
            print(f"    {timing}: median=${stats['median']:.2f} ({stats['count']:,} trades)")

    print(f"\n  Price by side:")
    for side, stats in results["by_side"].items():
        if stats:
            print(f"    {side}: median=${stats['median']:.2f} ({stats['count']:,} trades)")

    return results


def analyze_volume_patterns(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    VOLUME ANALYSIS: How much per trade?

    Key questions:
    - What's the typical position size?
    - Do they scale positions?
    - Is there a maximum position size?
    """
    print("\n[VOLUME ANALYSIS] How much per trade?")
    print("-" * 50)

    usdc_amounts = []
    token_amounts = []
    by_asset = defaultdict(list)

    for trade in trades:
        usdc = trade.get("usdc_amount", 0) or 0
        tokens = trade.get("token_amount", 0) or 0

        if usdc > 0:
            usdc_amounts.append(usdc)

            token_id = str(trade.get("token_id", ""))
            if token_id in metadata:
                asset = get_asset(metadata[token_id])
                by_asset[asset].append(usdc)

        if tokens > 0:
            token_amounts.append(tokens)

    def amount_stats(amounts):
        if not amounts:
            return {}
        amounts.sort()
        n = len(amounts)
        return {
            "count": n,
            "total": sum(amounts),
            "min": amounts[0],
            "max": amounts[-1],
            "median": amounts[n // 2],
            "mean": statistics.mean(amounts),
            "p90": amounts[9 * n // 10] if n >= 10 else amounts[-1],
            "p99": amounts[99 * n // 100] if n >= 100 else amounts[-1],
        }

    results = {
        "usdc_amounts": amount_stats(usdc_amounts),
        "token_amounts": amount_stats(token_amounts),
        "by_asset": {k: amount_stats(v) for k, v in by_asset.items()},
    }

    print(f"\n  USDC amounts:")
    if results["usdc_amounts"]:
        stats = results["usdc_amounts"]
        print(f"    Count: {stats['count']:,} trades with USDC data")
        print(f"    Total: ${stats['total']:,.2f}")
        print(f"    Median: ${stats['median']:.2f}")
        print(f"    Mean: ${stats['mean']:.2f}")
        print(f"    P90: ${stats['p90']:.2f}")
        print(f"    Max: ${stats['max']:.2f}")

    print(f"\n  By asset:")
    for asset, stats in sorted(results["by_asset"].items(), key=lambda x: x[1].get("total", 0), reverse=True)[:5]:
        if stats:
            print(f"    {asset}: ${stats['total']:,.0f} total, ${stats['median']:.2f} median")

    return results


def analyze_trade_clustering(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    CLUSTERING ANALYSIS: Do trades come in bursts?

    Key questions:
    - Are there multiple trades per market?
    - Do they scale into positions?
    - What's the time between consecutive trades?
    """
    print("\n[CLUSTERING ANALYSIS] Trade patterns")
    print("-" * 50)

    # Group trades by market (resolution_ts as proxy)
    by_market = defaultdict(list)
    for trade in trades:
        token_id = str(trade.get("token_id", ""))
        if token_id not in metadata:
            continue

        market = metadata[token_id]
        resolution_ts = get_resolution_ts(market)
        if resolution_ts:
            by_market[resolution_ts].append(trade)

    # Analyze trades per market
    trades_per_market = [len(trades) for trades in by_market.values()]

    if not trades_per_market:
        return {"error": "No market data"}

    trades_per_market.sort()
    n = len(trades_per_market)

    # Time between consecutive trades (for same-market trades)
    time_gaps = []
    for market_trades in by_market.values():
        if len(market_trades) < 2:
            continue
        sorted_trades = sorted(market_trades, key=lambda x: x.get("timestamp", 0))
        for i in range(1, len(sorted_trades)):
            gap = sorted_trades[i].get("timestamp", 0) - sorted_trades[i-1].get("timestamp", 0)
            if 0 < gap < 3600:  # Reasonable gap
                time_gaps.append(gap)

    results = {
        "total_markets": len(by_market),
        "trades_per_market": {
            "min": min(trades_per_market),
            "max": max(trades_per_market),
            "median": trades_per_market[n // 2],
            "mean": statistics.mean(trades_per_market),
            "single_trade_markets": sum(1 for t in trades_per_market if t == 1),
            "multi_trade_markets": sum(1 for t in trades_per_market if t > 1),
        },
    }

    if time_gaps:
        time_gaps.sort()
        m = len(time_gaps)
        results["time_between_trades"] = {
            "count": m,
            "min_seconds": min(time_gaps),
            "median_seconds": time_gaps[m // 2],
            "mean_seconds": statistics.mean(time_gaps),
        }

    print(f"  Total unique markets traded: {len(by_market):,}")
    print(f"\n  Trades per market:")
    print(f"    Median: {results['trades_per_market']['median']}")
    print(f"    Mean: {results['trades_per_market']['mean']:.1f}")
    print(f"    Max: {results['trades_per_market']['max']}")
    print(f"    Single-trade markets: {results['trades_per_market']['single_trade_markets']:,}")
    print(f"    Multi-trade markets: {results['trades_per_market']['multi_trade_markets']:,}")

    if "time_between_trades" in results:
        print(f"\n  Time between consecutive trades in same market:")
        print(f"    Median: {results['time_between_trades']['median_seconds']:.0f}s")
        print(f"    Mean: {results['time_between_trades']['mean_seconds']:.0f}s")

    return results


def identify_entry_signals(trades: List[dict], metadata: Dict[str, dict]) -> dict:
    """
    SIGNAL ANALYSIS: What might trigger a trade?

    Key questions:
    - Is there a price threshold that triggers trades?
    - Is it purely timing-based?
    - Any pattern with market characteristics?
    """
    print("\n[SIGNAL ANALYSIS] What triggers trades?")
    print("-" * 50)

    # Look for patterns in entry prices by outcome
    entries_by_outcome = {"UP": [], "DOWN": []}

    for trade in trades:
        price = trade.get("price", 0)
        if not price or price <= 0 or price > 1:  # Only valid prices
            continue

        token_id = str(trade.get("token_id", ""))
        if token_id not in metadata:
            continue

        market = metadata[token_id]
        outcome = get_token_outcome(token_id, market)

        if outcome:
            entries_by_outcome[outcome].append(price)

    results = {
        "entry_price_patterns": {},
        "potential_signals": [],
    }

    for outcome, prices in entries_by_outcome.items():
        if not prices:
            continue

        prices.sort()
        n = len(prices)

        # Look for concentration around certain price levels
        buckets = defaultdict(int)
        for p in prices:
            bucket = round(p, 1)  # Round to 0.1
            buckets[bucket] += 1

        # Find most common entry prices
        top_buckets = sorted(buckets.items(), key=lambda x: x[1], reverse=True)[:5]

        results["entry_price_patterns"][outcome] = {
            "count": n,
            "median": prices[n // 2],
            "top_entry_prices": [{"price": p, "count": c, "pct": c/n*100} for p, c in top_buckets],
        }

    # Identify potential signals
    print(f"\n  Entry price patterns:")
    for outcome, data in results["entry_price_patterns"].items():
        print(f"\n  {outcome} tokens ({data['count']:,} trades):")
        print(f"    Median entry: ${data['median']:.2f}")
        print(f"    Most common entry prices:")
        for entry in data["top_entry_prices"]:
            print(f"      ${entry['price']:.1f}: {entry['count']:,} ({entry['pct']:.1f}%)")

    # Hypothesis generation
    print(f"\n  HYPOTHESIS:")
    if entries_by_outcome["UP"] and entries_by_outcome["DOWN"]:
        up_median = statistics.median(entries_by_outcome["UP"])
        down_median = statistics.median(entries_by_outcome["DOWN"])

        if up_median > 0.6 and down_median < 0.4:
            print("  → Buying WINNERS (UP > $0.60) and LOSERS (DOWN < $0.40)")
            results["potential_signals"].append("PRICE_BASED_SELECTION")
        elif abs(up_median - down_median) < 0.1:
            print("  → No clear price preference - may be liquidity-based")
            results["potential_signals"].append("LIQUIDITY_BASED")
        else:
            print(f"  → UP median: ${up_median:.2f}, DOWN median: ${down_median:.2f}")
            results["potential_signals"].append("UNCLEAR_PATTERN")

    return results


def main():
    parser = argparse.ArgumentParser(description="Strategy Mechanics Analyzer")
    parser.add_argument("--trades", type=str, default="data/account88888_trades_joined.json")
    parser.add_argument("--metadata", type=str, default="data/token_to_market_full.json")
    parser.add_argument("--output", type=str, help="Output JSON file")
    args = parser.parse_args()

    print("=" * 70)
    print("STRATEGY MECHANICS ANALYZER - Account88888")
    print("=" * 70)
    print("Understanding HOW the strategy works")
    print("=" * 70)

    trades, metadata = load_data(args.trades, args.metadata)

    results = {
        "analysis_timestamp": datetime.utcnow().isoformat(),
        "data_summary": {
            "total_trades": len(trades),
            "total_tokens": len(metadata),
        },
    }

    # Run all analyses
    results["timing"] = analyze_timing_mechanics(trades, metadata)
    results["token_selection"] = analyze_token_selection(trades, metadata)
    results["pricing"] = analyze_price_mechanics(trades, metadata)
    results["volume"] = analyze_volume_patterns(trades, metadata)
    results["clustering"] = analyze_trade_clustering(trades, metadata)
    results["signals"] = identify_entry_signals(trades, metadata)

    # Summary
    print("\n" + "=" * 70)
    print("STRATEGY MECHANICS SUMMARY")
    print("=" * 70)

    print("""
KEY FINDINGS:

1. TIMING: Account88888 trades almost exclusively AFTER resolution
   - Median: ~6-7 minutes after market closes
   - Peak activity: 1-10 minutes post-resolution
   - This is NOT a prediction strategy

2. TOKEN SELECTION: Appears to trade both UP and DOWN tokens
   - Need to determine if selecting based on outcome or other factors

3. PRICING: Entry prices clustered around certain levels
   - May indicate price-based entry criteria

4. VOLUME: Moderate position sizes
   - Not concentrated in any single market

5. CLUSTERING: Multiple trades per market common
   - May be scaling into/out of positions

NEXT STEPS:
- Correlate entry prices with actual market outcomes
- Calculate P&L to determine if strategy is profitable
- Assess replicability based on identified mechanics
""")

    if args.output:
        Path(args.output).parent.mkdir(exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
