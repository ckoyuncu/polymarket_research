#!/usr/bin/env python3
"""
Enrich Account88888 Trades with Market Metadata

Joins trades with token_to_market mapping to create enriched dataset
with market context including asset, resolution time, etc.

Usage:
    python enrich_trades_with_markets.py
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def parse_resolution_time(slug: str, question: str) -> Optional[int]:
    """
    Extract resolution timestamp from slug or question.

    Slug format: btc-updown-15m-1764933300
    Question format: "Bitcoin Up or Down - December 5, 6:15AM-6:30AM ET"
    """
    # Try to extract from slug first (most reliable)
    if "-15m-" in slug:
        try:
            return int(slug.split("-15m-")[1])
        except (ValueError, IndexError):
            pass

    # Could add question parsing as fallback if needed
    return None


def parse_asset_from_question(question: str) -> str:
    """Extract asset from question text."""
    q_lower = question.lower()

    if "bitcoin" in q_lower or "btc" in q_lower:
        return "BTC"
    elif "ethereum" in q_lower or "eth" in q_lower:
        return "ETH"
    elif "solana" in q_lower or "sol" in q_lower:
        return "SOL"
    elif "xrp" in q_lower or "ripple" in q_lower:
        return "XRP"
    elif "doge" in q_lower or "dogecoin" in q_lower:
        return "DOGE"
    else:
        return "OTHER"


def parse_market_type(question: str, slug: str) -> str:
    """Determine market type from question/slug."""
    q_lower = question.lower()

    if "up or down" in q_lower:
        if "-15m-" in slug:
            return "updown_15m"
        else:
            return "updown_other"
    elif "above" in q_lower or "below" in q_lower:
        return "price_threshold"
    else:
        return "other"


def enrich_trade(trade: dict, market: Optional[dict]) -> dict:
    """Enrich a single trade with market metadata."""
    enriched = trade.copy()

    if market:
        question = market.get("question", "")
        slug = market.get("slug", "")

        enriched["market_question"] = question
        enriched["market_slug"] = slug
        enriched["asset"] = parse_asset_from_question(question)
        enriched["market_type"] = parse_market_type(question, slug)
        enriched["resolution_ts"] = parse_resolution_time(slug, question)
        enriched["condition_id"] = market.get("condition_id")
        enriched["market_id"] = market.get("id")

        # Parse resolution time to human readable
        res_ts = enriched["resolution_ts"]
        if res_ts:
            try:
                dt = datetime.fromtimestamp(res_ts, tz=timezone.utc)
                enriched["resolution_time_utc"] = dt.isoformat()
            except:
                enriched["resolution_time_utc"] = None
        else:
            enriched["resolution_time_utc"] = None

        enriched["has_market_data"] = True
    else:
        enriched["market_question"] = None
        enriched["market_slug"] = None
        enriched["asset"] = None
        enriched["market_type"] = None
        enriched["resolution_ts"] = None
        enriched["resolution_time_utc"] = None
        enriched["condition_id"] = None
        enriched["market_id"] = None
        enriched["has_market_data"] = False

    return enriched


def main():
    parser = argparse.ArgumentParser(description="Enrich Trades with Market Metadata")
    parser.add_argument(
        "--trades",
        type=str,
        default="data/etherscan_trades_0x7f69983e.json",
        help="Path to trades JSON file"
    )
    parser.add_argument(
        "--markets",
        type=str,
        default="data/token_to_market.json",
        help="Path to token-to-market mapping JSON file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/account88888_trades_enriched.json",
        help="Output file for enriched trades"
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    trades_file = project_root / args.trades
    markets_file = project_root / args.markets
    output_file = project_root / args.output

    print("=" * 60)
    print("Enrich Account88888 Trades with Market Metadata")
    print("=" * 60)
    print(f"Trades file: {trades_file}")
    print(f"Markets file: {markets_file}")
    print(f"Output file: {output_file}")
    print()

    # Load trades
    print("Loading trades...")
    with open(trades_file) as f:
        trades = json.load(f)
    print(f"Loaded {len(trades)} trades")

    # Load token-to-market mapping
    print("Loading token-to-market mapping...")
    with open(markets_file) as f:
        market_data = json.load(f)

    token_to_market = market_data.get("token_to_market", {})
    print(f"Loaded {len(token_to_market)} token mappings")
    print()

    # Enrich trades
    print("Enriching trades...")
    enriched_trades = []
    matched = 0
    unmatched = 0

    for trade in trades:
        token_id = str(trade.get("token_id", ""))
        market = token_to_market.get(token_id)

        enriched = enrich_trade(trade, market)
        enriched_trades.append(enriched)

        if market:
            matched += 1
        else:
            unmatched += 1

    print(f"Enriched {len(enriched_trades)} trades")
    print(f"  - Matched with market data: {matched}")
    print(f"  - Unmatched (no market found): {unmatched}")
    print()

    # Analyze enriched trades
    print("=" * 60)
    print("ENRICHED DATASET ANALYSIS")
    print("=" * 60)
    print()

    # Asset distribution
    asset_counts = {}
    asset_sizes = {}
    for trade in enriched_trades:
        asset = trade.get("asset") or "NO_DATA"
        asset_counts[asset] = asset_counts.get(asset, 0) + 1

        size = float(trade.get("usdc_amount", 0))
        if asset not in asset_sizes:
            asset_sizes[asset] = []
        asset_sizes[asset].append(size)

    print("Asset Distribution (trade count):")
    for asset, count in sorted(asset_counts.items(), key=lambda x: -x[1]):
        avg_size = sum(asset_sizes[asset]) / len(asset_sizes[asset]) if asset_sizes[asset] else 0
        total_vol = sum(asset_sizes[asset])
        print(f"  {asset}: {count} trades (avg ${avg_size:.2f}, total ${total_vol:.2f})")

    print()

    # Market type distribution
    market_type_counts = {}
    for trade in enriched_trades:
        mt = trade.get("market_type") or "NO_DATA"
        market_type_counts[mt] = market_type_counts.get(mt, 0) + 1

    print("Market Type Distribution:")
    for mt, count in sorted(market_type_counts.items(), key=lambda x: -x[1]):
        print(f"  {mt}: {count}")

    print()

    # 15-min updown specific analysis
    updown_15m_trades = [t for t in enriched_trades if t.get("market_type") == "updown_15m"]
    print(f"15-min Up/Down Trades: {len(updown_15m_trades)}")

    if updown_15m_trades:
        # BTC/ETH breakdown for 15m markets
        btc_eth_15m = {"BTC": [], "ETH": []}
        for t in updown_15m_trades:
            asset = t.get("asset")
            if asset in btc_eth_15m:
                btc_eth_15m[asset].append(t)

        print()
        print("BTC/ETH 15-min trades breakdown:")
        for asset, trades_list in btc_eth_15m.items():
            if trades_list:
                sizes = [float(t.get("usdc_amount", 0)) for t in trades_list]
                print(f"  {asset}: {len(trades_list)} trades, avg ${sum(sizes)/len(sizes):.2f}, total ${sum(sizes):.2f}")

    # Time range analysis
    print()
    timestamps = []
    for trade in enriched_trades:
        ts = trade.get("timestamp")
        if ts and ts > 0:
            timestamps.append(ts)

    if timestamps:
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        min_dt = datetime.fromtimestamp(min_ts, tz=timezone.utc)
        max_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc)
        print(f"Trade Time Range:")
        print(f"  From: {min_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  To:   {max_dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Span: {(max_ts - min_ts) / 86400:.1f} days")

    # Save enriched trades
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "source_trades": str(trades_file),
            "source_markets": str(markets_file),
            "total_trades": len(enriched_trades),
            "matched_with_market": matched,
            "unmatched": unmatched,
            "asset_distribution": asset_counts,
            "market_type_distribution": market_type_counts,
            "updown_15m_count": len(updown_15m_trades),
            "generated_at": datetime.now(timezone.utc).isoformat()
        },
        "trades": enriched_trades
    }

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print()
    print(f"Saved enriched trades to {output_file}")

    # Show sample enriched trade
    print()
    print("=" * 60)
    print("SAMPLE ENRICHED TRADE")
    print("=" * 60)

    # Find a good BTC 15m example
    sample = None
    for t in enriched_trades:
        if t.get("asset") == "BTC" and t.get("market_type") == "updown_15m":
            sample = t
            break

    if sample:
        for k, v in sample.items():
            if k in ["market_question", "market_slug", "asset", "market_type",
                     "resolution_ts", "resolution_time_utc", "timestamp", "usdc_amount",
                     "token_amount", "side", "price", "token_id"]:
                if k == "token_id":
                    v = str(v)[:30] + "..."
                print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
