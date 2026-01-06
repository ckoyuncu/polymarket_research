#!/usr/bin/env python3
"""
Fetch Market Metadata for Account88888 Token IDs

This script fetches market metadata from Polymarket's Gamma API for
the specific token_ids found in Account88888's trades.

Usage:
    python fetch_market_metadata.py
    python fetch_market_metadata.py --output data/token_to_market.json
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class GammaMarketFetcher:
    """Fetches market metadata from Polymarket Gamma API."""

    BASE_URL = "https://gamma-api.polymarket.com"

    def __init__(self, rate_limit: float = 0.15):
        """Initialize fetcher with rate limiting."""
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.last_request_time = 0
        self.cache: Dict[str, dict] = {}

    def _rate_limit(self):
        """Enforce rate limiting."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()

    def get_market_by_clob_token(self, clob_token_id: str) -> Optional[dict]:
        """
        Fetch market data by CLOB token ID.

        Args:
            clob_token_id: The CLOB token ID to look up

        Returns:
            Market data dict or None if not found
        """
        if clob_token_id in self.cache:
            return self.cache[clob_token_id]

        self._rate_limit()

        url = f"{self.BASE_URL}/markets"
        params = {"clob_token_ids": clob_token_id}

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data and len(data) > 0:
                market = data[0]
                self.cache[clob_token_id] = market
                return market

        except Exception as e:
            pass

        return None

    def get_markets_one_by_one(self, token_ids: List[str], save_progress_file: str = None) -> Dict[str, dict]:
        """
        Fetch markets one token at a time (more reliable than batch).

        Args:
            token_ids: List of CLOB token IDs
            save_progress_file: Optional file to save progress incrementally

        Returns:
            Dict mapping token_id to market data
        """
        results = {}
        total = len(token_ids)
        errors = 0

        # Load existing progress if file exists
        if save_progress_file and os.path.exists(save_progress_file):
            try:
                with open(save_progress_file) as f:
                    saved = json.load(f)
                    results = saved.get("token_to_market", {})
                    print(f"Loaded {len(results)} cached results")
            except:
                pass

        for i, token_id in enumerate(token_ids):
            # Skip if already fetched
            if token_id in results:
                continue

            market = self.get_market_by_clob_token(token_id)

            if market:
                results[token_id] = market
            else:
                errors += 1

            # Progress every 50 tokens
            if (i + 1) % 50 == 0:
                print(f"  Progress: {i+1}/{total} ({len(results)} found, {errors} errors)")

                # Save progress incrementally
                if save_progress_file:
                    with open(save_progress_file, 'w') as f:
                        json.dump({"token_to_market": results}, f)

        print(f"  Final: {total}/{total} ({len(results)} found, {errors} errors)")
        return results


def load_trades(trades_file: str) -> List[dict]:
    """Load trades from JSON file."""
    with open(trades_file, 'r') as f:
        data = json.load(f)
        # Handle both formats: array or object with "trades" key
        if isinstance(data, list):
            return data
        elif isinstance(data, dict) and "trades" in data:
            return data["trades"]
        else:
            return data


def extract_unique_token_ids(trades: List[dict]) -> Set[str]:
    """Extract unique token IDs from trades."""
    token_ids = set()
    for trade in trades:
        token_id = trade.get("token_id")
        if token_id:
            token_ids.add(str(token_id))
    return token_ids


def parse_market_details(market: dict) -> dict:
    """Parse market details to extract asset, strike, resolution time."""
    question = market.get("question", "")
    slug = market.get("slug", "")

    # Determine asset
    q_lower = question.lower()
    if "bitcoin" in q_lower or "btc" in q_lower:
        asset = "BTC"
    elif "ethereum" in q_lower or "eth" in q_lower:
        asset = "ETH"
    else:
        asset = "UNKNOWN"

    # Determine market type
    if "up or down" in q_lower:
        market_type = "updown_15m"
    elif "above" in q_lower or "below" in q_lower:
        market_type = "price_threshold"
    else:
        market_type = "other"

    # Try to extract resolution time from slug (e.g., "eth-updown-15m-1764913500")
    resolution_ts = None
    if "-15m-" in slug:
        try:
            resolution_ts = int(slug.split("-15m-")[1])
        except:
            pass

    return {
        "asset": asset,
        "market_type": market_type,
        "resolution_ts": resolution_ts,
        "question": question,
        "slug": slug
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Market Metadata for Token IDs")
    parser.add_argument(
        "--trades",
        type=str,
        default="data/etherscan_trades_0x7f69983e.json",
        help="Path to trades JSON file"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/token_to_market.json",
        help="Output file for token-to-market mapping"
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    trades_file = project_root / args.trades
    output_file = project_root / args.output

    print("=" * 60)
    print("Fetch Market Metadata for Account88888 Trades")
    print("=" * 60)
    print(f"Trades file: {trades_file}")
    print(f"Output file: {output_file}")
    print()

    # Load trades
    print("Loading trades...")
    trades = load_trades(trades_file)
    print(f"Loaded {len(trades)} trades")

    # Extract unique token IDs
    token_ids = extract_unique_token_ids(trades)
    print(f"Found {len(token_ids)} unique token IDs")
    print()

    # Fetch market metadata (one by one with progress saving)
    print("Fetching market metadata from Gamma API...")
    print("(This may take a few minutes for many tokens)")
    print()

    fetcher = GammaMarketFetcher(rate_limit=0.15)  # ~7 requests/sec

    token_ids_list = list(token_ids)
    results = fetcher.get_markets_one_by_one(
        token_ids_list,
        save_progress_file=str(output_file)
    )

    print()
    print(f"Successfully fetched metadata for {len(results)} / {len(token_ids)} token IDs")
    print()

    # Analyze results
    market_types = {}
    assets = {}
    updown_15m_count = 0

    for token_id, market in results.items():
        details = parse_market_details(market)

        market_types[details["market_type"]] = market_types.get(details["market_type"], 0) + 1
        assets[details["asset"]] = assets.get(details["asset"], 0) + 1

        if details["market_type"] == "updown_15m":
            updown_15m_count += 1

    print("Market type distribution:")
    for mtype, count in sorted(market_types.items(), key=lambda x: -x[1]):
        print(f"  {mtype}: {count}")

    print()
    print("Asset distribution:")
    for asset, count in sorted(assets.items(), key=lambda x: -x[1]):
        print(f"  {asset}: {count}")

    print()
    print(f"15-min Up/Down markets: {updown_15m_count}")

    # Save results
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "total_trades": len(trades),
            "unique_token_ids": len(token_ids),
            "tokens_with_metadata": len(results),
            "market_types": market_types,
            "assets": assets,
            "updown_15m_count": updown_15m_count
        },
        "token_to_market": results
    }

    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print()
    print(f"Saved token-to-market mapping to {output_file}")

    # Show some examples
    print()
    print("Sample 15-min Up/Down markets found:")
    count = 0
    for token_id, market in results.items():
        if "up or down" in market.get("question", "").lower():
            print(f"  [{count+1}] {market.get('question', 'N/A')[:70]}")
            print(f"      Slug: {market.get('slug', 'N/A')}")
            count += 1
            if count >= 5:
                break


if __name__ == "__main__":
    main()
