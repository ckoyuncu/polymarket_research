"""
Paper Trading Module

Simulates trades without real money to track strategy performance.
Records hypothetical trades and calculates P&L as if trades were executed.
"""
import time
import json
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from enum import Enum

from ..api import DataAPIClient, GammaClient
from ..storage.db import db
from ..config import DATA_DIR


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass
class PaperPosition:
    """A paper trading position."""
    market_id: str
    market_name: str
    token_id: str
    side: str  # "yes" or "no"
    
    size: float  # Number of shares
    avg_cost: float  # Average cost per share
    
    # Tracking
    opened_at: int  # Timestamp
    last_update: int
    
    # Current state
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    
    @property
    def cost_basis(self) -> float:
        """Total cost basis."""
        return self.size * self.avg_cost
    
    @property
    def current_value(self) -> float:
        """Current market value."""
        return self.size * self.current_price
    
    @property
    def pnl_percent(self) -> float:
        """PnL as percentage."""
        if self.cost_basis == 0:
            return 0.0
        return (self.unrealized_pnl / self.cost_basis) * 100
    
    def update_price(self, price: float):
        """Update current price and recalculate PnL."""
        self.current_price = price
        self.unrealized_pnl = self.current_value - self.cost_basis
        self.last_update = int(time.time())
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "market_id": self.market_id,
            "market_name": self.market_name,
            "token_id": self.token_id,
            "side": self.side,
            "size": self.size,
            "avg_cost": self.avg_cost,
            "cost_basis": self.cost_basis,
            "current_price": self.current_price,
            "current_value": self.current_value,
            "unrealized_pnl": self.unrealized_pnl,
            "pnl_percent": self.pnl_percent,
            "opened_at": self.opened_at,
            "last_update": self.last_update
        }


@dataclass
class PaperTrade:
    """A paper trading order."""
    id: str
    timestamp: int
    
    # Order details
    market_id: str
    market_name: str
    token_id: str
    side: OrderSide
    outcome: str  # "yes" or "no"
    
    size: float
    price: float
    
    # Status
    status: OrderStatus = OrderStatus.FILLED
    fill_price: float = 0.0
    
    # Tracking
    source: str = "manual"  # "manual", "signal", "clone"
    signal_wallet: Optional[str] = None  # If cloning a wallet
    notes: str = ""
    
    @property
    def value(self) -> float:
        """Trade value in USD."""
        return self.size * (self.fill_price or self.price)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "market_id": self.market_id,
            "market_name": self.market_name,
            "token_id": self.token_id,
            "side": self.side.value,
            "outcome": self.outcome,
            "size": self.size,
            "price": self.price,
            "fill_price": self.fill_price,
            "value": self.value,
            "status": self.status.value,
            "source": self.source,
            "signal_wallet": self.signal_wallet,
            "notes": self.notes
        }


