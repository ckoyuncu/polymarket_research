"""
Market Finder for 15-minute Crypto Markets.

Discovers and tracks the active 15-minute BTC/ETH up/down markets.
These markets resolve every 15 minutes (:00, :15, :30, :45).

API Discovery Notes:
- Markets have slugs like: btc-updown-15m-{unix_timestamp}
- The timestamp is the market END time (resolution time)
- Markets are created by a series: btc-up-or-down-15m, eth-up-or-down-15m
- Resolution source: Chainlink BTC/USD or ETH/USD data streams
- Example: btc-updown-15m-1767729600 ends at 2026-01-06 20:00:00 UTC
"""
import time
import json
import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime

import requests

from ..config import GAMMA_API_URL

logger = logging.getLogger(__name__)

# Supported assets for 15-minute markets
SUPPORTED_ASSETS = ["btc", "eth", "sol", "xrp"]


@dataclass
class Market15Min:
    """Represents a 15-minute crypto market."""

    condition_id: str
    question: str
    slug: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    volume_24h: float
    liquidity: float
    end_time: int  # Unix timestamp

    @property
    def spread(self) -> float:
        """Calculate bid-ask spread."""
        return 1.0 - (self.yes_price + self.no_price)

    @property
    def mid_price(self) -> float:
        """Calculate mid price."""
        return self.yes_price

    @property
    def seconds_to_resolution(self) -> int:
        """Seconds until market resolves."""
        return max(0, self.end_time - int(time.time()))

    @property
    def is_tradeable(self) -> bool:
        """Check if market is still tradeable (>60s to resolution)."""
        return self.seconds_to_resolution > 60

    def to_dict(self) -> Dict:
        return {
            "condition_id": self.condition_id,
            "question": self.question,
            "slug": self.slug,
            "yes_token_id": self.yes_token_id,
            "no_token_id": self.no_token_id,
            "yes_price": self.yes_price,
            "no_price": self.no_price,
            "spread": self.spread,
            "volume_24h": self.volume_24h,
            "liquidity": self.liquidity,
            "end_time": self.end_time,
            "seconds_to_resolution": self.seconds_to_resolution,
        }


