"""
Market Scanner

Scans Polymarket for active 15-minute resolution markets
that are suitable for arbitrage trading.

FIXED: Now implements actual Polymarket API integration
"""
import re
import time
from typing import List, Optional, Dict
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class ArbitrageMarket:
    """
    A market suitable for arbitrage.

    Represents a binary market like:
    "Will BTC be above $95,000 at 12:15 UTC?"
    """
    condition_id: str
    question: str
    asset: str  # "BTC" or "ETH"
    strike_price: float  # e.g., 95000
    resolution_time: int  # Unix timestamp
    yes_token_id: str
    no_token_id: str
    yes_price: float  # Current YES price (0-1)
    no_price: float  # Current NO price (0-1)
    liquidity: float  # Total liquidity in USD
    volume_24h: float  # 24h volume
    slug: str = ""  # Market slug

    @property
    def resolution_datetime(self) -> datetime:
        """Get resolution time as datetime."""
        return datetime.fromtimestamp(self.resolution_time)

    @property
    def seconds_until_resolution(self) -> float:
        """Seconds until market resolves."""
        now = datetime.utcnow().timestamp()
        return max(0, self.resolution_time - now)

    @property
    def is_above_strike(self) -> bool:
        """True if question asks 'above' or 'up', False if 'below' or 'down'."""
        q_lower = self.question.lower()
        # Check for "above" or "up" patterns
        if "above" in q_lower or "over" in q_lower:
            return True
        # For "Up or Down" markets, check the outcome we're trading
        if "up or down" in q_lower:
            # These markets resolve based on price movement
            return True  # YES = price went up
        return False

    def __repr__(self) -> str:
        return (
            f"ArbitrageMarket({self.asset} @ ${self.strike_price:,.0f}, "
            f"resolves in {self.seconds_until_resolution:.0f}s)"
        )


