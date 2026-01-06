#!/usr/bin/env python3
"""
Deep Strategy Analysis for Account88888

Analyzes the post-resolution trading pattern to understand:
1. What exactly is being bought/sold
2. Price patterns relative to resolution
3. Profitability calculation
4. Time decay of prices after resolution

This script works with partial data and can be re-run with complete data.

Usage:
    python scripts/analysis/analyze_strategy_deep.py
    python scripts/analysis/analyze_strategy_deep.py --output reports/strategy_deep.json
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import statistics


def load_trades(trades_path: str) -> List[dict]:
    """Load trades from JSON file."""
    with open(trades_path, 'r') as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "trades" in data:
            trades = data["trades"]
            return list(trades.values()) if isinstance(trades, dict) else trades
        return list(data.values())
    return data


def load_metadata(metadata_path: str) -> Dict[str, dict]:
    """Load token -> market metadata mapping."""
    with open(metadata_path, 'r') as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "token_to_market" in data:
            return data["token_to_market"]
        first_key = next(iter(data.keys()), "")
        if len(first_key) > 50:
            return data
    return data


def get_resolution_timestamp(market: dict) -> Optional[int]:
    """Extract resolution timestamp from market metadata."""
    # Try end_date_iso first
    resolution_ts = market.get("end_date_iso")
    if resolution_ts:
        try:
            return int(datetime.fromisoformat(resolution_ts.replace('Z', '+00:00')).timestamp())
        except:
            pass

    # Try extracting from slug (format: asset-updown-timestamp)
    slug = market.get("slug", "")
    if slug:
        parts = slug.split("-")
        for part in reversed(parts):
            try:
                ts = int(part)
                if 1700000000 < ts < 1800000000:  # Valid timestamp range
                    return ts
            except:
                continue

    return None


def analyze_trade(trade: dict, metadata: Dict[str, dict]) -> Optional[dict]:
    """
    Analyze a single trade's relationship to resolution.
    Returns enriched trade data or None if can't analyze.
    """
    token_id = str(trade.get("token_id", ""))
    if not token_id or token_id not in metadata:
        return None

    market = metadata[token_id]
    resolution_ts = get_resolution_timestamp(market)

    if not resolution_ts:
        return None

    trade_ts = trade.get("timestamp", 0)
    if not trade_ts:
        return None

    # Calculate timing relative to resolution
    time_diff = trade_ts - resolution_ts
    is_after_resolution = time_diff > 0

    # Get trade direction
    side = trade.get("side", "").upper()
    is_buy = side == "BUY"
    is_sell = side == "SELL"

    if not is_buy and not is_sell:
        wallet = "0x7f69983eb28245bba0d5083502a78744a8f66162".lower()
        is_buy = trade.get("to", "").lower() == wallet
        is_sell = trade.get("from", "").lower() == wallet

    # Calculate price
    price = trade.get("price") or trade.get("entry_price")
    if not price:
        usdc_amount = trade.get("usdc_amount", 0) or 0
        token_amount = trade.get("token_amount", 0) or 0
        if not token_amount:
            value = trade.get("value", 0)
            if value:
                token_amount = int(value) / 1e6
        if token_amount > 0 and usdc_amount > 0:
            price = usdc_amount / token_amount

    if not price or price <= 0:
        return None

    # Get market outcome info from slug (format: {asset}-updown-15m-{timestamp})
    slug = market.get("slug", "")
    asset = ""
    outcome = ""
    if slug:
        parts = slug.split("-")
        if len(parts) >= 2:
            asset = parts[0].upper()  # btc -> BTC
            if "up" in slug.lower():
                # Check outcomes field to determine which token this is
                outcomes = market.get("outcomes", [])
                clob_ids = market.get("clobTokenIds", [])
                if clob_ids and token_id in clob_ids:
                    idx = clob_ids.index(token_id)
                    if outcomes and len(outcomes) > idx:
                        outcome = outcomes[idx]  # "Up" or "Down"

    return {
        "trade_ts": trade_ts,
        "resolution_ts": resolution_ts,
        "seconds_from_resolution": time_diff,
        "is_after_resolution": is_after_resolution,
        "is_buy": is_buy,
        "is_sell": is_sell,
        "price": price,
        "outcome": outcome,
        "asset": asset,
        "slug": slug,
        "usdc_amount": trade.get("usdc_amount", 0) or 0,
        "token_amount": trade.get("token_amount", 0) or int(trade.get("value", 0)) / 1e6,
    }


def analyze_price_decay_after_resolution(trades: List[dict]) -> dict:
    """
    Analyze how prices change over time after resolution.
    This helps understand if there's a price inefficiency being exploited.
    """
    # Group trades by time bucket after resolution
    time_buckets = {
        "0-1min": (0, 60),
        "1-5min": (60, 300),
        "5-10min": (300, 600),
        "10-30min": (600, 1800),
        "30min+": (1800, float('inf')),
    }

    price_by_bucket = defaultdict(list)

    for t in trades:
        if not t.get("is_after_resolution"):
            continue

        seconds_after = t["seconds_from_resolution"]
        price = t["price"]

        for bucket_name, (low, high) in time_buckets.items():
            if low <= seconds_after < high:
                price_by_bucket[bucket_name].append(price)
                break

    results = {}
    for bucket_name in time_buckets.keys():
        prices = price_by_bucket[bucket_name]
        if prices:
            results[bucket_name] = {
                "count": len(prices),
                "avg_price": statistics.mean(prices),
                "median_price": statistics.median(prices),
                "min_price": min(prices),
                "max_price": max(prices),
                "std_dev": statistics.stdev(prices) if len(prices) > 1 else 0,
            }
        else:
            results[bucket_name] = {"count": 0}

    return results


def estimate_profit_potential(trades: List[dict]) -> dict:
    """
    Estimate profit potential from the trading pattern.

    For post-resolution trades:
    - Buying at < $1 and redeeming = profit of ($1 - price) per share
    - But this only works if you're buying WINNERS
    - Buying losers at any price = loss (redeem at $0)
    """
    # Separate by price level (proxy for winner/loser)
    high_price_buys = [t for t in trades if t.get("is_buy") and t.get("price", 0) > 0.7]
    mid_price_buys = [t for t in trades if t.get("is_buy") and 0.3 <= t.get("price", 0) <= 0.7]
    low_price_buys = [t for t in trades if t.get("is_buy") and t.get("price", 0) < 0.3]

    # Calculate potential redemption profit from high-price buys (likely winners)
    redemption_profit = 0
    for t in high_price_buys:
        price = t["price"]
        shares = t.get("token_amount", 0) or t.get("usdc_amount", 0) / price if price > 0 else 0
        redemption_profit += (1.0 - price) * shares

    # Calculate loss from low-price buys (likely losers - worth $0)
    loser_loss = sum(t.get("usdc_amount", 0) for t in low_price_buys)

    # Mid-price trades are uncertain
    mid_price_volume = sum(t.get("usdc_amount", 0) for t in mid_price_buys)

    return {
        "high_price_buys": {
            "count": len(high_price_buys),
            "total_volume": sum(t.get("usdc_amount", 0) for t in high_price_buys),
            "potential_redemption_profit": redemption_profit,
            "avg_price": statistics.mean([t["price"] for t in high_price_buys]) if high_price_buys else 0,
        },
        "mid_price_buys": {
            "count": len(mid_price_buys),
            "total_volume": mid_price_volume,
            "avg_price": statistics.mean([t["price"] for t in mid_price_buys]) if mid_price_buys else 0,
        },
        "low_price_buys": {
            "count": len(low_price_buys),
            "total_volume": loser_loss,
            "potential_loss_if_losers": loser_loss,
            "avg_price": statistics.mean([t["price"] for t in low_price_buys]) if low_price_buys else 0,
        },
        "net_estimate": redemption_profit - loser_loss,
    }


def analyze_by_asset(trades: List[dict]) -> dict:
    """Break down analysis by asset (BTC, ETH, SOL, etc.)."""
    by_asset = defaultdict(list)

    for t in trades:
        asset = t.get("asset", "UNKNOWN")
        by_asset[asset].append(t)

    results = {}
    for asset, asset_trades in by_asset.items():
        buys = [t for t in asset_trades if t.get("is_buy")]
        sells = [t for t in asset_trades if t.get("is_sell")]

        buy_prices = [t["price"] for t in buys if t.get("price")]
        sell_prices = [t["price"] for t in sells if t.get("price")]

        results[asset] = {
            "total_trades": len(asset_trades),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "buy_avg_price": statistics.mean(buy_prices) if buy_prices else 0,
            "buy_median_price": statistics.median(buy_prices) if buy_prices else 0,
            "sell_avg_price": statistics.mean(sell_prices) if sell_prices else 0,
            "total_volume": sum(t.get("usdc_amount", 0) for t in asset_trades),
        }

    return dict(sorted(results.items(), key=lambda x: x[1]["total_trades"], reverse=True))


def main():
    parser = argparse.ArgumentParser(description="Deep Strategy Analysis")
    parser.add_argument("--trades", type=str, default="data/account88888_trades_joined.json")
    parser.add_argument("--metadata", type=str, default="data/token_to_market_full.json")
    parser.add_argument("--output", type=str, help="Output JSON file")
    parser.add_argument("--limit", type=int, default=500000, help="Max trades to analyze")
    args = parser.parse_args()

    print("=" * 70)
    print("DEEP STRATEGY ANALYSIS - Account88888")
    print("=" * 70)

    # Load data
    print("\nLoading data...")
    trades = load_trades(args.trades)
    metadata = load_metadata(args.metadata)
    print(f"  Trades: {len(trades):,}")
    print(f"  Token mappings: {len(metadata):,}")

    # Analyze trades
    print("\nAnalyzing trades...")
    analyzed = []
    for i, trade in enumerate(trades[:args.limit]):
        result = analyze_trade(trade, metadata)
        if result:
            analyzed.append(result)
        if (i + 1) % 100000 == 0:
            print(f"  Processed {i+1:,}, analyzed {len(analyzed):,}")

    print(f"\nTotal analyzed: {len(analyzed):,} trades")

    # Split before/after resolution
    before = [t for t in analyzed if not t["is_after_resolution"]]
    after = [t for t in analyzed if t["is_after_resolution"]]

    print(f"\n{'='*70}")
    print("TIMING DISTRIBUTION")
    print(f"{'='*70}")
    print(f"\nBEFORE resolution: {len(before):,} trades ({100*len(before)/len(analyzed):.2f}%)")
    print(f"AFTER resolution:  {len(after):,} trades ({100*len(after)/len(analyzed):.2f}%)")

    # Price decay analysis
    print(f"\n{'='*70}")
    print("PRICE DECAY AFTER RESOLUTION")
    print(f"{'='*70}")

    decay = analyze_price_decay_after_resolution(after)
    print("\nBuy prices by time after resolution:")
    print(f"{'Bucket':<15} {'Count':>10} {'Avg Price':>12} {'Median':>10}")
    print("-" * 50)
    for bucket, stats in decay.items():
        if stats["count"] > 0:
            print(f"{bucket:<15} {stats['count']:>10,} ${stats['avg_price']:>10.2f} ${stats['median_price']:>8.2f}")

    # Profit potential
    print(f"\n{'='*70}")
    print("PROFIT POTENTIAL ESTIMATE")
    print(f"{'='*70}")

    profit = estimate_profit_potential(after)

    print("\nHigh-price buys (>$0.70, likely WINNERS):")
    hp = profit["high_price_buys"]
    print(f"  Count: {hp['count']:,}")
    print(f"  Volume: ${hp['total_volume']:,.2f}")
    print(f"  Avg price: ${hp['avg_price']:.2f}")
    print(f"  Potential redemption profit: ${hp['potential_redemption_profit']:,.2f}")

    print("\nMid-price buys ($0.30-$0.70, UNCERTAIN):")
    mp = profit["mid_price_buys"]
    print(f"  Count: {mp['count']:,}")
    print(f"  Volume: ${mp['total_volume']:,.2f}")
    print(f"  Avg price: ${mp['avg_price']:.2f}")

    print("\nLow-price buys (<$0.30, likely LOSERS):")
    lp = profit["low_price_buys"]
    print(f"  Count: {lp['count']:,}")
    print(f"  Volume: ${lp['total_volume']:,.2f}")
    print(f"  Avg price: ${lp['avg_price']:.2f}")
    print(f"  Potential loss if losers: ${lp['potential_loss_if_losers']:,.2f}")

    print(f"\nNet estimate: ${profit['net_estimate']:,.2f}")

    # By asset breakdown
    print(f"\n{'='*70}")
    print("BREAKDOWN BY ASSET")
    print(f"{'='*70}")

    by_asset = analyze_by_asset(after)
    print(f"\n{'Asset':<8} {'Trades':>10} {'Buys':>10} {'Sells':>8} {'Avg Buy$':>10} {'Volume':>12}")
    print("-" * 65)
    for asset, stats in list(by_asset.items())[:10]:
        print(f"{asset:<8} {stats['total_trades']:>10,} {stats['buy_count']:>10,} "
              f"{stats['sell_count']:>8,} ${stats['buy_avg_price']:>8.2f} ${stats['total_volume']:>10,.0f}")

    # Strategy interpretation
    print(f"\n{'='*70}")
    print("STRATEGY INTERPRETATION")
    print(f"{'='*70}")

    buy_ratio = sum(1 for t in after if t.get("is_buy")) / len(after) if after else 0
    avg_buy_price = statistics.mean([t["price"] for t in after if t.get("is_buy") and t.get("price")]) if after else 0

    print(f"""
