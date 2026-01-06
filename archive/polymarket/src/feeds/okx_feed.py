"""
OKX WebSocket Price Feed

Real-time price feed for BTC and ETH from OKX Exchange.
"""

import json
import time
from typing import Optional

from .exchange_base import ExchangeFeedBase, PriceRecord, get_current_time_ms


class OKXFeed(ExchangeFeedBase):
    """
    Real-time price feed from OKX.

    WebSocket URL: wss://ws.okx.com:8443/ws/v5/public
    Symbols: BTC-USDT, ETH-USDT

    Example:
        feed = OKXFeed()
        feed.subscribe(lambda r: print(f"{r.symbol}: {r.price}"))
        feed.start()
    """

    WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

    # Symbol mapping: OKX -> Normalized
    SYMBOL_MAP = {
        "BTC-USDT": "BTCUSDT",
        "ETH-USDT": "ETHUSDT",
    }

    def __init__(self, symbols: Optional[list] = None):
        """
        Initialize OKX feed.

        Args:
            symbols: List of symbols (default: ["BTC-USDT", "ETH-USDT"])
        """
        if symbols is None:
            symbols = ["BTC-USDT", "ETH-USDT"]

        super().__init__(
            exchange_name="okx",
            symbols=symbols,
        )

    def _get_ws_url(self) -> str:
        return self.WS_URL

    def _get_subscribe_message(self) -> Optional[dict]:
        # OKX requires args as list of objects
        args = [{"channel": "tickers", "instId": sym} for sym in self.symbols]
        return {
            "op": "subscribe",
            "args": args
        }

    def _parse_message(self, message: str) -> Optional[PriceRecord]:
        """
        Parse OKX ticker message.

        OKX format:
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT"},
            "data": [{"last": "97234.5", "ts": "1704500000000", ...}]
        }
        """
        try:
            data = json.loads(message)

            # Skip subscription confirmations, pings, etc.
            if "data" not in data:
                return None

            arg = data.get("arg", {})
            channel = arg.get("channel")
            inst_id = arg.get("instId")  # e.g., "BTC-USDT"

            if channel != "tickers" or not inst_id:
                return None

            # Get ticker data (first item in data array)
            ticker_list = data.get("data", [])
            if not ticker_list:
                return None

            ticker = ticker_list[0]

            # Get price
            price_str = ticker.get("last")
            if not price_str:
                return None

            price = float(price_str)

            # Get timestamps
            ts_exchange_str = ticker.get("ts")  # milliseconds as string
            ts_exchange = int(ts_exchange_str) if ts_exchange_str else get_current_time_ms()
            ts_received = get_current_time_ms()

            # Normalize symbol
            normalized_symbol = self.SYMBOL_MAP.get(inst_id, self._normalize_symbol(inst_id))

            # Get 24h volume if available
            volume_24h = None
            if ticker.get("vol24h"):
                volume_24h = float(ticker["vol24h"])

            return PriceRecord(
                exchange="okx",
                symbol=normalized_symbol,
                price=price,
                ts_exchange=ts_exchange,
                ts_received=ts_received,
                latency_ms=ts_received - ts_exchange,
                raw_symbol=inst_id,
                volume_24h=volume_24h,
            )

        except Exception as e:
            return None


def test_okx_feed():
    """Test the OKX feed."""
    print("Testing OKX feed...")

    feed = OKXFeed()

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
    test_okx_feed()
