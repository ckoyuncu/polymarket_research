"""RTDS WebSocket client for real-time price feeds."""
import json
import time
import threading
from typing import Callable, Dict, List, Optional
from queue import Queue

try:
    import websocket
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


class RTDSWebSocket:
    """
    WebSocket client for Polymarket RTDS (Real-Time Data Stream).
    
    Provides:
    - Binance crypto prices
    - Chainlink crypto prices
    """
    
    WS_URL = "wss://ws-live-data.polymarket.com"
    
    def __init__(self):
        self.ws: Optional[websocket.WebSocketApp] = None
        self.subscriptions: List[Dict] = []
        self.handlers: List[Callable] = []
        self.message_queue: Queue = Queue()
        self.running = False
        self._thread: Optional[threading.Thread] = None
        self.latest_prices: Dict[str, Dict] = {}  # symbol -> {binance: x, chainlink: y}
    
    def subscribe_binance(self, symbols: List[str] = None):
        """Subscribe to Binance price feed."""
        symbols = symbols or ["BTC", "ETH"]
        
        self.subscriptions.append({
            "type": "subscribe",
            "channel": "crypto_prices",
            "source": "binance",
            "symbols": symbols,
        })
    
    def subscribe_chainlink(self, symbols: List[str] = None):
        """Subscribe to Chainlink price feed."""
        symbols = symbols or ["BTC", "ETH"]
        
        self.subscriptions.append({
            "type": "subscribe",
            "channel": "crypto_prices_chainlink",
            "symbols": symbols,
        })
    
    def add_handler(self, handler: Callable):
        """Add a message handler callback."""
        self.handlers.append(handler)
    
    def _on_message(self, ws, message):
        """Handle incoming messages."""
        try:
            data = json.loads(message)
            
            # Update latest prices
            self._update_prices(data)
            
            # Queue for processing
            self.message_queue.put(data)
            
            # Call handlers
            for handler in self.handlers:
                try:
                    handler(data)
                except Exception as e:
                    print(f"Handler error: {e}")
        
        except json.JSONDecodeError:
            pass
    
    def _update_prices(self, data: Dict):
        """Update latest prices cache."""
        msg_type = data.get("type") or data.get("channel")
        
        if "price" in msg_type.lower() if msg_type else False:
            symbol = data.get("symbol", "").upper()
            source = data.get("source", "unknown")
            price = data.get("price")
            
            if symbol and price:
                if symbol not in self.latest_prices:
                    self.latest_prices[symbol] = {}
                
                self.latest_prices[symbol][source] = {
                    "price": float(price),
                    "ts": int(time.time() * 1000),
                }
    
    def _on_error(self, ws, error):
        """Handle errors."""
        print(f"RTDS WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle connection close."""
        print(f"RTDS WebSocket closed: {close_status_code}")
        self.running = False
    
    def _on_open(self, ws):
        """Handle connection open."""
        print("✓ RTDS WebSocket connected")
        
        # Send subscriptions
        for sub in self.subscriptions:
            ws.send(json.dumps(sub))
            print(f"  Subscribed to {sub.get('channel')}")
    
    def connect(self, blocking: bool = False):
        """
        Connect to WebSocket.
        
        Args:
            blocking: If True, run in current thread. If False, run in background.
        """
        if not HAS_WEBSOCKET:
            raise ImportError("websocket-client required. Run: pip install websocket-client")
        
        # Default subscriptions if none set
        if not self.subscriptions:
            self.subscribe_binance()
            self.subscribe_chainlink()
        
        self.ws = websocket.WebSocketApp(
            self.WS_URL,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
        )
        
        self.running = True
        
        if blocking:
            self.ws.run_forever()
        else:
            self._thread = threading.Thread(target=self.ws.run_forever, daemon=True)
            self._thread.start()
            time.sleep(1)  # Wait for connection
    
    def disconnect(self):
        """Disconnect WebSocket."""
        self.running = False
        if self.ws:
            self.ws.close()
    
    def get_messages(self, timeout: float = 0.1) -> List[Dict]:
        """Get queued messages."""
        messages = []
        while not self.message_queue.empty():
            try:
                messages.append(self.message_queue.get_nowait())
            except Exception:
                break
        return messages
    
    def get_price(self, symbol: str, source: str = "chainlink") -> Optional[float]:
        """Get latest price for a symbol."""
        symbol = symbol.upper()
        if symbol in self.latest_prices:
            if source in self.latest_prices[symbol]:
                return self.latest_prices[symbol][source]["price"]
        return None
    
    def get_price_delta(self, symbol: str) -> Optional[float]:
        """Get delta between Binance and Chainlink prices."""
        symbol = symbol.upper()
        if symbol not in self.latest_prices:
            return None
        
        prices = self.latest_prices[symbol]
        
        if "binance" in prices and "chainlink" in prices:
            return prices["binance"]["price"] - prices["chainlink"]["price"]
        
        return None
    
    def parse_price_tick(self, message: Dict) -> Optional[Dict]:
        """
        Parse a price tick message.
        
        Returns normalized price tick for storage.
        """
        symbol = message.get("symbol", "").upper()
        price = message.get("price")
        source = message.get("source", "unknown")
        
        if not symbol or price is None:
            return None
        
        return {
            "ts": int(time.time() * 1000),
            "symbol": symbol,
            "source": source,
            "price": float(price),
        }
