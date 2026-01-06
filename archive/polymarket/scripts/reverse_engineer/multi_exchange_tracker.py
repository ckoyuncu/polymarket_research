#!/usr/bin/env python3
"""
Multi-Exchange Price Tracker

Tracks prices across multiple exchanges simultaneously to find:
1. Lead-lag relationships (which exchange moves first?)
2. Cross-exchange arbitrage signals
3. Millisecond-level timing differences

Exchanges tracked:
- Binance (primary)
- Coinbase (via REST API)
- Kraken (via REST API)

The hypothesis is that Account88888 may be using a non-Binance exchange
as their signal source, or aggregating multiple exchanges for earlier signals.

Usage:
    python scripts/reverse_engineer/multi_exchange_tracker.py --duration 300

Output:
    data/research/multi_exchange/prices_{timestamp}.json
"""

import json
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import deque
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class PriceTick:
    """Single price observation from an exchange."""
    timestamp: float  # Local receive time
    exchange: str
    symbol: str  # BTC or ETH
    price: float
    exchange_timestamp: Optional[float] = None  # Exchange's timestamp if available

    def to_dict(self):
        return asdict(self)


@dataclass
class LeadLagMeasurement:
    """Measurement of which exchange moved first."""
    timestamp: float
    symbol: str
    direction: str  # "up" or "down"
    leader: str  # Exchange that moved first
    lag_ms: float  # How many ms later the follower moved
    price_move_pct: float


