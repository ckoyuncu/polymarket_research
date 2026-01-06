#!/usr/bin/env python3
"""
Multi-Exchange Price Logger

Captures real-time prices from multiple exchanges with latency tracking.
Designed for continuous operation with hourly log rotation.

Usage:
    python multi_exchange_logger.py --region tokyo
    python multi_exchange_logger.py --region us-east --log-dir /data/logs

Exchanges:
    - Binance (BTCUSDT, ETHUSDT)
    - Coinbase (BTC-USD, ETH-USD)
    - Kraken (XBT/USD, ETH/USD)
    - OKX (BTC-USDT, ETH-USDT)
"""

import argparse
import json
import os
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.logging.rotating_logger import RotatingJSONLLogger
from src.feeds.binance_feed import BinanceFeed, PriceTick
from src.feeds.coinbase_feed import CoinbaseFeed
from src.feeds.kraken_feed import KrakenFeed
from src.feeds.okx_feed import OKXFeed
from src.feeds.exchange_base import PriceRecord, get_current_time_ms


class BinanceFeedAdapter:
    """
    Adapter to make existing BinanceFeed compatible with PriceRecord interface.
    """

    def __init__(self):
        self._feed = BinanceFeed()
        self._callbacks = []

    def subscribe(self, callback):
        """Subscribe with PriceRecord callback."""
        def adapter_callback(tick: PriceTick):
            record = PriceRecord(
                exchange="binance",
                symbol=tick.symbol,
                price=tick.price,
                ts_exchange=tick.timestamp,
                ts_received=get_current_time_ms(),
                latency_ms=tick.latency_ms,
                raw_symbol=tick.symbol,
            )
            callback(record)

        self._callbacks.append(callback)
        self._feed.subscribe(adapter_callback)

    def start(self):
        self._feed.start()

    def stop(self):
        self._feed.stop()

    def is_healthy(self, max_age_seconds: int = 10) -> bool:
        return self._feed.is_healthy(max_age_seconds)

    def get_stats(self):
        stats = self._feed.get_stats()
        # Adapt to expected format
        return {
            "exchange": "binance",
            "running": stats.get("running", False),
            "connected": stats.get("running", False) and stats.get("healthy", False),
            "healthy": stats.get("healthy", False),
            "updates_received": stats.get("updates_received", 0),
            "connection_errors": stats.get("connection_errors", 0),
            "reconnects": 0,
            "seconds_since_update": stats.get("seconds_since_update", 0),
            "latency_avg_ms": 0,  # Not tracked in original
            "latency_min_ms": 0,
            "latency_max_ms": 0,
            "symbols_tracked": stats.get("symbols_tracked", 0),
            "prices": stats.get("prices", {}),
        }


