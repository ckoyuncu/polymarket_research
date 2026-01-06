"""Execute strategies against market data."""
from typing import Dict, List, Optional
import time

from .spec import StrategySpec, Condition
from ..storage import db


class StrategyExecutor:
    """Execute strategy specs in live or backtest mode."""
    
    def __init__(self, strategy: StrategySpec):
        self.strategy = strategy
        self.positions: Dict[str, Dict] = {}  # condition_id -> position info
        self.trades: List[Dict] = []
    
    def evaluate_conditions(
        self,
        conditions: List[Condition],
        features: Dict[str, float],
        require_all: bool = True
    ) -> bool:
        """
        Evaluate a list of conditions.
        
        Args:
            conditions: List of conditions to evaluate
            features: Current feature values
            require_all: If True, ALL conditions must be true. If False, ANY can be true.
        """
        if not conditions:
            return False
        
        results = [
            cond.evaluate(features.get(cond.feature, 0.0))
            for cond in conditions
        ]
        
        return all(results) if require_all else any(results)
    
    def check_entry(self, condition_id: str, token_id: str, features: Dict[str, float]) -> bool:
        """Check if entry conditions are met."""
        # Don't enter if already in position
        if condition_id in self.positions:
            return False
        
        return self.evaluate_conditions(
            self.strategy.entry_conditions,
            features,
            require_all=True
        )
    
    def check_exit(self, condition_id: str, features: Dict[str, float]) -> bool:
        """Check if exit conditions are met."""
        # Can only exit if in position
        if condition_id not in self.positions:
            return False
        
        return self.evaluate_conditions(
            self.strategy.exit_conditions,
            features,
            require_all=False  # ANY exit condition can trigger
        )
    
    def execute_entry(self, condition_id: str, token_id: str, current_price: float, timestamp: int):
        """Execute entry action."""
        if not self.strategy.entry_action:
            return
        
        action = self.strategy.entry_action
        
        # Calculate size
        size = action.size or 0.0
        if action.size_pct:
            # In real implementation, would use available capital
            size = action.size_pct * 1000  # Placeholder
        
        # Record position
        self.positions[condition_id] = {
            "token_id": token_id,
            "side": action.type,
            "entry_price": current_price,
            "size": size,
            "entry_time": timestamp,
        }
        
        # Record trade
        self.trades.append({
            "timestamp": timestamp,
            "condition_id": condition_id,
            "token_id": token_id,
            "action": action.type,
            "price": current_price,
            "size": size,
        })
    
    def execute_exit(self, condition_id: str, current_price: float, timestamp: int):
        """Execute exit action."""
        if condition_id not in self.positions:
            return
        
        position = self.positions[condition_id]
        
        # Calculate PnL
        pnl = (current_price - position["entry_price"]) * position["size"]
        
        # Record trade
        self.trades.append({
            "timestamp": timestamp,
            "condition_id": condition_id,
            "token_id": position["token_id"],
            "action": "close",
            "price": current_price,
            "size": position["size"],
            "pnl": pnl,
        })
        
        # Close position
        del self.positions[condition_id]
    
    def backtest(self, start_ts: int, end_ts: int) -> Dict:
        """
        Backtest strategy over historical data.
        
        Returns performance metrics.
        """
        # Query all features in time range
        query = """
            SELECT * FROM features
            WHERE ts >= ? AND ts <= ?
            ORDER BY ts
        """
        rows = db.execute(query, (start_ts, end_ts))
        
        for row in rows:
            condition_id = row["condition_id"]
            timestamp = row["ts"]
            
            # Build feature dict
            features = {
                "t_since_start": row["t_since_start"],
                "cl_delta": row["cl_delta"],
                "cl_delta_bps": row["cl_delta_bps"],
                "mid_up": row["mid_up"],
                "mid_down": row["mid_down"],
                "spread_up": row["spread_up"],
                "spread_down": row["spread_down"],
            }
            
            # Get current price (mid)
            ob_query = """
                SELECT mid FROM orderbook_snapshots
                WHERE condition_id = ? AND ts <= ?
                ORDER BY ts DESC LIMIT 1
            """
            ob_row = db.execute(ob_query, (condition_id, timestamp))
            if not ob_row:
                continue
            
            current_price = ob_row[0]["mid"]
            
            # Check exit first (if in position)
            if self.check_exit(condition_id, features):
                self.execute_exit(condition_id, current_price, timestamp)
            
            # Check entry
            elif self.check_entry(condition_id, "token_0", features):
                self.execute_entry(condition_id, "token_0", current_price, timestamp)
        
        # Calculate metrics
        total_pnl = sum(t.get("pnl", 0) for t in self.trades)
        num_trades = len([t for t in self.trades if t["action"] != "close"]) // 2
        
        return {
            "total_pnl": total_pnl,
            "num_trades": num_trades,
            "trades": self.trades,
        }