class MarketFinder:
    """
    Finds and tracks 15-minute crypto markets on Polymarket.

    These markets use a predictable slug format:
    - {asset}-updown-15m-{end_timestamp}
    - Example: btc-updown-15m-1767729600

    The timestamp is when the market resolves (end of the 15-minute window).

    Example:
        finder = MarketFinder()
        markets = finder.find_active_markets()
        for market in markets:
            print(f"{market.question}: UP={market.yes_price:.2f}, DOWN={market.no_price:.2f}")
    """

    def __init__(self, assets: Optional[List[str]] = None):
        """
        Initialize the market finder.

        Args:
            assets: List of assets to track (default: ["btc", "eth"])
        """
        self.gamma_url = GAMMA_API_URL
        self.assets = assets or ["btc", "eth"]
        self._cache: Dict[str, Market15Min] = {}
        self._last_fetch = 0
        self._cache_ttl = 10  # seconds

    @staticmethod
    def get_next_15m_timestamp() -> int:
        """
        Get the Unix timestamp for the next 15-minute boundary.

        Returns:
            Unix timestamp when the current 15-minute window ends
        """
        now = int(time.time())
        return ((now // 900) + 1) * 900

    @staticmethod
    def get_current_15m_timestamp() -> int:
        """
        Get the Unix timestamp for the current 15-minute window's end.

        If we're within the first few seconds after a boundary,
        return that boundary. Otherwise, return the next one.
        """
        now = int(time.time())
        next_boundary = ((now // 900) + 1) * 900
        # If the boundary just passed (within 60 seconds), use it
        if now - (next_boundary - 900) < 60:
            return next_boundary - 900
        return next_boundary

    def _build_market_slug(self, asset: str, timestamp: int) -> str:
        """Build the market slug for a given asset and timestamp."""
        return f"{asset.lower()}-updown-15m-{timestamp}"

    def _fetch_market_by_slug(self, slug: str) -> Optional[Dict]:
        """
        Fetch a single market by its exact slug.

        Args:
            slug: Market slug (e.g., "btc-updown-15m-1767729600")

        Returns:
            Market dictionary or None
        """
        try:
            url = f"{self.gamma_url}/markets"
            params = {"slug": slug}

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return None

        except requests.RequestException as e:
            logger.debug(f"Failed to fetch market {slug}: {e}")
            return None

    def _fetch_markets_from_gamma(self, slug: str) -> List[Dict]:
        """
        Fetch market data from Gamma API (legacy method for compatibility).

        Args:
            slug: Market slug

        Returns:
            List of market dictionaries
        """
        market = self._fetch_market_by_slug(slug)
        return [market] if market else []

    def _parse_market(self, data: Dict) -> Optional[Market15Min]:
        """
        Parse market data into Market15Min object.

        The 15-minute markets have outcomes "Up" and "Down" instead of "Yes" and "No".
        We map: Up -> yes_token_id, Down -> no_token_id

        Args:
            data: Raw market data from API

        Returns:
            Market15Min object or None
        """
        try:
            # Parse outcomes and prices from JSON strings
            outcomes_str = data.get("outcomes", "[]")
            prices_str = data.get("outcomePrices", "[]")
            token_ids_str = data.get("clobTokenIds", "[]")

            outcomes = json.loads(outcomes_str) if isinstance(outcomes_str, str) else outcomes_str
            prices = json.loads(prices_str) if isinstance(prices_str, str) else prices_str
            token_ids = json.loads(token_ids_str) if isinstance(token_ids_str, str) else token_ids_str

            if len(outcomes) < 2 or len(prices) < 2 or len(token_ids) < 2:
                logger.warning(f"Market {data.get('slug')} has incomplete data")
                return None

            # Find Up and Down (or Yes and No) indices
            up_idx = None
            down_idx = None

            for i, outcome in enumerate(outcomes):
                outcome_upper = outcome.upper()
                if outcome_upper in ("UP", "YES"):
                    up_idx = i
                elif outcome_upper in ("DOWN", "NO"):
                    down_idx = i

            if up_idx is None or down_idx is None:
                logger.warning(f"Could not find Up/Down outcomes in {outcomes}")
                return None

            # Extract prices and token IDs
            up_price = float(prices[up_idx])
            down_price = float(prices[down_idx])
            up_token_id = token_ids[up_idx]
            down_token_id = token_ids[down_idx]

            # Parse end time from various formats
            end_date = data.get("endDate") or data.get("endDateIso") or data.get("end_date_iso")
            if end_date:
                # Handle ISO format with timezone
                if isinstance(end_date, str):
                    end_date = end_date.replace("Z", "+00:00")
                    try:
                        end_time = int(datetime.fromisoformat(end_date).timestamp())
                    except ValueError:
                        # Try parsing without timezone
                        end_time = int(datetime.fromisoformat(end_date.replace("+00:00", "")).timestamp())
                else:
                    end_time = int(end_date)
            else:
                # Extract from slug if available (e.g., btc-updown-15m-1767729600)
                slug = data.get("slug", "")
                parts = slug.split("-")
                if len(parts) >= 4 and parts[-1].isdigit():
                    end_time = int(parts[-1])
                else:
                    end_time = int(time.time()) + 900

            return Market15Min(
                condition_id=data.get("conditionId", "") or data.get("condition_id", ""),
                question=data.get("question", "Unknown"),
                slug=data.get("slug", ""),
                yes_token_id=up_token_id,  # "Up" maps to yes
                no_token_id=down_token_id,  # "Down" maps to no
                yes_price=up_price,
                no_price=down_price,
                volume_24h=float(data.get("volume24hr", 0) or data.get("volume_24hr", 0) or data.get("volumeNum", 0) or 0),
                liquidity=float(data.get("liquidity", 0) or data.get("liquidityNum", 0) or 0),
                end_time=end_time,
            )

        except Exception as e:
            logger.error(f"Failed to parse market: {e}", exc_info=True)
            return None

    def find_active_markets(self, force_refresh: bool = False) -> List[Market15Min]:
        """
        Find all active 15-minute crypto markets.

        Uses the predictable slug pattern to fetch current markets:
        - Calculates multiple 15-minute boundary timestamps
        - Fetches markets for each configured asset
        - Note: BTC and ETH markets may be offset by 15 minutes

        Args:
            force_refresh: Force refresh even if cache is valid

        Returns:
            List of Market15Min objects
        """
        # Check cache
        now = time.time()
        if not force_refresh and (now - self._last_fetch) < self._cache_ttl:
            return list(self._cache.values())

        markets = []

        # Calculate timestamps to check - check multiple windows since
        # different assets may have offset schedules
        base_ts = self.get_next_15m_timestamp()
        timestamps = [
            base_ts - 900,   # Previous window
            base_ts,         # Current window
            base_ts + 900,   # Next window
        ]

        # Fetch markets for each asset and timestamp
        for asset in self.assets:
            found_for_asset = False
            for ts in timestamps:
                if found_for_asset:
                    break  # Already found a tradeable market for this asset

                slug = self._build_market_slug(asset, ts)
                raw_market = self._fetch_market_by_slug(slug)

                if raw_market:
                    market = self._parse_market(raw_market)
                    if market and market.is_tradeable:
                        # Avoid duplicates
                        if market.condition_id not in [m.condition_id for m in markets]:
                            markets.append(market)
                            found_for_asset = True
                            logger.debug(f"Found market: {market.slug} (ends in {market.seconds_to_resolution}s)")

        # Update cache
        self._cache = {m.condition_id: m for m in markets}
        self._last_fetch = now

        logger.info(f"Found {len(markets)} active 15-minute markets for {self.assets}")
        return markets

    def find_market_for_asset(self, asset: str) -> Optional[Market15Min]:
        """
        Find the currently active market for a specific asset.

        Args:
            asset: Asset symbol (btc, eth, sol, xrp)

        Returns:
            Market15Min or None
        """
        asset = asset.lower()

        # Try multiple timestamps since assets may have offset schedules
        base_ts = self.get_next_15m_timestamp()
        timestamps = [
            base_ts - 900,   # Previous window
            base_ts,         # Current window
            base_ts + 900,   # Next window
        ]

        for ts in timestamps:
            slug = self._build_market_slug(asset, ts)
            raw_market = self._fetch_market_by_slug(slug)

            if raw_market:
                market = self._parse_market(raw_market)
                if market and market.is_tradeable:
                    return market

        return None

    def get_market_by_condition(self, condition_id: str) -> Optional[Market15Min]:
        """
        Get a specific market by condition ID.

        Args:
            condition_id: Market condition ID

        Returns:
            Market15Min or None
        """
        if condition_id in self._cache:
            return self._cache[condition_id]

        # Refresh and try again
        self.find_active_markets(force_refresh=True)
        return self._cache.get(condition_id)

    def get_best_market(self, asset: str = "btc") -> Optional[Market15Min]:
        """
        Get the best market for maker rebates.

        Best = highest volume, good spread, enough time to resolution.

        Args:
            asset: "btc" or "eth"

        Returns:
            Best Market15Min or None
        """
        markets = self.find_active_markets()

        # Filter by asset
        asset_markets = [
            m for m in markets
            if asset.lower() in m.question.lower() or asset.lower() in m.slug.lower()
        ]

        if not asset_markets:
            return None

        # Sort by volume (highest first) and time (most time remaining)
        def score(m: Market15Min) -> float:
            volume_score = m.volume_24h / 100000  # Normalize
            time_score = min(m.seconds_to_resolution / 900, 1.0)  # Cap at 1
            spread_penalty = max(0, m.spread - 0.02) * 10  # Penalize wide spreads
            return volume_score + time_score - spread_penalty

        asset_markets.sort(key=score, reverse=True)
        return asset_markets[0]


def demo():
    """Demo the market finder."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    print(f"\n{'='*70}")
    print("Polymarket 15-Minute Crypto Market Finder")
    print(f"{'='*70}")
    print(f"Current time: {datetime.now()}")
    next_ts = MarketFinder.get_next_15m_timestamp()
    print(f"Next 15m boundary: {datetime.fromtimestamp(next_ts)} (ts={next_ts})")
    print()

    # Find markets for BTC and ETH
    finder = MarketFinder(assets=["btc", "eth"])
    markets = finder.find_active_markets()

    print(f"\n{'='*70}")
    print(f"Found {len(markets)} active 15-minute markets")
    print(f"{'='*70}\n")

    for market in markets:
        print(f"Market: {market.question}")
        print(f"  Slug: {market.slug}")
        print(f"  Condition ID: {market.condition_id}")
        print(f"  UP price: {market.yes_price:.3f} | DOWN price: {market.no_price:.3f}")
        print(f"  Spread: {market.spread:.3f} ({market.spread*100:.1f}%)")
        print(f"  Time left: {market.seconds_to_resolution}s ({market.seconds_to_resolution//60}m {market.seconds_to_resolution%60}s)")
        print(f"  Tradeable: {market.is_tradeable}")
        print(f"  Volume: ${market.volume_24h:,.2f}")
        print(f"  Liquidity: ${market.liquidity:,.2f}")
        print(f"  UP Token ID: {market.yes_token_id}")
        print(f"  DOWN Token ID: {market.no_token_id}")
        print()

    # Test individual asset lookup
    print(f"\n{'='*70}")
    print("Testing individual asset lookup")
    print(f"{'='*70}\n")

    for asset in ["btc", "eth"]:
        market = finder.find_market_for_asset(asset)
        if market:
            print(f"{asset.upper()}: Found market ending in {market.seconds_to_resolution}s")
            print(f"  {market.question}")
            print(f"  UP: {market.yes_price:.3f} | DOWN: {market.no_price:.3f}")
        else:
            print(f"{asset.upper()}: No active market found")
        print()


if __name__ == "__main__":
    demo()