class MarketScanner:
    """
    Scans Polymarket for arbitrage-suitable markets.

    Looks for:
    - 15-minute resolution markets
    - BTC/ETH price-based questions
    - Active markets (not yet resolved)
    - Sufficient liquidity (>$500)

    Example:
        from src.api.data_api import DataAPIClient
        from src.api.gamma import GammaClient

        scanner = MarketScanner(DataAPIClient(), GammaClient())
        markets = scanner.scan()

        for market in markets:
            print(f"{market.asset}: ${market.strike_price:,.0f}")
            print(f"  YES: {market.yes_price:.3f}")
            print(f"  NO: {market.no_price:.3f}")
            print(f"  Resolves in: {market.seconds_until_resolution:.0f}s")
    """

    def __init__(self, data_api=None, gamma_client=None):
        """
        Initialize scanner.

        Args:
            data_api: DataAPIClient instance
            gamma_client: GammaClient instance (optional, will create if None)
        """
        self.data_api = data_api

        # Import and create GammaClient if not provided
        if gamma_client is None:
            from ..api import GammaClient
            self.gamma = GammaClient()
        else:
            self.gamma = gamma_client

        # Filters
        self.min_liquidity = 500  # $500
        self.supported_assets = ["BTC", "ETH", "BITCOIN", "ETHEREUM"]

        # Account88888 market patterns (from deep analysis)
        self.target_slugs = [
            "btc-updown-15m",
            "eth-updown-15m",
            "bitcoin-up-or-down",
            "ethereum-up-or-down",
        ]

        self.target_keywords = [
            "Bitcoin Up or Down",
            "Ethereum Up or Down",
            "BTC Up or Down",
            "ETH Up or Down",
            "15 minute",
            "15m",
        ]

        # Cache
        self._market_cache: Dict[str, ArbitrageMarket] = {}
        self._last_scan_time = 0
        self._cache_duration = 30  # seconds

    def scan(self, force_refresh: bool = False) -> List[ArbitrageMarket]:
        """
        Scan for active arbitrage markets.

        Uses two strategies:
        1. Construct known 15-min market slugs based on current time
        2. Fall back to keyword search

        Args:
            force_refresh: Force refresh even if cached

        Returns:
            List of ArbitrageMarket objects
        """
        now = time.time()

        # Use cache if recent
        if not force_refresh and (now - self._last_scan_time) < self._cache_duration:
            cached = list(self._market_cache.values())
            # Filter out expired markets
            return [m for m in cached if m.seconds_until_resolution > 0]

        markets = []
        seen_ids = set()

        try:
            # Strategy 1: Construct 15-min market slugs directly
            # These markets use format: {asset}-updown-15m-{unix_timestamp}
            constructed_markets = self._scan_constructed_slugs()
            for market in constructed_markets:
                if market and market.condition_id not in seen_ids:
                    if self._passes_filters(market):
                        markets.append(market)
                        seen_ids.add(market.condition_id)

            # Strategy 2: Fall back to keyword search if no constructed markets found
            if not markets:
                for keyword in self.target_keywords:
                    try:
                        results = self.gamma.search_markets(keyword, limit=50, active=True)

                        for market_data in results:
                            market = self._parse_market(market_data)
                            if market and market.condition_id not in seen_ids:
                                if self._passes_filters(market):
                                    markets.append(market)
                                    seen_ids.add(market.condition_id)

                    except Exception as e:
                        continue

                    time.sleep(0.1)

            print(f"✅ Found {len(markets)} arbitrage-suitable markets")

        except Exception as e:
            print(f"Error scanning markets: {e}")

        self._last_scan_time = now
        self._market_cache = {m.condition_id: m for m in markets}

        return markets

    def _scan_constructed_slugs(self) -> List[ArbitrageMarket]:
        """
        Construct and fetch 15-minute market slugs.

        Account88888's markets use format:
        - btc-updown-15m-{unix_timestamp}
        - eth-updown-15m-{unix_timestamp}

        Where timestamp is the resolution time (e.g., :00, :15, :30, :45)
        """
        from datetime import datetime, timezone

        markets = []
        now = datetime.now(timezone.utc)

        # Calculate next few 15-minute windows
        # Windows are at :00, :15, :30, :45
        current_minute = now.minute
        current_second = now.second

        # Find next window times
        window_minutes = [0, 15, 30, 45]
        windows_to_check = []

        for offset_hours in range(2):  # Check current and next hour
            for wm in window_minutes:
                # Calculate window time
                window_time = now.replace(minute=wm, second=0, microsecond=0)
                if offset_hours > 0:
                    window_time = window_time.replace(hour=(now.hour + offset_hours) % 24)

                # Only include future windows within 2 hours
                window_ts = int(window_time.timestamp())
                current_ts = int(now.timestamp())

                if 0 < (window_ts - current_ts) < 7200:  # Within 2 hours
                    windows_to_check.append(window_ts)

        # Remove duplicates and sort
        windows_to_check = sorted(set(windows_to_check))[:8]  # Max 8 windows

        # Try to fetch each potential market
        assets = ["btc", "eth"]

        for asset in assets:
            for window_ts in windows_to_check:
                slug = f"{asset}-updown-15m-{window_ts}"
                try:
                    market_data = self.gamma.get_market_by_slug(slug)
                    if market_data and market_data.get("active"):
                        market = self._parse_market(market_data)
                        if market:
                            markets.append(market)
                except Exception:
                    continue

                time.sleep(0.05)  # Small delay

        return markets

    def _parse_market(self, market_data: Dict) -> Optional[ArbitrageMarket]:
        """
        Parse raw market data into ArbitrageMarket.

        Args:
            market_data: Raw market dict from Gamma API

        Returns:
            ArbitrageMarket or None if parsing fails
        """
        try:
            question = market_data.get("question", "")
            slug = market_data.get("slug", "")

            # Check if it's a target market type
            if not self._is_target_market(slug, question):
                return None

            # Extract asset
            asset = self._extract_asset(question, slug)
            if not asset:
                return None

            # Extract strike price
            strike = self._extract_strike_price(question, asset)

            # Get resolution time
            # PRIORITY: Extract from slug first for 15-min markets (more accurate)
            resolution_time = self._extract_timestamp_from_slug(slug)

            if not resolution_time:
                # Fall back to endDateIso
                end_date = market_data.get("endDateIso") or market_data.get("endDate")
                resolution_time = self._parse_iso_timestamp(end_date)

            if not resolution_time:
                return None

            # Skip already resolved markets
            if resolution_time < time.time():
                return None

            # Get token IDs
            clob_ids = market_data.get("clobTokenIds", [])
            outcomes = market_data.get("outcomes", ["Yes", "No"])

            yes_token_id = clob_ids[0] if len(clob_ids) > 0 else ""
            no_token_id = clob_ids[1] if len(clob_ids) > 1 else ""

            # Get prices from outcomes or outcomePrices
            outcome_prices = market_data.get("outcomePrices", [])
            if outcome_prices and len(outcome_prices) >= 2:
                try:
                    yes_price = float(outcome_prices[0])
                    no_price = float(outcome_prices[1])
                except (ValueError, TypeError):
                    yes_price = 0.5
                    no_price = 0.5
            else:
                # Try to get from tokens
                tokens = market_data.get("tokens", [])
                yes_price = 0.5
                no_price = 0.5
                for token in tokens:
                    outcome = token.get("outcome", "").lower()
                    price = float(token.get("price", 0.5))
                    if outcome == "yes":
                        yes_price = price
                    elif outcome == "no":
                        no_price = price

            # Get liquidity
            liquidity = float(market_data.get("liquidity", 0) or 0)
            volume = float(market_data.get("volume24hr", 0) or market_data.get("volume", 0) or 0)

            return ArbitrageMarket(
                condition_id=market_data.get("conditionId") or market_data.get("condition_id", ""),
                question=question,
                asset=asset,
                strike_price=strike,
                resolution_time=resolution_time,
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                yes_price=yes_price,
                no_price=no_price,
                liquidity=liquidity,
                volume_24h=volume,
                slug=slug
            )

        except Exception as e:
            print(f"   Warning: Failed to parse market: {e}")
            return None

    def _is_target_market(self, slug: str, question: str) -> bool:
        """Check if market matches our target patterns."""
        slug_lower = slug.lower()
        question_lower = question.lower()

        # Check slug patterns
        for target in self.target_slugs:
            if target in slug_lower:
                return True

        # Check question patterns
        is_up_down = "up or down" in question_lower or "up/down" in question_lower
        is_crypto = any(asset.lower() in question_lower for asset in ["bitcoin", "btc", "ethereum", "eth"])
        has_time = "15" in question_lower or re.search(r"\d{1,2}:\d{2}", question_lower)

        if is_up_down and is_crypto:
            return True

        if is_crypto and has_time and ("above" in question_lower or "below" in question_lower):
            return True

        return False

    def _extract_asset(self, question: str, slug: str) -> Optional[str]:
        """Extract asset (BTC/ETH) from question or slug."""
        text = (question + " " + slug).lower()

        if "btc" in text or "bitcoin" in text:
            return "BTC"
        elif "eth" in text or "ethereum" in text:
            return "ETH"

        return None

    def _extract_strike_price(self, question: str, asset: str) -> float:
        """Extract strike price from question."""
        # Pattern to match prices like $95,000 or 95000 or 3,500.50
        price_pattern = r'\$?([\d,]+(?:\.\d+)?)'

        matches = re.findall(price_pattern, question)

        for match in matches:
            try:
                price = float(match.replace(',', ''))

                # Validate price is in reasonable range for asset
                if asset == "BTC" and 10000 < price < 500000:
                    return price
                elif asset == "ETH" and 100 < price < 50000:
                    return price

            except ValueError:
                continue

        # Default strike prices based on current rough prices
        # This is a fallback; ideally we always extract from question
        return 95000 if asset == "BTC" else 3500

    def _extract_timestamp_from_slug(self, slug: str) -> Optional[int]:
        """Extract Unix timestamp from slug like btc-updown-15m-1767541500."""
        match = re.search(r'-(\d{10})$', slug)
        if match:
            return int(match.group(1))
        return None

    def _parse_iso_timestamp(self, date_str: Optional[str]) -> Optional[int]:
        """Parse ISO date string to Unix timestamp."""
        if not date_str:
            return None

        try:
            # Handle various ISO formats
            for fmt in [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S%z",
            ]:
                try:
                    dt = datetime.strptime(date_str.replace("+00:00", "Z").rstrip("Z") + "Z", fmt.rstrip("Z") + "Z" if "Z" in fmt else fmt)
                    return int(dt.timestamp())
                except ValueError:
                    continue

            # Try fromisoformat as fallback
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return int(dt.timestamp())

        except Exception:
            pass

        return None

    def _passes_filters(self, market: ArbitrageMarket) -> bool:
        """Check if market passes all filters."""
        # Must resolve in the future
        if market.seconds_until_resolution <= 0:
            return False

        # Must resolve within reasonable time (next 2 hours)
        if market.seconds_until_resolution > 7200:
            return False

        # Must have minimum liquidity
        if market.liquidity < self.min_liquidity:
            # Be lenient - some markets may not report liquidity correctly
            # but still have good volume
            if market.volume_24h < 100:
                return False

        # Must have valid token IDs
        if not market.yes_token_id or not market.no_token_id:
            return False

        # Must have valid prices
        if market.yes_price <= 0 or market.no_price <= 0:
            return False

        return True

    def matches_target_pattern(self, market_slug: str, market_title: str) -> bool:
        """
        Check if a market matches Account88888's target patterns.

        Matches markets like:
        - btc-updown-15m-1767541500
        - eth-updown-15m-1767541500
        - "Bitcoin Up or Down - January 4, 10:45AM-11:00AM ET"

        Args:
            market_slug: Market slug (e.g., "btc-updown-15m-1767541500")
            market_title: Market title/question

        Returns:
            True if matches target pattern
        """
        return self._is_target_market(market_slug, market_title)

    def parse_question(self, question: str) -> Optional[Dict]:
        """
        Parse a market question to extract details.

        Example questions:
        - "Will BTC be above $95,000 at 12:15 UTC?"
        - "Will ETH be below $3,500 at 18:30 UTC?"
        - "Bitcoin Up or Down - January 4, 10:45AM-11:00AM ET"

        Returns:
            Dict with:
            - asset: "BTC" or "ETH"
            - direction: "above" or "below" or "up_or_down"
            - strike_price: float
            - time_str: "12:15" or "10:45AM-11:00AM"
        """
        # Pattern to match price
        price_pattern = r'\$?([\d,]+(?:\.\d+)?)'

        # Pattern to match asset
        asset_pattern = r'(BTC|ETH|Bitcoin|Ethereum)'

        # Pattern to match direction
        direction_pattern = r'(above|below|over|under|up or down|up/down)'

        # Pattern to match time
        time_pattern = r'(\d{1,2}:\d{2}(?:AM|PM)?(?:\s*-\s*\d{1,2}:\d{2}(?:AM|PM)?)?)'

        # Extract components
        price_match = re.search(price_pattern, question)
        asset_match = re.search(asset_pattern, question, re.IGNORECASE)
        direction_match = re.search(direction_pattern, question, re.IGNORECASE)
        time_match = re.search(time_pattern, question, re.IGNORECASE)

        if not asset_match:
            return None

        # Parse asset
        asset = asset_match.group(1).upper()
        if asset in ["BITCOIN"]:
            asset = "BTC"
        elif asset in ["ETHEREUM"]:
            asset = "ETH"

        # Parse direction
        direction = "unknown"
        if direction_match:
            direction = direction_match.group(1).lower()
            if direction in ["over"]:
                direction = "above"
            elif direction in ["under"]:
                direction = "below"
            elif "up" in direction and "down" in direction:
                direction = "up_or_down"

        # Parse price
        strike_price = 0.0
        if price_match:
            price_str = price_match.group(1).replace(',', '')
            try:
                strike_price = float(price_str)
            except ValueError:
                pass

        return {
            "asset": asset,
            "direction": direction,
            "strike_price": strike_price,
            "time_str": time_match.group(1) if time_match else ""
        }

    def find_markets_for_next_window(
        self,
        window_time: datetime,
        max_seconds_before: int = 300
    ) -> List[ArbitrageMarket]:
        """
        Find markets that resolve at a specific window.

        Args:
            window_time: Target window time
            max_seconds_before: Only include markets this close to window

        Returns:
            Markets resolving near this window
        """
        all_markets = self.scan()

        target_timestamp = int(window_time.timestamp())
        matching = []

        for market in all_markets:
            # Check if resolution time is close to window
            time_diff = abs(market.resolution_time - target_timestamp)

            if time_diff <= max_seconds_before:
                matching.append(market)

        return matching

    def get_market(self, condition_id: str) -> Optional[ArbitrageMarket]:
        """
        Get a specific market by condition ID.

        Args:
            condition_id: Market condition ID

        Returns:
            ArbitrageMarket or None
        """
        # Check cache first
        if condition_id in self._market_cache:
            return self._market_cache[condition_id]

        # Fetch from API
        try:
            market_data = self.gamma.get_market(condition_id)
            if market_data:
                return self._parse_market(market_data)
        except Exception as e:
            print(f"   Error fetching market {condition_id}: {e}")

        return None

    def filter_by_asset(
        self,
        markets: List[ArbitrageMarket],
        asset: str
    ) -> List[ArbitrageMarket]:
        """Filter markets by asset."""
        asset = asset.upper()
        if asset == "BITCOIN":
            asset = "BTC"
        elif asset == "ETHEREUM":
            asset = "ETH"

        return [m for m in markets if m.asset == asset]

    def filter_by_liquidity(
        self,
        markets: List[ArbitrageMarket],
        min_liquidity: float
    ) -> List[ArbitrageMarket]:
        """Filter markets by minimum liquidity."""
        return [m for m in markets if m.liquidity >= min_liquidity]

    def get_markets_expiring_soon(
        self,
        max_seconds: int = 120
    ) -> List[ArbitrageMarket]:
        """
        Get markets expiring within max_seconds.

        Args:
            max_seconds: Maximum seconds until resolution

        Returns:
            Markets about to resolve
        """
        all_markets = self.scan()
        return [
            m for m in all_markets
            if 0 < m.seconds_until_resolution <= max_seconds
        ]


