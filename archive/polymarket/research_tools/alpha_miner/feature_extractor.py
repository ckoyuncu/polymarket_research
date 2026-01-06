"""Extract features from market data."""
import time
from typing import Optional, Dict, List
from ..storage import db
from ..ingestion import event_bus, Event, EventType


class FeatureExtractor:
    """
    Compute derived features from orderbook and price data.
    
    Features are stored in the 'features' table for use by both
    Alpha Miner and Wallet Cloner.
    """
    
    def __init__(self, auto_subscribe: bool = True):
        self.market_state: Dict[str, Dict] = {}  # Track market state
        
        if auto_subscribe:
            # Subscribe to orderbook updates
            event_bus.subscribe(EventType.ORDERBOOK_UPDATE, self.on_orderbook_update)
            event_bus.subscribe(EventType.PRICE_TICK, self.on_price_tick)
    
    def on_orderbook_update(self, event: Event):
        """Handle orderbook update events."""
        data = event.data
        condition_id = data["condition_id"]
        
        # Update market state
        if condition_id not in self.market_state:
            self.market_state[condition_id] = {
                "first_seen": event.timestamp,
                "mid_history": [],
                "spread_history": [],
            }
        
        state = self.market_state[condition_id]
        state["mid_history"].append(data["mid"])
        state["spread_history"].append(data["spread"])
        state["last_mid"] = data["mid"]
        state["last_spread"] = data["spread"]
        
        # Compute features
        features = self.compute_features(condition_id, event.timestamp)
        
        if features:
            self.store_features(condition_id, event.timestamp, features)
    
    def on_price_tick(self, event: Event):
        """Handle price tick events (for cross-market analysis)."""
        # Can be used to compute correlation features
        pass
    
    def compute_features(self, condition_id: str, timestamp: int) -> Optional[Dict]:
        """
        Compute features for a market at a given time.
        
        Returns dict of features or None if insufficient data.
        """
        if condition_id not in self.market_state:
            return None
        
        state = self.market_state[condition_id]
        
        # Time since market start
        t_since_start = timestamp - state["first_seen"]
        
        # Need at least some history
        if len(state["mid_history"]) < 2:
            return None
        
        # Get cross-linked price (if available)
        cl_price = self._get_crosslinked_price(condition_id, timestamp)
        
        # Calculate deltas
        cl_delta = state["last_mid"] - cl_price if cl_price else 0.0
        cl_delta_bps = (cl_delta / cl_price * 10000) if cl_price else 0.0
        
        # Calculate directional changes (last vs previous)
        mid_up = max(0, state["mid_history"][-1] - state["mid_history"][-2])
        mid_down = max(0, state["mid_history"][-2] - state["mid_history"][-1])
        
        spread_up = max(0, state["spread_history"][-1] - state["spread_history"][-2])
        spread_down = max(0, state["spread_history"][-2] - state["spread_history"][-1])
        
        return {
            "t_since_start": t_since_start,
            "cl_delta": cl_delta,
            "cl_delta_bps": cl_delta_bps,
            "mid_up": mid_up,
            "mid_down": mid_down,
            "spread_up": spread_up,
            "spread_down": spread_down,
        }
    
    def _get_crosslinked_price(self, condition_id: str, timestamp: int) -> Optional[float]:
        """Get cross-linked price from external source."""
        # Query the most recent price tick
        query = """
            SELECT price FROM price_ticks
            WHERE ts <= ?
            ORDER BY ts DESC
            LIMIT 1
        """
        result = db.execute(query, (timestamp,))
        
        if result:
            return result[0]["price"]
        return None
    
    def store_features(self, condition_id: str, timestamp: int, features: Dict):
        """Store computed features in database."""
        query = """
            INSERT INTO features 
            (ts, condition_id, t_since_start, cl_delta, cl_delta_bps, 
             mid_up, mid_down, spread_up, spread_down)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        db.execute(query, (
            timestamp,
            condition_id,
            features["t_since_start"],
            features["cl_delta"],
            features["cl_delta_bps"],
            features["mid_up"],
            features["mid_down"],
            features["spread_up"],
            features["spread_down"],
        ))
    
    def backfill_features(self, start_ts: int, end_ts: int):
        """Compute features for historical data."""
        # Get all orderbook snapshots in time range
        query = """
            SELECT * FROM orderbook_snapshots
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts
        """
        rows = db.execute(query, (start_ts, end_ts))
        
        print(f"Backfilling features for {len(rows)} snapshots...")
        
        # Process each snapshot
        for row in rows:
            # Simulate orderbook update event
            event = Event(
                type=EventType.ORDERBOOK_UPDATE,
                timestamp=row["ts"],
                data={
                    "condition_id": row["condition_id"],
                    "token_id": row["token_id"],
                    "best_bid": row["best_bid"],
                    "best_ask": row["best_ask"],
                    "mid": row["mid"],
                    "spread": row["spread"],
                }
            )
            self.on_orderbook_update(event)
        
        print("✓ Feature backfill complete")
