#!/usr/bin/env python3
"""
Final Minute Tracker - Real-Time Data Capture

This tool captures high-resolution data during the final 60 seconds before
market resolution to discover Account88888's potential edge:

1. Binance prices every 100ms
2. Polymarket orderbook every 500ms
3. All trades in the final minute
4. Price divergence between Binance and Polymarket implied price

The goal is to find timing/information edges that are NOT visible in
1-minute candle data.

Usage:
    python scripts/reverse_engineer/final_minute_tracker.py

Output:
    data/research/final_minute/capture_{timestamp}.json
"""

import json
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field, asdict
from collections import deque
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class PriceSnapshot:
    """Single price observation."""
    timestamp: float
    source: str  # "binance" or "polymarket"
    asset: str
    price: float
    extra: Dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)


@dataclass
class OrderbookSnapshot:
    """Orderbook state at a point in time."""
    timestamp: float
    asset: str
    token_id: str
    outcome: str  # "up" or "down"
    best_bid: Optional[float]
    best_ask: Optional[float]
    bid_depth: float  # Total size at top 3 bids
    ask_depth: float  # Total size at top 3 asks
    spread: Optional[float]
    mid_price: Optional[float]

    def to_dict(self):
        return asdict(self)


@dataclass
class MarketWindow:
    """Tracking state for a single 15-minute market window."""
    asset: str
    slug: str
    window_start: int
    window_end: int
    token_up: str
    token_down: str

    # Captured data
    binance_prices: List[PriceSnapshot] = field(default_factory=list)
    orderbook_snapshots: List[OrderbookSnapshot] = field(default_factory=list)

    # Analysis
    start_price: Optional[float] = None
    end_price: Optional[float] = None
    implied_up_prob: Optional[float] = None

    def to_dict(self):
        return {
            "asset": self.asset,
            "slug": self.slug,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "token_up": self.token_up,
            "token_down": self.token_down,
            "start_price": self.start_price,
            "end_price": self.end_price,
            "implied_up_prob": self.implied_up_prob,
            "binance_prices": [p.to_dict() for p in self.binance_prices],
            "orderbook_snapshots": [s.to_dict() for s in self.orderbook_snapshots],
        }


