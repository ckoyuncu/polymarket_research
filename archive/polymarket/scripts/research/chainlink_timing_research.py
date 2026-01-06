#!/usr/bin/env python3
"""
Chainlink Timing Research Tool

This tool investigates potential timing edges in Polymarket 15-minute markets by:
1. Comparing Binance real-time prices vs Polymarket orderbook prices
2. Measuring latency between price sources
3. Analyzing when Polymarket prices "catch up" to Binance

Research Questions:
- How quickly do Polymarket prices reflect Binance price moves?
- Is there a measurable lag between Binance and Polymarket?
- Could Account88888 be exploiting this lag?

Usage:
    python scripts/research/chainlink_timing_research.py

Requirements:
    pip install websocket-client requests
"""

import json
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import deque
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@dataclass
class PriceObservation:
    """Single price observation from a source."""
    source: str  # "binance" or "polymarket"
    asset: str  # "BTC" or "ETH"
    price: float
    timestamp: float  # Unix timestamp

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "asset": self.asset,
            "price": self.price,
            "timestamp": self.timestamp,
            "time_str": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).strftime("%H:%M:%S.%f")[:-3]
        }


@dataclass
class LatencyMeasurement:
    """Measurement of latency between price sources."""
    asset: str
    binance_price: float
    binance_time: float
    polymarket_mid: float
    polymarket_time: float
    price_diff_pct: float
    time_diff_ms: float

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "binance_price": self.binance_price,
            "polymarket_mid": self.polymarket_mid,
            "price_diff_pct": self.price_diff_pct,
            "time_diff_ms": self.time_diff_ms,
            "timestamp": datetime.fromtimestamp(self.binance_time, tz=timezone.utc).isoformat()
        }


