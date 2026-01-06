"""Analyze wallet trade patterns."""
from typing import List, Dict, Optional, Tuple
from collections import defaultdict

from ..storage import db


class TradeAnalyzer:
    """
    Analyze historical trades from a wallet to identify patterns.
    
    Looks for consistent entry/exit logic that can be codified.
    """
    
    def __init__(self, wallet_address: str):
        self.wallet_address = wallet_address
        self.trades: List[Dict] = []
        self.positions: Dict[str, List] = defaultdict(list)
    
    def load_trades(self, start_ts: int = 0, end_ts: Optional[int] = None):
        """Load all trades for this wallet from database."""
        query = """
            SELECT * FROM wallet_trades
            WHERE wallet = ? AND ts >= ?
        """
        params = [self.wallet_address, start_ts]
        
        if end_ts:
            query += " AND ts <= ?"
            params.append(end_ts)
        
        query += " ORDER BY ts"
        
        rows = db.execute(query, tuple(params))
        self.trades = [dict(row) for row in rows]
        
        print(f"✓ Loaded {len(self.trades)} trades for {self.wallet_address}")
        
        return self.trades
    
    def reconstruct_positions(self):
        """
        Reconstruct position lifecycle (entry -> exit).
        
        Returns matched position pairs.
        """
        positions = []
        open_positions: Dict[Tuple[str, str], Dict] = {}  # (condition_id, token_id) -> position
        
        for trade in self.trades:
            key = (trade["condition_id"], trade["token_id"])
            
            if trade["side"] == "buy":
                # Open or add to position
                if key not in open_positions:
                    open_positions[key] = {
                        "condition_id": trade["condition_id"],
                        "token_id": trade["token_id"],
                        "entries": [],
                        "exits": [],
                    }
                open_positions[key]["entries"].append(trade)
            
            elif trade["side"] == "sell":
                # Close or reduce position
                if key in open_positions:
                    open_positions[key]["exits"].append(trade)
                    
                    # If position fully closed (simplified logic)
                    if len(open_positions[key]["exits"]) >= len(open_positions[key]["entries"]):
                        positions.append(open_positions[key])
                        del open_positions[key]
        
        # Add unclosed positions
        for pos in open_positions.values():
            positions.append(pos)
        
        self.positions = positions
        print(f"✓ Reconstructed {len(positions)} positions")
        
        return positions
    
    def get_market_state_at_trade(self, trade: Dict) -> Optional[Dict]:
        """Get market features at the time of a trade."""
        query = """
            SELECT * FROM features
            WHERE condition_id = ? AND ts <= ?
            ORDER BY ts DESC
            LIMIT 1
        """
        rows = db.execute(query, (trade["condition_id"], trade["ts"]))
        
        if rows:
            return dict(rows[0])
        return None
    
    def analyze_entry_patterns(self) -> Dict:
        """
        Analyze what features were present at entry times.
        
        Returns statistical summary of feature values at entries.
        """
        feature_values = defaultdict(list)
        
        for position in self.positions:
            if not position["entries"]:
                continue
            
            # Look at first entry
            entry_trade = position["entries"][0]
            state = self.get_market_state_at_trade(entry_trade)
            
            if state:
                for key, value in state.items():
                    if key not in ["id", "ts", "condition_id"]:
                        feature_values[key].append(value)
        
        # Calculate statistics
        stats = {}
        for feature, values in feature_values.items():
            if values:
                stats[feature] = {
                    "mean": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                }
        
        return stats
    
    def analyze_exit_patterns(self) -> Dict:
        """
        Analyze what features were present at exit times.
        
        Returns statistical summary of feature values at exits.
        """
        feature_values = defaultdict(list)
        
        for position in self.positions:
            if not position["exits"]:
                continue
            
            # Look at first exit
            exit_trade = position["exits"][0]
            state = self.get_market_state_at_trade(exit_trade)
            
            if state:
                for key, value in state.items():
                    if key not in ["id", "ts", "condition_id"]:
                        feature_values[key].append(value)
        
        # Calculate statistics
        stats = {}
        for feature, values in feature_values.items():
            if values:
                stats[feature] = {
                    "mean": sum(values) / len(values),
                    "min": min(values),
                    "max": max(values),
                    "count": len(values),
                }
        
        return stats
    
    def calculate_performance(self) -> Dict:
        """Calculate overall performance metrics."""
        total_pnl = 0.0
        winning_trades = 0
        losing_trades = 0
        
        for position in self.positions:
            if not position["entries"] or not position["exits"]:
                continue
            
            # Simplified P&L calculation
            entry_price = position["entries"][0]["price"]
            entry_size = position["entries"][0]["size"]
            
            exit_price = position["exits"][0]["price"]
            
            pnl = (exit_price - entry_price) * entry_size
            total_pnl += pnl
            
            if pnl > 0:
                winning_trades += 1
            else:
                losing_trades += 1
        
        total_trades = winning_trades + losing_trades
        win_rate = winning_trades / total_trades if total_trades > 0 else 0
        
        return {
            "total_pnl": total_pnl,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "win_rate": win_rate,
        }
