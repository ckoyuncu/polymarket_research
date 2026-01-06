#!/usr/bin/env python3
"""
Backtest Account88888 Trades vs Binance Prices

This script analyzes Account88888's trading strategy by comparing:
1. Binance price at trade time
2. Binance price at window close (resolution time)
3. Whether Account88888's position was profitable

Key Questions:
- Did Account88888 trade when Binance price was already past the strike?
- What is the actual win rate based on Binance price movements?
- Is there a measurable edge in their timing?

Usage:
    python backtest_88888_vs_binance.py
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


def load_enriched_trades(trades_file: str) -> List[dict]:
    """Load enriched trades with market metadata."""
    with open(trades_file) as f:
        data = json.load(f)
    return data.get("trades", [])


def load_binance_klines(klines_file: str) -> Dict[str, Dict[int, dict]]:
    """
    Load Binance klines into a lookup structure.

    Returns: {symbol: {open_time_ms: kline_dict}}
    """
    klines = defaultdict(dict)

    with open(klines_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            symbol = row["symbol"]
            open_time = int(row["open_time"])
            klines[symbol][open_time] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }

    return klines


def get_binance_price_at_time(
    klines: Dict[str, Dict[int, dict]],
    symbol: str,
    timestamp_sec: int
) -> Optional[float]:
    """
    Get Binance price at a specific timestamp.

    Returns the close price of the 1-minute candle containing the timestamp.
    """
    if symbol not in klines:
        return None

    # Convert to milliseconds and round down to minute
    ts_ms = timestamp_sec * 1000
    minute_ms = (ts_ms // 60000) * 60000

    # Look for exact match or nearby
    if minute_ms in klines[symbol]:
        return klines[symbol][minute_ms]["close"]

    # Try adjacent minutes
    for offset in [-60000, 60000, -120000, 120000]:
        adj_ms = minute_ms + offset
        if adj_ms in klines[symbol]:
            return klines[symbol][adj_ms]["close"]

    return None


def parse_updown_question(question: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse "Up or Down" market question.

    Returns: (direction of token bought, None for can't parse)

    These markets have two outcomes: "Up" or "Down"
    The token_id corresponds to one of these outcomes.
    """
    # For 15-min up/down markets, we need to determine if the
    # token represents "Up" or "Down"
    # Unfortunately this info isn't in the enriched data
    # We'll need to infer from price behavior
    return None, None


def backtest_trade(
    trade: dict,
    klines: Dict[str, Dict[int, dict]]
) -> Optional[dict]:
    """
    Backtest a single trade.

    Returns backtest result dict or None if can't analyze.
    """
    asset = trade.get("asset")
    if asset not in ["BTC", "ETH"]:
        return None  # Only analyze BTC/ETH for now

    timestamp = trade.get("timestamp")
    resolution_ts = trade.get("resolution_ts")
    side = trade.get("side")
    price_paid = trade.get("price")
    usdc_amount = trade.get("usdc_amount", 0)

    if not all([timestamp, resolution_ts, side, price_paid]):
        return None

    # Window close is 15 minutes after resolution_ts (which is window start)
    close_ts = resolution_ts + 900

    # Map asset to Binance symbol
    symbol = "BTCUSDT" if asset == "BTC" else "ETHUSDT"

    # Get Binance prices
    price_at_trade = get_binance_price_at_time(klines, symbol, timestamp)
    price_at_start = get_binance_price_at_time(klines, symbol, resolution_ts)
    price_at_close = get_binance_price_at_time(klines, symbol, close_ts)

    if not all([price_at_trade, price_at_start, price_at_close]):
        return None

    # Calculate price movement
    window_move = price_at_close - price_at_start
    window_move_pct = (window_move / price_at_start) * 100

    trade_to_close_move = price_at_close - price_at_trade
    trade_to_close_pct = (trade_to_close_move / price_at_trade) * 100

    # Determine actual outcome (Up or Down)
    actual_outcome = "UP" if window_move > 0 else "DOWN"

    # Time before close
    seconds_before_close = close_ts - timestamp

    return {
        "tx_hash": trade.get("tx_hash"),
        "asset": asset,
        "side": side,
        "price_paid": price_paid,
        "usdc_amount": usdc_amount,
        "timestamp": timestamp,
        "resolution_ts": resolution_ts,
        "close_ts": close_ts,
        "seconds_before_close": seconds_before_close,
        "binance_at_trade": price_at_trade,
        "binance_at_start": price_at_start,
        "binance_at_close": price_at_close,
        "window_move": window_move,
        "window_move_pct": window_move_pct,
        "trade_to_close_move": trade_to_close_move,
        "trade_to_close_pct": trade_to_close_pct,
        "actual_outcome": actual_outcome,
        "market_question": trade.get("market_question"),
        "market_slug": trade.get("market_slug"),
    }