class FinalMinuteTracker:
    """
    Captures high-resolution data during final 60 seconds of market windows.
    """

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or PROJECT_ROOT / "data" / "research" / "final_minute"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Current tracking state
        self.active_windows: Dict[str, MarketWindow] = {}  # slug -> window
        self.binance_prices: Dict[str, float] = {}  # asset -> latest price

        # Control
        self._running = False
        self._lock = threading.Lock()

        # Stats
        self.stats = {
            "windows_tracked": 0,
            "binance_samples": 0,
            "orderbook_samples": 0,
            "start_time": None,
        }

    def discover_upcoming_windows(self) -> List[MarketWindow]:
        """Find markets that will close in the next 2-20 minutes."""
        windows = []
        now = int(time.time())

        for asset in ["btc", "eth"]:
            # Find current window (resolution time is when it closes)
            current_slot = now - (now % 900) + 900  # Next :00/:15/:30/:45

            # Check if we're within tracking range (2-20 minutes before close)
            time_to_close = current_slot - now

            if 120 < time_to_close < 1200:  # 2-20 minutes
                slug = f"{asset}-updown-15m-{current_slot - 900}"  # Slug uses START time

                try:
                    response = requests.get(
                        f"{self.GAMMA_API}/markets/slug/{slug}",
                        timeout=10
                    )

                    if response.ok:
                        data = response.json()

                        clob_ids = data.get("clobTokenIds", [])
                        outcomes = data.get("outcomes", [])

                        if isinstance(clob_ids, str):
                            clob_ids = json.loads(clob_ids)
                        if isinstance(outcomes, str):
                            outcomes = json.loads(outcomes)

                        token_up = None
                        token_down = None

                        for i, outcome in enumerate(outcomes):
                            if outcome.lower() == "up" and i < len(clob_ids):
                                token_up = clob_ids[i]
                            elif outcome.lower() == "down" and i < len(clob_ids):
                                token_down = clob_ids[i]

                        if token_up and token_down:
                            window = MarketWindow(
                                asset=asset.upper(),
                                slug=slug,
                                window_start=current_slot - 900,
                                window_end=current_slot,
                                token_up=token_up,
                                token_down=token_down,
                            )
                            windows.append(window)
                            print(f"Found {asset.upper()} window: closes in {time_to_close}s")

                except Exception as e:
                    pass

        return windows

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
        except Exception:
            pass
        return None

    def capture_orderbook(self, window: MarketWindow):
        """Capture orderbook state for a window."""
        now = time.time()

        for outcome, token_id in [("up", window.token_up), ("down", window.token_down)]:
            book = self.get_orderbook(token_id)
            if not book:
                continue

            bids = book.get("bids", [])
            asks = book.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else None
            best_ask = float(asks[0]["price"]) if asks else None

            # Calculate depth (top 3 levels)
            bid_depth = sum(float(b.get("size", 0)) for b in bids[:3])
            ask_depth = sum(float(a.get("size", 0)) for a in asks[:3])

            spread = (best_ask - best_bid) if (best_bid and best_ask) else None
            mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else None

            snapshot = OrderbookSnapshot(
                timestamp=now,
                asset=window.asset,
                token_id=token_id,
                outcome=outcome,
                best_bid=best_bid,
                best_ask=best_ask,
                bid_depth=bid_depth,
                ask_depth=ask_depth,
                spread=spread,
                mid_price=mid_price,
            )

            with self._lock:
                window.orderbook_snapshots.append(snapshot)
                self.stats["orderbook_samples"] += 1

                # Update implied UP probability
                if outcome == "up" and mid_price:
                    window.implied_up_prob = mid_price

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

    def poll_binance_prices(self):
        """Poll Binance.US for prices (REST API instead of blocked WebSocket)."""
        print("Using Binance.US REST API (WebSocket blocked in US regions)")
        while self._running:
            for asset in ["BTC", "ETH"]:
                price = self.fetch_binance_price(asset)
                if price:
                    now = time.time()
                    with self._lock:
                        self.binance_prices[asset] = price
                        self.stats["binance_samples"] += 1

                        # Add to active windows
                        for slug, window in self.active_windows.items():
                            if window.asset == asset:
                                snapshot = PriceSnapshot(
                                    timestamp=now,
                                    source="binance",
                                    asset=asset,
                                    price=price,
                                )
                                window.binance_prices.append(snapshot)

                                # Track start price
                                if window.start_price is None:
                                    window.start_price = price
            time.sleep(0.2)  # Poll every 200ms for high-res data

    def start_binance_feed(self):
        """Start Binance price feed (REST API polling for US compatibility)."""
        thread = threading.Thread(target=self.poll_binance_prices, daemon=True)
        thread.start()

    def track_window(self, window: MarketWindow):
        """Track a window through its final minute."""
        print(f"\n{'='*60}")
        print(f"TRACKING: {window.asset} window")
        print(f"Slug: {window.slug}")
        print(f"Closes at: {datetime.fromtimestamp(window.window_end, tz=timezone.utc)}")
        print(f"{'='*60}")

        with self._lock:
            self.active_windows[window.slug] = window
            self.stats["windows_tracked"] += 1

        # Wait until final 60 seconds
        while self._running:
            now = time.time()
            time_to_close = window.window_end - now

            if time_to_close <= 0:
                # Market closed
                break

            if time_to_close <= 65:  # Final 65 seconds - start intensive capture
                # Capture orderbook every 500ms
                self.capture_orderbook(window)
                time.sleep(0.5)
            else:
                # Just wait
                time.sleep(1)

        # Record final price
        if window.asset in self.binance_prices:
            window.end_price = self.binance_prices[window.asset]

        # Save window data
        self.save_window(window)

        with self._lock:
            if window.slug in self.active_windows:
                del self.active_windows[window.slug]

        print(f"\nCompleted tracking {window.asset} window")

    def save_window(self, window: MarketWindow):
        """Save captured data for a window."""
        filename = f"{window.slug}_{int(time.time())}.json"
        filepath = self.output_dir / filename

        with open(filepath, 'w') as f:
            json.dump(window.to_dict(), f, indent=2)

        print(f"Saved: {filepath}")

        # Print summary
        self.print_window_summary(window)

    def print_window_summary(self, window: MarketWindow):
        """Print analysis of captured window."""
        print(f"\n--- WINDOW SUMMARY: {window.asset} ---")
        print(f"Binance samples: {len(window.binance_prices)}")
        print(f"Orderbook samples: {len(window.orderbook_snapshots)}")

        if window.start_price and window.end_price:
            change = (window.end_price - window.start_price) / window.start_price * 100
            direction = "UP" if change > 0 else "DOWN"
            print(f"Price change: {change:+.4f}% ({direction})")

        if window.implied_up_prob:
            print(f"Final UP probability: {window.implied_up_prob:.3f}")

        # Analyze timing patterns
        if window.orderbook_snapshots:
            up_snapshots = [s for s in window.orderbook_snapshots if s.outcome == "up"]
            if up_snapshots:
                spreads = [s.spread for s in up_snapshots if s.spread]
                if spreads:
                    print(f"Avg UP spread: {sum(spreads)/len(spreads):.4f}")

                # Look for spread changes
                if len(spreads) > 5:
                    early_spread = sum(spreads[:5]) / 5
                    late_spread = sum(spreads[-5:]) / 5
                    print(f"Spread early vs late: {early_spread:.4f} → {late_spread:.4f}")

    def run(self, duration_minutes: int = 30):
        """Run tracker for specified duration."""
        print("=" * 60)
        print("FINAL MINUTE TRACKER")
        print("=" * 60)
        print()
        print("This tool captures high-resolution data during the")
        print("final 60 seconds before market resolution.")
        print()
        print(f"Running for {duration_minutes} minutes...")
        print("Press Ctrl+C to stop")
        print()

        self._running = True
        self.stats["start_time"] = time.time()

        # Start Binance feed
        print("Starting Binance WebSocket feed...")
        self.start_binance_feed()
        time.sleep(2)

        # Main loop - discover and track windows
        end_time = time.time() + (duration_minutes * 60)

        try:
            while time.time() < end_time and self._running:
                # Discover upcoming windows
                windows = self.discover_upcoming_windows()

                for window in windows:
                    if window.slug not in self.active_windows:
                        # Start tracking in separate thread
                        thread = threading.Thread(
                            target=self.track_window,
                            args=(window,),
                            daemon=True
                        )
                        thread.start()

                time.sleep(30)  # Check for new windows every 30 seconds

        except KeyboardInterrupt:
            print("\nStopped by user")

        self._running = False

        # Final stats
        print("\n" + "=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        runtime = time.time() - self.stats["start_time"]
        print(f"Runtime: {runtime/60:.1f} minutes")
        print(f"Windows tracked: {self.stats['windows_tracked']}")
        print(f"Binance samples: {self.stats['binance_samples']}")
        print(f"Orderbook samples: {self.stats['orderbook_samples']}")


def main():
    """Run the final minute tracker."""
    import argparse

    parser = argparse.ArgumentParser(description="Final Minute Tracker")
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="How long to run in minutes (default: 30)"
    )

    args = parser.parse_args()

    tracker = FinalMinuteTracker()
    tracker.run(duration_minutes=args.duration)


if __name__ == "__main__":
    main()
