"""
Position Tracker

Tracks open positions across paper and live trading with:
- Real-time P&L calculation
- Position aging
- Market price updates
- Auto-close triggers
"""
import time
import json
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum

from ..api import GammaClient, DataAPIClient
from ..config import DATA_DIR


class PositionStatus(Enum):
    """Position status."""
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    EXPIRED = "expired"


@dataclass
class Position:
    """A trading position."""
    id: str
    market_id: str
    market_name: str
    token_id: str
    
    # Position details
    side: str  # "buy" or "sell"
    outcome: str  # "yes" or "no"
    size: float  # Number of shares
    entry_price: float
    
    # Timestamps
    opened_at: int
    updated_at: int = 0
    closed_at: int = 0
    
    # Current state
    current_price: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    
    # P&L
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    exit_price: float = 0.0
    
    # Metadata
    source: str = "manual"  # "manual", "clone", "signal"
    signal_wallet: str = ""
    notes: str = ""
    
    def __post_init__(self):
        if self.updated_at == 0:
            self.updated_at = self.opened_at
        if self.current_price == 0:
            self.current_price = self.entry_price
    
    @property
    def cost_basis(self) -> float:
        """Total cost of position."""
        return self.size * self.entry_price
    
    @property
    def current_value(self) -> float:
        """Current market value."""
        return self.size * self.current_price
    
    @property
    def pnl_percent(self) -> float:
        """P&L as percentage."""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100
    
    @property
    def age_seconds(self) -> int:
        """How long position has been open."""
        if self.status == PositionStatus.CLOSED:
            return self.closed_at - self.opened_at
        return int(time.time()) - self.opened_at
    
    @property
    def age_human(self) -> str:
        """Human-readable age."""
        age = self.age_seconds
        if age < 60:
            return f"{age}s"
        elif age < 3600:
            return f"{age // 60}m"
        else:
            return f"{age // 3600}h {(age % 3600) // 60}m"
    
    def update_price(self, price: float):
        """Update current price and recalculate P&L."""
        self.current_price = price
        self.unrealized_pnl = self.current_value - self.cost_basis
        self.updated_at = int(time.time())
    
    def close(self, exit_price: float):
        """Close the position."""
        self.exit_price = exit_price
        self.realized_pnl = (exit_price - self.entry_price) * self.size
        self.unrealized_pnl = 0.0
        self.status = PositionStatus.CLOSED
        self.closed_at = int(time.time())
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "market_id": self.market_id,
            "market_name": self.market_name,
            "token_id": self.token_id,
            "side": self.side,
            "outcome": self.outcome,
            "size": self.size,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "cost_basis": self.cost_basis,
            "current_value": self.current_value,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl": self.realized_pnl,
            "pnl_percent": self.pnl_percent,
            "status": self.status.value,
            "opened_at": self.opened_at,
            "updated_at": self.updated_at,
            "closed_at": self.closed_at,
            "age_seconds": self.age_seconds,
            "age_human": self.age_human,
            "source": self.source,
            "signal_wallet": self.signal_wallet,
            "notes": self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> "Position":
        """Create from dictionary."""
        return cls(
            id=data["id"],
            market_id=data["market_id"],
            market_name=data["market_name"],
            token_id=data["token_id"],
            side=data["side"],
            outcome=data["outcome"],
            size=data["size"],
            entry_price=data["entry_price"],
            opened_at=data["opened_at"],
            updated_at=data.get("updated_at", 0),
            closed_at=data.get("closed_at", 0),
            current_price=data.get("current_price", 0),
            status=PositionStatus(data.get("status", "open")),
            unrealized_pnl=data.get("unrealized_pnl", 0),
            realized_pnl=data.get("realized_pnl", 0),
            exit_price=data.get("exit_price", 0),
            source=data.get("source", "manual"),
            signal_wallet=data.get("signal_wallet", ""),
            notes=data.get("notes", "")
        )


