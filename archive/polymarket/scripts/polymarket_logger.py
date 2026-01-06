#!/usr/bin/env python3
"""
Polymarket Data Logger

Captures real-time order book snapshots from Polymarket CLOB REST API.
Focuses on 15-minute crypto markets (BTC/ETH Up or Down).

Usage:
    python polymarket_logger.py --region tokyo
    python polymarket_logger.py --region us-east --log-dir /data/logs

Data Captured:
    - Order book snapshots (best bid/ask, depth) - polled every 1 second
    - Market discovery (15-min markets)
"""

import argparse
import json
import os
import signal
import sys
import threading
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging.rotating_logger import RotatingJSONLLogger


class Market15MinTracker:
    """
    Tracks and discovers 15-minute crypto markets.

    Uses direct slug construction to find markets:
    - btc-updown-15m-{timestamp}
    - eth-updown-15m-{timestamp}
    """

    def __init__(self, gamma_client=None):
        """Initialize tracker."""
        if gamma_client is None:
            try:
                from src.api import GammaClient
                self.gamma = GammaClient()
            except Exception as e:
                print(f"Warning: Could not initialize GammaClient: {e}")
                self.gamma = None
        else:
            self.gamma = gamma_client

        # Active markets cache: condition_id -> market_info
        self._markets: Dict[str, dict] = {}
        self._lock = threading.Lock()
        self._last_scan = 0
        self._scan_interval = 300  # Rescan every 5 minutes

    def scan_markets(self) -> List[dict]:
        """
        Scan for active 15-minute markets.

        Returns:
            List of market dicts with token_ids
        """
        if self.gamma is None:
            return []

        now = time.time()

        # Use cached results if recent
        if now - self._last_scan < self._scan_interval:
            with self._lock:
                return list(self._markets.values())

        markets = []
        seen_ids = set()

        # Calculate next 15-minute windows (next 2 hours)
        windows = self._get_upcoming_windows(8)

        # Try to fetch markets for each window
        for asset in ["btc", "eth"]:
            for window_ts in windows:
                slug = f"{asset}-updown-15m-{window_ts}"
                try:
                    market_data = self.gamma.get_market_by_slug(slug)
                    if market_data and market_data.get("active"):
                        market = self._parse_market(market_data)
                        if market and market["condition_id"] not in seen_ids:
                            markets.append(market)
                            seen_ids.add(market["condition_id"])
                except Exception:
                    continue

                time.sleep(0.05)

        # Update cache
        with self._lock:
            self._markets = {m["condition_id"]: m for m in markets}
            self._last_scan = now

        return markets

    def _get_upcoming_windows(self, count: int) -> List[int]:
        """Get next N 15-minute window timestamps."""
        now = datetime.now(timezone.utc)
        windows = []

        # Start from next window
        current_minute = now.minute
        next_window_minute = ((current_minute // 15) + 1) * 15

        window_time = now.replace(minute=0, second=0, microsecond=0)
        if next_window_minute >= 60:
            window_time = window_time.replace(hour=(now.hour + 1) % 24)
            next_window_minute = 0
        window_time = window_time.replace(minute=next_window_minute)

        # Generate windows
        for i in range(count):
            windows.append(int(window_time.timestamp()))
            # Add 15 minutes
            window_time = datetime.fromtimestamp(
                window_time.timestamp() + 900,
                tz=timezone.utc
            )

        return windows

    def _parse_market(self, data: dict) -> Optional[dict]:
        """Parse market data into tracking format."""
        try:
            clob_ids = data.get("clobTokenIds", [])

            # Handle case where clobTokenIds is a JSON string
            if isinstance(clob_ids, str):
                clob_ids = json.loads(clob_ids)

            if len(clob_ids) < 2:
                return None

            return {
                "condition_id": data.get("conditionId", ""),
                "slug": data.get("slug", ""),
                "question": data.get("question", ""),
                "yes_token_id": clob_ids[0],
                "no_token_id": clob_ids[1],
                "end_date": data.get("endDateIso", ""),
            }
        except Exception:
            return None

    def get_token_ids(self) -> List[str]:
        """Get all tracked token IDs (YES and NO)."""
        with self._lock:
            token_ids = []
            for market in self._markets.values():
                token_ids.append(market["yes_token_id"])
                token_ids.append(market["no_token_id"])
            return token_ids

    def get_market_for_token(self, token_id: str) -> Optional[dict]:
        """Get market info for a token ID."""
        with self._lock:
            for market in self._markets.values():
                if token_id in [market["yes_token_id"], market["no_token_id"]]:
                    return market
            return None


class CLOBRestClient:
    """Simple REST client for Polymarket CLOB API."""

    BASE_URL = "https://clob.polymarket.com"

    def __init__(self, timeout: float = 5.0):
        self.timeout = timeout
        self.session = requests.Session()

    def get_order_book(self, token_id: str) -> Optional[dict]:
        """
        Get order book for a token.

        Args:
            token_id: The CLOB token ID

        Returns:
            Order book dict with bids, asks, timestamp
        """
        try:
            url = f"{self.BASE_URL}/book?token_id={token_id}"
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return None


class PolymarketLogger:
    """
    Logs Polymarket order book data using REST API polling.

    Features:
    - Order book snapshots every ~1 second per market
    - 15-minute market discovery
    - Hourly gzip rotation
    - Health monitoring
    """

    def __init__(
        self,
        region: str = "unknown",
        log_dir: str = "/data/logs",
        health_dir: str = "/data/logs/health",
        poll_interval: float = 1.0,
    ):
        """
        Initialize the Polymarket logger.

        Args:
            region: Region identifier (e.g., "tokyo", "us-east")
            log_dir: Directory for log files
            health_dir: Directory for health status files
            poll_interval: Seconds between polling each market
        """
        self.region = region
        self.log_dir = Path(log_dir)
        self.health_dir = Path(health_dir)
        self.poll_interval = poll_interval

        # Ensure directories exist
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.health_dir.mkdir(parents=True, exist_ok=True)

        # Initialize logger
        self.book_logger = RotatingJSONLLogger(
            base_dir=str(self.log_dir),
            prefix="polymarket_books",
            rotation_interval_seconds=3600,
            compress=True,
        )

        # Initialize market tracker
        self.market_tracker = Market15MinTracker()

        # REST client
        self.clob = CLOBRestClient()

        # State
        self._running = False
        self._lock = threading.Lock()
        self._poll_thread = None
        self._scan_thread = None
        self._health_thread = None

        # Stats
        self.started_at = None
        self.records_logged = 0
        self.last_poll_ts = 0
        self.markets_tracked = 0
        self.api_errors = 0

    def _poll_loop(self) -> None:
        """Main polling loop for order books."""
        while self._running:
            try:
                token_ids = self.market_tracker.get_token_ids()

                if not token_ids:
                    time.sleep(5)  # Wait for markets to be discovered
                    continue

                # Poll each token
                for token_id in token_ids:
                    if not self._running:
                        break

                    try:
                        book = self.clob.get_order_book(token_id)
                        if book:
                            self._log_order_book(token_id, book)
                    except Exception as e:
                        with self._lock:
                            self.api_errors += 1

                    # Small delay between requests to avoid rate limiting
                    time.sleep(max(0.05, self.poll_interval / max(len(token_ids), 1)))

            except Exception as e:
                print(f"Error in poll loop: {e}")
                time.sleep(1)

    def _log_order_book(self, token_id: str, book: dict) -> None:
        """Log an order book snapshot."""
        ts_received = int(time.time() * 1000)

        # Parse exchange timestamp if available
        ts_exchange = int(book.get("timestamp", ts_received))
        latency_ms = ts_received - ts_exchange

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        # Get best bid/ask
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        best_bid_size = float(bids[0].get("size", 0)) if bids else 0.0
        best_ask_size = float(asks[0].get("size", 0)) if asks else 0.0

        # Calculate metrics
        mid = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask < 1 else 0.5
        spread = best_ask - best_bid

        # Get market info
        market = self.market_tracker.get_market_for_token(token_id)

        # Build log record
        record = {
            "ts_received": ts_received,
            "ts_exchange": ts_exchange,
            "latency_ms": latency_ms,
            "token_id": token_id,
            "best_bid": best_bid,
            "best_bid_size": best_bid_size,
            "best_ask": best_ask,
            "best_ask_size": best_ask_size,
            "mid": round(mid, 6),
            "spread": round(spread, 6),
            "bid_depth": len(bids),
            "ask_depth": len(asks),
            "region": self.region,
        }

        # Add market context if available
        if market:
            record["condition_id"] = market["condition_id"]
            record["slug"] = market["slug"]

        # Write to log
        self.book_logger.write(record)

        with self._lock:
            self.records_logged += 1
            self.last_poll_ts = ts_received

    def _scan_loop(self) -> None:
        """Periodically scan for new markets."""
        while self._running:
            try:
                markets = self.market_tracker.scan_markets()
                with self._lock:
                    self.markets_tracked = len(markets)

            except Exception as e:
                print(f"Error in scan loop: {e}")

            # Sleep 5 minutes between scans
            for _ in range(300):
                if not self._running:
                    break
                time.sleep(1)

    def _health_loop(self) -> None:
        """Periodically write health status."""
        while self._running:
            try:
                self._write_health_status()
            except Exception as e:
                print(f"Error writing health: {e}")

            # Sleep 10 seconds
            for _ in range(100):
                if not self._running:
                    break
                time.sleep(0.1)

    def _write_health_status(self) -> None:
        """Write health status to file."""
        now = datetime.utcnow()
        now_ms = int(time.time() * 1000)

        with self._lock:
            poll_age = (now_ms - self.last_poll_ts) / 1000.0 if self.last_poll_ts else 999

        health = {
            "status": "healthy" if self._is_healthy() else "unhealthy",
            "last_update": now.isoformat() + "Z",
            "uptime_seconds": int(time.time() - self.started_at) if self.started_at else 0,
            "region": self.region,
            "polling": {
                "records_logged": self.records_logged,
                "seconds_since_update": round(poll_age, 1),
                "api_errors": self.api_errors,
            },
            "markets_tracked": self.markets_tracked,
        }

        # Write to file
        health_path = self.health_dir / "polymarket_logger.json"
        with open(health_path, 'w') as f:
            json.dump(health, f, indent=2)

    def _is_healthy(self) -> bool:
        """Check if logger is healthy."""
        now_ms = int(time.time() * 1000)

        # Check we're polling successfully (within 30 seconds)
        with self._lock:
            if self.last_poll_ts > 0:
                poll_age = (now_ms - self.last_poll_ts) / 1000.0
                if poll_age > 30:
                    return False
            elif self.started_at and (time.time() - self.started_at) > 30:
                # Should have polls by now
                return False

        return True

    def start(self) -> None:
        """Start the logger."""
        if self._running:
            print("Logger already running")
            return

        self._running = True
        self.started_at = time.time()

        print(f"Starting Polymarket Logger (region: {self.region})")
        print(f"Log directory: {self.log_dir}")
        print(f"Poll interval: {self.poll_interval}s")
        print()

        # Initial market scan
        print("Scanning for 15-minute markets...")
        markets = self.market_tracker.scan_markets()
        print(f"  Found {len(markets)} active markets")
        self.markets_tracked = len(markets)

        for m in markets[:5]:
            print(f"    - {m['slug']}")
        if len(markets) > 5:
            print(f"    ... and {len(markets) - 5} more")

        token_ids = self.market_tracker.get_token_ids()
        print(f"  Tracking {len(token_ids)} token IDs")

        # Start poll thread
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()

        # Start scan thread (for discovering new markets)
        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()

        # Start health thread
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True)
        self._health_thread.start()

        print()
        print("Logger started. Polling order books...")

    def stop(self) -> None:
        """Stop the logger."""
        print("\nStopping logger...")

        self._running = False

        # Close logger
        self.book_logger.close()

        print()
        print(f"Logger stopped.")
        print(f"  Records logged: {self.records_logged}")
        print(f"  Markets tracked: {self.markets_tracked}")
        print(f"  API errors: {self.api_errors}")

    def run_forever(self) -> None:
        """Run until interrupted."""
        self.start()

        try:
            while self._running:
                time.sleep(1)

                # Periodic status (every 60 seconds)
                if int(time.time()) % 60 == 0:
                    self._print_status()

        except KeyboardInterrupt:
            print("\nInterrupted by user")
        finally:
            self.stop()

    def _print_status(self) -> None:
        """Print current status."""
        uptime = int(time.time() - self.started_at) if self.started_at else 0
        status = "healthy" if self._is_healthy() else "unhealthy"

        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
              f"Records: {self.records_logged:,} | "
              f"Markets: {self.markets_tracked} | "
              f"Errors: {self.api_errors} | "
              f"Status: {status} | "
              f"Uptime: {uptime}s")


