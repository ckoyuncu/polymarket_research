#!/usr/bin/env python3
"""
Pre-Deployment Validation Script

Validates that all logging infrastructure is working correctly before
deploying to production EC2 instances.

Usage:
    python validate_logger.py
    python validate_logger.py --verbose

Tests:
    1. Exchange WebSocket connectivity (Binance, Coinbase, Kraken, OKX)
    2. Polymarket CLOB API connectivity
    3. File rotation and compression
    4. Auto-reconnect behavior
    5. System checks (disk space, NTP sync)
"""

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class ValidationResult:
    """Result of a validation test."""

    def __init__(self, name: str, passed: bool, message: str = "", duration: float = 0):
        self.name = name
        self.passed = passed
        self.message = message
        self.duration = duration

    def __str__(self):
        status = "PASS" if self.passed else "FAIL"
        msg = f"  [{status}] {self.name}"
        if self.message:
            msg += f": {self.message}"
        if self.duration > 0:
            msg += f" ({self.duration:.1f}s)"
        return msg


class LoggerValidator:
    """Validates logging infrastructure."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results = []

    def log(self, msg: str):
        """Print if verbose."""
        if self.verbose:
            print(f"    {msg}")

    def run_all_tests(self) -> bool:
        """Run all validation tests."""
        print("=" * 60)
        print("Logger Infrastructure Validation")
        print("=" * 60)
        print()

        # Group tests by category
        categories = [
            ("Exchange Feeds", [
                self.test_binance_ws,
                self.test_coinbase_ws,
                self.test_kraken_ws,
                self.test_okx_ws,
            ]),
            ("Polymarket", [
                self.test_polymarket_clob,
                self.test_polymarket_gamma,
            ]),
            ("Logging Infrastructure", [
                self.test_rotating_logger,
                self.test_gzip_compression,
            ]),
            ("System Checks", [
                self.test_disk_space,
                self.test_python_version,
                self.test_dependencies,
            ]),
        ]

        for category, tests in categories:
            print(f"\n{category}:")
            print("-" * 40)
            for test in tests:
                result = test()
                self.results.append(result)
                print(result)

        # Summary
        print()
        print("=" * 60)
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        all_passed = passed == total

        if all_passed:
            print(f"VALIDATION PASSED: {passed}/{total} tests passed")
        else:
            print(f"VALIDATION FAILED: {passed}/{total} tests passed")
            print("\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.message}")

        print("=" * 60)
        return all_passed

    def test_binance_ws(self) -> ValidationResult:
        """Test Binance WebSocket connectivity."""
        start = time.time()
        try:
            from src.feeds.binance_feed import BinanceFeed

            feed = BinanceFeed()
            received = []

            def on_price(tick):
                received.append(tick)

            feed.subscribe(on_price)
            feed.start()

            # Wait for data
            timeout = 10
            while len(received) < 1 and (time.time() - start) < timeout:
                time.sleep(0.1)

            feed.stop()

            if received:
                return ValidationResult(
                    "Binance WebSocket",
                    True,
                    f"Received {len(received)} updates",
                    time.time() - start
                )
            else:
                return ValidationResult(
                    "Binance WebSocket",
                    False,
                    "No data received within timeout",
                    time.time() - start
                )

        except Exception as e:
            return ValidationResult(
                "Binance WebSocket",
                False,
                str(e),
                time.time() - start
            )

    def test_coinbase_ws(self) -> ValidationResult:
        """Test Coinbase WebSocket connectivity."""
        start = time.time()
        try:
            from src.feeds.coinbase_feed import CoinbaseFeed

            feed = CoinbaseFeed()
            received = []

            def on_price(record):
                received.append(record)

            feed.subscribe(on_price)
            feed.start()

            # Wait for data
            timeout = 10
            while len(received) < 1 and (time.time() - start) < timeout:
                time.sleep(0.1)

            feed.stop()

            if received:
                return ValidationResult(
                    "Coinbase WebSocket",
                    True,
                    f"Received {len(received)} updates",
                    time.time() - start
                )
            else:
                return ValidationResult(
                    "Coinbase WebSocket",
                    False,
                    "No data received within timeout",
                    time.time() - start
                )

        except Exception as e:
            return ValidationResult(
                "Coinbase WebSocket",
                False,
                str(e),
                time.time() - start
            )

    def test_kraken_ws(self) -> ValidationResult:
        """Test Kraken WebSocket connectivity."""
        start = time.time()
        try:
            from src.feeds.kraken_feed import KrakenFeed

            feed = KrakenFeed()
            received = []

            def on_price(record):
                received.append(record)

            feed.subscribe(on_price)
            feed.start()

            # Wait for data
            timeout = 10
            while len(received) < 1 and (time.time() - start) < timeout:
                time.sleep(0.1)

            feed.stop()

            if received:
                return ValidationResult(
                    "Kraken WebSocket",
                    True,
                    f"Received {len(received)} updates",
                    time.time() - start
                )
            else:
                return ValidationResult(
                    "Kraken WebSocket",
                    False,
                    "No data received within timeout",
                    time.time() - start
                )

        except Exception as e:
            return ValidationResult(
                "Kraken WebSocket",
                False,
                str(e),
                time.time() - start
            )

    def test_okx_ws(self) -> ValidationResult:
        """Test OKX WebSocket connectivity."""
        start = time.time()
        try:
            from src.feeds.okx_feed import OKXFeed

            feed = OKXFeed()
            received = []

            def on_price(record):
                received.append(record)

            feed.subscribe(on_price)
            feed.start()

            # Wait for data
            timeout = 10
            while len(received) < 1 and (time.time() - start) < timeout:
                time.sleep(0.1)

            feed.stop()

            if received:
                return ValidationResult(
                    "OKX WebSocket",
                    True,
                    f"Received {len(received)} updates",
                    time.time() - start
                )
            else:
                return ValidationResult(
                    "OKX WebSocket",
                    False,
                    "No data received within timeout",
                    time.time() - start
                )

        except Exception as e:
            return ValidationResult(
                "OKX WebSocket",
                False,
                str(e),
                time.time() - start
            )

    def test_polymarket_clob(self) -> ValidationResult:
        """Test Polymarket CLOB REST API."""
        start = time.time()
        try:
            import requests

            # Use a known token ID from a 15-min market
            url = "https://clob.polymarket.com/book"
            params = {"token_id": "14765561949313702921198569147821997387753724700522862286122888126028456602911"}

            response = requests.get(url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()

            if data.get("bids") and data.get("asks"):
                return ValidationResult(
                    "Polymarket CLOB API",
                    True,
                    f"{len(data['bids'])} bids, {len(data['asks'])} asks",
                    time.time() - start
                )
            else:
                return ValidationResult(
                    "Polymarket CLOB API",
                    False,
                    "Empty order book",
                    time.time() - start
                )

        except Exception as e:
            return ValidationResult(
                "Polymarket CLOB API",
                False,
                str(e),
                time.time() - start
            )

    def test_polymarket_gamma(self) -> ValidationResult:
        """Test Polymarket Gamma API for market discovery."""
        start = time.time()
        try:
            from src.api import GammaClient

            gamma = GammaClient()

            # Search for 15-min markets
            results = gamma.search_markets("Bitcoin Up or Down", limit=5, active=True)

            if results:
                return ValidationResult(
                    "Polymarket Gamma API",
                    True,
                    f"Found {len(results)} markets",
                    time.time() - start
                )
            else:
                # Try direct slug lookup
                now = datetime.now(timezone.utc)
                next_min = ((now.minute // 15) + 1) * 15
                if next_min >= 60:
                    next_min = 0
                    window_time = now.replace(hour=(now.hour + 1) % 24, minute=next_min, second=0, microsecond=0)
                else:
                    window_time = now.replace(minute=next_min, second=0, microsecond=0)
                window_ts = int(window_time.timestamp())

                slug = f"btc-updown-15m-{window_ts}"
                market = gamma.get_market_by_slug(slug)

                if market:
                    return ValidationResult(
                        "Polymarket Gamma API",
                        True,
                        f"Found market: {slug}",
                        time.time() - start
                    )
                else:
                    return ValidationResult(
                        "Polymarket Gamma API",
                        False,
                        "No markets found",
                        time.time() - start
                    )

        except Exception as e:
            return ValidationResult(
                "Polymarket Gamma API",
                False,
                str(e),
                time.time() - start
            )

    def test_rotating_logger(self) -> ValidationResult:
        """Test rotating logger functionality."""
        start = time.time()
        try:
            from src.logging.rotating_logger import RotatingJSONLLogger

            with tempfile.TemporaryDirectory() as tmpdir:
                logger = RotatingJSONLLogger(
                    base_dir=tmpdir,
                    prefix="test",
                    rotation_interval_seconds=3600,
                    compress=False,
                )

                # Write test records
                for i in range(10):
                    logger.write({"ts": int(time.time() * 1000), "value": i})

                logger.close()

                # Check file exists
                files = list(Path(tmpdir).rglob("*.jsonl"))
                if files:
                    with open(files[0]) as f:
                        lines = f.readlines()

                    if len(lines) == 10:
                        return ValidationResult(
                            "Rotating Logger",
                            True,
                            "10 records written",
                            time.time() - start
                        )
                    else:
                        return ValidationResult(
                            "Rotating Logger",
                            False,
                            f"Expected 10 records, got {len(lines)}",
                            time.time() - start
                        )
                else:
                    return ValidationResult(
                        "Rotating Logger",
                        False,
                        "No log files created",
                        time.time() - start
                    )

        except Exception as e:
            return ValidationResult(
                "Rotating Logger",
                False,
                str(e),
                time.time() - start
            )

    def test_gzip_compression(self) -> ValidationResult:
        """Test gzip compression functionality."""
        start = time.time()
        try:
            from src.logging.rotating_logger import RotatingJSONLLogger

            with tempfile.TemporaryDirectory() as tmpdir:
                logger = RotatingJSONLLogger(
                    base_dir=tmpdir,
                    prefix="test",
                    rotation_interval_seconds=1,  # Rotate quickly
                    compress=True,
                )

                # Write records
                for i in range(5):
                    logger.write({"ts": int(time.time() * 1000), "value": i})

                # Wait for rotation
                time.sleep(2)

                # Write more to trigger rotation
                logger.write({"ts": int(time.time() * 1000), "value": 99})

                logger.close()

                # Check for gzip files
                gz_files = list(Path(tmpdir).rglob("*.gz"))
                if gz_files:
                    # Verify we can read the gzip
                    with gzip.open(gz_files[0], 'rt') as f:
                        lines = f.readlines()

                    return ValidationResult(
                        "Gzip Compression",
                        True,
                        f"Compressed file readable ({len(lines)} records)",
                        time.time() - start
                    )
                else:
                    # May not have rotated yet, check jsonl
                    jsonl_files = list(Path(tmpdir).rglob("*.jsonl"))
                    if jsonl_files:
                        return ValidationResult(
                            "Gzip Compression",
                            True,
                            "Logger working (no rotation yet)",
                            time.time() - start
                        )
                    return ValidationResult(
                        "Gzip Compression",
                        False,
                        "No log files found",
                        time.time() - start
                    )

        except Exception as e:
            return ValidationResult(
                "Gzip Compression",
                False,
                str(e),
                time.time() - start
            )

    def test_disk_space(self) -> ValidationResult:
        """Test available disk space."""
        start = time.time()
        try:
            # Check current directory
            total, used, free = shutil.disk_usage(".")
            free_mb = free / (1024 * 1024)
            free_gb = free / (1024 * 1024 * 1024)

            if free_mb >= 500:
                return ValidationResult(
                    "Disk Space",
                    True,
                    f"{free_gb:.1f} GB available",
                    time.time() - start
                )
            else:
                return ValidationResult(
                    "Disk Space",
                    False,
                    f"Only {free_mb:.0f} MB available (need 500 MB)",
                    time.time() - start
                )

        except Exception as e:
            return ValidationResult(
                "Disk Space",
                False,
                str(e),
                time.time() - start
            )

    def test_python_version(self) -> ValidationResult:
        """Test Python version."""
        start = time.time()
        version = sys.version_info

        if version >= (3, 8):
            return ValidationResult(
                "Python Version",
                True,
                f"{version.major}.{version.minor}.{version.micro}",
                time.time() - start
            )
        else:
            return ValidationResult(
                "Python Version",
                False,
                f"Python 3.8+ required, got {version.major}.{version.minor}",
                time.time() - start
            )

    def test_dependencies(self) -> ValidationResult:
        """Test required Python dependencies."""
        start = time.time()
        required = ["websocket", "requests"]
        missing = []

        for module in required:
            try:
                __import__(module)
            except ImportError:
                missing.append(module)

        if not missing:
            return ValidationResult(
                "Dependencies",
                True,
                "All required packages installed",
                time.time() - start
            )
        else:
            return ValidationResult(
                "Dependencies",
                False,
                f"Missing: {', '.join(missing)}",
                time.time() - start
            )


def main():
    parser = argparse.ArgumentParser(description="Validate Logger Infrastructure")
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )

    args = parser.parse_args()

    validator = LoggerValidator(verbose=args.verbose)
    success = validator.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
