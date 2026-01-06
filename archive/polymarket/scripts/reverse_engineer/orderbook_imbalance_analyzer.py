#!/usr/bin/env python3
"""
Orderbook Imbalance Analyzer

Analyzes Polymarket orderbook dynamics to find:
1. Bid/ask imbalances that predict price direction
2. Large order detection (whales entering)
3. Spread dynamics before resolution
4. Order flow patterns

The hypothesis is that Account88888 may be reading orderbook imbalances
to predict which direction the market will move.

Usage:
    python scripts/reverse_engineer/orderbook_imbalance_analyzer.py --duration 900

Output:
    data/research/orderbook/imbalance_{timestamp}.json
"""

import json
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict, field
from collections import deque
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class OrderbookSnapshot:
    """Full orderbook state at a point in time."""
    timestamp: float
    asset: str
    token_id: str
    outcome: str  # "up" or "down"

    # Top of book
    best_bid: Optional[float]
    best_ask: Optional[float]
    spread: Optional[float]
    mid_price: Optional[float]

    # Depth
    bid_depth_3: float  # Total size at top 3 bid levels
    ask_depth_3: float  # Total size at top 3 ask levels
    bid_depth_5: float  # Total size at top 5 bid levels
    ask_depth_5: float  # Total size at top 5 ask levels

    # Imbalance metrics
    imbalance_3: float  # (bid_depth - ask_depth) / total at 3 levels
    imbalance_5: float  # Same for 5 levels

    # Order counts
    bid_orders: int
    ask_orders: int

    def to_dict(self):
        return asdict(self)


@dataclass
class ImbalanceSignal:
    """Detected orderbook imbalance signal."""
    timestamp: float
    asset: str
    outcome: str
    signal_type: str  # "bid_heavy", "ask_heavy", "spread_tight", "whale_bid", "whale_ask"
    imbalance_value: float
    mid_price: float
    description: str


@dataclass
class MarketState:
    """Current state of a market (UP and DOWN tokens)."""
    asset: str
    slug: str
    window_end: int
    token_up: str
    token_down: str

    # Latest orderbook snapshots
    up_book: Optional[OrderbookSnapshot] = None
    down_book: Optional[OrderbookSnapshot] = None

    # Combined metrics
    combined_spread: Optional[float] = None  # up_ask + down_ask - 1 (arbitrage indicator)
    up_probability: Optional[float] = None

    # History
    snapshots: List[OrderbookSnapshot] = field(default_factory=list)
    signals: List[ImbalanceSignal] = field(default_factory=list)


