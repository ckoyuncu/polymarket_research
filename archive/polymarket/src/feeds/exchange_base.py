"""
Base Class for Exchange Price Feeds

Provides standardized interface and latency tracking for all exchange feeds.
"""

import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional


@dataclass
class PriceRecord:
    """
    Standardized price record with latency tracking.

    All exchange feeds produce this format for consistent logging.
    """
    exchange: str           # "binance", "coinbase", "kraken", "okx"
    symbol: str            # Normalized: "BTCUSDT", "ETHUSDT"
    price: float           # Current price
    ts_exchange: int       # Exchange timestamp (ms) - when they generated the data
    ts_received: int       # Local receive timestamp (ms) - when we received it
    latency_ms: float      # ts_received - ts_exchange
    region: str = ""       # "tokyo", "us-east" - set by logger
    volume_24h: Optional[float] = None  # Optional 24h volume
    raw_symbol: str = ""   # Original symbol from exchange


@dataclass
class FeedStats:
    """Statistics for a feed."""
    updates_received: int = 0
    connection_errors: int = 0
    reconnects: int = 0
    last_update_ts: int = 0
    avg_latency_ms: float = 0.0
    min_latency_ms: float = float('inf')
    max_latency_ms: float = 0.0
    _latency_samples: List[float] = field(default_factory=list)

    def record_latency(self, latency_ms: float, max_samples: int = 1000):
        """Record a latency sample."""
        self._latency_samples.append(latency_ms)
        if len(self._latency_samples) > max_samples:
            self._latency_samples.pop(0)

        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        self.avg_latency_ms = sum(self._latency_samples) / len(self._latency_samples)


