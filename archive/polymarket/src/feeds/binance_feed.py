"""
Binance WebSocket Price Feed

Real-time price feed for BTC and ETH from Binance spot market.
Uses WebSocket for sub-100ms latency.
"""
import json
import time
import threading
from typing import Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PriceTick:
    """Price update from Binance."""
    symbol: str
    price: float
    timestamp: int  # Unix timestamp in milliseconds
    latency_ms: float  # Time since update


class BinanceFeed:
    """
    Real-time price feed from Binance.

    Connects to Binance WebSocket streams for:
    - BTCUSDT (Bitcoin)
    - ETHUSDT (Ethereum)

    Example:
        feed = BinanceFeed()

        def on_price(tick: PriceTick):
            print(f"{tick.symbol}: ${tick.price:.2f}")

        feed.subscribe(on_price)
        feed.start()

        # Later
        btc_price = feed.get_price("BTC")
        print(f"Current BTC: ${btc_price}")
    """

    # Binance WebSocket URLs
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self):
        # Price cache
        self._prices: Dict[str, PriceTick] = {}
        self._lock = threading.Lock()

        # WebSocket
        self.ws = None
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Callbacks
        self._callbacks: list[Callable[[PriceTick], None]] = []

        # Symbols to track
        self.symbols = ["BTCUSDT", "ETHUSDT"]

        # Stats
        self.updates_received = 0
        self.connection_errors = 0
        self.last_update_time = 0

    def subscribe(self, callback: Callable[[PriceTick], None]):
        """
        Subscribe to price updates.

        Args:
            callback: Function that takes PriceTick as argument
        """
        self._callbacks.append(callback)

    def start(self):
        """Start the WebSocket feed."""
        if self._running:
            print("Feed already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        print(f"✅ Binance feed started for {', '.join(self.symbols)}")

    def stop(self):
        """Stop the WebSocket feed."""
        self._running = False

        if self.ws:
            self.ws.close()

        if self._thread:
            self._thread.join(timeout=2)

        print("Binance feed stopped")

    def _run(self):
        """Main WebSocket loop."""
        try:
            import websocket
        except ImportError:
            print("⚠️  websocket-client not installed")
            print("   Install: pip install websocket-client")
            self._running = False
            return

        # Create stream URL for multiple symbols
        streams = [f"{s.lower()}@ticker" for s in self.symbols]
        stream_url = f"{self.WS_BASE_URL}/{'/'.join(streams)}"

        print(f"Connecting to Binance WebSocket...")

        def on_message(ws, message):
            """Handle incoming price updates."""
            try:
                data = json.loads(message)

                # Handle combined stream format
                if "stream" in data:
                    data = data["data"]

                # Extract price data
                symbol = data.get("s")  # e.g., "BTCUSDT"
                price = float(data.get("c", 0))  # Current price
                event_time = data.get("E", int(time.time() * 1000))

                if symbol and price > 0:
                    # Calculate latency
                    now = int(time.time() * 1000)
                    latency = now - event_time

                    # Create tick
                    tick = PriceTick(
                        symbol=symbol,
                        price=price,
                        timestamp=event_time,
                        latency_ms=latency
                    )

                    # Update cache
                    with self._lock:
                        self._prices[symbol] = tick
                        self.updates_received += 1
                        self.last_update_time = now

                    # Notify callbacks
                    for callback in self._callbacks:
                        try:
                            callback(tick)
                        except Exception as e:
                            print(f"Error in callback: {e}")

            except Exception as e:
                print(f"Error processing message: {e}")

        def on_error(ws, error):
            """Handle WebSocket errors."""
            print(f"WebSocket error: {error}")
            self.connection_errors += 1

        def on_close(ws, close_status_code, close_msg):
            """Handle WebSocket close."""
            print(f"WebSocket closed: {close_status_code} - {close_msg}")

            # Auto-reconnect if still running
            if self._running:
                print("Reconnecting in 5 seconds...")
                time.sleep(5)
                if self._running:
                    self._run()

        def on_open(ws):
            """Handle WebSocket open."""
            print(f"✅ Connected to Binance stream")

        # Create WebSocket
        self.ws = websocket.WebSocketApp(
            stream_url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        # Run forever (blocks until closed)
        self.ws.run_forever()

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol.

        Args:
            symbol: "BTC" or "ETH" or "BTCUSDT" or "ETHUSDT"

        Returns:
            Current price or None if not available
        """
        # Normalize symbol
        if symbol.upper() in ["BTC", "BITCOIN"]:
            symbol = "BTCUSDT"
        elif symbol.upper() in ["ETH", "ETHEREUM"]:
            symbol = "ETHUSDT"
        else:
            symbol = symbol.upper()

        with self._lock:
            tick = self._prices.get(symbol)
            return tick.price if tick else None

    def get_tick(self, symbol: str) -> Optional[PriceTick]:
        """
        Get full price tick data.

        Args:
            symbol: Symbol to get (e.g., "BTC", "ETH")

        Returns:
            PriceTick or None
        """
        # Normalize symbol
        if symbol.upper() in ["BTC", "BITCOIN"]:
            symbol = "BTCUSDT"
        elif symbol.upper() in ["ETH", "ETHEREUM"]:
            symbol = "ETHUSDT"
        else:
            symbol = symbol.upper()

        with self._lock:
            return self._prices.get(symbol)

    def is_healthy(self, max_age_seconds: int = 10) -> bool:
        """
        Check if feed is healthy.

        Args:
            max_age_seconds: Max time since last update

        Returns:
            True if feed is receiving updates
        """
        if not self._running:
            return False

        now = int(time.time() * 1000)
        age = (now - self.last_update_time) / 1000.0

        return age < max_age_seconds

    def get_stats(self) -> Dict:
        """Get feed statistics."""
        now = int(time.time() * 1000)
        age = (now - self.last_update_time) / 1000.0 if self.last_update_time else 0

        return {
            "running": self._running,
            "updates_received": self.updates_received,
            "connection_errors": self.connection_errors,
            "seconds_since_update": age,
            "healthy": self.is_healthy(),
            "symbols_tracked": len(self._prices),
            "prices": {
                symbol: tick.price
                for symbol, tick in self._prices.items()
            }
        }


def test_feed():
    """Test the Binance feed."""
    print("Testing Binance feed...")

    feed = BinanceFeed()

    # Subscribe to updates
    def on_price(tick: PriceTick):
        print(f"  {tick.symbol}: ${tick.price:,.2f} (latency: {tick.latency_ms}ms)")

    feed.subscribe(on_price)

    # Start feed
    feed.start()

    # Wait for updates
    print("\nWaiting for price updates (5 seconds)...")
    time.sleep(5)

    # Check prices
    print("\n--- Current Prices ---")
    btc = feed.get_price("BTC")
    eth = feed.get_price("ETH")

    if btc:
        print(f"BTC: ${btc:,.2f}")
    if eth:
        print(f"ETH: ${eth:,.2f}")

    # Stats
    print("\n--- Feed Stats ---")
    stats = feed.get_stats()
    for key, value in stats.items():
        if key != "prices":
            print(f"{key}: {value}")

    # Stop
    print("\nStopping feed...")
    feed.stop()
    print("✅ Test complete")


if __name__ == "__main__":
    test_feed()