class OrderbookImbalanceAnalyzer:
    """
    Analyzes orderbook imbalances to find predictive signals.
    """

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    # Thresholds for signal detection
    IMBALANCE_THRESHOLD = 0.3  # 30% imbalance triggers signal
    WHALE_SIZE_THRESHOLD = 1000  # $1000+ order is a whale
    TIGHT_SPREAD_THRESHOLD = 0.02  # 2 cent spread is tight

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or PROJECT_ROOT / "data" / "research" / "orderbook"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Active markets being tracked
        self.markets: Dict[str, MarketState] = {}  # slug -> state

        # All signals detected
        self.all_signals: List[ImbalanceSignal] = []

        # Control
        self._running = False
        self._lock = threading.Lock()

        # Stats
        self.stats = {
            "snapshots": 0,
            "signals_detected": 0,
            "markets_tracked": 0,
            "start_time": None,
        }

    def discover_active_markets(self) -> List[MarketState]:
        """Find currently active 15-minute markets."""
        markets = []
        now = int(time.time())

        for asset in ["btc", "eth"]:
            # Find current window
            current_slot = now - (now % 900) + 900
            time_to_close = current_slot - now

            # Only track if 2+ minutes remain
            if time_to_close > 120:
                slug = f"{asset}-updown-15m-{current_slot - 900}"

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
                            state = MarketState(
                                asset=asset.upper(),
                                slug=slug,
                                window_end=current_slot,
                                token_up=token_up,
                                token_down=token_down,
                            )
                            markets.append(state)
                            print(f"Found {asset.upper()} market: {time_to_close}s remaining")

                except Exception as e:
                    pass

        return markets

    def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch full orderbook for a token."""
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

    def analyze_orderbook(self, book: dict, asset: str, token_id: str, outcome: str) -> Optional[OrderbookSnapshot]:
        """Analyze orderbook and create snapshot."""
        if not book:
            return None

        now = time.time()
        bids = book.get("bids", [])
        asks = book.get("asks", [])

        # Best prices
        best_bid = float(bids[0]["price"]) if bids else None
        best_ask = float(asks[0]["price"]) if asks else None

        spread = (best_ask - best_bid) if (best_bid and best_ask) else None
        mid_price = (best_bid + best_ask) / 2 if (best_bid and best_ask) else None

        # Calculate depth at different levels
        bid_depth_3 = sum(float(b.get("size", 0)) for b in bids[:3])
        ask_depth_3 = sum(float(a.get("size", 0)) for a in asks[:3])
        bid_depth_5 = sum(float(b.get("size", 0)) for b in bids[:5])
        ask_depth_5 = sum(float(a.get("size", 0)) for a in asks[:5])

        # Calculate imbalance
        total_3 = bid_depth_3 + ask_depth_3
        total_5 = bid_depth_5 + ask_depth_5

        imbalance_3 = (bid_depth_3 - ask_depth_3) / total_3 if total_3 > 0 else 0
        imbalance_5 = (bid_depth_5 - ask_depth_5) / total_5 if total_5 > 0 else 0

        snapshot = OrderbookSnapshot(
            timestamp=now,
            asset=asset,
            token_id=token_id,
            outcome=outcome,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            mid_price=mid_price,
            bid_depth_3=bid_depth_3,
            ask_depth_3=ask_depth_3,
            bid_depth_5=bid_depth_5,
            ask_depth_5=ask_depth_5,
            imbalance_3=imbalance_3,
            imbalance_5=imbalance_5,
            bid_orders=len(bids),
            ask_orders=len(asks),
        )

        return snapshot

    def detect_signals(self, snapshot: OrderbookSnapshot, market: MarketState) -> List[ImbalanceSignal]:
        """Detect trading signals from orderbook state."""
        signals = []
        now = snapshot.timestamp

        # 1. Heavy bid imbalance (more buying pressure)
        if snapshot.imbalance_5 > self.IMBALANCE_THRESHOLD:
            signal = ImbalanceSignal(
                timestamp=now,
                asset=market.asset,
                outcome=snapshot.outcome,
                signal_type="bid_heavy",
                imbalance_value=snapshot.imbalance_5,
                mid_price=snapshot.mid_price or 0,
                description=f"{snapshot.outcome.upper()} has {snapshot.imbalance_5:.1%} bid imbalance"
            )
            signals.append(signal)

        # 2. Heavy ask imbalance (more selling pressure)
        if snapshot.imbalance_5 < -self.IMBALANCE_THRESHOLD:
            signal = ImbalanceSignal(
                timestamp=now,
                asset=market.asset,
                outcome=snapshot.outcome,
                signal_type="ask_heavy",
                imbalance_value=snapshot.imbalance_5,
                mid_price=snapshot.mid_price or 0,
                description=f"{snapshot.outcome.upper()} has {abs(snapshot.imbalance_5):.1%} ask imbalance"
            )
            signals.append(signal)

        # 3. Tight spread (high confidence/liquidity)
        if snapshot.spread and snapshot.spread < self.TIGHT_SPREAD_THRESHOLD:
            signal = ImbalanceSignal(
                timestamp=now,
                asset=market.asset,
                outcome=snapshot.outcome,
                signal_type="spread_tight",
                imbalance_value=snapshot.spread,
                mid_price=snapshot.mid_price or 0,
                description=f"{snapshot.outcome.upper()} spread only ${snapshot.spread:.3f}"
            )
            signals.append(signal)

        # 4. Large orders (whale detection)
        if snapshot.bid_depth_3 > self.WHALE_SIZE_THRESHOLD:
            signal = ImbalanceSignal(
                timestamp=now,
                asset=market.asset,
                outcome=snapshot.outcome,
                signal_type="whale_bid",
                imbalance_value=snapshot.bid_depth_3,
                mid_price=snapshot.mid_price or 0,
                description=f"${snapshot.bid_depth_3:,.0f} in top 3 bids for {snapshot.outcome.upper()}"
            )
            signals.append(signal)

        return signals

    def capture_market_state(self, market: MarketState):
        """Capture current orderbook state for a market."""
        # Fetch UP orderbook
        up_book = self.fetch_orderbook(market.token_up)
        up_snapshot = self.analyze_orderbook(up_book, market.asset, market.token_up, "up")

        # Fetch DOWN orderbook
        down_book = self.fetch_orderbook(market.token_down)
        down_snapshot = self.analyze_orderbook(down_book, market.asset, market.token_down, "down")

        with self._lock:
            if up_snapshot:
                market.up_book = up_snapshot
                market.snapshots.append(up_snapshot)
                self.stats["snapshots"] += 1

                # Detect signals
                signals = self.detect_signals(up_snapshot, market)
                market.signals.extend(signals)
                self.all_signals.extend(signals)
                self.stats["signals_detected"] += len(signals)

            if down_snapshot:
                market.down_book = down_snapshot
                market.snapshots.append(down_snapshot)
                self.stats["snapshots"] += 1

                signals = self.detect_signals(down_snapshot, market)
                market.signals.extend(signals)
                self.all_signals.extend(signals)
                self.stats["signals_detected"] += len(signals)

            # Calculate combined metrics
            if market.up_book and market.down_book:
                if market.up_book.best_ask and market.down_book.best_ask:
                    market.combined_spread = market.up_book.best_ask + market.down_book.best_ask - 1
                if market.up_book.mid_price:
                    market.up_probability = market.up_book.mid_price

    def print_status(self):
        """Print current market status."""
        print(f"\n--- Orderbook Status ---")
        print(f"Snapshots: {self.stats['snapshots']}, Signals: {self.stats['signals_detected']}")

        for slug, market in self.markets.items():
            now = time.time()
            time_left = market.window_end - now

            print(f"\n{market.asset} ({time_left:.0f}s left):")

            if market.up_book:
                up = market.up_book
                imbal_str = f"{up.imbalance_5:+.1%}" if up.imbalance_5 is not None else "N/A"
                print(f"  UP:   mid=${up.mid_price:.3f}, spread=${up.spread:.3f}, imbal={imbal_str}")

            if market.down_book:
                down = market.down_book
                imbal_str = f"{down.imbalance_5:+.1%}" if down.imbalance_5 is not None else "N/A"
                print(f"  DOWN: mid=${down.mid_price:.3f}, spread=${down.spread:.3f}, imbal={imbal_str}")

            if market.combined_spread is not None:
                arb = "YES" if market.combined_spread < 0 else "NO"
                print(f"  Combined spread: ${market.combined_spread:.4f} (arb: {arb})")

            # Recent signals
            recent = [s for s in market.signals if now - s.timestamp < 30]
            if recent:
                print(f"  Recent signals: {len(recent)}")
                for s in recent[-3:]:
                    print(f"    - {s.signal_type}: {s.description}")

    def analyze_results(self):
        """Analyze collected data for patterns."""
        print("\n" + "=" * 60)
        print("ORDERBOOK IMBALANCE ANALYSIS")
        print("=" * 60)

        runtime = time.time() - self.stats["start_time"]
        print(f"\nRuntime: {runtime:.1f} seconds")
        print(f"Total snapshots: {self.stats['snapshots']}")
        print(f"Total signals: {self.stats['signals_detected']}")

        if not self.all_signals:
            print("\nNo signals detected. May need longer runtime or more volatile markets.")
            return

        # Signal type breakdown
        print("\n--- Signal Types ---")
        signal_counts = {}
        for s in self.all_signals:
            signal_counts[s.signal_type] = signal_counts.get(s.signal_type, 0) + 1

        for stype, count in sorted(signal_counts.items(), key=lambda x: -x[1]):
            print(f"  {stype}: {count}")

        # Imbalance patterns
        print("\n--- Imbalance Patterns ---")
        bid_heavy = [s for s in self.all_signals if s.signal_type == "bid_heavy"]
        ask_heavy = [s for s in self.all_signals if s.signal_type == "ask_heavy"]

        if bid_heavy:
            avg_imbal = sum(s.imbalance_value for s in bid_heavy) / len(bid_heavy)
            print(f"Bid-heavy signals: {len(bid_heavy)}, avg imbalance: {avg_imbal:.1%}")

        if ask_heavy:
            avg_imbal = sum(abs(s.imbalance_value) for s in ask_heavy) / len(ask_heavy)
            print(f"Ask-heavy signals: {len(ask_heavy)}, avg imbalance: {avg_imbal:.1%}")

        # Implications
        print("\n--- Implications for Account88888 ---")
        print("  If they read orderbook imbalances:")
        print("    - Bid-heavy UP + Ask-heavy DOWN → likely UP resolution")
        print("    - Ask-heavy UP + Bid-heavy DOWN → likely DOWN resolution")
        print("    - They would buy the side with more bid pressure")
        print()
        print("  To validate: correlate imbalance signals with actual resolutions")

    def save_results(self):
        """Save collected data."""
        timestamp = int(time.time())
        filename = f"orderbook_imbalance_{timestamp}.json"
        filepath = self.output_dir / filename

        data = {
            "metadata": {
                "start_time": self.stats["start_time"],
                "runtime_seconds": time.time() - self.stats["start_time"],
                "snapshots": self.stats["snapshots"],
                "signals": self.stats["signals_detected"],
            },
            "markets": {
                slug: {
                    "asset": m.asset,
                    "window_end": m.window_end,
                    "final_up_prob": m.up_probability,
                    "snapshots_count": len(m.snapshots),
                    "signals_count": len(m.signals),
                }
                for slug, m in self.markets.items()
            },
            "all_signals": [asdict(s) for s in self.all_signals],
            "sample_snapshots": [s.to_dict() for s in list(self.all_signals)[:100]],
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\nSaved results to: {filepath}")

    def run(self, duration_seconds: int = 900):
        """Run the orderbook analyzer."""
        print("=" * 60)
        print("ORDERBOOK IMBALANCE ANALYZER")
        print("=" * 60)
        print()
        print("Analyzing Polymarket orderbooks to find predictive signals:")
        print("  - Bid/ask imbalances")
        print("  - Whale order detection")
        print("  - Spread dynamics")
        print()
        print(f"Running for {duration_seconds} seconds...")
        print("Press Ctrl+C to stop early")
        print()

        self._running = True
        self.stats["start_time"] = time.time()

        # Main loop
        end_time = time.time() + duration_seconds
        last_status = 0
        status_interval = 30
        poll_interval = 1.0  # Poll every second

        try:
            while time.time() < end_time and self._running:
                now = time.time()

                # Discover new markets periodically
                if not self.markets or now % 60 < poll_interval:
                    new_markets = self.discover_active_markets()
                    for m in new_markets:
                        if m.slug not in self.markets:
                            self.markets[m.slug] = m
                            self.stats["markets_tracked"] += 1

                # Capture orderbook state for all active markets
                for slug, market in list(self.markets.items()):
                    if now > market.window_end:
                        # Market closed, remove it
                        del self.markets[slug]
                        continue

                    self.capture_market_state(market)

                # Print status
                if now - last_status > status_interval:
                    self.print_status()
                    last_status = now

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\nStopped by user")

        self._running = False

        # Analyze and save
        self.analyze_results()
        self.save_results()


def main():
    """Run the orderbook imbalance analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Orderbook Imbalance Analyzer")
    parser.add_argument(
        "--duration",
        type=int,
        default=900,
        help="How long to run in seconds (default: 900 = 15 min)"
    )

    args = parser.parse_args()

    analyzer = OrderbookImbalanceAnalyzer()
    analyzer.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
