#!/usr/bin/env python3
"""
Fast Market Metadata Fetcher

Fetches market metadata for unique token_ids using Gamma API.
Uses existing cache and saves progress incrementally.
"""

import json
import os
import sys
import time
from pathlib import Path
import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent
CACHE_FILE = PROJECT_ROOT / "data/token_to_market_full.json"
TOKEN_IDS_FILE = PROJECT_ROOT / "data/unique_token_ids.json"
GAMMA_URL = "https://gamma-api.polymarket.com/markets"
RATE_LIMIT = 0.12  # ~8 requests/sec


def main():
    print("=" * 60)
    print("Fast Market Metadata Fetcher")
    print("=" * 60)

    # Load unique token_ids
    with open(TOKEN_IDS_FILE) as f:
        all_token_ids = set(json.load(f))
    print(f"Total unique token_ids: {len(all_token_ids):,}")

    # Load existing cache
    cache = {}
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            data = json.load(f)
            cache = data.get("token_to_market", {})
    print(f"Existing cache: {len(cache):,} tokens")

    # Find tokens to fetch
    to_fetch = all_token_ids - set(cache.keys())
    print(f"Tokens to fetch: {len(to_fetch):,}")
    print()

    if not to_fetch:
        print("All tokens already cached!")
        return

    # Fetch in batches
    session = requests.Session()
    to_fetch_list = list(to_fetch)
    errors = 0

    for i, token_id in enumerate(to_fetch_list):
        try:
            resp = session.get(GAMMA_URL, params={"clob_token_ids": token_id}, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data and len(data) > 0:
                    cache[token_id] = data[0]
        except Exception as e:
            errors += 1
            if errors < 5:
                print(f"Error fetching {token_id[:20]}...: {e}")

        # Progress every 100
        if (i + 1) % 100 == 0:
            print(f"Progress: {i+1:,}/{len(to_fetch_list):,} (found: {len(cache):,}, errors: {errors})")

            # Save checkpoint every 500
            if (i + 1) % 500 == 0:
                with open(CACHE_FILE, 'w') as f:
                    json.dump({"token_to_market": cache}, f)

        time.sleep(RATE_LIMIT)

    # Final save
    with open(CACHE_FILE, 'w') as f:
        json.dump({
            "token_to_market": cache,
            "metadata": {
                "total_tokens": len(all_token_ids),
                "fetched": len(cache),
                "errors": errors
            }
        }, f)

    print()
    print(f"Complete! Cached {len(cache):,} tokens to {CACHE_FILE}")


if __name__ == "__main__":
    main()
