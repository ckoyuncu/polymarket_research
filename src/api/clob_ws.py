"""CLOB WebSocket client for orderbook data."""
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
    print("Warning: websocket-client not installed. Run: pip install websocket-client")


class CLOBWebSocket:
    """
    WebSocket client for Polymarket CLOB market data.
    
    Subscribes to order book updates for specific token IDs.
    """
    
    WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    def __init__(self):
        self.ws: Optional[websocket.WebSocketApp] = None
        self.subscriptions: List[str] = []
        self.handlers: List[Callable] = []
        self.message_queue: Queue = Queue()
        self.running = False
        self._thread: Optional[threading.Thread] = None
    
    def subscribe(self, token_ids: List[str]):
        """Add token IDs to subscription list."""
        self.subscriptions.extend(token_ids)
    
    def add_handler(self, handler: Callable):
        """Add a message handler callback."""
        self.handlers.append(handler)
    
    def _on_message(self, ws, message):
        """Handle incoming messages."""
        try:
            data = json.loads(message)
            
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
    
    def _on_error(self, ws, error):
        """Handle errors."""
        print(f"WebSocket error: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """Handle connection close."""
        print(f"WebSocket closed: {close_status_code} - {close_msg}")
        self.running = False
    
    def _on_open(self, ws):
        """Handle connection open."""
        print("✓ CLOB WebSocket connected")
        
        # Subscribe to token IDs
        for token_id in self.subscriptions:
            sub_msg = {
                "type": "subscribe",
                "channel": "market",
                "market": token_id,
            }
            ws.send(json.dumps(sub_msg))
            print(f"  Subscribed to {token_id[:16]}...")
    
    def connect(self, blocking: bool = False):
        """
        Connect to WebSocket.
        
        Args:
            blocking: If True, run in current thread. If False, run in background.
        """
        if not HAS_WEBSOCKET:
            raise ImportError("websocket-client required. Run: pip install websocket-client")
        
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
    
    def parse_book_update(self, message: Dict) -> Optional[Dict]:
        """
        Parse a book update message.
        
        Returns normalized orderbook snapshot.
        """
        if message.get("type") != "book":
            return None
        
        data = message.get("data", message)
        
        bids = data.get("bids", [])
        asks = data.get("asks", [])
        
        best_bid = float(bids[0]["price"]) if bids else 0.0
        best_ask = float(asks[0]["price"]) if asks else 1.0
        
        best_bid_size = float(bids[0].get("size", 0)) if bids else 0.0
        best_ask_size = float(asks[0].get("size", 0)) if asks else 0.0
        
        mid = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        
        return {
            "ts": int(time.time() * 1000),
            "token_id": data.get("market") or data.get("asset_id"),
            "best_bid": best_bid,
            "best_bid_size": best_bid_size,
            "best_ask": best_ask,
            "best_ask_size": best_ask_size,
            "mid": mid,
            "spread": spread,
        }
    
    def parse_price_change(self, message: Dict) -> Optional[Dict]:
        """Parse a price change message."""
        if message.get("type") != "price_change":
            return None
        
        data = message.get("data", message)
        
        return {
            "ts": int(time.time() * 1000),
            "token_id": data.get("market") or data.get("asset_id"),
            "price": float(data.get("price", 0)),
        }