def main():
    parser = argparse.ArgumentParser(description="Polymarket Data Logger")
    parser.add_argument(
        "--region",
        type=str,
        default="unknown",
        help="Region identifier (e.g., tokyo, us-east)"
    )
    parser.add_argument(
        "--log-dir",
        type=str,
        default="/data/logs",
        help="Directory for log files"
    )
    parser.add_argument(
        "--health-dir",
        type=str,
        default=None,
        help="Directory for health status files (defaults to log-dir/health)"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between polling each market (default: 1.0)"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Run in test mode (60 seconds)"
    )

    args = parser.parse_args()

    # Set health_dir default based on log_dir
    health_dir = args.health_dir if args.health_dir else f"{args.log_dir}/health"

    # Create logger
    logger = PolymarketLogger(
        region=args.region,
        log_dir=args.log_dir,
        health_dir=health_dir,
        poll_interval=args.poll_interval,
    )

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}")
        logger.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    if args.test:
        # Test mode: run for 60 seconds
        print("Running in TEST mode (60 seconds)...")
        logger.start()

        for i in range(60):
            time.sleep(1)
            if i % 15 == 0:
                print(f"  {i}s - Records: {logger.records_logged}, "
                      f"Markets: {logger.markets_tracked}, "
                      f"Errors: {logger.api_errors}")

        logger.stop()

        # Print final stats
        print("\n--- Final Stats ---")
        print(f"Records logged: {logger.records_logged}")
        print(f"Markets tracked: {logger.markets_tracked}")
        print(f"API errors: {logger.api_errors}")

    else:
        # Production mode: run forever
        logger.run_forever()


if __name__ == "__main__":
    main()
