#!/usr/bin/env python3
"""
Spread Dynamics Analyzer

Analyzes Polymarket orderbook spread patterns to find:
1. Spread narrowing before Account88888's entries
2. Correlation between spread width and outcome predictability
3. Spread patterns that could signal informed trading

Hypothesis: Narrow spreads indicate market makers have conviction,
which could be a signal Account88888 exploits.

Usage:
    python scripts/reverse_engineer/spread_dynamics_analyzer.py --duration 900

Output:
    Analysis of spread patterns and their predictive value
"""

import json
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import statistics
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class SpreadSnapshot:
    """Single spread observation."""
    timestamp: float
    asset: str
    slug: str
    token_id: str
    outcome: str  # "up" or "down"
    best_bid: float
    best_ask: float
    spread: float
    spread_pct: float  # Spread as % of mid price
    mid_price: float
    bid_depth: float  # Size at best bid
    ask_depth: float  # Size at best ask


@dataclass
class SpreadEvent:
    """Significant spread event."""
    timestamp: float
    asset: str
    slug: str
    event_type: str  # "narrowing", "widening", "tight", "wide"
    spread_before: float
    spread_after: float
    change_pct: float


@dataclass
class MarketSpreadAnalysis:
    """Analysis of spreads for a single market."""
    slug: str
    asset: str
    window_start: int
    window_end: int

    # Spread statistics
    avg_spread_up: float = 0
    avg_spread_down: float = 0
    min_spread_up: float = 1.0
    min_spread_down: float = 1.0

    # Timing patterns
    spread_at_start: float = 0
    spread_at_end: float = 0
    narrowed_over_time: bool = False

    # Combined spread (arbitrage indicator)
    avg_combined_spread: float = 0
    min_combined_spread: float = 2.0


