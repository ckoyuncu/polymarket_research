#!/usr/bin/env python3
"""
Resolution Monitor for 15-Minute Markets

Tracks market resolutions for the post-resolution spread capture strategy.
Discovers upcoming and recently resolved markets.

Key functionality:
- Find active 15-min markets via Gamma API
- Track resolution timestamps
- Notify when markets resolve
- Monitor orderbook liquidity post-resolution
"""

import time
import json
import requests
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class Market15m:
    """Represents a 15-minute Up/Down market."""
    slug: str
    question: str
    condition_id: str
    end_timestamp: int
    token_up: str
    token_down: str
    asset: str  # BTC, ETH, SOL, XRP

    # State
    resolved: bool = False
    resolution_time: Optional[int] = None
    winning_outcome: Optional[str] = None  # "Up" or "Down"

    # Prices at resolution
    up_price: float = 0.0
    down_price: float = 0.0

    def time_to_resolution(self) -> float:
        """Seconds until resolution (negative if past)."""
        return self.end_timestamp - time.time()

    def is_active(self) -> bool:
        """Market is still open."""
        return not self.resolved and self.time_to_resolution() > 0

    def is_recently_resolved(self, window_seconds: int = 900) -> bool:
        """Market resolved within window (default 15 min)."""
        if not self.resolved:
            return self.time_to_resolution() < 0 and abs(self.time_to_resolution()) < window_seconds
        return False

    def to_dict(self) -> Dict:
        return {
            "slug": self.slug,
            "question": self.question,
            "condition_id": self.condition_id,
            "end_timestamp": self.end_timestamp,
            "token_up": self.token_up,
            "token_down": self.token_down,
            "asset": self.asset,
            "resolved": self.resolved,
            "winning_outcome": self.winning_outcome,
            "up_price": self.up_price,
            "down_price": self.down_price,
        }


