#!/usr/bin/env python3
"""
Real-Time Orderbook Monitor for Polymarket 15-Min Markets

This tool monitors orderbook dynamics to understand:
1. How liquidity behaves before/after market resolution
2. Price movement patterns in the final minutes
3. Large order detection and timing

Research Questions:
- When do large orders appear?
- How does the spread change near resolution?
- Can we detect "informed" trading patterns?

Usage:
    # Monitor for 15 minutes (one full window)
    python scripts/research/orderbook_monitor.py

    # Monitor with custom duration
    python scripts/research/orderbook_monitor.py --duration 900

    # Focus on BTC only
    python scripts/research/orderbook_monitor.py --asset BTC
"""

import json
import time
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


@dataclass
class OrderbookSnapshot:
    """Single orderbook snapshot."""
    token_id: str
    token_type: str  # "UP" or "DOWN"
    asset: str
    timestamp: float
    bids: List[Tuple[float, float]]  # (price, size)
    asks: List[Tuple[float, float]]  # (price, size)

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0][0] if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return self.best_bid or self.best_ask

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def total_bid_depth(self) -> float:
        return sum(size for _, size in self.bids)

    @property
    def total_ask_depth(self) -> float:
        return sum(size for _, size in self.asks)

    def to_dict(self) -> dict:
        return {
            "token_id": self.token_id,
            "token_type": self.token_type,
            "asset": self.asset,
            "timestamp": self.timestamp,
            "time_str": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).strftime("%H:%M:%S"),
            "best_bid": self.best_bid,
            "best_ask": self.best_ask,
            "mid_price": self.mid_price,
            "spread": self.spread,
            "bid_depth": self.total_bid_depth,
            "ask_depth": self.total_ask_depth,
            "bid_levels": len(self.bids),
            "ask_levels": len(self.asks),
        }


@dataclass
class MarketState:
    """Current state of a market."""
    asset: str
    slug: str
    end_ts: int
    question: str
    token_up: str
    token_down: str
    up_snapshots: deque = field(default_factory=lambda: deque(maxlen=1000))
    down_snapshots: deque = field(default_factory=lambda: deque(maxlen=1000))

    @property
    def seconds_to_close(self) -> float:
        return self.end_ts - time.time()

    @property
    def minutes_to_close(self) -> float:
        return self.seconds_to_close / 60