class SpreadDynamicsAnalyzer:
    """Analyzes spread dynamics in real-time."""

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or PROJECT_ROOT / "data" / "research" / "spread_dynamics"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.snapshots: Dict[str, List[SpreadSnapshot]] = defaultdict(list)
        self.events: List[SpreadEvent] = []
        self.market_analyses: Dict[str, MarketSpreadAnalysis] = {}

        self._running = False
        self._lock = threading.Lock()

        self.stats = {
            "snapshots": 0,
            "events": 0,
            "markets_analyzed": 0,
            "start_time": None,
        }

    def get_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch orderbook for a token."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
                timeout=5
            )
            if response.ok:
                return response.json()
        except:
            pass
        return None

    def get_market_info(self, asset: str) -> Optional[dict]:
        """Get current 15-min market info."""
        now = int(time.time())
        current_slot = now - (now % 900) + 900
        slug = f"{asset.lower()}-updown-15m-{current_slot - 900}"

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

                token_up = token_down = None
                for i, outcome in enumerate(outcomes):
                    if outcome.lower() == "up" and i < len(clob_ids):
                        token_up = clob_ids[i]
                    elif outcome.lower() == "down" and i < len(clob_ids):
                        token_down = clob_ids[i]

                return {
                    "slug": slug,
                    "window_start": current_slot - 900,
                    "window_end": current_slot,
                    "token_up": token_up,
                    "token_down": token_down,
                    "asset": asset,
                }
        except:
            pass
        return None

    def capture_spread(self, market: dict, outcome: str, token_id: str):
        """Capture current spread for a token."""
        book = self.get_orderbook(token_id)
        if not book:
            return

        bids = book.get("bids", [])
        asks = book.get("asks", [])

        if not bids or not asks:
            return

        best_bid = float(bids[0]["price"])
        best_ask = float(asks[0]["price"])
        spread = best_ask - best_bid

        mid_price = (best_bid + best_ask) / 2
        spread_pct = spread / mid_price if mid_price > 0 else 0

        bid_depth = float(bids[0].get("size", 0))
        ask_depth = float(asks[0].get("size", 0))

        snapshot = SpreadSnapshot(
            timestamp=time.time(),
            asset=market["asset"],
            slug=market["slug"],
            token_id=token_id,
            outcome=outcome,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=spread,
            spread_pct=spread_pct,
            mid_price=mid_price,
            bid_depth=bid_depth,
            ask_depth=ask_depth,
        )

        with self._lock:
            self.snapshots[market["slug"]].append(snapshot)
            self.stats["snapshots"] += 1

            # Check for spread events
            self._check_spread_events(market, snapshot)

    def _check_spread_events(self, market: dict, new_snapshot: SpreadSnapshot):
        """Check for significant spread changes."""
        slug = market["slug"]
        snapshots = self.snapshots[slug]

        if len(snapshots) < 2:
            return

        # Get previous snapshot for same outcome
        prev_snapshots = [
            s for s in snapshots[-10:]
            if s.outcome == new_snapshot.outcome and s != new_snapshot
        ]

        if not prev_snapshots:
            return

        prev = prev_snapshots[-1]

        # Check for significant change
        spread_change = new_snapshot.spread - prev.spread
        change_pct = spread_change / prev.spread if prev.spread > 0 else 0

        event_type = None
        if change_pct < -0.2:  # Spread narrowed by >20%
            event_type = "narrowing"
        elif change_pct > 0.3:  # Spread widened by >30%
            event_type = "widening"
        elif new_snapshot.spread < 0.02:  # Very tight spread
            event_type = "tight"
        elif new_snapshot.spread > 0.15:  # Wide spread
            event_type = "wide"

        if event_type:
            event = SpreadEvent(
                timestamp=new_snapshot.timestamp,
                asset=market["asset"],
                slug=slug,
                event_type=event_type,
                spread_before=prev.spread,
                spread_after=new_snapshot.spread,
                change_pct=change_pct,
            )
            self.events.append(event)
            self.stats["events"] += 1

    def analyze_market(self, slug: str) -> Optional[MarketSpreadAnalysis]:
        """Analyze spread patterns for a completed market."""
        snapshots = self.snapshots.get(slug, [])
        if len(snapshots) < 5:
            return None

        # Separate by outcome
        up_snapshots = [s for s in snapshots if s.outcome == "up"]
        down_snapshots = [s for s in snapshots if s.outcome == "down"]

        if not up_snapshots or not down_snapshots:
            return None

        # Calculate statistics
        up_spreads = [s.spread for s in up_snapshots]
        down_spreads = [s.spread for s in down_snapshots]

        # Combined spread over time
        combined_spreads = []
        for up in up_snapshots:
            matching_down = [
                d for d in down_snapshots
                if abs(d.timestamp - up.timestamp) < 5
            ]
            if matching_down:
                combined = up.mid_price + matching_down[0].mid_price
                combined_spreads.append(combined)

        # Parse window times
        try:
            parts = slug.split("-")
            window_start = int(parts[-1])
            window_end = window_start + 900
        except:
            window_start = window_end = 0

        analysis = MarketSpreadAnalysis(
            slug=slug,
            asset=snapshots[0].asset,
            window_start=window_start,
            window_end=window_end,
            avg_spread_up=statistics.mean(up_spreads),
            avg_spread_down=statistics.mean(down_spreads),
            min_spread_up=min(up_spreads),
            min_spread_down=min(down_spreads),
            avg_combined_spread=statistics.mean(combined_spreads) if combined_spreads else 1.0,
            min_combined_spread=min(combined_spreads) if combined_spreads else 1.0,
        )

        # Check if spread narrowed over time
        if len(up_snapshots) >= 3:
            early_spread = statistics.mean([s.spread for s in up_snapshots[:3]])
            late_spread = statistics.mean([s.spread for s in up_snapshots[-3:]])
            analysis.spread_at_start = early_spread
            analysis.spread_at_end = late_spread
            analysis.narrowed_over_time = late_spread < early_spread * 0.8

        return analysis

    def print_status(self):
        """Print current status."""
        now = datetime.now().strftime("%H:%M:%S")
        print(f"\n--- Spread Status ({now}) ---")
        print(f"Snapshots: {self.stats['snapshots']}, Events: {self.stats['events']}")

        # Current spreads by asset
        for asset in ["BTC", "ETH"]:
            market = self.get_market_info(asset)
            if not market:
                continue

            slug = market["slug"]
            snapshots = self.snapshots.get(slug, [])

            up_recent = [s for s in snapshots[-5:] if s.outcome == "up"]
            down_recent = [s for s in snapshots[-5:] if s.outcome == "down"]

            if up_recent and down_recent:
                up_spread = up_recent[-1].spread
                down_spread = down_recent[-1].spread
                combined = up_recent[-1].mid_price + down_recent[-1].mid_price

                print(f"\n{asset}:")
                print(f"  UP spread: ${up_spread:.4f} ({up_spread*100:.2f}%)")
                print(f"  DOWN spread: ${down_spread:.4f} ({down_spread*100:.2f}%)")
                print(f"  Combined: ${combined:.4f} (arb: {'YES' if combined < 1.0 else 'NO'})")

        # Recent events
        recent_events = self.events[-5:]
        if recent_events:
            print("\nRecent Events:")
            for e in recent_events:
                print(f"  {e.event_type}: {e.asset} spread {e.spread_before:.4f} → {e.spread_after:.4f}")

    def analyze_results(self):
        """Analyze collected data."""
        print("\n" + "=" * 60)
        print("SPREAD DYNAMICS ANALYSIS")
        print("=" * 60)

        runtime = time.time() - self.stats["start_time"]
        print(f"\nRuntime: {runtime/60:.1f} minutes")
        print(f"Total snapshots: {self.stats['snapshots']}")
        print(f"Total events: {self.stats['events']}")

        # Analyze completed markets
        print("\n--- Market Analysis ---")
        for slug in list(self.snapshots.keys()):
            analysis = self.analyze_market(slug)
            if analysis:
                self.market_analyses[slug] = analysis
                self.stats["markets_analyzed"] += 1

        print(f"Markets analyzed: {len(self.market_analyses)}")

        # Event distribution
        if self.events:
            print("\n--- Event Distribution ---")
            event_counts = defaultdict(int)
            for e in self.events:
                event_counts[e.event_type] += 1

            for event_type, count in sorted(event_counts.items(), key=lambda x: -x[1]):
                print(f"  {event_type}: {count}")

        # Spread patterns
        if self.market_analyses:
            print("\n--- Spread Patterns ---")

            avg_spreads = [a.avg_spread_up for a in self.market_analyses.values()]
            min_spreads = [a.min_spread_up for a in self.market_analyses.values()]
            combined_spreads = [a.avg_combined_spread for a in self.market_analyses.values()]

            narrowing_count = sum(1 for a in self.market_analyses.values() if a.narrowed_over_time)

            print(f"Average UP spread: ${statistics.mean(avg_spreads):.4f}")
            print(f"Average min spread: ${statistics.mean(min_spreads):.4f}")
            print(f"Average combined: ${statistics.mean(combined_spreads):.4f}")
            print(f"Markets with narrowing spreads: {narrowing_count}/{len(self.market_analyses)}")

            arb_opportunities = sum(1 for a in self.market_analyses.values() if a.min_combined_spread < 1.0)
            print(f"Arbitrage opportunities: {arb_opportunities}")

        # Implications
        print("\n--- Implications for Account88888 ---")
        print("If spreads narrow over time:")
        print("  → Market makers gain conviction → possible signal")
        print("If tight spreads correlate with direction:")
        print("  → Narrow spread = strong consensus → bet with it")

    def save_results(self):
        """Save analysis results."""
        timestamp = int(time.time())

        # Save snapshots sample
        sample = []
        for slug, snaps in self.snapshots.items():
            sample.extend([asdict(s) for s in snaps[-50:]])

        data = {
            "metadata": {
                "runtime_seconds": time.time() - self.stats["start_time"],
                "total_snapshots": self.stats["snapshots"],
                "total_events": self.stats["events"],
                "markets_analyzed": self.stats["markets_analyzed"],
            },
            "events": [asdict(e) for e in self.events],
            "market_analyses": {k: asdict(v) for k, v in self.market_analyses.items()},
            "sample_snapshots": sample,
        }

        filepath = self.output_dir / f"spread_analysis_{timestamp}.json"
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\nSaved results to: {filepath}")

    def run(self, duration_seconds: int = 900):
        """Run spread dynamics analyzer."""
        print("=" * 60)
        print("SPREAD DYNAMICS ANALYZER")
        print("=" * 60)
        print()
        print("Analyzing orderbook spread patterns to find predictive signals.")
        print(f"Running for {duration_seconds/60:.0f} minutes...")
        print()

        self._running = True
        self.stats["start_time"] = time.time()
        end_time = time.time() + duration_seconds
        last_status = 0

        try:
            while time.time() < end_time and self._running:
                # Capture spreads for all assets
                for asset in ["BTC", "ETH"]:
                    market = self.get_market_info(asset)
                    if not market:
                        continue

                    # Capture both UP and DOWN spreads
                    if market.get("token_up"):
                        self.capture_spread(market, "up", market["token_up"])
                    if market.get("token_down"):
                        self.capture_spread(market, "down", market["token_down"])

                # Status update
                if time.time() - last_status > 60:
                    self.print_status()
                    last_status = time.time()

                time.sleep(2)  # Capture every 2 seconds

        except KeyboardInterrupt:
            print("\nStopped by user")

        self._running = False

        # Analyze and save
        self.analyze_results()
        self.save_results()


def main():
    """Run spread dynamics analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Spread Dynamics Analyzer")
    parser.add_argument(
        "--duration",
        type=int,
        default=900,
        help="Duration in seconds (default: 900 = 15 min)"
    )

    args = parser.parse_args()

    analyzer = SpreadDynamicsAnalyzer()
    analyzer.run(duration_seconds=args.duration)


if __name__ == "__main__":
    main()