Key observations:
1. {100*buy_ratio:.1f}% of trades are BUYS (not sells)
2. Average buy price: ${avg_buy_price:.2f}
3. Trading happens 1-10 minutes AFTER resolution
4. High volume in low-price tokens (potentially buying losers)

Possible strategies:
""")

    if avg_buy_price < 0.40:
        print("  → LOSER SPECULATION: Buying cheap resolved tokens hoping for")
        print("    settlement delays or resolution reversals")
    elif avg_buy_price > 0.60:
        print("  → REDEMPTION ARBITRAGE: Buying discounted winners for immediate")
        print("    redemption profit")
    else:
        print("  → MARKET MAKING: Providing post-resolution liquidity")
        print("    Profit from spread, not direction")

    # Save results
    if args.output:
        results = {
            "summary": {
                "total_analyzed": len(analyzed),
                "before_resolution": len(before),
                "after_resolution": len(after),
                "buy_ratio": buy_ratio,
                "avg_buy_price": avg_buy_price,
            },
            "price_decay": decay,
            "profit_potential": profit,
            "by_asset": by_asset,
            "metadata": {
                "trades_file": args.trades,
                "trades_loaded": len(trades),
                "analyzed_with_metadata": len(analyzed),
                "timestamp": datetime.utcnow().isoformat(),
            }
        }

        Path(args.output).parent.mkdir(exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