@dataclass
class PortfolioStats:
    """Portfolio statistics."""
    total_value: float = 0.0
    cash: float = 0.0
    positions_value: float = 0.0
    
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    @property
    def win_rate(self) -> float:
        """Win rate percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    def to_dict(self) -> Dict:
        return {
            "total_value": self.total_value,
            "cash": self.cash,
            "positions_value": self.positions_value,
            "total_pnl": self.total_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate
        }


class PaperTradingEngine:
    """
    Paper trading engine for simulating trades.
    
    Features:
    - Track hypothetical positions
    - Calculate P&L in real-time
    - Clone trades from monitored wallets
    - Export trade history for analysis
    
    Example:
        engine = PaperTradingEngine(initial_capital=500)
        engine.place_order("market_id", "buy", "yes", size=100, price=0.55)
        engine.update_prices()
        print(engine.get_portfolio_summary())
    """
    
    def __init__(
        self,
        initial_capital: float = 500.0,
        name: str = "default"
    ):
        self.name = name
        self.initial_capital = initial_capital
        self.cash = initial_capital
        
        # State
        self.positions: Dict[str, PaperPosition] = {}  # token_id -> Position
        self.trades: List[PaperTrade] = []
        self.closed_trades: List[Dict] = []  # For realized P&L tracking
        
        # Stats
        self.stats = PortfolioStats(
            total_value=initial_capital,
            cash=initial_capital
        )
        
        # APIs
        self.data_api = DataAPIClient()
        self.gamma = GammaClient()
        
        # Persistence
        self.data_dir = DATA_DIR / "paper_trading"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Trade counter
        self._trade_counter = 0
        
        # Load existing state if any
        self._load_state()
    
    def _generate_trade_id(self) -> str:
        """Generate unique trade ID."""
        self._trade_counter += 1
        return f"PT{int(time.time())}_{self._trade_counter}"
    
    def place_order(
        self,
        market_id: str,
        side: str,  # "buy" or "sell"
        outcome: str,  # "yes" or "no"
        size: float,
        price: float,
        market_name: str = "",
        token_id: str = "",
        source: str = "manual",
        signal_wallet: Optional[str] = None,
        notes: str = ""
    ) -> Optional[PaperTrade]:
        """
        Place a paper trade order.
        
        Args:
            market_id: Market condition ID
            side: "buy" or "sell"
            outcome: "yes" or "no" token
            size: Number of shares
            price: Price per share (0-1)
            market_name: Human-readable market name
            token_id: Token ID (will look up if not provided)
            source: Trade source ("manual", "signal", "clone")
            signal_wallet: Wallet being cloned (if applicable)
            notes: Optional notes
        
        Returns:
            PaperTrade if successful, None if failed
        """
        # Validate
        if side not in ["buy", "sell"]:
            print(f"⚠ Invalid side: {side}")
            return None
        
        if outcome not in ["yes", "no"]:
            print(f"⚠ Invalid outcome: {outcome}")
            return None
        
        trade_value = size * price
        
        # Check buying power
        if side == "buy" and trade_value > self.cash:
            print(f"⚠ Insufficient funds. Need ${trade_value:.2f}, have ${self.cash:.2f}")
            return None
        
        # Get market info if not provided
        if not market_name or not token_id:
            try:
                market = self.gamma.get_market(market_id)
                if market:
                    market_name = market_name or market.get("question", market_id[:16])
                    
                    # Get token ID based on outcome
                    tokens = market.get("tokens", [])
                    for t in tokens:
                        if t.get("outcome", "").lower() == outcome.lower():
                            token_id = token_id or t.get("token_id", "")
                            break
            except Exception as e:
                print(f"   Warning: Could not fetch market info: {e}")
                market_name = market_name or market_id[:16]
        
        # Create trade
        trade = PaperTrade(
            id=self._generate_trade_id(),
            timestamp=int(time.time()),
            market_id=market_id,
            market_name=market_name,
            token_id=token_id or f"{market_id}_{outcome}",
            side=OrderSide(side),
            outcome=outcome,
            size=size,
            price=price,
            fill_price=price,  # Assume fill at limit price
            status=OrderStatus.FILLED,
            source=source,
            signal_wallet=signal_wallet,
            notes=notes
        )
        
        self.trades.append(trade)
        self.stats.total_trades += 1
        
        # Update position
        self._update_position(trade)
        
        # Update cash
        if side == "buy":
            self.cash -= trade_value
        else:
            self.cash += trade_value
        
        self._update_stats()
        self._save_state()
        
        action = "📈" if side == "buy" else "📉"
        print(f"{action} Paper trade: {side.upper()} {size:.0f} {outcome.upper()} @ ${price:.4f} = ${trade_value:.2f}")
        
        return trade
    
    def _update_position(self, trade: PaperTrade):
        """Update position based on trade."""
        key = trade.token_id
        
        if trade.side == OrderSide.BUY:
            if key in self.positions:
                # Add to existing position
                pos = self.positions[key]
                total_cost = pos.cost_basis + (trade.size * trade.fill_price)
                total_size = pos.size + trade.size
                pos.avg_cost = total_cost / total_size if total_size > 0 else 0
                pos.size = total_size
                pos.last_update = int(time.time())
            else:
                # New position
                self.positions[key] = PaperPosition(
                    market_id=trade.market_id,
                    market_name=trade.market_name,
                    token_id=trade.token_id,
                    side=trade.outcome,
                    size=trade.size,
                    avg_cost=trade.fill_price,
                    current_price=trade.fill_price,
                    opened_at=int(time.time()),
                    last_update=int(time.time())
                )
        
        elif trade.side == OrderSide.SELL:
            if key in self.positions:
                pos = self.positions[key]
                
                # Calculate realized P&L
                realized = (trade.fill_price - pos.avg_cost) * min(trade.size, pos.size)
                self.stats.realized_pnl += realized
                
                if realized >= 0:
                    self.stats.winning_trades += 1
                else:
                    self.stats.losing_trades += 1
                
                # Reduce position
                pos.size -= trade.size
                pos.last_update = int(time.time())
                
                # Record closed trade
                self.closed_trades.append({
                    "trade_id": trade.id,
                    "market_id": trade.market_id,
                    "realized_pnl": realized,
                    "timestamp": int(time.time())
                })
                
                # Remove if fully closed
                if pos.size <= 0:
                    del self.positions[key]
    
    def _update_stats(self):
        """Recalculate portfolio stats."""
        positions_value = sum(p.current_value for p in self.positions.values())
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        
        self.stats.cash = self.cash
        self.stats.positions_value = positions_value
        self.stats.total_value = self.cash + positions_value
        self.stats.unrealized_pnl = unrealized
        self.stats.total_pnl = self.stats.realized_pnl + unrealized
    
    def update_prices(self):
        """Update all position prices from market."""
        print("   Updating prices...")
        
        for key, pos in self.positions.items():
            try:
                market = self.gamma.get_market(pos.market_id)
                if market:
                    tokens = market.get("tokens", [])
                    for t in tokens:
                        if t.get("token_id") == pos.token_id:
                            price = float(t.get("price", pos.current_price))
                            pos.update_price(price)
                            break
            except Exception as e:
                print(f"   Error updating {pos.market_name}: {e}")
        
        self._update_stats()
        self._save_state()
    
    def clone_trade(
        self,
        wallet_trade: Dict,
        scale_factor: float = 1.0,
        max_position: float = 50.0
    ) -> Optional[PaperTrade]:
        """
        Clone a trade from a monitored wallet.
        
        Args:
            wallet_trade: Trade data from monitored wallet
            scale_factor: Scale position size (e.g., 0.5 = half size)
            max_position: Maximum position size in USD
        
        Returns:
            PaperTrade if successful
        """
        side = wallet_trade.get("side", "buy")
        size = float(wallet_trade.get("size", 0)) * scale_factor
        price = float(wallet_trade.get("price", 0))
        
        # Cap at max position
        if size * price > max_position:
            size = max_position / price
        
        return self.place_order(
            market_id=wallet_trade.get("market", wallet_trade.get("conditionId", "")),
            side=side,
            outcome=wallet_trade.get("outcome", "yes"),
            size=size,
            price=price,
            source="clone",
            signal_wallet=wallet_trade.get("wallet"),
            notes=f"Cloned from {wallet_trade.get('wallet', 'unknown')[:10]}"
        )
    
    def get_positions(self) -> List[Dict]:
        """Get all open positions."""
        return [p.to_dict() for p in self.positions.values()]
    
    def get_trades(self) -> List[Dict]:
        """Get all trades."""
        return [t.to_dict() for t in self.trades]
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary."""
        self._update_stats()
        
        return {
            "name": self.name,
            "initial_capital": self.initial_capital,
            "stats": self.stats.to_dict(),
            "positions_count": len(self.positions),
            "trades_count": len(self.trades),
            "pnl_percent": (self.stats.total_pnl / self.initial_capital) * 100 if self.initial_capital > 0 else 0
        }
    
    def print_summary(self):
        """Print portfolio summary to console."""
        summary = self.get_portfolio_summary()
        stats = summary["stats"]
        
        print(f"\n{'='*50}")
        print(f"📊 PAPER PORTFOLIO: {self.name}")
        print(f"{'='*50}")
        print(f"Initial Capital:  ${self.initial_capital:.2f}")
        print(f"Total Value:      ${stats['total_value']:.2f}")
        print(f"Cash:             ${stats['cash']:.2f}")
        print(f"Positions Value:  ${stats['positions_value']:.2f}")
        print(f"{'─'*50}")
        print(f"Total P&L:        ${stats['total_pnl']:.2f} ({summary['pnl_percent']:.1f}%)")
        print(f"  Realized:       ${stats['realized_pnl']:.2f}")
        print(f"  Unrealized:     ${stats['unrealized_pnl']:.2f}")
        print(f"{'─'*50}")
        print(f"Trades:           {stats['total_trades']}")
        print(f"Win Rate:         {stats['win_rate']:.1f}%")
        print(f"{'='*50}")
        
        if self.positions:
            print(f"\n📌 Open Positions:")
            for pos in self.positions.values():
                pnl_emoji = "🟢" if pos.unrealized_pnl >= 0 else "🔴"
                print(f"  {pnl_emoji} {pos.market_name[:30]}")
                print(f"     {pos.size:.0f} {pos.side.upper()} @ ${pos.avg_cost:.4f} → ${pos.current_price:.4f}")
                print(f"     P&L: ${pos.unrealized_pnl:.2f} ({pos.pnl_percent:.1f}%)")
    
    def _save_state(self):
        """Save state to disk."""
        state = {
            "name": self.name,
            "initial_capital": self.initial_capital,
            "cash": self.cash,
            "trade_counter": self._trade_counter,
            "positions": [p.to_dict() for p in self.positions.values()],
            "trades": [t.to_dict() for t in self.trades],
            "closed_trades": self.closed_trades,
            "stats": self.stats.to_dict(),
            "saved_at": int(time.time())
        }
        
        filepath = self.data_dir / f"portfolio_{self.name}.json"
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _load_state(self):
        """Load state from disk."""
        filepath = self.data_dir / f"portfolio_{self.name}.json"
        
        if not filepath.exists():
            return
        
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            self.initial_capital = state.get("initial_capital", self.initial_capital)
            self.cash = state.get("cash", self.cash)
            self._trade_counter = state.get("trade_counter", 0)
            self.closed_trades = state.get("closed_trades", [])
            
            # Restore positions
            for p_data in state.get("positions", []):
                pos = PaperPosition(
                    market_id=p_data["market_id"],
                    market_name=p_data["market_name"],
                    token_id=p_data["token_id"],
                    side=p_data["side"],
                    size=p_data["size"],
                    avg_cost=p_data["avg_cost"],
                    opened_at=p_data["opened_at"],
                    last_update=p_data["last_update"],
                    current_price=p_data.get("current_price", 0),
                    unrealized_pnl=p_data.get("unrealized_pnl", 0)
                )
                self.positions[pos.token_id] = pos
            
            # Restore trades
            for t_data in state.get("trades", []):
                trade = PaperTrade(
                    id=t_data["id"],
                    timestamp=t_data["timestamp"],
                    market_id=t_data["market_id"],
                    market_name=t_data["market_name"],
                    token_id=t_data["token_id"],
                    side=OrderSide(t_data["side"]),
                    outcome=t_data["outcome"],
                    size=t_data["size"],
                    price=t_data["price"],
                    fill_price=t_data.get("fill_price", t_data["price"]),
                    status=OrderStatus(t_data.get("status", "filled")),
                    source=t_data.get("source", "manual"),
                    signal_wallet=t_data.get("signal_wallet"),
                    notes=t_data.get("notes", "")
                )
                self.trades.append(trade)
            
            # Restore stats
            if "stats" in state:
                s = state["stats"]
                self.stats = PortfolioStats(
                    total_value=s.get("total_value", 0),
                    cash=s.get("cash", 0),
                    positions_value=s.get("positions_value", 0),
                    total_pnl=s.get("total_pnl", 0),
                    realized_pnl=s.get("realized_pnl", 0),
                    unrealized_pnl=s.get("unrealized_pnl", 0),
                    total_trades=s.get("total_trades", 0),
                    winning_trades=s.get("winning_trades", 0),
                    losing_trades=s.get("losing_trades", 0)
                )
            
            print(f"   ✓ Loaded portfolio '{self.name}' with {len(self.positions)} positions")
        
        except Exception as e:
            print(f"   Warning: Could not load state: {e}")
    
    def reset(self):
        """Reset the portfolio to initial state."""
        self.cash = self.initial_capital
        self.positions = {}
        self.trades = []
        self.closed_trades = []
        self._trade_counter = 0
        self.stats = PortfolioStats(
            total_value=self.initial_capital,
            cash=self.initial_capital
        )
        self._save_state()
        print(f"✓ Portfolio '{self.name}' reset to ${self.initial_capital:.2f}")
    
    def export_trades(self, filepath: Optional[Path] = None) -> Path:
        """Export trades to JSON file."""
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = self.data_dir / f"trades_{self.name}_{timestamp}.json"
        
        export_data = {
            "portfolio": self.name,
            "initial_capital": self.initial_capital,
            "exported_at": datetime.now().isoformat(),
            "summary": self.get_portfolio_summary(),
            "trades": self.get_trades(),
            "positions": self.get_positions()
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        print(f"✓ Exported to {filepath}")
        return filepath


# Convenience function for quick paper trading
def quick_paper_trade(
    market_query: str,
    side: str,
    outcome: str,
    amount_usd: float,
    portfolio_name: str = "quick"
) -> Optional[PaperTrade]:
    """
    Quick paper trade by searching for market.
    
    Example:
        quick_paper_trade("BTC above 100k", "buy", "yes", 50)
    """
    engine = PaperTradingEngine(initial_capital=1000, name=portfolio_name)
    gamma = GammaClient()
    
    # Search for market
    markets = gamma.search_markets(market_query, limit=5, active=True)
    
    if not markets:
        print(f"⚠ No markets found for: {market_query}")
        return None
    
    market = markets[0]
    market_id = market.get("condition_id") or market.get("conditionId")
    
    # Get current price
    tokens = market.get("tokens", [])
    price = 0.5  # Default
    for t in tokens:
        if t.get("outcome", "").lower() == outcome.lower():
            price = float(t.get("price", 0.5))
            break
    
    # Calculate size from USD amount
    size = amount_usd / price if price > 0 else 0
    
    return engine.place_order(
        market_id=market_id,
        side=side,
        outcome=outcome,
        size=size,
        price=price,
        market_name=market.get("question", "")
    )