class PositionTracker:
    """
    Tracks all positions with real-time updates.
    
    Features:
    - Open/close position tracking
    - Real-time price updates
    - P&L calculation
    - Position aging and auto-close alerts
    - History persistence
    
    Example:
        tracker = PositionTracker()
        
        # Open position
        pos = tracker.open_position(
            market_id="abc123",
            market_name="BTC above 100k",
            side="buy",
            outcome="yes",
            size=100,
            entry_price=0.55
        )
        
        # Update prices
        tracker.update_prices()
        
        # Close position
        tracker.close_position(pos.id, exit_price=0.65)
    """
    
    def __init__(self, auto_update: bool = False, update_interval: int = 30):
        # Positions
        self.positions: Dict[str, Position] = {}
        self.closed_positions: List[Position] = []
        
        # APIs
        self.gamma = GammaClient()
        self.data_api = DataAPIClient()
        
        # Persistence
        self.data_dir = DATA_DIR / "positions"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Auto-update
        self._auto_update = auto_update
        self._update_interval = update_interval
        self._update_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Callbacks
        self._on_pnl_change: List[Callable[[Position], None]] = []
        self._on_position_aged: List[Callable[[Position], None]] = []
        
        # Counter
        self._position_counter = 0
        
        # Load existing state
        self._load_state()
        
        # Start auto-update if enabled
        if auto_update:
            self.start_auto_update()
    
    def _generate_id(self) -> str:
        """Generate unique position ID."""
        self._position_counter += 1
        return f"POS{int(time.time())}_{self._position_counter}"
    
    def open_position(
        self,
        market_id: str,
        side: str,
        outcome: str,
        size: float,
        entry_price: float,
        market_name: str = "",
        token_id: str = "",
        source: str = "manual",
        signal_wallet: str = "",
        notes: str = ""
    ) -> Position:
        """
        Open a new position.
        
        Args:
            market_id: Condition ID
            side: "buy" or "sell"
            outcome: "yes" or "no"
            size: Number of shares
            entry_price: Entry price per share
            market_name: Human-readable name
            token_id: Token ID
            source: Trade source
            signal_wallet: Wallet being cloned
            notes: Optional notes
        
        Returns:
            Position object
        """
        # Get market info if not provided
        if not market_name or not token_id:
            try:
                market = self.gamma.get_market(market_id)
                if market:
                    market_name = market_name or market.get("question", market_id[:20])
                    tokens = market.get("tokens", [])
                    for t in tokens:
                        if t.get("outcome", "").lower() == outcome.lower():
                            token_id = token_id or t.get("token_id", "")
                            break
            except Exception:
                pass
        
        position = Position(
            id=self._generate_id(),
            market_id=market_id,
            market_name=market_name or market_id[:20],
            token_id=token_id or f"{market_id}_{outcome}",
            side=side,
            outcome=outcome,
            size=size,
            entry_price=entry_price,
            opened_at=int(time.time()),
            current_price=entry_price,
            source=source,
            signal_wallet=signal_wallet,
            notes=notes
        )
        
        self.positions[position.id] = position
        self._save_state()
        
        return position
    
    def close_position(self, position_id: str, exit_price: float) -> Optional[Position]:
        """
        Close a position.
        
        Args:
            position_id: Position ID
            exit_price: Exit price
        
        Returns:
            Closed position or None
        """
        if position_id not in self.positions:
            return None
        
        position = self.positions[position_id]
        position.close(exit_price)
        
        # Move to closed
        del self.positions[position_id]
        self.closed_positions.append(position)
        
        # Keep last 1000 closed positions
        if len(self.closed_positions) > 1000:
            self.closed_positions = self.closed_positions[-1000:]
        
        self._save_state()
        
        return position
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID."""
        return self.positions.get(position_id)
    
    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self.positions.values())
    
    def get_positions_by_market(self, market_id: str) -> List[Position]:
        """Get positions for a specific market."""
        return [p for p in self.positions.values() if p.market_id == market_id]
    
    def update_prices(self):
        """Update prices for all open positions."""
        for position in self.positions.values():
            try:
                market = self.gamma.get_market(position.market_id)
                if market:
                    tokens = market.get("tokens", [])
                    for t in tokens:
                        if t.get("token_id") == position.token_id:
                            new_price = float(t.get("price", position.current_price))
                            old_pnl = position.unrealized_pnl
                            position.update_price(new_price)
                            
                            # Trigger callbacks if P&L changed significantly
                            if abs(position.unrealized_pnl - old_pnl) > 0.01:
                                for callback in self._on_pnl_change:
                                    try:
                                        callback(position)
                                    except Exception:
                                        pass
                            break
            except Exception:
                pass
        
        self._save_state()
    
    def check_aged_positions(self, max_age_seconds: int = 3600) -> List[Position]:
        """
        Check for positions that have exceeded max age.
        
        Args:
            max_age_seconds: Maximum position age in seconds
        
        Returns:
            List of aged positions
        """
        aged = []
        
        for position in self.positions.values():
            if position.age_seconds > max_age_seconds:
                aged.append(position)
                
                # Trigger callbacks
                for callback in self._on_position_aged:
                    try:
                        callback(position)
                    except Exception:
                        pass
        
        return aged
    
    def on_pnl_change(self, callback: Callable[[Position], None]):
        """Register callback for P&L changes."""
        self._on_pnl_change.append(callback)
        return self
    
    def on_position_aged(self, callback: Callable[[Position], None]):
        """Register callback for aged positions."""
        self._on_position_aged.append(callback)
        return self
    
    def start_auto_update(self):
        """Start automatic price updates."""
        if self._running:
            return
        
        self._running = True
        self._update_thread = threading.Thread(
            target=self._auto_update_loop,
            daemon=True
        )
        self._update_thread.start()
    
    def stop_auto_update(self):
        """Stop automatic price updates."""
        self._running = False
        if self._update_thread:
            self._update_thread.join(timeout=2)
    
    def _auto_update_loop(self):
        """Background loop for auto updates."""
        while self._running:
            try:
                if self.positions:
                    self.update_prices()
            except Exception:
                pass
            
            time.sleep(self._update_interval)
    
    def get_summary(self) -> Dict:
        """Get positions summary."""
        open_positions = list(self.positions.values())
        
        total_cost = sum(p.cost_basis for p in open_positions)
        total_value = sum(p.current_value for p in open_positions)
        total_unrealized = sum(p.unrealized_pnl for p in open_positions)
        total_realized = sum(p.realized_pnl for p in self.closed_positions)
        
        return {
            "open_positions": len(open_positions),
            "closed_positions": len(self.closed_positions),
            "total_cost": total_cost,
            "total_value": total_value,
            "unrealized_pnl": total_unrealized,
            "realized_pnl": total_realized,
            "total_pnl": total_unrealized + total_realized,
            "positions": [p.to_dict() for p in open_positions]
        }
    
    def print_positions(self):
        """Print positions to console."""
        positions = self.get_open_positions()
        
        if not positions:
            print("\n📌 No open positions")
            return
        
        print(f"\n{'='*60}")
        print(f"📌 OPEN POSITIONS ({len(positions)})")
        print(f"{'='*60}")
        
        for pos in positions:
            pnl_emoji = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
            print(f"\n{pnl_emoji} {pos.market_name[:40]}")
            print(f"   ID: {pos.id}")
            print(f"   {pos.size:.0f} {pos.outcome.upper()} @ ${pos.entry_price:.4f} → ${pos.current_price:.4f}")
            print(f"   P&L: ${pos.unrealized_pnl:.2f} ({pos.pnl_percent:.1f}%)")
            print(f"   Age: {pos.age_human}")
        
        summary = self.get_summary()
        print(f"\n{'─'*60}")
        print(f"Total Value: ${summary['total_value']:.2f}")
        print(f"Unrealized P&L: ${summary['unrealized_pnl']:.2f}")
        print(f"{'='*60}")
    
    def _save_state(self):
        """Save state to disk."""
        state = {
            "positions": {pid: p.to_dict() for pid, p in self.positions.items()},
            "closed": [p.to_dict() for p in self.closed_positions[-100:]],  # Last 100
            "counter": self._position_counter,
            "saved_at": int(time.time())
        }
        
        filepath = self.data_dir / "tracker_state.json"
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _load_state(self):
        """Load state from disk."""
        filepath = self.data_dir / "tracker_state.json"
        
        if not filepath.exists():
            return
        
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            self._position_counter = state.get("counter", 0)
            
            # Restore open positions
            for pid, pdata in state.get("positions", {}).items():
                self.positions[pid] = Position.from_dict(pdata)
            
            # Restore closed positions
            for pdata in state.get("closed", []):
                self.closed_positions.append(Position.from_dict(pdata))
            
            if self.positions:
                print(f"   ✓ Loaded {len(self.positions)} open position(s)")
                
        except Exception as e:
            print(f"   Warning: Could not load positions: {e}")


# Global instance
_tracker: Optional[PositionTracker] = None


def get_position_tracker(auto_update: bool = False) -> PositionTracker:
    """Get or create global position tracker."""
    global _tracker
    if _tracker is None:
        _tracker = PositionTracker(auto_update=auto_update)
    return _tracker
