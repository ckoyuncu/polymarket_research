#!/usr/bin/env python3
"""
Post-Resolution Trading Analysis for Account88888

Analyzes trades that occur AFTER market resolution to understand:
1. Are they buying winners or losers?
2. What discount/premium are they paying?
3. Is this a settlement arbitrage strategy?

Key finding: 99.98% of Account88888 trades occur AFTER resolution.
This script investigates what strategy that represents.

Usage:
    python scripts/analysis/post_resolution_analysis.py
    python scripts/analysis/post_resolution_analysis.py --output reports/post_resolution_analysis.json
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


def load_trades(trades_path: str) -> List[dict]:
    """Load enriched trades with metadata."""
    with open(trades_path, 'r') as f:
        data = json.load(f)

    # Handle different file formats
    if isinstance(data, dict):
        # Check for nested trades key
        if "trades" in data:
            trades = data["trades"]
            if isinstance(trades, list):
                return trades
            return list(trades.values())
        return list(data.values())
    return data


def load_metadata(metadata_path: str) -> Dict[str, dict]:
    """Load token -> market metadata mapping."""
    with open(metadata_path, 'r') as f:
        data = json.load(f)

    # Handle nested structure
    if isinstance(data, dict):
        if "token_to_market" in data:
            return data["token_to_market"]
        # Check if it's already the mapping (keys are token IDs)
        first_key = next(iter(data.keys()), "")
        if len(first_key) > 50:  # Token IDs are long
            return data
    return data


def analyze_trade_direction(trade: dict, metadata: dict) -> Optional[dict]:
    """
    Analyze if a post-resolution trade is buying/selling winners or losers.

    For a trade AFTER resolution:
    - If they BUY the winning token at <1.00, they profit (redemption arbitrage)
    - If they SELL the winning token at <1.00, they lose value
    - If they BUY the losing token at >0.00, they lose (paying for worthless)
    - If they SELL the losing token at >0.00, they profit (selling worthless)
    """
    token_id = str(trade.get("token_id", ""))
    if not token_id or token_id not in metadata:
        return None

    market = metadata[token_id]

    # Get market resolution info
    resolution_ts = market.get("end_date_iso")
    if resolution_ts:
        try:
            resolution_ts = int(datetime.fromisoformat(resolution_ts.replace('Z', '+00:00')).timestamp())
        except:
            resolution_ts = None

    if not resolution_ts:
        # Try extracting from slug
        slug = market.get("slug", "")
        try:
            resolution_ts = int(slug.split("-")[-1])
        except:
            return None

    trade_ts = trade.get("timestamp", 0)
    if trade_ts <= resolution_ts:
        return None  # This is a PRE-resolution trade

    seconds_after = trade_ts - resolution_ts

    # Determine trade direction from 'side' field or from/to address
    side = trade.get("side", "").upper()
    is_buy = side == "BUY"
    is_sell = side == "SELL"

    # Fallback to address-based detection
    if not is_buy and not is_sell:
        wallet = "0x7f69983eb28245bba0d5083502a78744a8f66162".lower()
        is_buy = trade.get("to", "").lower() == wallet
        is_sell = trade.get("from", "").lower() == wallet

    # Get outcome info
    outcome = market.get("outcome")  # "UP" or "DOWN"

    # Try to determine if this token WON or LOST
    # This requires knowing the actual market result
    # For now, we'll analyze based on price patterns

    # If entry price is close to 1.0, likely a winner
    # If entry price is close to 0.0, likely a loser
    price = trade.get("price") or trade.get("entry_price")
    if not price:
        # Calculate from USDC/token amounts
        usdc_amount = trade.get("usdc_amount", 0) or 0
        token_amount = trade.get("token_amount", 0) or 0
        if not token_amount:
            token_amount = int(trade.get("value", 0)) / 1e6 if trade.get("value") else 0
        if token_amount > 0 and usdc_amount > 0:
            price = usdc_amount / token_amount

    if not price:
        return None

    # Classify the trade
    likely_winner = price > 0.7  # Resolved winners should trade near $1
    likely_loser = price < 0.3   # Resolved losers should trade near $0

    token_amount = trade.get("token_amount", 0) or 0
    if not token_amount:
        token_amount = int(trade.get("value", 0)) / 1e6 if trade.get("value") else 0

    return {
        "trade_ts": trade_ts,
        "resolution_ts": resolution_ts,
        "seconds_after": seconds_after,
        "is_buy": is_buy,
        "is_sell": is_sell,
        "price": price,
        "likely_winner": likely_winner,
        "likely_loser": likely_loser,
        "outcome": outcome,
        "slug": market.get("slug"),
        "asset": market.get("asset"),
        "usdc_amount": trade.get("usdc_amount", 0) or 0,
        "token_amount": token_amount,
    }


def analyze_redemption_strategy(analyzed_trades: List[dict]) -> dict:
    """
    Analyze if Account88888 is doing redemption arbitrage.

    Redemption arbitrage: Buy winning tokens at discount, redeem for $1
    Expected pattern:
    - BUY trades at price 0.90-0.99 (winners at small discount)
    - High volume in first few minutes after resolution
    """
    if not analyzed_trades:
        return {}

    # Filter to BUY trades only
    buys = [t for t in analyzed_trades if t.get("is_buy")]
    sells = [t for t in analyzed_trades if t.get("is_sell")]

    # Analyze price distribution for buys
    buy_prices = [t["price"] for t in buys if t.get("price")]
    sell_prices = [t["price"] for t in sells if t.get("price")]

    # Timing distribution
    buy_timing = [t["seconds_after"] for t in buys]
    sell_timing = [t["seconds_after"] for t in sells]

    def stats(values):
        if not values:
            return {"count": 0}
        values = sorted(values)
        n = len(values)
        return {
            "count": n,
            "min": values[0],
            "max": values[-1],
            "median": values[n // 2],
            "p10": values[n // 10] if n >= 10 else values[0],
            "p90": values[9 * n // 10] if n >= 10 else values[-1],
            "avg": sum(values) / n,
        }

    # Classify trades by likely outcome
    buy_likely_winners = [t for t in buys if t.get("likely_winner")]
    buy_likely_losers = [t for t in buys if t.get("likely_loser")]
    sell_likely_winners = [t for t in sells if t.get("likely_winner")]
    sell_likely_losers = [t for t in sells if t.get("likely_loser")]

    # Calculate potential profit
    # Buying winners at discount: profit = (1 - price) * amount
    potential_profit_from_buys = sum(
        (1.0 - t["price"]) * t.get("usdc_amount", 0) / t["price"]
        for t in buy_likely_winners
        if t.get("price") and t["price"] > 0
    )

    return {
        "total_analyzed": len(analyzed_trades),
        "buy_trades": len(buys),
        "sell_trades": len(sells),

        "buy_price_stats": stats(buy_prices),
        "sell_price_stats": stats(sell_prices),

        "buy_timing_stats": stats(buy_timing),
        "sell_timing_stats": stats(sell_timing),

        "buy_likely_winners": len(buy_likely_winners),
        "buy_likely_losers": len(buy_likely_losers),
        "sell_likely_winners": len(sell_likely_winners),
        "sell_likely_losers": len(sell_likely_losers),

        "potential_profit_from_winner_buys": potential_profit_from_buys,

        "strategy_hypothesis": determine_strategy(
            buy_likely_winners, buy_likely_losers,
            sell_likely_winners, sell_likely_losers,
            buy_prices, sell_prices
        ),
    }


def determine_strategy(
    buy_winners, buy_losers, sell_winners, sell_losers,
    buy_prices, sell_prices
) -> str:
    """Determine the most likely strategy based on trade patterns."""

    # Calculate ratios
    total_buys = len(buy_winners) + len(buy_losers)
    total_sells = len(sell_winners) + len(sell_losers)

    if total_buys == 0 and total_sells == 0:
        return "INSUFFICIENT_DATA"

    hypotheses = []

    # Hypothesis 1: Redemption Arbitrage (buy winners cheap, redeem for $1)
    if buy_winners and buy_prices:
        avg_buy_price = sum(buy_prices) / len(buy_prices)
        if avg_buy_price > 0.8 and len(buy_winners) > len(buy_losers):
            edge = (1.0 - avg_buy_price) * 100
            hypotheses.append(f"REDEMPTION_ARBITRAGE (buying winners at avg {avg_buy_price:.2f}, ~{edge:.1f}% edge)")

    # Hypothesis 2: Market Making (both buy and sell near fair value)
    if total_buys > 0 and total_sells > 0:
        buy_sell_ratio = total_buys / total_sells
        if 0.5 < buy_sell_ratio < 2.0:
            hypotheses.append("MARKET_MAKING (balanced buy/sell activity)")

    # Hypothesis 3: Position Cleanup (selling resolved positions)
    if total_sells > total_buys * 2:
        hypotheses.append("POSITION_CLEANUP (mostly selling)")

    # Hypothesis 4: Loser Speculation (buying losers hoping for resolution error)
    if len(buy_losers) > len(buy_winners):
        hypotheses.append("LOSER_SPECULATION (buying resolved losers)")

    if not hypotheses:
        return "UNKNOWN_PATTERN"

    return " | ".join(hypotheses)


def main():
    parser = argparse.ArgumentParser(description="Post-Resolution Trading Analysis")
    parser.add_argument(
        "--trades",
        type=str,
        default="data/account88888_trades_enriched.json",
        help="Path to enriched trades file"
    )
    parser.add_argument(
        "--metadata",
        type=str,
        default="data/token_to_market_full.json",
        help="Path to metadata file"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output file for analysis results (JSON)"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100000,
        help="Max trades to analyze"
    )

    args = parser.parse_args()

    # Load data
    print("Loading trades...")
    trades = load_trades(args.trades)
    print(f"  Loaded {len(trades):,} trades")

    print("\nLoading metadata...")
    metadata = load_metadata(args.metadata)
    print(f"  Loaded {len(metadata):,} token mappings")

    # Analyze post-resolution trades
    print("\nAnalyzing post-resolution trades...")
    analyzed = []

    for i, trade in enumerate(trades[:args.limit]):
        result = analyze_trade_direction(trade, metadata)
        if result:
            analyzed.append(result)

        if (i + 1) % 10000 == 0:
            print(f"  Processed {i + 1:,} trades, {len(analyzed):,} post-resolution")

    print(f"\nFound {len(analyzed):,} post-resolution trades")

    if not analyzed:
        print("No post-resolution trades found!")
        return

    # Analyze patterns
    print("\n" + "=" * 60)
    print("POST-RESOLUTION TRADING ANALYSIS")
    print("=" * 60)

    analysis = analyze_redemption_strategy(analyzed)

    print(f"\nTotal post-resolution trades: {analysis['total_analyzed']:,}")
    print(f"  BUY trades: {analysis['buy_trades']:,}")
    print(f"  SELL trades: {analysis['sell_trades']:,}")

    print(f"\nBuy Price Distribution:")
    bp = analysis.get("buy_price_stats", {})
    if bp.get("count"):
        print(f"  Median: ${bp['median']:.2f}")
        print(f"  P10-P90: ${bp['p10']:.2f} - ${bp['p90']:.2f}")
        print(f"  Average: ${bp['avg']:.2f}")

    print(f"\nSell Price Distribution:")
    sp = analysis.get("sell_price_stats", {})
    if sp.get("count"):
        print(f"  Median: ${sp['median']:.2f}")
        print(f"  P10-P90: ${sp['p10']:.2f} - ${sp['p90']:.2f}")
        print(f"  Average: ${sp['avg']:.2f}")

    print(f"\nTiming (seconds after resolution):")
    bt = analysis.get("buy_timing_stats", {})
    if bt.get("count"):
        print(f"  BUY median: {bt['median']:.0f}s ({bt['median']/60:.1f} min)")
    st = analysis.get("sell_timing_stats", {})
    if st.get("count"):
        print(f"  SELL median: {st['median']:.0f}s ({st['median']/60:.1f} min)")

    print(f"\nOutcome Classification:")
    print(f"  BUY likely winners: {analysis['buy_likely_winners']:,}")
    print(f"  BUY likely losers: {analysis['buy_likely_losers']:,}")
    print(f"  SELL likely winners: {analysis['sell_likely_winners']:,}")
    print(f"  SELL likely losers: {analysis['sell_likely_losers']:,}")

    print(f"\nPotential profit from buying winners:")
    print(f"  ${analysis['potential_profit_from_winner_buys']:,.2f}")

    print(f"\n" + "=" * 60)
    print(f"STRATEGY HYPOTHESIS:")
    print(f"  {analysis['strategy_hypothesis']}")
    print("=" * 60)

    # Show some example trades
    print("\nExample post-resolution trades:")
    for t in analyzed[:5]:
        direction = "BUY" if t["is_buy"] else "SELL"
        outcome = "WINNER" if t["likely_winner"] else ("LOSER" if t["likely_loser"] else "?")
        print(f"  {direction} {t['asset']} {t['outcome']} at ${t['price']:.2f} "
              f"({t['seconds_after']/60:.1f}min after) - likely {outcome}")

    # Save results
    if args.output:
        results = {
            "summary": analysis,
            "sample_trades": analyzed[:100],
            "metadata": {
                "total_trades_loaded": len(trades),
                "post_resolution_analyzed": len(analyzed),
                "analysis_timestamp": datetime.utcnow().isoformat(),
            }
        }
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
