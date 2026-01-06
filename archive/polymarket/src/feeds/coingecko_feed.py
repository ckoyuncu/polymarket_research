"""
CoinGecko Price Feed

Alternative to Binance for regions with geo-restrictions.
Free API, no authentication required, works globally.
"""
import requests
import time
import threading
from typing import Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PriceTick:
    """Price update."""
    symbol: str
    price: float
    timestamp: int  # Unix timestamp in milliseconds
    latency_ms: float  # Time since update


class CoinGeckoFeed:
    """
    Real-time price feed from CoinGecko API.

    Free tier: 10-50 calls/minute (more than enough for our needs)
    No authentication required.
    Works from any region including Singapore.

    Example:
        feed = CoinGeckoFeed()

        def on_price(tick: PriceTick):
            print(f"{tick.symbol}: ${tick.price:.2f}")

        feed.subscribe(on_price)
        feed.start()

        # Later
        btc_price = feed.get_price("BTC")
    """

    API_BASE = "https://api.coingecko.com/api/v3"

    # CoinGecko IDs for our assets
    COIN_IDS = {
        "BTC": "bitcoin",
        "ETH": "ethereum"
    }

    def __init__(self, update_interval: float = 5.0):
        """
        Initialize CoinGecko feed.

        Args:
            update_interval: Seconds between price updates (default: 5s)
        """
        self.update_interval = update_interval
        self._prices: Dict[str, PriceTick] = {}
        self._running = False
        self._thread = None
        self._callbacks: list[Callable[[PriceTick], None]] = []

    def subscribe(self, callback: Callable[[PriceTick], None]):
        """Subscribe to price updates."""
        self._callbacks.append(callback)

    def start(self):
        """Start fetching prices."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._fetch_loop, daemon=True)
        self._thread.start()
        print(f"✅ CoinGecko feed started (updates every {self.update_interval}s)")

    def stop(self):
        """Stop fetching prices."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        print("CoinGecko feed stopped")

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for symbol.

        Args:
            symbol: "BTC" or "ETH"

        Returns:
            Current price in USD, or None if not available
        """
        # Normalize symbol
        symbol = symbol.upper().replace("USDT", "").replace("USD", "")

        tick = self._prices.get(symbol)
        return tick.price if tick else None

    def _fetch_loop(self):
        """Background loop to fetch prices."""
        while self._running:
            try:
                self._fetch_prices()
            except Exception as e:
                print(f"Error fetching prices: {e}")

            time.sleep(self.update_interval)

    def _fetch_prices(self):
        """Fetch current prices from CoinGecko."""
        try:
            # Build request for all our coins
            coin_ids = ",".join(self.COIN_IDS.values())
            url = f"{self.API_BASE}/simple/price"
            params = {
                "ids": coin_ids,
                "vs_currencies": "usd",
                "include_last_updated_at": "true"
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            # Process each coin
            for symbol, coin_id in self.COIN_IDS.items():
                if coin_id in data:
                    coin_data = data[coin_id]
                    price = coin_data.get("usd")
                    last_updated = coin_data.get("last_updated_at", int(time.time()))

                    if price:
                        # Create price tick
                        now_ms = int(time.time() * 1000)
                        tick = PriceTick(
                            symbol=symbol,
                            price=price,
                            timestamp=last_updated * 1000,
                            latency_ms=(now_ms - last_updated * 1000)
                        )

                        self._prices[symbol] = tick

                        # Notify subscribers
                        for callback in self._callbacks:
                            try:
                                callback(tick)
                            except Exception as e:
                                print(f"Error in callback: {e}")

        except Exception as e:
            print(f"Failed to fetch from CoinGecko: {e}")


def test_feed():
    """Test CoinGecko feed."""
    print("Testing CoinGecko Feed...")
    print("=" * 50)

    feed = CoinGeckoFeed(update_interval=3.0)

    def on_price(tick):
        print(f"✅ {tick.symbol}: ${tick.price:,.2f} (latency: {tick.latency_ms/1000:.1f}s)")

    feed.subscribe(on_price)
    feed.start()

    print("\nFetching prices for 10 seconds...\n")
    time.sleep(10)

    # Check final prices
    btc = feed.get_price("BTC")
    eth = feed.get_price("ETH")

    print("\n" + "=" * 50)
    print("Final Prices:")
    print(f"  BTC: ${btc:,.2f}" if btc else "  BTC: Not available")
    print(f"  ETH: ${eth:,.2f}" if eth else "  ETH: Not available")
    print("=" * 50)

    feed.stop()
    print("\n✅ CoinGecko feed test complete")


if __name__ == "__main__":
    test_feed()