class MultiExchangeLogger:
    """
    Aggregates price feeds from multiple exchanges and logs them.

    Features:
    - Connects to 4 exchanges simultaneously
    - Logs prices with latency tracking
    - Hourly gzip rotation
    - Health monitoring
    - Graceful shutdown
    """

    def __init__(
        self,
        region: str = "unknown",
        log_dir: str = "/data/logs",
        health_dir: str = "/data/logs/health",
    ):
        """
        Initialize the multi-exchange logger.

        Args:
            region: Region identifier (e.g., "tokyo", "us-east")
            log_dir: Directory for log files
            health_dir: Directory for health status files
        """
        self.region = region
        self.log_dir = Path(log_dir)
        self.health_dir = Path(health_dir)

        # Ensure directories exist
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.health_dir.mkdir(parents=True, exist_ok=True)

        # Initialize logger
        self.logger = RotatingJSONLLogger(
            base_dir=str(self.log_dir),
            prefix="prices",
            rotation_interval_seconds=3600,
            compress=True,
        )

        # Initialize feeds
        self.feeds = {
            "binance": BinanceFeedAdapter(),
            "coinbase": CoinbaseFeed(),
            "kraken": KrakenFeed(),
            "okx": OKXFeed(),
        }

        # State
        self._running = False
        self._lock = threading.Lock()
        self._health_thread = None

        # Stats
        self.started_at = None
        self.records_logged = 0

    def _on_price(self, record: PriceRecord) -> None:
        """Handle price update from any feed."""
        try:
            # Build log record
            log_record = {
                "ts_received": record.ts_received,
                "ts_exchange": record.ts_exchange,
                "latency_ms": record.latency_ms,
                "exchange": record.exchange,
                "symbol": record.symbol,
                "price": record.price,
                "region": self.region,
            }

            # Add optional fields
            if record.volume_24h is not None:
                log_record["volume_24h"] = record.volume_24h
            if record.raw_symbol and record.raw_symbol != record.symbol:
                log_record["raw_symbol"] = record.raw_symbol

            # Write to log
            self.logger.write(log_record)

            with self._lock:
                self.records_logged += 1

        except Exception as e:
            print(f"Error logging price: {e}")

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

        health = {
            "status": "healthy" if self._is_healthy() else "unhealthy",
            "last_update": now.isoformat() + "Z",
            "uptime_seconds": int(time.time() - self.started_at) if self.started_at else 0,
            "records_logged": self.records_logged,
            "region": self.region,
            "feeds": {},
        }

        for name, feed in self.feeds.items():
            stats = feed.get_stats()
            health["feeds"][name] = {
                "status": "connected" if stats["connected"] else "disconnected",
                "healthy": stats["healthy"],
                "updates_received": stats["updates_received"],
                "latency_avg_ms": stats["latency_avg_ms"],
                "seconds_since_update": round(stats["seconds_since_update"], 1),
            }

        # Write to file
        health_path = self.health_dir / "multi_exchange_logger.json"
        with open(health_path, 'w') as f:
            json.dump(health, f, indent=2)

    def _is_healthy(self) -> bool:
        """Check if logger is healthy."""
        # At least 2 feeds should be healthy
        healthy_count = sum(1 for feed in self.feeds.values() if feed.is_healthy())
        return healthy_count >= 2

    def start(self) -> None:
        """Start all feeds and logging."""
        if self._running:
            print("Logger already running")
            return

        self._running = True
        self.started_at = time.time()

        print(f"Starting Multi-Exchange Logger (region: {self.region})")
        print(f"Log directory: {self.log_dir}")
        print()

        # Subscribe and start each feed
        for name, feed in self.feeds.items():
            feed.subscribe(self._on_price)
            feed.start()
            print(f"  Started {name} feed")

        # Start health thread
        self._health_thread = threading.Thread(target=self._health_loop, daemon=True)
        self._health_thread.start()

        print()
        print("All feeds started. Logging prices...")

    def stop(self) -> None:
        """Stop all feeds and close logger."""
        print("\nStopping logger...")

        self._running = False

        # Stop all feeds
        for name, feed in self.feeds.items():
            feed.stop()
            print(f"  Stopped {name} feed")

        # Close logger
        self.logger.close()

        print()
        print(f"Logger stopped. Total records logged: {self.records_logged}")

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
        healthy = sum(1 for f in self.feeds.values() if f.is_healthy())

        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] "
              f"Records: {self.records_logged:,} | "
              f"Feeds: {healthy}/{len(self.feeds)} healthy | "
              f"Uptime: {uptime}s")


def main():
    parser = argparse.ArgumentParser(description="Multi-Exchange Price Logger")
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
        "--test",
        action="store_true",
        help="Run in test mode (30 seconds)"
    )

    args = parser.parse_args()

    # Set health_dir default based on log_dir
    health_dir = args.health_dir if args.health_dir else f"{args.log_dir}/health"

    # Create logger
    logger = MultiExchangeLogger(
        region=args.region,
        log_dir=args.log_dir,
        health_dir=health_dir,
    )

    # Handle signals for graceful shutdown
    def signal_handler(signum, frame):
        print(f"\nReceived signal {signum}")
        logger.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    if args.test:
        # Test mode: run for 30 seconds
        print("Running in TEST mode (30 seconds)...")
        logger.start()

        for i in range(30):
            time.sleep(1)
            if i % 10 == 0:
                print(f"  {i}s - Records logged: {logger.records_logged}")

        logger.stop()

        # Print final stats
        print("\n--- Final Stats ---")
        for name, feed in logger.feeds.items():
            stats = feed.get_stats()
            print(f"{name}: {stats['updates_received']} updates, "
                  f"avg latency: {stats['latency_avg_ms']}ms")

    else:
        # Production mode: run forever
        logger.run_forever()


if __name__ == "__main__":
    main()