class ResolutionMonitor:
    """
    Monitors 15-minute markets for resolutions.

    Strategy:
    1. Discover upcoming markets via Gamma API
    2. Track resolution times
    3. Check for liquidity after resolution
    4. Signal trading opportunities
    """

    GAMMA_API = "https://gamma-api.polymarket.com"
    CLOB_API = "https://clob.polymarket.com"

    # Assets we track
    ASSETS = ["btc", "eth", "sol", "xrp"]

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data/post_resolution")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Active markets being tracked
        self.markets: Dict[str, Market15m] = {}

        # Resolution queue (markets about to resolve)
        self.resolution_queue: List[str] = []

        # Recently resolved (within 15 min)
        self.recently_resolved: Dict[str, Market15m] = {}

        # Stats
        self.markets_discovered = 0
        self.resolutions_detected = 0

    def discover_markets(self, hours_ahead: int = 2, hours_behind: int = 1) -> List[Market15m]:
        """
        Discover upcoming and recently resolved 15-minute markets.

        Searches for markets resolving in the next N hours and past M hours.
        """
        discovered = []
        now = int(time.time())
        min_ts = now - (hours_behind * 3600)
        max_ts = now + (hours_ahead * 3600)

        for asset in self.ASSETS:
            # Generate potential market slugs based on 15-min intervals
            # Markets resolve at :00, :15, :30, :45
            current_ts = now - (now % 900)  # Round to nearest 15 min

            # Check past markets too (for post-resolution trading)
            start_slot = int(current_ts - (hours_behind * 4 * 900))

            for i in range(int((hours_ahead + hours_behind) * 4) + 1):
                slot_ts = start_slot + (i * 900)

                if slot_ts > max_ts:
                    break

                if slot_ts < min_ts:
                    continue

                slug = f"{asset}-updown-15m-{slot_ts}"

                # Skip if already tracking
                if slug in self.markets:
                    continue

                # Try to fetch from Gamma API
                market = self._fetch_market(slug)

                if market:
                    self.markets[slug] = market
                    discovered.append(market)
                    self.markets_discovered += 1

                    # Small delay to avoid rate limiting
                    time.sleep(0.1)

        return discovered

    def _fetch_market(self, slug: str) -> Optional[Market15m]:
        """Fetch market details from Gamma API."""
        try:
            response = requests.get(
                f"{self.GAMMA_API}/markets/slug/{slug}",
                timeout=10
            )

            if not response.ok:
                return None

            data = response.json()

            # Extract asset from slug
            asset = slug.split("-")[0].upper()

            # Get token IDs (API returns JSON strings, not lists)
            clob_ids = data.get("clobTokenIds", [])
            outcomes = data.get("outcomes", [])

            # Parse if strings
            if isinstance(clob_ids, str):
                clob_ids = json.loads(clob_ids)
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)

            if len(clob_ids) < 2 or len(outcomes) < 2:
                return None

            # Map tokens to outcomes
            token_up = None
            token_down = None

            for i, outcome in enumerate(outcomes):
                if outcome.lower() == "up":
                    token_up = clob_ids[i]
                elif outcome.lower() == "down":
                    token_down = clob_ids[i]

            if not token_up or not token_down:
                return None

            # Parse end timestamp from slug
            try:
                end_ts = int(slug.split("-15m-")[1])
            except:
                return None

            return Market15m(
                slug=slug,
                question=data.get("question", ""),
                condition_id=data.get("conditionId", ""),
                end_timestamp=end_ts,
                token_up=token_up,
                token_down=token_down,
                asset=asset,
            )

        except Exception as e:
            return None

    def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Get orderbook for a token."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
                timeout=10
            )

            if response.ok:
                return response.json()
            return None

        except Exception:
            return None

    def check_resolutions(self) -> List[Market15m]:
        """
        Check for markets that have just resolved.

        Returns list of newly resolved markets.
        """
        now = time.time()
        newly_resolved = []

        for slug, market in list(self.markets.items()):
            if market.resolved:
                continue

            # Check if past resolution time
            if market.time_to_resolution() < 0:
                # Market has resolved
                market.resolved = True
                market.resolution_time = market.end_timestamp

                # Get current prices to determine winner
                self._update_prices(market)

                # Determine winning outcome based on prices
                if market.up_price > 0.9:
                    market.winning_outcome = "Up"
                elif market.down_price > 0.9:
                    market.winning_outcome = "Down"

                newly_resolved.append(market)
                self.recently_resolved[slug] = market
                self.resolutions_detected += 1

        return newly_resolved

    def _update_prices(self, market: Market15m):
        """Update market prices from orderbook."""
        # Get UP token price
        up_book = self.get_orderbook(market.token_up)
        if up_book:
            bids = up_book.get("bids", [])
            asks = up_book.get("asks", [])

            if bids:
                market.up_price = float(bids[0]["price"])
            elif asks:
                market.up_price = float(asks[0]["price"])

        # Get DOWN token price
        down_book = self.get_orderbook(market.token_down)
        if down_book:
            bids = down_book.get("bids", [])
            asks = down_book.get("asks", [])

            if bids:
                market.down_price = float(bids[0]["price"])
            elif asks:
                market.down_price = float(asks[0]["price"])

    def get_active_markets(self) -> List[Market15m]:
        """Get all active (not yet resolved) markets."""
        return [m for m in self.markets.values() if m.is_active()]

    def get_upcoming_resolutions(self, within_seconds: int = 300) -> List[Market15m]:
        """Get markets resolving within N seconds."""
        return [
            m for m in self.markets.values()
            if m.is_active() and 0 < m.time_to_resolution() < within_seconds
        ]

    def get_recently_resolved(self, within_seconds: int = 900) -> List[Market15m]:
        """Get markets that resolved within N seconds."""
        now = time.time()
        return [
            m for m in self.markets.values()
            if m.resolved and (now - m.end_timestamp) < within_seconds
        ]

    def get_tradeable_markets(self) -> List[Tuple[Market15m, Dict, Dict]]:
        """
        Get markets that are tradeable (resolved with liquidity).

        Returns list of (market, up_orderbook, down_orderbook) tuples.
        """
        tradeable = []

        for market in self.get_recently_resolved():
            up_book = self.get_orderbook(market.token_up)
            down_book = self.get_orderbook(market.token_down)

            # Check if there's liquidity
            has_up_liquidity = up_book and (up_book.get("bids") or up_book.get("asks"))
            has_down_liquidity = down_book and (down_book.get("bids") or down_book.get("asks"))

            if has_up_liquidity or has_down_liquidity:
                tradeable.append((market, up_book or {}, down_book or {}))

        return tradeable

    def cleanup_old_markets(self, max_age_hours: int = 2):
        """Remove markets that are too old to trade."""
        now = time.time()
        cutoff = now - (max_age_hours * 3600)

        # Remove from main dict
        to_remove = [
            slug for slug, m in self.markets.items()
            if m.end_timestamp < cutoff
        ]

        for slug in to_remove:
            del self.markets[slug]
            if slug in self.recently_resolved:
                del self.recently_resolved[slug]

    def save_state(self):
        """Save current state to disk."""
        state = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "markets": {slug: m.to_dict() for slug, m in self.markets.items()},
            "stats": {
                "markets_discovered": self.markets_discovered,
                "resolutions_detected": self.resolutions_detected,
            }
        }

        filepath = self.data_dir / "monitor_state.json"
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)

    def load_state(self):
        """Load state from disk."""
        filepath = self.data_dir / "monitor_state.json"

        if not filepath.exists():
            return

        try:
            with open(filepath) as f:
                state = json.load(f)

            for slug, data in state.get("markets", {}).items():
                self.markets[slug] = Market15m(
                    slug=data["slug"],
                    question=data["question"],
                    condition_id=data["condition_id"],
                    end_timestamp=data["end_timestamp"],
                    token_up=data["token_up"],
                    token_down=data["token_down"],
                    asset=data["asset"],
                    resolved=data.get("resolved", False),
                    winning_outcome=data.get("winning_outcome"),
                    up_price=data.get("up_price", 0),
                    down_price=data.get("down_price", 0),
                )

            stats = state.get("stats", {})
            self.markets_discovered = stats.get("markets_discovered", 0)
            self.resolutions_detected = stats.get("resolutions_detected", 0)

        except Exception as e:
            print(f"Error loading state: {e}")

    def print_status(self):
        """Print current monitor status."""
        now = time.time()

        print("\n" + "=" * 60)
        print("RESOLUTION MONITOR STATUS")
        print("=" * 60)
        print(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
        print(f"Markets tracked: {len(self.markets)}")
        print(f"Active: {len(self.get_active_markets())}")
        print(f"Resolved: {len([m for m in self.markets.values() if m.resolved])}")

        upcoming = self.get_upcoming_resolutions(within_seconds=300)
        if upcoming:
            print(f"\nUpcoming resolutions (next 5 min):")
            for m in upcoming[:5]:
                secs = m.time_to_resolution()
                print(f"  {m.asset} {m.slug[-10:]} - {secs:.0f}s")

        recently = self.get_recently_resolved(within_seconds=900)
        if recently:
            print(f"\nRecently resolved (last 15 min):")
            for m in recently[:5]:
                age = now - m.end_timestamp
                print(f"  {m.asset} {m.slug[-10:]} - {age:.0f}s ago - Winner: {m.winning_outcome}")


def main():
    """Test the resolution monitor."""
    monitor = ResolutionMonitor()

    print("Discovering markets...")
    discovered = monitor.discover_markets(hours_ahead=1)
    print(f"Discovered {len(discovered)} markets")

    for m in discovered[:5]:
        print(f"  {m.slug}: {m.question[:50]}")

    print("\nChecking for resolutions...")
    resolved = monitor.check_resolutions()
    print(f"Found {len(resolved)} newly resolved markets")

    print("\nGetting tradeable markets...")
    tradeable = monitor.get_tradeable_markets()
    print(f"Found {len(tradeable)} tradeable markets")

    for market, up_book, down_book in tradeable[:3]:
        print(f"\n  {market.slug}")
        print(f"    UP bids: {len(up_book.get('bids', []))}, asks: {len(up_book.get('asks', []))}")
        print(f"    DOWN bids: {len(down_book.get('bids', []))}, asks: {len(down_book.get('asks', []))}")

    monitor.print_status()


if __name__ == "__main__":
    main()