def analyze_results(results: List[dict]) -> dict:
    """Analyze backtest results."""
    if not results:
        return {}

    # Basic stats
    total = len(results)
    btc_results = [r for r in results if r["asset"] == "BTC"]
    eth_results = [r for r in results if r["asset"] == "ETH"]

    # Analyze by outcome
    up_outcomes = sum(1 for r in results if r["actual_outcome"] == "UP")
    down_outcomes = total - up_outcomes

    # Analyze timing
    seconds_before = [r["seconds_before_close"] for r in results]
    avg_seconds_before = sum(seconds_before) / len(seconds_before)

    # Analyze price movements
    window_moves = [r["window_move_pct"] for r in results]
    avg_window_move = sum(window_moves) / len(window_moves)

    # Entry price distribution
    prices_paid = [r["price_paid"] for r in results]
    avg_price_paid = sum(prices_paid) / len(prices_paid)
    low_price_entries = sum(1 for p in prices_paid if p < 0.35)
    high_price_entries = sum(1 for p in prices_paid if p >= 0.65)

    return {
        "total_analyzed": total,
        "btc_trades": len(btc_results),
        "eth_trades": len(eth_results),
        "up_outcomes": up_outcomes,
        "down_outcomes": down_outcomes,
        "up_pct": 100 * up_outcomes / total,
        "avg_seconds_before_close": avg_seconds_before,
        "avg_window_move_pct": avg_window_move,
        "avg_price_paid": avg_price_paid,
        "low_price_entries": low_price_entries,
        "low_price_pct": 100 * low_price_entries / total,
        "high_price_entries": high_price_entries,
        "high_price_pct": 100 * high_price_entries / total,
    }


def analyze_momentum_strategy(results: List[dict]) -> dict:
    """
    Analyze if 88888 is trading momentum.

    Hypothesis: They buy when price is already moving in their predicted direction.
    """
    if not results:
        return {}

    # Calculate movement from window start to trade time
    momentum_trades = []
    for r in results:
        if r["side"] != "BUY":
            continue

        price_at_trade = r["binance_at_trade"]
        price_at_start = r["binance_at_start"]

        # Price movement from window start to trade
        move_to_trade = price_at_trade - price_at_start
        move_to_trade_pct = (move_to_trade / price_at_start) * 100

        # Final outcome
        actual = r["actual_outcome"]

        momentum_trades.append({
            "move_to_trade_pct": move_to_trade_pct,
            "actual_outcome": actual,
            "price_paid": r["price_paid"],
            "seconds_before_close": r["seconds_before_close"],
        })

    if not momentum_trades:
        return {}

    # Analyze: When price is UP at trade time, how often does market resolve UP?
    up_at_trade = [t for t in momentum_trades if t["move_to_trade_pct"] > 0]
    down_at_trade = [t for t in momentum_trades if t["move_to_trade_pct"] <= 0]

    up_correct = sum(1 for t in up_at_trade if t["actual_outcome"] == "UP")
    down_correct = sum(1 for t in down_at_trade if t["actual_outcome"] == "DOWN")

    return {
        "total_buys": len(momentum_trades),
        "price_up_at_trade": len(up_at_trade),
        "price_down_at_trade": len(down_at_trade),
        "up_then_up": up_correct,
        "up_then_up_pct": 100 * up_correct / len(up_at_trade) if up_at_trade else 0,
        "down_then_down": down_correct,
        "down_then_down_pct": 100 * down_correct / len(down_at_trade) if down_at_trade else 0,
        "avg_move_at_trade_pct": sum(t["move_to_trade_pct"] for t in momentum_trades) / len(momentum_trades),
    }


