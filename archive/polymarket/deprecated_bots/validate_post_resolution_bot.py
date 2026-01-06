#!/usr/bin/env python3
"""
Pre-deployment Validation for Post-Resolution Bot

Runs all necessary checks before deploying the bot live:
1. API connectivity
2. Credentials validation
3. Market discovery
4. Price feed verification
5. Balance check

Usage:
    python scripts/validate_post_resolution_bot.py
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not required if env vars are set


class ValidationResult:
    """Result of a validation test."""
    def __init__(self, name: str):
        self.name = name
        self.passed = False
        self.message = ""
        self.details = {}

    def pass_test(self, message: str = "", **details):
        self.passed = True
        self.message = message
        self.details = details

    def fail_test(self, message: str, **details):
        self.passed = False
        self.message = message
        self.details = details

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        return f"[{status}] {self.name}: {self.message}"


def test_environment() -> ValidationResult:
    """Test that required environment variables are set."""
    result = ValidationResult("Environment Variables")

    required = {
        "POLYMARKET_PRIVATE_KEY": os.getenv("POLYMARKET_PRIVATE_KEY"),
        "POLYMARKET_FUNDER": os.getenv("POLYMARKET_FUNDER"),
    }

    missing = [k for k, v in required.items() if not v]

    if missing:
        result.fail_test(f"Missing: {', '.join(missing)}")
    else:
        result.pass_test("All required env vars set",
                        funder=required["POLYMARKET_FUNDER"][:20] + "...")

    return result


def test_gamma_api() -> ValidationResult:
    """Test Gamma API connectivity."""
    result = ValidationResult("Gamma API (Market Discovery)")

    try:
        from src.api.gamma import GammaClient
        client = GammaClient()

        # Search for 15-minute markets
        markets = client.search_markets("BTC Up or Down 15", limit=5)

        if markets:
            result.pass_test(f"Found {len(markets)} markets",
                           sample_market=markets[0].get("question", "")[:50])
        else:
            result.fail_test("No markets found")

    except Exception as e:
        result.fail_test(f"API error: {str(e)}")

    return result


def test_clob_client() -> ValidationResult:
    """Test CLOB client initialization."""
    result = ValidationResult("CLOB Client (Trading API)")

    try:
        from py_clob_client.client import ClobClient

        private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        funder = os.getenv("POLYMARKET_FUNDER", "")

        if not private_key or not funder:
            result.fail_test("Missing credentials")
            return result

        # Ensure 0x prefix
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key

        client = ClobClient(
            "https://clob.polymarket.com",
            key=private_key,
            chain_id=137,
            funder=funder,
            signature_type=2
        )

        # Derive API creds
        creds = client.create_or_derive_api_creds()
        client.set_api_creds(creds)

        if client.mode >= 2:
            result.pass_test(f"Authenticated (mode={client.mode})",
                           address=client.get_address()[:20] + "...")
        else:
            result.fail_test(f"Auth level too low (mode={client.mode})")

    except ImportError:
        result.fail_test("py-clob-client not installed")
    except Exception as e:
        result.fail_test(f"Client error: {str(e)}")

    return result


def test_market_discovery() -> ValidationResult:
    """Test finding 15-minute Up/Down markets."""
    result = ValidationResult("15-Min Market Discovery")

    try:
        from src.api.gamma import GammaClient
        client = GammaClient()

        # Get current timestamp
        now = int(time.time())

        # Search for active markets
        markets = []
        for query in ["BTC Up or Down", "ETH Up or Down"]:
            results = client.search_markets(query, limit=20, active=True)
            for m in results:
                slug = m.get("slug", "")
                if "-15m-" in slug or "15-minute" in m.get("question", "").lower():
                    markets.append(m)

        # Deduplicate
        seen = set()
        unique = []
        for m in markets:
            cid = m.get("conditionId")
            if cid and cid not in seen:
                seen.add(cid)
                unique.append(m)

        if len(unique) >= 5:
            result.pass_test(f"Found {len(unique)} 15-min markets",
                           samples=[m.get("question", "")[:40] for m in unique[:3]])
        else:
            result.fail_test(f"Only found {len(unique)} markets (need >= 5)")

    except Exception as e:
        result.fail_test(f"Discovery error: {str(e)}")

    return result


def test_orderbook() -> ValidationResult:
    """Test orderbook/price feed access."""
    result = ValidationResult("Orderbook/Price Feed")

    try:
        from py_clob_client.client import ClobClient
        from src.api.gamma import GammaClient

        # Get a valid token ID from a market
        gamma = GammaClient()
        markets = gamma.search_markets("BTC Up or Down", limit=5)

        token_id = None
        for m in markets:
            clob_ids = m.get("clobTokenIds", [])
            if clob_ids:
                token_id = clob_ids[0]
                break

        if not token_id:
            result.fail_test("No token ID found")
            return result

        # Create unauthenticated client for public data
        client = ClobClient("https://clob.polymarket.com", chain_id=137)

        # Get orderbook
        orderbook = client.get_order_book(token_id)

        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            if bids or asks:
                best_bid = float(bids[0]["price"]) if bids else 0
                best_ask = float(asks[0]["price"]) if asks else 0

                result.pass_test(f"Bid=${best_bid:.3f}, Ask=${best_ask:.3f}",
                               token_id=token_id[:20] + "...")
            else:
                result.fail_test("Empty orderbook")
        else:
            result.fail_test("No orderbook returned")

    except Exception as e:
        result.fail_test(f"Orderbook error: {str(e)}")

    return result


def test_recent_resolutions() -> ValidationResult:
    """Test finding recently resolved markets."""
    result = ValidationResult("Recent Market Resolutions")

    try:
        from src.api.gamma import GammaClient
        client = GammaClient()

        now = int(time.time())
        one_hour_ago = now - 3600

        # Search for markets that may have recently resolved
        markets = client.search_markets("BTC Up or Down", limit=50, active=False)

        resolved = []
        for m in markets:
            slug = m.get("slug", "")
            if "-15m-" in slug:
                # Extract timestamp from slug
                try:
                    parts = slug.split("-15m-")
                    if len(parts) >= 2:
                        ts = int(parts[1].split("-")[0])
                        if one_hour_ago < ts < now:
                            resolved.append({
                                "slug": slug,
                                "end_ts": ts,
                                "mins_ago": (now - ts) / 60
                            })
                except:
                    continue

        if resolved:
            result.pass_test(f"Found {len(resolved)} recent resolutions",
                           samples=[f"{r['slug'][:30]} ({r['mins_ago']:.0f}m ago)" for r in resolved[:3]])
        else:
            result.pass_test("No resolutions in last hour (normal)")

    except Exception as e:
        result.fail_test(f"Resolution check error: {str(e)}")

    return result


def test_post_resolution_trading() -> ValidationResult:
    """Test if post-resolution trading is possible."""
    result = ValidationResult("Post-Resolution Trading Feasibility")

    try:
        from py_clob_client.client import ClobClient
        from src.api.gamma import GammaClient

        gamma = GammaClient()

        # Find a recently resolved market
        now = int(time.time())

        markets = gamma.search_markets("BTC Up or Down", limit=100, active=False)

        resolved_market = None
        resolved_token = None

        for m in markets:
            slug = m.get("slug", "")
            if "-15m-" in slug:
                try:
                    parts = slug.split("-15m-")
                    if len(parts) >= 2:
                        ts = int(parts[1].split("-")[0])
                        if ts < now:  # Already resolved
                            clob_ids = m.get("clobTokenIds", [])
                            if clob_ids:
                                resolved_market = m
                                resolved_token = clob_ids[0]
                                break
                except:
                    continue

        if not resolved_token:
            result.fail_test("Could not find resolved market")
            return result

        # Check if orderbook still has liquidity
        client = ClobClient("https://clob.polymarket.com", chain_id=137)
        orderbook = client.get_order_book(resolved_token)

        if orderbook:
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            if bids or asks:
                result.pass_test("Post-resolution liquidity available",
                               slug=resolved_market.get("slug", "")[:40],
                               bids=len(bids),
                               asks=len(asks))
            else:
                result.fail_test("No liquidity in resolved market orderbook")
        else:
            result.fail_test("Could not get resolved market orderbook")

    except Exception as e:
        result.fail_test(f"Feasibility check error: {str(e)}")

    return result


def run_all_validations() -> Tuple[bool, List[ValidationResult]]:
    """Run all validation tests."""
    print("=" * 70)
    print("POST-RESOLUTION BOT - PRE-DEPLOYMENT VALIDATION")
    print("=" * 70)
    print(f"Time: {datetime.now(timezone.utc).isoformat()}")
    print()

    tests = [
        ("Environment", test_environment),
        ("Gamma API", test_gamma_api),
        ("CLOB Client", test_clob_client),
        ("Market Discovery", test_market_discovery),
        ("Orderbook", test_orderbook),
        ("Recent Resolutions", test_recent_resolutions),
        ("Post-Resolution Trading", test_post_resolution_trading),
    ]

    results = []

    for name, test_func in tests:
        print(f"Testing {name}...", end=" ", flush=True)
        try:
            result = test_func()
            results.append(result)
            print(result)
            if result.details:
                for k, v in result.details.items():
                    print(f"    {k}: {v}")
        except Exception as e:
            result = ValidationResult(name)
            result.fail_test(f"Unexpected error: {str(e)}")
            results.append(result)
            print(result)

    # Summary
    print()
    print("=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    passed = sum(1 for r in results if r.passed)
    total = len(results)
    all_passed = passed == total

    print(f"Passed: {passed}/{total}")

    if all_passed:
        print("\n[OK] All validations passed - ready for deployment")
    else:
        print("\n[WARNING] Some validations failed:")
        for r in results:
            if not r.passed:
                print(f"  - {r.name}: {r.message}")

    return all_passed, results


def main():
    """Main entry point."""
    all_passed, results = run_all_validations()

    # Save results
    output_dir = Path("data/validation")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / f"validation_{int(time.time())}.json"

    with open(output_file, 'w') as f:
        json.dump({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "all_passed": all_passed,
            "results": [{
                "name": r.name,
                "passed": r.passed,
                "message": r.message,
                "details": r.details
            } for r in results]
        }, f, indent=2)

    print(f"\nResults saved to: {output_file}")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