class MultiExchangeTracker:
    """
    Tracks prices across multiple exchanges to find timing edges.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or PROJECT_ROOT / "data" / "research" / "multi_exchange"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Price history per exchange/symbol
        self.prices: Dict[str, Dict[str, deque]] = {
            "binance": {"BTC": deque(maxlen=1000), "ETH": deque(maxlen=1000)},
            "coinbase": {"BTC": deque(maxlen=1000), "ETH": deque(maxlen=1000)},
            "kraken": {"BTC": deque(maxlen=1000), "ETH": deque(maxlen=1000)},
        }

        # Latest prices
        self.latest: Dict[str, Dict[str, float]] = {
            "binance": {},
            "coinbase": {},
            "kraken": {},
        }

        # All ticks for analysis
        self.all_ticks: List[PriceTick] = []
        self.lead_lag_events: List[LeadLagMeasurement] = []

        # Control
        self._running = False
        self._lock = threading.Lock()

        # Stats
        self.stats = {
            "binance_ticks": 0,
            "coinbase_ticks": 0,
            "kraken_ticks": 0,
            "lead_lag_events": 0,
            "start_time": None,
        }

    def fetch_coinbase_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from Coinbase."""
        try:
            pair = f"{symbol}-USD"
            response = requests.get(
                f"https://api.coinbase.com/v2/prices/{pair}/spot",
                timeout=2
            )
            if response.ok:
                data = response.json()
                return float(data["data"]["amount"])
        except Exception:
            pass
        return None

    def fetch_kraken_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from Kraken."""
        try:
            # Kraken uses XBT for Bitcoin, not BTC
            pair = "XBTUSD" if symbol == "BTC" else f"{symbol}USD"
            response = requests.get(
                f"https://api.kraken.com/0/public/Ticker",
                params={"pair": pair},
                timeout=2
            )
            if response.ok:
                data = response.json()
                result = data.get("result", {})
                if result and not data.get("error"):
                    # Get first result key (Kraken adds XX prefix sometimes)
                    key = list(result.keys())[0]
                    return float(result[key]["c"][0])  # Last trade price
        except Exception:
            pass
        return None

    def record_tick(self, exchange: str, symbol: str, price: float, exchange_ts: Optional[float] = None):
        """Record a price tick."""
        now = time.time()
        tick = PriceTick(
            timestamp=now,
            exchange=exchange,
            symbol=symbol,
            price=price,
            exchange_timestamp=exchange_ts
        )

        with self._lock:
            self.prices[exchange][symbol].append(tick)
            self.latest[exchange][symbol] = price
            self.all_ticks.append(tick)
            self.stats[f"{exchange}_ticks"] += 1

            # Check for lead-lag events
            self._check_lead_lag(symbol)

    def _check_lead_lag(self, symbol: str):
        """Check if any exchange is leading price moves."""
        # Get recent prices from all exchanges
        exchanges = ["binance", "coinbase", "kraken"]
        recent = {}

        for ex in exchanges:
            if self.prices[ex][symbol]:
                ticks = list(self.prices[ex][symbol])[-10:]  # Last 10 ticks
                if len(ticks) >= 2:
                    recent[ex] = ticks

        if len(recent) < 2:
            return  # Need at least 2 exchanges

        # Look for significant price moves (>0.05%)
        for ex, ticks in recent.items():
            if len(ticks) < 2:
                continue

            move = (ticks[-1].price - ticks[-2].price) / ticks[-2].price
            if abs(move) > 0.0005:  # 0.05% move
                direction = "up" if move > 0 else "down"

                # Check if other exchanges followed
                for other_ex, other_ticks in recent.items():
                    if other_ex == ex:
                        continue

                    # Did other exchange move in same direction after?
                    for other_tick in other_ticks:
                        if other_tick.timestamp > ticks[-1].timestamp:
                            other_move = (other_tick.price - ticks[-1].price) / ticks[-1].price
                            if (direction == "up" and other_move > 0) or (direction == "down" and other_move < 0):
                                lag_ms = (other_tick.timestamp - ticks[-1].timestamp) * 1000

                                event = LeadLagMeasurement(
                                    timestamp=ticks[-1].timestamp,
                                    symbol=symbol,
                                    direction=direction,
                                    leader=ex,
                                    lag_ms=lag_ms,
                                    price_move_pct=move * 100
                                )
                                self.lead_lag_events.append(event)
                                self.stats["lead_lag_events"] += 1
                                break

    def fetch_binance_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from Binance.US REST API (works in US regions)."""
        try:
            pair = f"{symbol}USD"
            # Try Binance.US first (works in US), fallback to global
            for base_url in ["https://api.binance.us", "https://api.binance.com"]:
                try:
                    response = requests.get(
                        f"{base_url}/api/v3/ticker/price",
                        params={"symbol": pair},
                        timeout=2
                    )
                    if response.ok:
                        data = response.json()
                        return float(data["price"])
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def poll_binance(self):
        """Poll Binance.US for prices (REST API instead of blocked WebSocket)."""
        print("Using Binance.US REST API (WebSocket blocked in US regions)")
        while self._running:
            for symbol in ["BTC", "ETH"]:
                price = self.fetch_binance_price(symbol)
                if price:
                    self.record_tick("binance", symbol, price)
            time.sleep(0.3)  # Poll every 300ms for faster updates

    def poll_other_exchanges(self):
        """Poll Coinbase and Kraken for prices."""
        while self._running:
            for symbol in ["BTC", "ETH"]:
                # Coinbase
                price = self.fetch_coinbase_price(symbol)
                if price:
                    self.record_tick("coinbase", symbol, price)

                # Kraken
                price = self.fetch_kraken_price(symbol)
                if price:
                    self.record_tick("kraken", symbol, price)

            time.sleep(0.5)  # Poll every 500ms

    def print_status(self):
        """Print current status."""
        print(f"\n--- Status ---")
        for ex in ["binance", "coinbase", "kraken"]:
            btc = self.latest[ex].get("BTC", 0)
            eth = self.latest[ex].get("ETH", 0)
            ticks = self.stats[f"{ex}_ticks"]
            print(f"{ex:10s}: BTC=${btc:,.2f}  ETH=${eth:,.2f}  (ticks: {ticks})")

        if len(self.lead_lag_events) > 0:
            print(f"\nLead-lag events: {len(self.lead_lag_events)}")
            # Count leaders
            leaders = {}
            for event in self.lead_lag_events:
                leaders[event.leader] = leaders.get(event.leader, 0) + 1
            for leader, count in sorted(leaders.items(), key=lambda x: -x[1]):
                print(f"  {leader}: {count} times led")

    def analyze_results(self):
        """Analyze collected data for patterns."""
        print("\n" + "=" * 60)
        print("ANALYSIS RESULTS")
        print("=" * 60)

        runtime = time.time() - self.stats["start_time"]
        print(f"\nRuntime: {runtime:.1f} seconds")
        print(f"Total ticks: {len(self.all_ticks)}")

        # Price comparison at end
        print("\n--- Price Comparison ---")
        for symbol in ["BTC", "ETH"]:
            prices = {ex: self.latest[ex].get(symbol, 0) for ex in ["binance", "coinbase", "kraken"]}
            if all(prices.values()):
                avg = sum(prices.values()) / len(prices)
                print(f"\n{symbol}:")
                for ex, p in prices.items():
                    diff = (p - avg) / avg * 100
                    print(f"  {ex:10s}: ${p:,.2f} ({diff:+.4f}% vs avg)")

        # Lead-lag analysis
        if self.lead_lag_events:
            print("\n--- Lead-Lag Analysis ---")
            print(f"Total lead-lag events detected: {len(self.lead_lag_events)}")

            # Count by leader
            leader_counts = {}
            leader_lags = {}
            for event in self.lead_lag_events:
                leader_counts[event.leader] = leader_counts.get(event.leader, 0) + 1
                if event.leader not in leader_lags:
                    leader_lags[event.leader] = []
                leader_lags[event.leader].append(event.lag_ms)

            print("\nWhich exchange leads price moves?")
            for leader, count in sorted(leader_counts.items(), key=lambda x: -x[1]):
                pct = count / len(self.lead_lag_events) * 100
                avg_lag = sum(leader_lags[leader]) / len(leader_lags[leader])
                print(f"  {leader:10s}: {count:3d} times ({pct:.1f}%), avg lag: {avg_lag:.0f}ms")

            # Implications
            print("\n--- Implications for Account88888 ---")
            if leader_counts:
                top_leader = max(leader_counts, key=leader_counts.get)
                if top_leader != "binance":
                    print(f"  ! {top_leader.upper()} leads Binance - potential signal source!")
                    print(f"    Account88888 might be watching {top_leader} for earlier signals")
                else:
                    print("  Binance leads other exchanges - unlikely to be their edge")
        else:
            print("\nNo lead-lag events detected (may need longer runtime)")

    def save_results(self):
        """Save collected data."""
        timestamp = int(time.time())
        filename = f"multi_exchange_{timestamp}.json"
        filepath = self.output_dir / filename

        data = {
            "metadata": {
                "start_time": self.stats["start_time"],
                "runtime_seconds": time.time() - self.stats["start_time"],
                "total_ticks": len(self.all_ticks),
                "ticks_per_exchange": {
                    ex: self.stats[f"{ex}_ticks"] for ex in ["binance", "coinbase", "kraken"]
                }
            },
            "final_prices": self.latest,
            "lead_lag_events": [asdict(e) for e in self.lead_lag_events],
            "sample_ticks": [t.to_dict() for t in self.all_ticks[-500:]],  # Last 500 ticks
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\nSaved results to: {filepath}")

    def run(self, duration_seconds: int = 300):
        """Run the multi-exchange tracker."""
        print("=" * 60)
        print("MULTI-EXCHANGE PRICE TRACKER")
        print("=" * 60)
        print()
        print("Tracking prices across Binance, Coinbase, and Kraken")
        print("to find lead-lag relationships and potential signal sources.")
        print()
        print(f"Running for {duration_seconds} seconds...")
        print("Press Ctrl+C to stop early")
        print()

        self._running = True
        self.stats["start_time"] = time.time()

        # Start Binance polling (REST API - WebSocket blocked in US)
        print("Starting Binance.US polling...")
        binance_thread = threading.Thread(target=self.poll_binance, daemon=True)
        binance_thread.start()

        # Start polling other exchanges
        print("Starting Coinbase/Kraken polling...")
        poll_thread = threading.Thread(target=self.poll_other_exchanges, daemon=True)
        poll_thread.start()

        # Wait for initial data
        time.sleep(3)

        # Main loop
        end_time = time.time() + duration_seconds
        last_status = 0
        status_interval = 30

        try:
            while time.time() < end_time and self._running:
                now = time.time()
                if now - last_status > status_interval:
                    self.print_status()
                    last_status = now
                time.sleep(1)

        except KeyboardInterrupt:
            print("\nStopped by user")

        self._running = False

        # Analyze and save
        self.analyze_results()
        self.save_results()


def main():
    """Run the multi-exchange tracker."""
    import argparse

    parser = argparse.ArgumentParser(description="Multi-Exchange Price Tracker")
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="How long to run in seconds (default: 300)"
    )

    args = parser.parse_args()

    tracker = MultiExchangeTracker()
    tracker.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