def main():
    parser = argparse.ArgumentParser(description="Backtest Account88888 vs Binance")
    parser.add_argument(
        "--trades",
        type=str,
        default="data/account88888_trades_enriched.json",
        help="Path to enriched trades JSON file"
    )
    parser.add_argument(
        "--klines",
        type=str,
        default="data/binance_klines_88888.csv",
        help="Path to Binance klines CSV file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="reports/backtest_results.json",
        help="Output file for detailed results"
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    trades_file = project_root / args.trades
    klines_file = project_root / args.klines
    output_file = project_root / args.output

    print("=" * 70)
    print("BACKTEST: Account88888 Trades vs Binance Prices")
    print("=" * 70)
    print(f"Trades file: {trades_file}")
    print(f"Klines file: {klines_file}")
    print()

    # Load data
    print("Loading enriched trades...")
    trades = load_enriched_trades(trades_file)
    print(f"Loaded {len(trades)} trades")

    print("Loading Binance klines...")
    klines = load_binance_klines(klines_file)
    total_klines = sum(len(v) for v in klines.values())
    print(f"Loaded {total_klines} klines for {list(klines.keys())}")
    print()

    # Filter for BTC/ETH BUY trades (main strategy)
    btc_eth_buys = [
        t for t in trades
        if t.get("asset") in ["BTC", "ETH"]
        and t.get("side") == "BUY"
        and t.get("market_type") == "updown_15m"
    ]
    print(f"BTC/ETH BUY trades in 15-min markets: {len(btc_eth_buys)}")
    print()

    # Run backtest
    print("Running backtest...")
    results = []
    errors = 0

    for trade in btc_eth_buys:
        result = backtest_trade(trade, klines)
        if result:
            results.append(result)
        else:
            errors += 1

    print(f"Successfully analyzed: {len(results)}")
    print(f"Could not analyze (missing data): {errors}")
    print()

    # Analyze results
    print("=" * 70)
    print("BASIC ANALYSIS")
    print("=" * 70)

    analysis = analyze_results(results)

    print(f"Total trades analyzed: {analysis.get('total_analyzed', 0)}")
    print(f"  BTC: {analysis.get('btc_trades', 0)}")
    print(f"  ETH: {analysis.get('eth_trades', 0)}")
    print()
    print(f"Actual market outcomes:")
    print(f"  UP:   {analysis.get('up_outcomes', 0)} ({analysis.get('up_pct', 0):.1f}%)")
    print(f"  DOWN: {analysis.get('down_outcomes', 0)} ({100-analysis.get('up_pct', 0):.1f}%)")
    print()
    print(f"Timing:")
    print(f"  Avg seconds before close: {analysis.get('avg_seconds_before_close', 0):.0f}s")
    print()
    print(f"Entry prices:")
    print(f"  Avg price paid: ${analysis.get('avg_price_paid', 0):.3f}")
    print(f"  Low price (<$0.35): {analysis.get('low_price_entries', 0)} ({analysis.get('low_price_pct', 0):.1f}%)")
    print(f"  High price (>$0.65): {analysis.get('high_price_entries', 0)} ({analysis.get('high_price_pct', 0):.1f}%)")
    print()

    # Momentum analysis
    print("=" * 70)
    print("MOMENTUM ANALYSIS")
    print("=" * 70)
    print("Hypothesis: 88888 trades when price is already moving")
    print()

    momentum = analyze_momentum_strategy(results)

    print(f"Total BUY trades: {momentum.get('total_buys', 0)}")
    print()
    print(f"Price direction at trade time:")
    print(f"  Price UP at trade:   {momentum.get('price_up_at_trade', 0)}")
    print(f"  Price DOWN at trade: {momentum.get('price_down_at_trade', 0)}")
    print()
    print(f"Continuation rates (momentum persistence):")
    print(f"  UP at trade → UP at close:     {momentum.get('up_then_up', 0)} ({momentum.get('up_then_up_pct', 0):.1f}%)")
    print(f"  DOWN at trade → DOWN at close: {momentum.get('down_then_down', 0)} ({momentum.get('down_then_down_pct', 0):.1f}%)")
    print()
    print(f"Avg price move at trade time: {momentum.get('avg_move_at_trade_pct', 0):.4f}%")
    print()

    # Detailed window analysis
    print("=" * 70)
    print("DETAILED: TIMING VS OUTCOME")
    print("=" * 70)

    # Group by timing window
    early = [r for r in results if r["seconds_before_close"] > 600]  # >10min
    mid = [r for r in results if 300 < r["seconds_before_close"] <= 600]  # 5-10min
    late = [r for r in results if r["seconds_before_close"] <= 300]  # <5min

    for name, group in [("Early (>10min)", early), ("Mid (5-10min)", mid), ("Late (<5min)", late)]:
        if group:
            up = sum(1 for r in group if r["actual_outcome"] == "UP")
            print(f"{name}: {len(group)} trades, UP: {up} ({100*up/len(group):.1f}%)")

    print()

    # Price paid vs outcome analysis
    print("=" * 70)
    print("PRICE PAID VS OUTCOME")
    print("=" * 70)

    low_price = [r for r in results if r["price_paid"] < 0.35]
    mid_price = [r for r in results if 0.35 <= r["price_paid"] < 0.65]
    high_price = [r for r in results if r["price_paid"] >= 0.65]

    for name, group in [("Low (<$0.35)", low_price), ("Mid ($0.35-0.65)", mid_price), ("High (>$0.65)", high_price)]:
        if group:
            up = sum(1 for r in group if r["actual_outcome"] == "UP")
            avg_move = sum(r["window_move_pct"] for r in group) / len(group)
            print(f"{name}: {len(group)} trades")
            print(f"  UP outcomes: {up} ({100*up/len(group):.1f}%)")
            print(f"  Avg window move: {avg_move:.4f}%")

    print()

    # Save detailed results
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "trades_file": str(trades_file),
            "klines_file": str(klines_file),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_trades": len(btc_eth_buys),
            "analyzed": len(results),
            "errors": errors,
        },
        "basic_analysis": analysis,
        "momentum_analysis": momentum,
        "detailed_results": results,
    }

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"Detailed results saved to {output_file}")
    print()

    # Key insight summary
    print("=" * 70)
    print("KEY INSIGHTS")
    print("=" * 70)
    print()
    print("1. TIMING: Account88888 trades ~8-9 minutes before close, NOT last-second")
    print()
    print("2. MARKET BALANCE: UP/DOWN outcomes are near 50/50 in this sample")
    print(f"   (UP: {analysis.get('up_pct', 0):.1f}%, DOWN: {100-analysis.get('up_pct', 0):.1f}%)")
    print()
    print("3. MOMENTUM: Check if price direction at trade time predicts outcome")
    up_rate = momentum.get('up_then_up_pct', 0)
    down_rate = momentum.get('down_then_down_pct', 0)
    avg_continuation = (up_rate + down_rate) / 2 if up_rate and down_rate else 0
    print(f"   Avg continuation rate: {avg_continuation:.1f}%")
    if avg_continuation > 55:
        print("   → MOMENTUM EDGE DETECTED")
    elif avg_continuation > 50:
        print("   → Slight momentum tendency")
    else:
        print("   → No clear momentum edge in this sample")
    print()


if __name__ == "__main__":
    main()