class ChainlinkTimingResearch:
    """
    Research tool for analyzing timing edges in Polymarket markets.

    This tool:
    1. Connects to Binance WebSocket for real-time BTC/ETH prices
    2. Polls Polymarket CLOB API for orderbook data
    3. Calculates implied price from Polymarket orderbooks
    4. Measures and logs the latency/difference
    """

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("data/research/chainlink_timing")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Price caches
        self.binance_prices: Dict[str, PriceObservation] = {}
        self.polymarket_prices: Dict[str, PriceObservation] = {}

        # Market tokens (will be populated)
        self.market_tokens: Dict[str, dict] = {}  # asset -> {token_up, token_down, slug}

        # Observations log
        self.observations: deque = deque(maxlen=10000)
        self.latency_measurements: deque = deque(maxlen=1000)

        # Control
        self._running = False
        self._lock = threading.Lock()

        # Stats
        self.stats = {
            "binance_updates": 0,
            "polymarket_polls": 0,
            "measurements": 0,
            "start_time": None,
        }

    def discover_active_markets(self) -> Dict[str, dict]:
        """
        Find currently active 15-minute markets for BTC and ETH.

        Returns: {asset: {token_up, token_down, slug, end_ts}}
        """
        markets = {}
        now = int(time.time())

        for asset in ["btc", "eth"]:
            # Find the current 15-minute window
            current_slot = now - (now % 900) + 900  # Next resolution time
            slug = f"{asset}-updown-15m-{current_slot}"

            try:
                response = requests.get(
                    f"{self.GAMMA_API}/markets/slug/{slug}",
                    timeout=10
                )

                if response.ok:
                    data = response.json()

                    # Parse token IDs
                    clob_ids = data.get("clobTokenIds", [])
                    outcomes = data.get("outcomes", [])

                    if isinstance(clob_ids, str):
                        clob_ids = json.loads(clob_ids)
                    if isinstance(outcomes, str):
                        outcomes = json.loads(outcomes)

                    token_up = None
                    token_down = None

                    for i, outcome in enumerate(outcomes):
                        if outcome.lower() == "up":
                            token_up = clob_ids[i]
                        elif outcome.lower() == "down":
                            token_down = clob_ids[i]

                    if token_up and token_down:
                        markets[asset.upper()] = {
                            "token_up": token_up,
                            "token_down": token_down,
                            "slug": slug,
                            "end_ts": current_slot,
                            "question": data.get("question", ""),
                        }
                        print(f"Found {asset.upper()} market: {slug}")

            except Exception as e:
                print(f"Error discovering {asset} market: {e}")

        return markets

    def get_orderbook(self, token_id: str) -> Optional[dict]:
        """Get orderbook for a token."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
                timeout=5
            )
            if response.ok:
                return response.json()
        except Exception as e:
            pass
        return None

    def calculate_implied_price(self, asset: str) -> Optional[float]:
        """
        Calculate implied Binance price from Polymarket orderbook.

        For 15-min Up/Down markets:
        - Market resolves based on whether price is UP or DOWN from start
        - UP token price reflects probability of price going up
        - Strike price is known from market question

        This is approximate - we're looking at probability-implied price.
        """
        if asset not in self.market_tokens:
            return None

        token_info = self.market_tokens[asset]

        # Get orderbooks
        up_book = self.get_orderbook(token_info["token_up"])
        down_book = self.get_orderbook(token_info["token_down"])

        if not up_book and not down_book:
            return None

        # Calculate mid prices
        up_mid = None
        down_mid = None

        if up_book:
            bids = up_book.get("bids", [])
            asks = up_book.get("asks", [])
            if bids and asks:
                up_mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            elif bids:
                up_mid = float(bids[0]["price"])
            elif asks:
                up_mid = float(asks[0]["price"])

        if down_book:
            bids = down_book.get("bids", [])
            asks = down_book.get("asks", [])
            if bids and asks:
                down_mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
            elif bids:
                down_mid = float(bids[0]["price"])
            elif asks:
                down_mid = float(asks[0]["price"])

        # Return UP probability (which reflects market's view of direction)
        # Higher UP price = market thinks price will go up
        if up_mid is not None:
            return up_mid
        elif down_mid is not None:
            return 1.0 - down_mid  # Implied UP probability

        return None

    def poll_polymarket(self):
        """Poll Polymarket for current prices."""
        for asset in self.market_tokens.keys():
            up_prob = self.calculate_implied_price(asset)

            if up_prob is not None:
                now = time.time()
                obs = PriceObservation(
                    source="polymarket",
                    asset=asset,
                    price=up_prob,
                    timestamp=now
                )

                with self._lock:
                    self.polymarket_prices[asset] = obs
                    self.observations.append(obs.to_dict())
                    self.stats["polymarket_polls"] += 1

    def start_binance_feed(self):
        """Start Binance WebSocket feed."""
        try:
            import websocket
        except ImportError:
            print("websocket-client not installed. Install with: pip install websocket-client")
            return

        def on_message(ws, message):
            try:
                data = json.loads(message)

                if "stream" in data:
                    data = data["data"]

                symbol = data.get("s")
                price = float(data.get("c", 0))
                event_time = data.get("E", int(time.time() * 1000))

                if symbol and price > 0:
                    asset = "BTC" if "BTC" in symbol else "ETH" if "ETH" in symbol else None
                    if asset:
                        now = time.time()
                        obs = PriceObservation(
                            source="binance",
                            asset=asset,
                            price=price,
                            timestamp=now
                        )

                        with self._lock:
                            self.binance_prices[asset] = obs
                            self.observations.append(obs.to_dict())
                            self.stats["binance_updates"] += 1

                            # Measure latency if we have polymarket price
                            self._measure_latency(asset)

            except Exception as e:
                pass

        def on_error(ws, error):
            print(f"WebSocket error: {error}")

        def on_close(ws, close_status_code, close_msg):
            if self._running:
                print("Reconnecting to Binance...")
                time.sleep(2)
                start_ws()

        def on_open(ws):
            print("Connected to Binance WebSocket")

        def start_ws():
            streams = ["btcusdt@ticker", "ethusdt@ticker"]
            url = f"wss://stream.binance.com:9443/ws/{'/'.join(streams)}"

            ws = websocket.WebSocketApp(
                url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open
            )
            ws.run_forever()

        thread = threading.Thread(target=start_ws, daemon=True)
        thread.start()

    def _measure_latency(self, asset: str):
        """Measure latency between Binance and Polymarket."""
        if asset not in self.binance_prices or asset not in self.polymarket_prices:
            return

        binance = self.binance_prices[asset]
        poly = self.polymarket_prices[asset]

        # Calculate time difference
        time_diff_ms = (binance.timestamp - poly.timestamp) * 1000

        # For proper latency measurement, we'd need to compare
        # Binance price direction vs Polymarket UP probability
        # This is complex because Polymarket is a probability, not absolute price

        # Simple approximation: compare Polymarket UP prob vs whether Binance is trending up
        # We'll log this for analysis

        measurement = LatencyMeasurement(
            asset=asset,
            binance_price=binance.price,
            binance_time=binance.timestamp,
            polymarket_mid=poly.price,
            polymarket_time=poly.timestamp,
            price_diff_pct=0,  # Not directly comparable
            time_diff_ms=abs(time_diff_ms)
        )

        self.latency_measurements.append(measurement)
        self.stats["measurements"] += 1

    def run(self, duration_seconds: int = 300):
        """
        Run the research tool for specified duration.

        Args:
            duration_seconds: How long to run (default 5 minutes)
        """
        print("=" * 60)
        print("CHAINLINK TIMING RESEARCH TOOL")
        print("=" * 60)
        print()

        # Discover markets
        print("Discovering active 15-minute markets...")
        self.market_tokens = self.discover_active_markets()

        if not self.market_tokens:
            print("No active markets found. Try again later.")
            return

        print(f"Found {len(self.market_tokens)} markets")
        for asset, info in self.market_tokens.items():
            print(f"  {asset}: {info['slug']}")
            print(f"    Question: {info['question'][:60]}...")
        print()

        self._running = True
        self.stats["start_time"] = time.time()

        # Start Binance feed
        print("Starting Binance WebSocket feed...")
        self.start_binance_feed()
        time.sleep(2)  # Wait for connection

        print(f"Running for {duration_seconds} seconds...")
        print("Press Ctrl+C to stop early")
        print()

        # Main polling loop
        end_time = time.time() + duration_seconds
        poll_interval = 0.5  # Poll Polymarket every 500ms
        status_interval = 30  # Print status every 30 seconds
        last_status = 0

        try:
            while time.time() < end_time and self._running:
                # Poll Polymarket
                self.poll_polymarket()

                # Print status periodically
                now = time.time()
                if now - last_status > status_interval:
                    self._print_status()
                    last_status = now

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\nStopped by user")

        self._running = False

        # Final report
        self._generate_report()

    def _print_status(self):
        """Print current status."""
        runtime = time.time() - (self.stats["start_time"] or time.time())

        print(f"\n--- Status ({runtime:.0f}s elapsed) ---")
        print(f"Binance updates: {self.stats['binance_updates']}")
        print(f"Polymarket polls: {self.stats['polymarket_polls']}")
        print(f"Latency measurements: {self.stats['measurements']}")

        # Current prices
        for asset in ["BTC", "ETH"]:
            if asset in self.binance_prices:
                bp = self.binance_prices[asset]
                print(f"{asset} Binance: ${bp.price:,.2f}")
            if asset in self.polymarket_prices:
                pp = self.polymarket_prices[asset]
                print(f"{asset} Polymarket UP prob: {pp.price:.3f}")

    def _generate_report(self):
        """Generate and save research report."""
        print()
        print("=" * 60)
        print("RESEARCH REPORT")
        print("=" * 60)

        runtime = time.time() - (self.stats["start_time"] or time.time())

        print(f"\nRuntime: {runtime:.0f} seconds")
        print(f"Binance updates received: {self.stats['binance_updates']}")
        print(f"Polymarket polls: {self.stats['polymarket_polls']}")
        print(f"Latency measurements: {self.stats['measurements']}")

        # Analyze latency measurements
        if self.latency_measurements:
            measurements = list(self.latency_measurements)

            time_diffs = [m.time_diff_ms for m in measurements]
            avg_time_diff = sum(time_diffs) / len(time_diffs)
            max_time_diff = max(time_diffs)
            min_time_diff = min(time_diffs)

            print(f"\nLatency Analysis:")
            print(f"  Avg time between sources: {avg_time_diff:.0f}ms")
            print(f"  Max: {max_time_diff:.0f}ms, Min: {min_time_diff:.0f}ms")

        # Save data
        report = {
            "metadata": {
                "start_time": datetime.fromtimestamp(self.stats["start_time"], tz=timezone.utc).isoformat() if self.stats["start_time"] else None,
                "runtime_seconds": runtime,
                "binance_updates": self.stats["binance_updates"],
                "polymarket_polls": self.stats["polymarket_polls"],
                "measurements": self.stats["measurements"],
            },
            "markets_tracked": {asset: info["slug"] for asset, info in self.market_tokens.items()},
            "observations": list(self.observations)[-500:],  # Last 500
            "latency_measurements": [m.to_dict() for m in self.latency_measurements],
        }

        output_file = self.output_dir / f"timing_research_{int(time.time())}.json"
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nReport saved to: {output_file}")

        # Key findings
        print()
        print("=" * 60)
        print("KEY FINDINGS")
        print("=" * 60)
        print()
        print("1. LATENCY NOTES:")
        print("   - Polymarket 15-min markets use Chainlink Data Streams")
        print("   - Chainlink provides 'sub-second' latency (not exact ms published)")
        print("   - Binance WebSocket provides ~10-50ms latency typically")
        print()
        print("2. POTENTIAL EDGE:")
        print("   - If Binance updates faster than Chainlink → brief arbitrage window")
        print("   - Account88888's ~30% edge over base rate suggests additional signal")
        print("   - Timing alone unlikely to explain 97.9% win rate")
        print()
        print("3. NEXT STEPS:")
        print("   - Monitor during high volatility periods")
        print("   - Compare Binance price direction vs Polymarket UP probability changes")
        print("   - Track price movement in final 60 seconds before resolution")


def main():
    """Run the research tool."""
    import argparse

    parser = argparse.ArgumentParser(description="Chainlink Timing Research Tool")
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="How long to run in seconds (default: 300)"
    )

    args = parser.parse_args()

    tool = ChainlinkTimingResearch()
    tool.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
