#!/usr/bin/env python3
"""
Full Backtest: Account88888 Strategy Analysis

Analyzes Account88888's 31-day trading history with:
- Market metadata enrichment (where available)
- Binance price correlation
- Win/loss calculation based on actual outcomes
- Timing pattern analysis

Usage:
    python backtest_88888_full.py
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def load_trades(trades_file: Path) -> List[dict]:
    """Load trades from joined JSON file."""
    print(f"Loading trades from {trades_file}...")
    with open(trades_file) as f:
        data = json.load(f)
    trades = data.get("trades", data if isinstance(data, list) else [])
    print(f"Loaded {len(trades):,} trades")
    return trades


def load_market_metadata(metadata_file: Path) -> Dict[str, dict]:
    """Load token-to-market mapping."""
    print(f"Loading market metadata from {metadata_file}...")
    if not metadata_file.exists():
        print("  No metadata file found")
        return {}

    with open(metadata_file) as f:
        data = json.load(f)

    token_to_market = data.get("token_to_market", {})
    print(f"Loaded {len(token_to_market):,} token mappings")
    return token_to_market


def load_binance_klines(klines_file: Path) -> Dict[str, Dict[int, dict]]:
    """Load Binance klines indexed by symbol and minute timestamp."""
    print(f"Loading Binance klines from {klines_file}...")
    if not klines_file.exists():
        print("  No klines file found")
        return {}

    klines = {"BTCUSDT": {}, "ETHUSDT": {}}

    with open(klines_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            # Convert ms to minute (floor to minute)
            open_time_ms = int(row["open_time"])
            minute_ts = (open_time_ms // 60000) * 60  # seconds

            klines[symbol][minute_ts] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }

    print(f"Loaded {len(klines['BTCUSDT']):,} BTC klines, {len(klines['ETHUSDT']):,} ETH klines")
    return klines


def parse_market_details(market: dict) -> dict:
    """Extract asset, market type, resolution time from market data."""
    question = market.get("question", "")
    slug = market.get("slug", "")
    q_lower = question.lower()

    # Determine asset
    if "bitcoin" in q_lower or "btc" in q_lower:
        asset = "BTC"
    elif "ethereum" in q_lower or "eth" in q_lower:
        asset = "ETH"
    elif "solana" in q_lower or "sol" in q_lower:
        asset = "SOL"
    elif "xrp" in q_lower or "ripple" in q_lower:
        asset = "XRP"
    elif "doge" in q_lower or "dogecoin" in q_lower:
        asset = "DOGE"
    else:
        asset = "OTHER"

    # Determine market type
    if "up or down" in q_lower:
        if "-15m-" in slug:
            market_type = "updown_15m"
        else:
            market_type = "updown_other"
    elif "above" in q_lower or "below" in q_lower:
        market_type = "price_threshold"
    else:
        market_type = "other"

    # Extract resolution timestamp from slug
    resolution_ts = None
    if "-15m-" in slug:
        try:
            resolution_ts = int(slug.split("-15m-")[1])
        except (ValueError, IndexError):
            pass

    # Try to determine which outcome this token represents (UP or DOWN)
    # The clobTokenIds field has [outcome1_token, outcome2_token]
    # outcome1 is typically "Up" and outcome2 is "Down" for updown markets
    token_outcome = None
    clob_tokens = market.get("clobTokenIds", "")
    if isinstance(clob_tokens, str) and clob_tokens:
        try:
            tokens = json.loads(clob_tokens)
            # We'll need to match the trade's token_id to determine UP/DOWN
        except:
            pass

    return {
        "asset": asset,
        "market_type": market_type,
        "resolution_ts": resolution_ts,
        "question": question,
        "slug": slug,
    }


def enrich_trade(trade: dict, token_to_market: Dict[str, dict]) -> dict:
    """Enrich a trade with market metadata."""
    enriched = trade.copy()
    token_id = str(trade.get("token_id", ""))

    market = token_to_market.get(token_id)
    if market:
        details = parse_market_details(market)
        enriched.update(details)
        enriched["has_market"] = True

        # Try to determine if this is UP or DOWN token
        clob_tokens = market.get("clobTokenIds", "")
        if isinstance(clob_tokens, str) and clob_tokens:
            try:
                tokens = json.loads(clob_tokens)
                if len(tokens) == 2:
                    if token_id == tokens[0]:
                        enriched["token_outcome"] = "UP"
                    elif token_id == tokens[1]:
                        enriched["token_outcome"] = "DOWN"
            except:
                pass
    else:
        enriched["has_market"] = False
        enriched["asset"] = None
        enriched["market_type"] = None
        enriched["resolution_ts"] = None

    return enriched


def get_binance_price(
    klines: Dict[str, Dict[int, dict]],
    asset: str,
    timestamp: int
) -> Optional[float]:
    """Get Binance close price for asset at given timestamp."""
    symbol = f"{asset}USDT"
    if symbol not in klines:
        return None

    # Floor to minute
    minute_ts = (timestamp // 60) * 60

    kline = klines[symbol].get(minute_ts)
    if kline:
        return kline["close"]
    return None


def analyze_timing_patterns(trades: List[dict]) -> dict:
    """Analyze timing patterns relative to 15-minute window boundaries.

    FIXED: Now properly handles trades that occur AFTER market resolution
    (negative seconds_before values were previously misclassified as 0-30s).
    """
    results = {
        "total_15m": 0,
        "timing_buckets_before": defaultdict(int),  # Trades BEFORE resolution
        "timing_buckets_after": defaultdict(int),   # Trades AFTER resolution
        "entry_prices": [],  # price paid
        "position_sizes": [],  # USDC amounts
        "by_asset": defaultdict(lambda: {"count": 0, "volume": 0}),
        "raw_timing": [],  # Store raw timing values for analysis
    }

    for trade in trades:
        if trade.get("market_type") != "updown_15m":
            continue
        if not trade.get("resolution_ts"):
            continue

        results["total_15m"] += 1

        resolution_ts = trade["resolution_ts"]
        trade_ts = trade.get("timestamp", 0)

        # Time difference: positive = trade BEFORE resolution, negative = trade AFTER resolution
        time_diff = resolution_ts - trade_ts
        results["raw_timing"].append(time_diff)

        if time_diff > 0:
            # Trade occurs BEFORE resolution (predicting outcome)
            seconds_before = time_diff
            if seconds_before <= 30:
                bucket = "0-30s before"
            elif seconds_before <= 60:
                bucket = "30-60s before"
            elif seconds_before <= 120:
                bucket = "1-2min before"
            elif seconds_before <= 300:
                bucket = "2-5min before"
            elif seconds_before <= 600:
                bucket = "5-10min before"
            elif seconds_before <= 900:
                bucket = "10-15min before"
            else:
                bucket = ">15min before"
            results["timing_buckets_before"][bucket] += 1
        else:
            # Trade occurs AFTER resolution (settlement/redemption)
            seconds_after = -time_diff  # Make positive
            if seconds_after <= 60:
                bucket = "0-60s after"
            elif seconds_after <= 300:
                bucket = "1-5min after"
            elif seconds_after <= 600:
                bucket = "5-10min after"
            elif seconds_after <= 900:
                bucket = "10-15min after"
            elif seconds_after <= 1800:
                bucket = "15-30min after"
            else:
                bucket = ">30min after"
            results["timing_buckets_after"][bucket] += 1

        # Entry price
        price = trade.get("price", 0)
        if price > 0:
            results["entry_prices"].append(price)

        # Position size
        usdc = trade.get("usdc_amount", 0)
        if usdc > 0:
            results["position_sizes"].append(usdc)

        # By asset
        asset = trade.get("asset", "OTHER")
        results["by_asset"][asset]["count"] += 1
        results["by_asset"][asset]["volume"] += usdc

    return results


def analyze_momentum_vs_reversion(
    trades: List[dict],
    klines: Dict[str, Dict[int, dict]]
) -> dict:
    """Analyze if trades follow momentum or mean reversion."""
    results = {
        "total_analyzed": 0,
        "momentum_continuation": 0,  # Bought in direction of recent move
        "mean_reversion": 0,  # Bought against recent move
        "no_data": 0,
    }

    for trade in trades:
        if trade.get("market_type") != "updown_15m":
            continue
        if not trade.get("token_outcome"):
            continue

        asset = trade.get("asset")
        if asset not in ["BTC", "ETH"]:
            continue

        trade_ts = trade.get("timestamp", 0)
        if trade_ts == 0:
            continue

        # Get price at trade time and 5 minutes before
        price_now = get_binance_price(klines, asset, trade_ts)
        price_5min_ago = get_binance_price(klines, asset, trade_ts - 300)

        if not price_now or not price_5min_ago:
            results["no_data"] += 1
            continue

        results["total_analyzed"] += 1

        # Recent price direction
        recent_up = price_now > price_5min_ago

        # Bet direction
        bet_up = trade["token_outcome"] == "UP"

        # Momentum = betting in same direction as recent move
        if (recent_up and bet_up) or (not recent_up and not bet_up):
            results["momentum_continuation"] += 1
        else:
            results["mean_reversion"] += 1

    return results


def calculate_win_rate(
    trades: List[dict],
    klines: Dict[str, Dict[int, dict]]
) -> dict:
    """Calculate actual win rate based on price at resolution."""
    results = {
        "total_resolved": 0,
        "wins": 0,
        "losses": 0,
        "no_data": 0,
        "by_asset": defaultdict(lambda: {"wins": 0, "losses": 0}),
    }

    for trade in trades:
        if trade.get("market_type") != "updown_15m":
            continue
        if not trade.get("token_outcome"):
            continue

        asset = trade.get("asset")
        if asset not in ["BTC", "ETH"]:
            continue

        resolution_ts = trade.get("resolution_ts")
        if not resolution_ts:
            continue

        trade_ts = trade.get("timestamp", 0)

        # Get price at window start (15 min before resolution) and at resolution
        window_start_ts = resolution_ts - (15 * 60)
        price_start = get_binance_price(klines, asset, window_start_ts)
        price_end = get_binance_price(klines, asset, resolution_ts)

        if not price_start or not price_end:
            results["no_data"] += 1
            continue

        results["total_resolved"] += 1

        # Actual outcome: did price go up or down in the window?
        actual_up = price_end > price_start

        # Did our bet win?
        bet_up = trade["token_outcome"] == "UP"
        won = (actual_up and bet_up) or (not actual_up and not bet_up)

        if won:
            results["wins"] += 1
            results["by_asset"][asset]["wins"] += 1
        else:
            results["losses"] += 1
            results["by_asset"][asset]["losses"] += 1

    return results


def main():
    parser = argparse.ArgumentParser(description="Full Account88888 Backtest")
    parser.add_argument(
        "--trades",
        type=str,
        default="data/account88888_trades_joined.json",
        help="Path to joined trades file"
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default="data/token_to_market_full.json",
        help="Path to token-to-market metadata"
    )
    parser.add_argument(
        "--klines",
        type=str,
        default="data/binance_klines_full.csv",
        help="Path to Binance klines"
    )

    args = parser.parse_args()

    project_root = Path(__file__).parent.parent.parent
    trades_file = project_root / args.trades
    metadata_file = project_root / args.metadata
    klines_file = project_root / args.klines

    print("=" * 70)
    print("ACCOUNT88888 FULL BACKTEST")
    print("=" * 70)
    print()

    # Load data
    raw_trades = load_trades(trades_file)
    token_to_market = load_market_metadata(metadata_file)
    klines = load_binance_klines(klines_file)
    print()

    # Filter trades with prices (matched with ERC20)
    trades_with_price = [t for t in raw_trades if t.get("usdc_amount", 0) > 0]
    print(f"Trades with USDC price: {len(trades_with_price):,} / {len(raw_trades):,}")

    # Enrich with market metadata
    print("\nEnriching trades with market metadata...")
    enriched_trades = []
    for trade in trades_with_price:
        enriched = enrich_trade(trade, token_to_market)
        enriched_trades.append(enriched)

    with_market = [t for t in enriched_trades if t.get("has_market")]
    print(f"Trades with market metadata: {len(with_market):,}")

    updown_15m = [t for t in enriched_trades if t.get("market_type") == "updown_15m"]
    print(f"15-min Up/Down trades: {len(updown_15m):,}")

    with_outcome = [t for t in updown_15m if t.get("token_outcome")]
    print(f"Trades with known outcome token (UP/DOWN): {len(with_outcome):,}")

    # Analyze timing patterns
    print("\n" + "=" * 70)
    print("TIMING ANALYSIS")
    print("=" * 70)

    timing = analyze_timing_patterns(enriched_trades)
    print(f"\nTotal 15-min trades analyzed: {timing['total_15m']:,}")

    # Count trades before vs after resolution
    before_count = sum(timing['timing_buckets_before'].values())
    after_count = sum(timing['timing_buckets_after'].values())

    print(f"\n*** CRITICAL FINDING ***")
    print(f"Trades BEFORE resolution: {before_count:,} ({before_count/timing['total_15m']*100:.1f}%)" if timing['total_15m'] > 0 else "")
    print(f"Trades AFTER resolution:  {after_count:,} ({after_count/timing['total_15m']*100:.1f}%)" if timing['total_15m'] > 0 else "")

    if timing['timing_buckets_before']:
        print("\nTrades BEFORE market resolution (prediction trades):")
        for bucket in ["0-30s before", "30-60s before", "1-2min before", "2-5min before", "5-10min before", "10-15min before", ">15min before"]:
            count = timing['timing_buckets_before'].get(bucket, 0)
            pct = count / timing['total_15m'] * 100 if timing['total_15m'] > 0 else 0
            if count > 0:
                print(f"  {bucket:>15}: {count:>6,} ({pct:>5.1f}%)")

    if timing['timing_buckets_after']:
        print("\nTrades AFTER market resolution (settlement/redemption trades):")
        for bucket in ["0-60s after", "1-5min after", "5-10min after", "10-15min after", "15-30min after", ">30min after"]:
            count = timing['timing_buckets_after'].get(bucket, 0)
            pct = count / timing['total_15m'] * 100 if timing['total_15m'] > 0 else 0
            if count > 0:
                print(f"  {bucket:>15}: {count:>6,} ({pct:>5.1f}%)")

    # Raw timing stats
    if timing['raw_timing']:
        raw = timing['raw_timing']
        raw.sort()
        print(f"\nRaw timing statistics (resolution_ts - trade_ts):")
        print(f"  Min: {min(raw)} seconds {'(AFTER)' if min(raw) < 0 else '(BEFORE)'}")
        print(f"  Max: {max(raw)} seconds {'(AFTER)' if max(raw) < 0 else '(BEFORE)'}")
        print(f"  Median: {raw[len(raw)//2]} seconds")

    if timing['entry_prices']:
        avg_price = sum(timing['entry_prices']) / len(timing['entry_prices'])
        median_price = sorted(timing['entry_prices'])[len(timing['entry_prices'])//2]
        print(f"\nEntry prices: avg=${avg_price:.4f}, median=${median_price:.4f}")

    if timing['position_sizes']:
        avg_size = sum(timing['position_sizes']) / len(timing['position_sizes'])
        median_size = sorted(timing['position_sizes'])[len(timing['position_sizes'])//2]
        total_vol = sum(timing['position_sizes'])
        print(f"Position sizes: avg=${avg_size:.2f}, median=${median_size:.2f}, total=${total_vol:,.2f}")

    if timing['by_asset']:
        print("\nBy asset:")
        for asset, stats in sorted(timing['by_asset'].items(), key=lambda x: -x[1]['count']):
            print(f"  {asset}: {stats['count']:,} trades, ${stats['volume']:,.2f}")

    # Momentum vs reversion
    print("\n" + "=" * 70)
    print("MOMENTUM VS MEAN REVERSION")
    print("=" * 70)

    momentum = analyze_momentum_vs_reversion(enriched_trades, klines)
    print(f"\nTotal analyzed: {momentum['total_analyzed']:,}")
    print(f"No Binance data: {momentum['no_data']:,}")

    if momentum['total_analyzed'] > 0:
        mom_pct = momentum['momentum_continuation'] / momentum['total_analyzed'] * 100
        rev_pct = momentum['mean_reversion'] / momentum['total_analyzed'] * 100
        print(f"\nMomentum continuation: {momentum['momentum_continuation']:,} ({mom_pct:.1f}%)")
        print(f"Mean reversion: {momentum['mean_reversion']:,} ({rev_pct:.1f}%)")

    # Win rate calculation
    print("\n" + "=" * 70)
    print("WIN RATE ANALYSIS")
    print("=" * 70)

    winrate = calculate_win_rate(enriched_trades, klines)
    print(f"\nTotal resolved: {winrate['total_resolved']:,}")
    print(f"No Binance data: {winrate['no_data']:,}")

    if winrate['total_resolved'] > 0:
        win_pct = winrate['wins'] / winrate['total_resolved'] * 100
        print(f"\nWins: {winrate['wins']:,}")
        print(f"Losses: {winrate['losses']:,}")
        print(f"Win Rate: {win_pct:.1f}%")

        print("\nBy asset:")
        for asset, stats in sorted(winrate['by_asset'].items()):
            total = stats['wins'] + stats['losses']
            if total > 0:
                wr = stats['wins'] / total * 100
                print(f"  {asset}: {stats['wins']}/{total} wins ({wr:.1f}%)")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"""
Dataset:
  Total trades: {len(raw_trades):,}
  With USDC price: {len(trades_with_price):,}
  With market metadata: {len(with_market):,}
  15-min Up/Down: {len(updown_15m):,}

Key Findings:
  Metadata coverage: {len(with_market)/len(trades_with_price)*100:.1f}% of priced trades
  15-min market focus: {len(updown_15m)/len(with_market)*100 if with_market else 0:.1f}% of mapped trades
""")

    if winrate['total_resolved'] > 0:
        print(f"  Win Rate: {winrate['wins']/winrate['total_resolved']*100:.1f}%")

    if momentum['total_analyzed'] > 0:
        print(f"  Momentum %: {momentum['momentum_continuation']/momentum['total_analyzed']*100:.1f}%")


if __name__ == "__main__":
    main()