def test_scanner():
    """Test the market scanner."""
    print("Testing Market Scanner...")
    print("="*60)

    # Create scanner with real API
    from ..api import GammaClient
    scanner = MarketScanner(None, GammaClient())

    # Test question parsing
    questions = [
        "Will BTC be above $95,000 at 12:15 UTC?",
        "Will ETH be below $3,500 at 18:30 UTC?",
        "Will Bitcoin be over $100,000 at 09:45 UTC?",
        "Bitcoin Up or Down - January 4, 10:45AM-11:00AM ET",
    ]

    print("\n--- Question Parsing ---")
    for q in questions:
        result = scanner.parse_question(q)
        print(f"\nQ: {q}")
        if result:
            print(f"   Asset: {result['asset']}")
            print(f"   Direction: {result['direction']}")
            print(f"   Strike: ${result['strike_price']:,.0f}")
            print(f"   Time: {result['time_str']}")
        else:
            print("   ❌ Could not parse")

    # Test market scanning
    print("\n--- Live Market Scan ---")
    markets = scanner.scan()

    if markets:
        print(f"\nFound {len(markets)} markets:")
        for m in markets[:5]:  # Show first 5
            print(f"\n  {m.asset} @ ${m.strike_price:,.0f}")
            print(f"    Question: {m.question[:60]}...")
            print(f"    Resolves in: {m.seconds_until_resolution:.0f}s")
            print(f"    YES: ${m.yes_price:.3f} / NO: ${m.no_price:.3f}")
            print(f"    Liquidity: ${m.liquidity:,.0f}")
    else:
        print("  No markets found (this may be normal if no 15-min markets are active)")

    print("\n✅ Test complete")


if __name__ == "__main__":
    test_scanner()