class ExchangeFeedBase(ABC):
    """
    Abstract base class for exchange price feeds.

    Provides:
    - Standardized callback system
    - Latency tracking
    - Auto-reconnect logic
    - Health monitoring
    - Statistics collection

    Subclasses must implement:
    - _connect(): Establish WebSocket connection
    - _subscribe(): Send subscription messages
    - _parse_message(): Parse exchange-specific messages into PriceRecord
    """

    def __init__(
        self,
        exchange_name: str,
        symbols: List[str],
        reconnect_delay: float = 5.0,
        max_reconnect_attempts: int = 100,
    ):
        """
        Initialize the feed.

        Args:
            exchange_name: Name of the exchange (e.g., "binance")
            symbols: List of symbols to track (exchange-specific format)
            reconnect_delay: Seconds to wait before reconnecting
            max_reconnect_attempts: Max reconnect attempts before giving up
        """
        self.exchange_name = exchange_name
        self.symbols = symbols
        self.reconnect_delay = reconnect_delay
        self.max_reconnect_attempts = max_reconnect_attempts

        # State
        self._running = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Callbacks
        self._callbacks: List[Callable[[PriceRecord], None]] = []

        # Price cache
        self._prices: Dict[str, PriceRecord] = {}

        # Stats
        self.stats = FeedStats()

        # WebSocket (set by subclass)
        self.ws = None

    @abstractmethod
    def _get_ws_url(self) -> str:
        """Get the WebSocket URL for this exchange."""
        pass

    @abstractmethod
    def _get_subscribe_message(self) -> Optional[dict]:
        """Get the subscription message to send after connecting."""
        pass

    @abstractmethod
    def _parse_message(self, message: str) -> Optional[PriceRecord]:
        """
        Parse an exchange message into a PriceRecord.

        Args:
            message: Raw message string from WebSocket

        Returns:
            PriceRecord if valid price update, None otherwise
        """
        pass

    def _normalize_symbol(self, raw_symbol: str) -> str:
        """
        Normalize symbol to standard format (BTCUSDT, ETHUSDT).

        Override in subclass if needed.
        """
        # Default: uppercase and remove common separators
        return raw_symbol.upper().replace("-", "").replace("/", "").replace("_", "")

    def subscribe(self, callback: Callable[[PriceRecord], None]) -> None:
        """
        Subscribe to price updates.

        Args:
            callback: Function that takes PriceRecord as argument
        """
        self._callbacks.append(callback)

    def start(self) -> None:
        """Start the WebSocket feed."""
        if self._running:
            print(f"{self.exchange_name}: Feed already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        print(f"{self.exchange_name}: Feed started for {', '.join(self.symbols)}")

    def stop(self) -> None:
        """Stop the WebSocket feed."""
        self._running = False
        self._connected = False

        if self.ws:
            try:
                self.ws.close()
            except:
                pass

        if self._thread:
            self._thread.join(timeout=2)

        print(f"{self.exchange_name}: Feed stopped")

    def _run_loop(self) -> None:
        """Main WebSocket loop with auto-reconnect."""
        try:
            import websocket
        except ImportError:
            print(f"{self.exchange_name}: websocket-client not installed")
            self._running = False
            return

        reconnect_attempts = 0

        while self._running and reconnect_attempts < self.max_reconnect_attempts:
            try:
                self._connect_and_run(websocket)
            except Exception as e:
                self.stats.connection_errors += 1
                print(f"{self.exchange_name}: Connection error: {e}")

            if self._running:
                reconnect_attempts += 1
                self.stats.reconnects += 1
                print(f"{self.exchange_name}: Reconnecting in {self.reconnect_delay}s (attempt {reconnect_attempts})...")
                time.sleep(self.reconnect_delay)

    def _connect_and_run(self, websocket_module) -> None:
        """Establish connection and run until disconnect."""
        url = self._get_ws_url()

        def on_message(ws, message):
            try:
                record = self._parse_message(message)
                if record:
                    # Update cache
                    with self._lock:
                        self._prices[record.symbol] = record

                    # Update stats
                    self.stats.updates_received += 1
                    self.stats.last_update_ts = record.ts_received
                    self.stats.record_latency(record.latency_ms)

                    # Notify callbacks
                    for callback in self._callbacks:
                        try:
                            callback(record)
                        except Exception as e:
                            print(f"{self.exchange_name}: Callback error: {e}")

            except Exception as e:
                print(f"{self.exchange_name}: Error processing message: {e}")

        def on_error(ws, error):
            print(f"{self.exchange_name}: WebSocket error: {error}")
            self.stats.connection_errors += 1

        def on_close(ws, close_status_code, close_msg):
            self._connected = False
            print(f"{self.exchange_name}: WebSocket closed: {close_status_code}")

        def on_open(ws):
            self._connected = True
            print(f"{self.exchange_name}: Connected to {url}")

            # Send subscription message
            sub_msg = self._get_subscribe_message()
            if sub_msg:
                import json
                ws.send(json.dumps(sub_msg))
                print(f"{self.exchange_name}: Sent subscription")

        # Create and run WebSocket
        self.ws = websocket_module.WebSocketApp(
            url,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
            on_open=on_open
        )

        self.ws.run_forever()

    def get_price(self, symbol: str) -> Optional[float]:
        """
        Get current price for a symbol.

        Args:
            symbol: Symbol (normalized format, e.g., "BTCUSDT")

        Returns:
            Current price or None
        """
        with self._lock:
            record = self._prices.get(symbol.upper())
            return record.price if record else None

    def get_record(self, symbol: str) -> Optional[PriceRecord]:
        """Get full price record for a symbol."""
        with self._lock:
            return self._prices.get(symbol.upper())

    def get_all_prices(self) -> Dict[str, float]:
        """Get all current prices."""
        with self._lock:
            return {sym: rec.price for sym, rec in self._prices.items()}

    def is_healthy(self, max_age_seconds: int = 10) -> bool:
        """
        Check if feed is healthy.

        Args:
            max_age_seconds: Max time since last update

        Returns:
            True if feed is receiving updates
        """
        if not self._running or not self._connected:
            return False

        now_ms = int(time.time() * 1000)
        age_seconds = (now_ms - self.stats.last_update_ts) / 1000.0

        return age_seconds < max_age_seconds

    def get_stats(self) -> Dict:
        """Get feed statistics."""
        now_ms = int(time.time() * 1000)
        age = (now_ms - self.stats.last_update_ts) / 1000.0 if self.stats.last_update_ts else 0

        return {
            "exchange": self.exchange_name,
            "running": self._running,
            "connected": self._connected,
            "healthy": self.is_healthy(),
            "updates_received": self.stats.updates_received,
            "connection_errors": self.stats.connection_errors,
            "reconnects": self.stats.reconnects,
            "seconds_since_update": age,
            "latency_avg_ms": round(self.stats.avg_latency_ms, 2),
            "latency_min_ms": round(self.stats.min_latency_ms, 2) if self.stats.min_latency_ms != float('inf') else 0,
            "latency_max_ms": round(self.stats.max_latency_ms, 2),
            "symbols_tracked": len(self._prices),
            "prices": self.get_all_prices(),
        }


def get_current_time_ms() -> int:
    """Get current time in milliseconds."""
    return int(time.time() * 1000)
