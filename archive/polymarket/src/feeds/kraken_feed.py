"""
Kraken WebSocket Price Feed

Real-time price feed for BTC and ETH from Kraken Exchange.
"""

import json
import time
from typing import Optional

from .exchange_base import ExchangeFeedBase, PriceRecord, get_current_time_ms


class KrakenFeed(ExchangeFeedBase):
    """
    Real-time price feed from Kraken.

    WebSocket URL: wss://ws.kraken.com
    Symbols: XBT/USD (Bitcoin), ETH/USD (Ethereum)

    Note: Kraken uses XBT instead of BTC for Bitcoin.

    Example:
        feed = KrakenFeed()
        feed.subscribe(lambda r: print(f"{r.symbol}: {r.price}"))
        feed.start()
    """

    WS_URL = "wss://ws.kraken.com"

    # Symbol mapping: Kraken -> Normalized
    SYMBOL_MAP = {
        "XBT/USD": "BTCUSDT",
        "ETH/USD": "ETHUSDT",
    }

    def __init__(self, symbols: Optional[list] = None):
        """
        Initialize Kraken feed.

        Args:
            symbols: List of symbols (default: ["XBT/USD", "ETH/USD"])
        """
        if symbols is None:
            symbols = ["XBT/USD", "ETH/USD"]

        super().__init__(
            exchange_name="kraken",
            symbols=symbols,
        )

    def _get_ws_url(self) -> str:
        return self.WS_URL

    def _get_subscribe_message(self) -> Optional[dict]:
        return {
            "event": "subscribe",
            "pair": self.symbols,
            "subscription": {"name": "ticker"}
        }

    def _parse_message(self, message: str) -> Optional[PriceRecord]:
        """
        Parse Kraken ticker message.

        Kraken format is an array:
        [channelID, {"c": ["price", "lot_volume"], ...}, "ticker", "XBT/USD"]
        """
        try:
            data = json.loads(message)

            # Skip non-array messages (heartbeat, status, etc.)
            if not isinstance(data, list):
                return None

            # Ticker data comes as: [channelId, tickerData, "ticker", "pair"]
            if len(data) < 4:
                return None

            channel_name = data[2] if len(data) > 2 else None
            if channel_name != "ticker":
                return None

            ticker_data = data[1]
            pair = data[3]  # e.g., "XBT/USD"

            # Get last trade price: "c" = [price, lot_volume]
            if "c" not in ticker_data:
                return None

            price = float(ticker_data["c"][0])

            ts_received = get_current_time_ms()
            # Kraken doesn't send timestamp in ticker, use received time
            ts_exchange = ts_received

            # Normalize symbol
            normalized_symbol = self.SYMBOL_MAP.get(pair, self._normalize_symbol(pair))

            # Get 24h volume if available: "v" = [today, last_24h]
            volume_24h = None
            if "v" in ticker_data and len(ticker_data["v"]) > 1:
                volume_24h = float(ticker_data["v"][1])

            return PriceRecord(
                exchange="kraken",
                symbol=normalized_symbol,
                price=price,
                ts_exchange=ts_exchange,
                ts_received=ts_received,
                latency_ms=0,  # Can't measure without exchange timestamp
                raw_symbol=pair,
                volume_24h=volume_24h,
            )

        except Exception as e:
            return None


def test_kraken_feed():
    """Test the Kraken feed."""
    print("Testing Kraken feed...")

    feed = KrakenFeed()

    # Subscribe to updates
    def on_price(record: PriceRecord):
        print(f"  {record.symbol}: ${record.price:,.2f} (raw: {record.raw_symbol})")

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
    test_kraken_feed()
