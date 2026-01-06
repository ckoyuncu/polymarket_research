"""
Coinbase WebSocket Price Feed

Real-time price feed for BTC and ETH from Coinbase Exchange.
"""

import json
import time
from typing import Optional

from .exchange_base import ExchangeFeedBase, PriceRecord, get_current_time_ms


class CoinbaseFeed(ExchangeFeedBase):
    """
    Real-time price feed from Coinbase.

    WebSocket URL: wss://ws-feed.exchange.coinbase.com
    Symbols: BTC-USD, ETH-USD

    Example:
        feed = CoinbaseFeed()
        feed.subscribe(lambda r: print(f"{r.symbol}: {r.price}"))
        feed.start()
    """

    WS_URL = "wss://ws-feed.exchange.coinbase.com"

    # Symbol mapping: Coinbase -> Normalized
    SYMBOL_MAP = {
        "BTC-USD": "BTCUSDT",
        "ETH-USD": "ETHUSDT",
    }

    def __init__(self, symbols: Optional[list] = None):
        """
        Initialize Coinbase feed.

        Args:
            symbols: List of symbols (default: ["BTC-USD", "ETH-USD"])
        """
        if symbols is None:
            symbols = ["BTC-USD", "ETH-USD"]

        super().__init__(
            exchange_name="coinbase",
            symbols=symbols,
        )

    def _get_ws_url(self) -> str:
        return self.WS_URL

    def _get_subscribe_message(self) -> Optional[dict]:
        return {
            "type": "subscribe",
            "product_ids": self.symbols,
            "channels": ["ticker"]
        }

    def _parse_message(self, message: str) -> Optional[PriceRecord]:
        """Parse Coinbase ticker message."""
        try:
            data = json.loads(message)

            # Only process ticker messages
            if data.get("type") != "ticker":
                return None

            product_id = data.get("product_id")  # e.g., "BTC-USD"
            price_str = data.get("price")
            time_str = data.get("time")  # ISO format: "2026-01-05T12:00:00.123456Z"

            if not product_id or not price_str:
                return None

            # Parse price
            price = float(price_str)

            # Parse exchange timestamp
            ts_exchange = self._parse_iso_timestamp(time_str) if time_str else get_current_time_ms()
            ts_received = get_current_time_ms()

            # Normalize symbol
            normalized_symbol = self.SYMBOL_MAP.get(product_id, self._normalize_symbol(product_id))

            return PriceRecord(
                exchange="coinbase",
                symbol=normalized_symbol,
                price=price,
                ts_exchange=ts_exchange,
                ts_received=ts_received,
                latency_ms=ts_received - ts_exchange,
                raw_symbol=product_id,
                volume_24h=float(data.get("volume_24h", 0)) if data.get("volume_24h") else None,
            )

        except Exception as e:
            return None

    def _parse_iso_timestamp(self, iso_str: str) -> int:
        """Parse ISO timestamp to milliseconds."""
        try:
            from datetime import datetime

            # Handle microseconds
            if "." in iso_str:
                # Truncate to 6 decimal places if needed
                parts = iso_str.replace("Z", "").split(".")
                if len(parts[1]) > 6:
                    parts[1] = parts[1][:6]
                iso_str = f"{parts[0]}.{parts[1]}Z"

            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return int(dt.timestamp() * 1000)
        except:
            return get_current_time_ms()


def test_coinbase_feed():
    """Test the Coinbase feed."""
    print("Testing Coinbase feed...")

    feed = CoinbaseFeed()

    # Subscribe to updates
    def on_price(record: PriceRecord):
        print(f"  {record.symbol}: ${record.price:,.2f} (latency: {record.latency_ms}ms)")

    feed.subscribe(on_price)

    # Start feed
    feed.start()

    # Wait for updates
    print("\nWaiting for price updates (10 seconds)...")
    time.sleep(10)

    # Check prices
    print("\n--- Current Prices ---")
    for symbol, price in feed.get_all_prices().items():
        print(f"{symbol}: ${price:,.2f}")

    # Stats
    print("\n--- Feed Stats ---")
    stats = feed.get_stats()
    for key, value in stats.items():
        if key != "prices":
            print(f"{key}: {value}")

    # Stop
    print("\nStopping feed...")
    feed.stop()
    print("Test complete!")


if __name__ == "__main__":
    test_coinbase_feed()
