#!/usr/bin/env python3
"""
Historical Binance Kline Fetcher

Fetches historical 1-minute klines (OHLCV) from Binance for BTC and ETH.
Designed to backfill price data around Account88888's trades.

Usage:
    # Fetch last 24 hours
    python fetch_historical_binance.py

    # Fetch specific date range
    python fetch_historical_binance.py --start 2025-12-01 --end 2025-12-31

    # Fetch around specific timestamps (from trade file)
    python fetch_historical_binance.py --trades data/account88888_trades.csv

    # Output to specific file
    python fetch_historical_binance.py --output data/binance_klines.csv

API Limits:
    - Binance allows 1000 klines per request
    - Rate limit: 1200 requests/minute (we use conservative 10 req/sec)
    - No API key required for public klines endpoint
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests


class BinanceHistoricalFetcher:
    """
    Fetches historical kline data from Binance.

    Binance Kline format:
    [
        open_time,      # 0: Unix timestamp (ms)
        open,           # 1: Open price
        high,           # 2: High price
        low,            # 3: Low price
        close,          # 4: Close price
        volume,         # 5: Volume
        close_time,     # 6: Close time (ms)
        quote_volume,   # 7: Quote asset volume
        trades,         # 8: Number of trades
        taker_buy_vol,  # 9: Taker buy base volume
        taker_buy_quote,# 10: Taker buy quote volume
        ignore          # 11: Ignore
    ]
    """

    BASE_URL = "https://api.binance.com"
    KLINES_ENDPOINT = "/api/v3/klines"

    # Symbols to fetch
    SYMBOLS = ["BTCUSDT", "ETHUSDT"]

    def __init__(self, rate_limit: float = 0.1):
        """
        Initialize fetcher.

        Args:
            rate_limit: Seconds between requests (default 0.1 = 10 req/sec)
        """
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.last_request_time = 0

    def _rate_limit(self):
        """Enforce rate limiting."""
        now = time.time()
        elapsed = now - self.last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self.last_request_time = time.time()

    def fetch_klines(
        self,
        symbol: str,
        interval: str = "1m",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
    ) -> List[List]:
        """
        Fetch klines from Binance.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Kline interval (default "1m")
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            limit: Number of klines (max 1000)

        Returns:
            List of kline data
        """
        self._rate_limit()

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }

        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        url = f"{self.BASE_URL}{self.KLINES_ENDPOINT}"

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching klines: {e}")
            return []

    def fetch_range(
        self,
        symbol: str,
        start_time: int,
        end_time: int,
        interval: str = "1m",
    ) -> List[Dict]:
        """
        Fetch all klines in a time range.

        Args:
            symbol: Trading pair
            start_time: Start timestamp (ms)
            end_time: End timestamp (ms)
            interval: Kline interval

        Returns:
            List of kline dicts
        """
        all_klines = []
        current_start = start_time

        # Calculate interval in milliseconds
        interval_ms = self._interval_to_ms(interval)

        while current_start < end_time:
            klines = self.fetch_klines(
                symbol=symbol,
                interval=interval,
                start_time=current_start,
                end_time=end_time,
                limit=1000,
            )

            if not klines:
                break

            for kline in klines:
                all_klines.append(self._parse_kline(symbol, kline))

            # Move to next batch
            last_close_time = klines[-1][6]  # close_time
            current_start = last_close_time + 1

            # Progress indicator
            if len(all_klines) % 10000 == 0:
                dt = datetime.fromtimestamp(current_start / 1000, tz=timezone.utc)
                print(f"  {symbol}: Fetched {len(all_klines):,} klines (up to {dt.strftime('%Y-%m-%d %H:%M')})")

        return all_klines

    def _parse_kline(self, symbol: str, kline: List) -> Dict:
        """Parse raw kline to dict."""
        return {
            "symbol": symbol,
            "open_time": int(kline[0]),
            "open": float(kline[1]),
            "high": float(kline[2]),
            "low": float(kline[3]),
            "close": float(kline[4]),
            "volume": float(kline[5]),
            "close_time": int(kline[6]),
            "quote_volume": float(kline[7]),
            "trades": int(kline[8]),
        }

    def _interval_to_ms(self, interval: str) -> int:
        """Convert interval string to milliseconds."""
        unit = interval[-1]
        value = int(interval[:-1])

        multipliers = {
            "m": 60 * 1000,
            "h": 60 * 60 * 1000,
            "d": 24 * 60 * 60 * 1000,
        }

        return value * multipliers.get(unit, 60 * 1000)


def parse_timestamp(ts_str: str) -> int:
    """Parse timestamp string to milliseconds."""
    # Try various formats
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(ts_str, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue

    # Try Unix timestamp
    try:
        ts = float(ts_str)
        if ts > 1e12:  # Already in ms
            return int(ts)
        return int(ts * 1000)
    except ValueError:
        pass

    raise ValueError(f"Cannot parse timestamp: {ts_str}")


def load_trade_timestamps(trades_file: str) -> List[int]:
    """Load timestamps from trades file."""
    timestamps = []

    with open(trades_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Try common timestamp field names
            ts_str = row.get("timestamp") or row.get("ts") or row.get("time")
            if ts_str:
                try:
                    ts = parse_timestamp(ts_str)
                    timestamps.append(ts)
                except ValueError:
                    continue

    return sorted(set(timestamps))


def get_time_windows_from_trades(
    timestamps: List[int],
    window_before_ms: int = 15 * 60 * 1000,  # 15 minutes
    window_after_ms: int = 5 * 60 * 1000,    # 5 minutes
) -> List[Tuple[int, int]]:
    """
    Get time windows around trade timestamps.

    Merges overlapping windows for efficiency.
    """
    if not timestamps:
        return []

    # Create windows
    windows = []
    for ts in timestamps:
        start = ts - window_before_ms
        end = ts + window_after_ms
        windows.append((start, end))

    # Sort by start time
    windows.sort()

    # Merge overlapping windows
    merged = [windows[0]]
    for start, end in windows[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            # Overlapping, extend
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    return merged


def save_klines_csv(klines: List[Dict], output_file: str):
    """Save klines to CSV file."""
    if not klines:
        print("No klines to save")
        return

    # Sort by symbol and time
    klines.sort(key=lambda k: (k["symbol"], k["open_time"]))

    # Write CSV
    fieldnames = ["symbol", "open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "trades"]

    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(klines)

    print(f"Saved {len(klines):,} klines to {output_file}")


def save_klines_jsonl(klines: List[Dict], output_file: str):
    """Save klines to JSONL file."""
    if not klines:
        print("No klines to save")
        return

    # Sort by symbol and time
    klines.sort(key=lambda k: (k["symbol"], k["open_time"]))

    with open(output_file, 'w') as f:
        for kline in klines:
            f.write(json.dumps(kline) + "\n")

    print(f"Saved {len(klines):,} klines to {output_file}")


def main():
    parser = argparse.ArgumentParser(description="Fetch Historical Binance Klines")
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)"
    )
    parser.add_argument(
        "--trades",
        type=str,
        help="Path to trades CSV file (fetch around trade timestamps)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/binance_klines.csv",
        help="Output file path (default: data/binance_klines.csv)"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        nargs="+",
        default=["BTCUSDT", "ETHUSDT"],
        help="Symbols to fetch (default: BTCUSDT ETHUSDT)"
    )
    parser.add_argument(
        "--interval",
        type=str,
        default="1m",
        help="Kline interval (default: 1m)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["csv", "jsonl"],
        default="csv",
        help="Output format (default: csv)"
    )

    args = parser.parse_args()

    # Determine time range
    if args.trades:
        # Fetch around trade timestamps
        print(f"Loading trades from {args.trades}...")
        timestamps = load_trade_timestamps(args.trades)
        print(f"Found {len(timestamps):,} trade timestamps")

        if not timestamps:
            print("No timestamps found in trades file")
            return

        windows = get_time_windows_from_trades(timestamps)
        print(f"Created {len(windows)} time windows")

        # Calculate total time coverage
        total_minutes = sum((end - start) / 60000 for start, end in windows)
        print(f"Total coverage: {total_minutes:,.0f} minutes")

    elif args.start and args.end:
        # Use explicit date range
        start_ms = parse_timestamp(args.start)
        end_ms = parse_timestamp(args.end)
        windows = [(start_ms, end_ms)]

        start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
        end_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
        print(f"Fetching from {start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')}")

    else:
        # Default: last 24 hours
        end_ms = int(time.time() * 1000)
        start_ms = end_ms - (24 * 60 * 60 * 1000)
        windows = [(start_ms, end_ms)]
        print("Fetching last 24 hours (use --start/--end for custom range)")

    # Create output directory
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Initialize fetcher
    fetcher = BinanceHistoricalFetcher()

    # Fetch klines
    all_klines = []

    for symbol in args.symbols:
        print(f"\nFetching {symbol}...")

        for i, (start_ms, end_ms) in enumerate(windows):
            if len(windows) > 1:
                start_dt = datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
                end_dt = datetime.fromtimestamp(end_ms / 1000, tz=timezone.utc)
                print(f"  Window {i+1}/{len(windows)}: {start_dt.strftime('%Y-%m-%d %H:%M')} - {end_dt.strftime('%Y-%m-%d %H:%M')}")

            klines = fetcher.fetch_range(
                symbol=symbol,
                start_time=start_ms,
                end_time=end_ms,
                interval=args.interval,
            )

            all_klines.extend(klines)
            print(f"  {symbol}: {len(klines):,} klines in this window")

    # Save results
    print(f"\nTotal klines: {len(all_klines):,}")

    if args.format == "jsonl":
        output_file = str(output_path).replace(".csv", ".jsonl") if args.output.endswith(".csv") else args.output
        save_klines_jsonl(all_klines, output_file)
    else:
        save_klines_csv(all_klines, str(output_path))

    # Print summary
    if all_klines:
        min_time = min(k["open_time"] for k in all_klines)
        max_time = max(k["close_time"] for k in all_klines)
        min_dt = datetime.fromtimestamp(min_time / 1000, tz=timezone.utc)
        max_dt = datetime.fromtimestamp(max_time / 1000, tz=timezone.utc)

        print(f"\nData range: {min_dt.strftime('%Y-%m-%d %H:%M')} to {max_dt.strftime('%Y-%m-%d %H:%M')}")

        for symbol in args.symbols:
            symbol_klines = [k for k in all_klines if k["symbol"] == symbol]
            if symbol_klines:
                print(f"  {symbol}: {len(symbol_klines):,} klines")


if __name__ == "__main__":
    main()