class OrderbookMonitor:
    """
    Real-time orderbook monitor for 15-minute markets.

    Tracks:
    - Price changes over time
    - Spread dynamics
    - Liquidity depth
    - Significant order events
    """

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, assets: List[str] = None, output_dir: Optional[Path] = None):
        self.assets = [a.lower() for a in (assets or ["btc", "eth"])]
        self.output_dir = output_dir or Path("data/research/orderbook")
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Market state
        self.markets: Dict[str, MarketState] = {}

        # Event log
        self.events: deque = deque(maxlen=5000)

        # Stats
        self.stats = {
            "snapshots": 0,
            "large_orders_detected": 0,
            "price_changes": 0,
            "start_time": None,
        }

    def discover_markets(self) -> Dict[str, MarketState]:
        """Find currently active 15-minute markets."""
        markets = {}
        now = int(time.time())

        for asset in self.assets:
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
                        markets[asset.upper()] = MarketState(
                            asset=asset.upper(),
                            slug=slug,
                            end_ts=current_slot,
                            question=data.get("question", ""),
                            token_up=token_up,
                            token_down=token_down,
                        )

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
        except Exception:
            pass
        return None

    def poll_orderbooks(self):
        """Poll all tracked orderbooks."""
        now = time.time()

        for asset, market in self.markets.items():
            # UP token
            up_book = self.get_orderbook(market.token_up)
            if up_book:
                snapshot = self._parse_orderbook(up_book, market.token_up, "UP", asset, now)
                self._record_snapshot(market, snapshot, "up")

            # DOWN token
            down_book = self.get_orderbook(market.token_down)
            if down_book:
                snapshot = self._parse_orderbook(down_book, market.token_down, "DOWN", asset, now)
                self._record_snapshot(market, snapshot, "down")

    def _parse_orderbook(self, book: dict, token_id: str, token_type: str, asset: str, timestamp: float) -> OrderbookSnapshot:
        """Parse orderbook response into snapshot."""
        bids = []
        asks = []

        for bid in book.get("bids", []):
            price = float(bid["price"])
            size = float(bid["size"])
            bids.append((price, size))

        for ask in book.get("asks", []):
            price = float(ask["price"])
            size = float(ask["size"])
            asks.append((price, size))

        return OrderbookSnapshot(
            token_id=token_id,
            token_type=token_type,
            asset=asset,
            timestamp=timestamp,
            bids=bids,
            asks=asks,
        )

    def _record_snapshot(self, market: MarketState, snapshot: OrderbookSnapshot, side: str):
        """Record snapshot and detect events."""
        snapshots = market.up_snapshots if side == "up" else market.down_snapshots

        # Check for significant changes
        if snapshots:
            prev = snapshots[-1]
            self._detect_changes(prev, snapshot, market)

        snapshots.append(snapshot)
        self.stats["snapshots"] += 1

    def _detect_changes(self, prev: OrderbookSnapshot, curr: OrderbookSnapshot, market: MarketState):
        """Detect significant orderbook changes."""
        # Price change
        if prev.mid_price and curr.mid_price:
            price_change = curr.mid_price - prev.mid_price
            if abs(price_change) > 0.01:  # >1 cent change
                self.events.append({
                    "type": "price_change",
                    "asset": curr.asset,
                    "token_type": curr.token_type,
                    "timestamp": curr.timestamp,
                    "time_to_close": market.seconds_to_close,
                    "prev_price": prev.mid_price,
                    "new_price": curr.mid_price,
                    "change": price_change,
                })
                self.stats["price_changes"] += 1

        # Large depth change (possible large order)
        prev_depth = prev.total_bid_depth + prev.total_ask_depth
        curr_depth = curr.total_bid_depth + curr.total_ask_depth

        if prev_depth > 0:
            depth_change_pct = (curr_depth - prev_depth) / prev_depth
            if abs(depth_change_pct) > 0.20:  # >20% depth change
                self.events.append({
                    "type": "large_depth_change",
                    "asset": curr.asset,
                    "token_type": curr.token_type,
                    "timestamp": curr.timestamp,
                    "time_to_close": market.seconds_to_close,
                    "prev_depth": prev_depth,
                    "new_depth": curr_depth,
                    "change_pct": depth_change_pct * 100,
                })
                self.stats["large_orders_detected"] += 1

    def run(self, duration_seconds: int = 900):
        """
        Run the monitor for specified duration.

        Args:
            duration_seconds: How long to run (default 15 min = 900s)
        """
        print("=" * 60)
        print("ORDERBOOK MONITOR")
        print("=" * 60)
        print()

        # Discover markets
        print("Discovering active 15-minute markets...")
        self.markets = self.discover_markets()

        if not self.markets:
            print("No active markets found. Try again later.")
            return

        for asset, market in self.markets.items():
            print(f"\n{asset}:")
            print(f"  Slug: {market.slug}")
            print(f"  Question: {market.question[:60]}...")
            print(f"  Time to close: {market.minutes_to_close:.1f} min")

        print()
        print(f"Monitoring for {duration_seconds} seconds...")
        print("Press Ctrl+C to stop early")
        print()

        self.stats["start_time"] = time.time()
        end_time = time.time() + duration_seconds
        poll_interval = 1.0  # Poll every second
        status_interval = 30  # Status every 30 seconds
        last_status = 0

        try:
            while time.time() < end_time:
                # Poll orderbooks
                self.poll_orderbooks()

                # Print status
                now = time.time()
                if now - last_status > status_interval:
                    self._print_status()
                    last_status = now

                # Check if market is about to close
                for market in self.markets.values():
                    if market.seconds_to_close < 10:
                        print(f"\n*** {market.asset} CLOSING IN {market.seconds_to_close:.0f}s ***")

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\nStopped by user")

        # Generate report
        self._generate_report()

    def _print_status(self):
        """Print current status."""
        runtime = time.time() - (self.stats["start_time"] or time.time())
        print(f"\n--- Status ({runtime:.0f}s) ---")

        for asset, market in self.markets.items():
            print(f"\n{asset} (closes in {market.minutes_to_close:.1f}m):")

            if market.up_snapshots:
                up = market.up_snapshots[-1]
                print(f"  UP:   bid={up.best_bid:.3f} ask={up.best_ask:.3f} spread={up.spread:.4f if up.spread else 'N/A'}")

            if market.down_snapshots:
                down = market.down_snapshots[-1]
                print(f"  DOWN: bid={down.best_bid:.3f} ask={down.best_ask:.3f} spread={down.spread:.4f if down.spread else 'N/A'}")

        # Arbitrage check
        for asset, market in self.markets.items():
            if market.up_snapshots and market.down_snapshots:
                up = market.up_snapshots[-1]
                down = market.down_snapshots[-1]

                if up.best_ask and down.best_ask:
                    cost_of_pair = up.best_ask + down.best_ask
                    print(f"\n{asset} pair cost: ${cost_of_pair:.4f} ({'ARBITRAGE!' if cost_of_pair < 1.0 else 'no arb'})")

        print(f"\nSnapshots: {self.stats['snapshots']}, Events: {len(self.events)}")

    def _generate_report(self):
        """Generate and save report."""
        print()
        print("=" * 60)
        print("ORDERBOOK MONITORING REPORT")
        print("=" * 60)

        runtime = time.time() - (self.stats["start_time"] or time.time())

        print(f"\nRuntime: {runtime:.0f} seconds")
        print(f"Snapshots captured: {self.stats['snapshots']}")
        print(f"Price changes detected: {self.stats['price_changes']}")
        print(f"Large depth changes: {self.stats['large_orders_detected']}")

        # Analyze price evolution
        print("\n--- Price Evolution ---")
        for asset, market in self.markets.items():
            if market.up_snapshots:
                first_up = market.up_snapshots[0]
                last_up = market.up_snapshots[-1]

                if first_up.mid_price and last_up.mid_price:
                    change = last_up.mid_price - first_up.mid_price
                    print(f"{asset} UP: {first_up.mid_price:.3f} → {last_up.mid_price:.3f} (Δ{change:+.3f})")

        # Analyze spread evolution
        print("\n--- Spread Analysis ---")
        for asset, market in self.markets.items():
            up_spreads = [s.spread for s in market.up_snapshots if s.spread]
            if up_spreads:
                avg_spread = sum(up_spreads) / len(up_spreads)
                min_spread = min(up_spreads)
                max_spread = max(up_spreads)
                print(f"{asset} UP spread: avg={avg_spread:.4f}, min={min_spread:.4f}, max={max_spread:.4f}")

        # Event analysis
        if self.events:
            print("\n--- Significant Events ---")
            # Group by type
            price_events = [e for e in self.events if e["type"] == "price_change"]
            depth_events = [e for e in self.events if e["type"] == "large_depth_change"]

            print(f"Price changes (>1c): {len(price_events)}")
            print(f"Large depth changes (>20%): {len(depth_events)}")

            # Show recent events
            recent_events = list(self.events)[-10:]
            if recent_events:
                print("\nRecent events:")
                for event in recent_events:
                    time_str = datetime.fromtimestamp(event["timestamp"], tz=timezone.utc).strftime("%H:%M:%S")
                    if event["type"] == "price_change":
                        print(f"  [{time_str}] {event['asset']} {event['token_type']}: price {event['prev_price']:.3f}→{event['new_price']:.3f}")
                    elif event["type"] == "large_depth_change":
                        print(f"  [{time_str}] {event['asset']} {event['token_type']}: depth changed {event['change_pct']:+.1f}%")

        # Save data
        report = {
            "metadata": {
                "start_time": datetime.fromtimestamp(self.stats["start_time"], tz=timezone.utc).isoformat() if self.stats["start_time"] else None,
                "runtime_seconds": runtime,
                "snapshots": self.stats["snapshots"],
            },
            "markets": {
                asset: {
                    "slug": m.slug,
                    "end_ts": m.end_ts,
                    "up_snapshots": [s.to_dict() for s in list(m.up_snapshots)[-200:]],
                    "down_snapshots": [s.to_dict() for s in list(m.down_snapshots)[-200:]],
                }
                for asset, m in self.markets.items()
            },
            "events": list(self.events),
        }

        output_file = self.output_dir / f"orderbook_monitor_{int(time.time())}.json"
        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2)

        print(f"\nReport saved to: {output_file}")


def main():
    """Run the orderbook monitor."""
    import argparse

    parser = argparse.ArgumentParser(description="Orderbook Monitor")
    parser.add_argument(
        "--duration",
        type=int,
        default=900,
        help="How long to run in seconds (default: 900 = 15 min)"
    )
    parser.add_argument(
        "--asset",
        type=str,
        default=None,
        help="Specific asset to monitor (BTC, ETH)"
    )

    args = parser.parse_args()

    assets = [args.asset] if args.asset else None
    monitor = OrderbookMonitor(assets=assets)
    monitor.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
