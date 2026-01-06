"""
Risk Manager

Centralized risk controls for production trading.
Prevents catastrophic losses through position limits, circuit breakers, and daily caps.
"""
import time
import json
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from enum import Enum

from ..config import DATA_DIR


class RiskLevel(Enum):
    """Risk level states."""
    NORMAL = "normal"
    ELEVATED = "elevated"  # Reduced position sizes
    CRITICAL = "critical"  # No new trades
    HALTED = "halted"      # System paused


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    # Position limits
    max_position_size: float = 50.0      # Max USD per trade
    max_position_pct: float = 0.20       # Max 20% of capital per trade
    max_open_positions: int = 5          # Max concurrent positions
    max_total_exposure: float = 0.50     # Max 50% of capital at risk
    
    # Daily limits
    daily_loss_limit: float = 0.10       # Stop after 10% daily loss
    daily_trade_limit: int = 100         # Max trades per day
    
    # Per-trade limits
    min_trade_size: float = 5.0          # Minimum trade size
    max_slippage: float = 0.05           # Max 5% slippage allowed
    
    # Circuit breakers
    consecutive_loss_limit: int = 5      # Pause after 5 losses in a row
    error_threshold: int = 3             # Pause after 3 errors
    
    # Time limits
    max_position_age_hours: float = 1.0  # Close positions after 1 hour


@dataclass
class DailyStats:
    """Daily trading statistics."""
    date: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    fees: float = 0.0
    errors: int = 0
    consecutive_losses: int = 0
    max_drawdown: float = 0.0
    peak_value: float = 0.0
    
    @property
    def win_rate(self) -> float:
        if self.trades == 0:
            return 0.0
        return self.wins / self.trades
    
    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "trades": self.trades,
            "wins": self.wins,
            "losses": self.losses,
            "pnl": self.pnl,
            "fees": self.fees,
            "errors": self.errors,
            "consecutive_losses": self.consecutive_losses,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate
        }


class RiskManager:
    """
    Centralized risk management for production trading.
    
    Features:
    - Position size limits
    - Daily loss limits
    - Circuit breakers
    - Consecutive loss tracking
    - Error rate monitoring
    
    Example:
        risk = RiskManager(capital=300)
        
        # Before each trade
        if risk.can_trade():
            size = risk.calculate_position_size(signal_strength=0.7)
            if risk.approve_trade(size=size, market="BTC-UP"):
                # Execute trade
                risk.record_trade(pnl=5.0)
    """
    
    def __init__(
        self,
        capital: float = 300.0,
        limits: Optional[RiskLimits] = None
    ):
        self.initial_capital = capital
        self.current_capital = capital
        self.limits = limits or RiskLimits()
        
        # State
        self.risk_level = RiskLevel.NORMAL
        self.open_positions: Dict[str, Dict] = {}
        self.today_stats = DailyStats(date=str(date.today()))
        
        # Persistence
        self.data_dir = DATA_DIR / "risk"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Load state
        self._load_state()
    
    def can_trade(self) -> tuple[bool, str]:
        """
        Check if trading is allowed.
        
        Returns:
            (allowed, reason)
        """
        # Check risk level
        if self.risk_level == RiskLevel.HALTED:
            return False, "Trading halted"
        
        if self.risk_level == RiskLevel.CRITICAL:
            return False, "Risk level critical - no new trades"
        
        # Check daily loss limit
        daily_loss_pct = abs(self.today_stats.pnl) / self.initial_capital if self.today_stats.pnl < 0 else 0
        if daily_loss_pct >= self.limits.daily_loss_limit:
            return False, f"Daily loss limit reached ({daily_loss_pct:.1%})"
        
        # Check daily trade limit
        if self.today_stats.trades >= self.limits.daily_trade_limit:
            return False, f"Daily trade limit reached ({self.today_stats.trades})"
        
        # Check consecutive losses
        if self.today_stats.consecutive_losses >= self.limits.consecutive_loss_limit:
            return False, f"Consecutive loss limit ({self.today_stats.consecutive_losses})"
        
        # Check error threshold
        if self.today_stats.errors >= self.limits.error_threshold:
            return False, f"Error threshold reached ({self.today_stats.errors})"
        
        # Check open positions
        if len(self.open_positions) >= self.limits.max_open_positions:
            return False, f"Max open positions ({len(self.open_positions)})"
        
        # Check total exposure
        total_exposure = sum(p.get("size", 0) for p in self.open_positions.values())
        if total_exposure / self.current_capital >= self.limits.max_total_exposure:
            return False, f"Max exposure reached ({total_exposure:.0f}/{self.current_capital:.0f})"
        
        return True, "OK"
    
    def calculate_position_size(
        self,
        signal_strength: float = 1.0,
        kelly_fraction: float = 0.25
    ) -> float:
        """
        Calculate safe position size using modified Kelly criterion.
        
        Args:
            signal_strength: 0-1 confidence in signal
            kelly_fraction: Fraction of Kelly to use (0.25 = quarter Kelly)
        
        Returns:
            Position size in USD
        """
        # Base size is percentage of capital
        base_size = self.current_capital * self.limits.max_position_pct
        
        # Adjust for signal strength
        adjusted_size = base_size * signal_strength * kelly_fraction
        
        # Apply limits
        adjusted_size = max(adjusted_size, self.limits.min_trade_size)
        adjusted_size = min(adjusted_size, self.limits.max_position_size)
        
        # Reduce if elevated risk
        if self.risk_level == RiskLevel.ELEVATED:
            adjusted_size *= 0.5
        
        # Don't exceed available capital
        available = self.current_capital - sum(p.get("size", 0) for p in self.open_positions.values())
        adjusted_size = min(adjusted_size, available * 0.5)
        
        return round(adjusted_size, 2)
    
    def approve_trade(
        self,
        size: float,
        market: str,
        side: str = "buy",
        price: float = 0.0
    ) -> tuple[bool, str]:
        """
        Final approval check before executing trade.
        
        Returns:
            (approved, reason)
        """
        can, reason = self.can_trade()
        if not can:
            return False, reason
        
        # Check minimum size
        if size < self.limits.min_trade_size:
            return False, f"Size too small (${size:.2f} < ${self.limits.min_trade_size})"
        
        # Check maximum size
        if size > self.limits.max_position_size:
            return False, f"Size too large (${size:.2f} > ${self.limits.max_position_size})"
        
        # Check if already in this market
        if market in self.open_positions:
            return False, f"Already have position in {market}"
        
        return True, "Approved"
    
    def record_trade_open(
        self,
        trade_id: str,
        market: str,
        side: str,
        size: float,
        price: float
    ):
        """Record opening a new position."""
        self.open_positions[market] = {
            "trade_id": trade_id,
            "market": market,
            "side": side,
            "size": size,
            "entry_price": price,
            "opened_at": int(time.time())
        }
        self._save_state()
    
    def record_trade_close(
        self,
        market: str,
        exit_price: float,
        pnl: float
    ):
        """Record closing a position."""
        # Remove from open positions
        if market in self.open_positions:
            del self.open_positions[market]
        
        # Update stats
        self.today_stats.trades += 1
        self.today_stats.pnl += pnl
        
        if pnl >= 0:
            self.today_stats.wins += 1
            self.today_stats.consecutive_losses = 0
        else:
            self.today_stats.losses += 1
            self.today_stats.consecutive_losses += 1
        
        # Update capital
        self.current_capital += pnl
        
        # Track drawdown
        if self.current_capital > self.today_stats.peak_value:
            self.today_stats.peak_value = self.current_capital
        else:
            drawdown = (self.today_stats.peak_value - self.current_capital) / self.today_stats.peak_value
            if drawdown > self.today_stats.max_drawdown:
                self.today_stats.max_drawdown = drawdown
        
        # Update risk level
        self._update_risk_level()
        self._save_state()
    
    def record_error(self, error_type: str = "general"):
        """Record an error occurrence."""
        self.today_stats.errors += 1
        self._update_risk_level()
        self._save_state()
    
    def _update_risk_level(self):
        """Update risk level based on current state."""
        # Check for critical conditions
        daily_loss_pct = abs(self.today_stats.pnl) / self.initial_capital if self.today_stats.pnl < 0 else 0
        
        if daily_loss_pct >= self.limits.daily_loss_limit:
            self.risk_level = RiskLevel.HALTED
        elif self.today_stats.consecutive_losses >= self.limits.consecutive_loss_limit:
            self.risk_level = RiskLevel.CRITICAL
        elif self.today_stats.errors >= self.limits.error_threshold:
            self.risk_level = RiskLevel.CRITICAL
        elif daily_loss_pct >= self.limits.daily_loss_limit * 0.5:
            self.risk_level = RiskLevel.ELEVATED
        elif self.today_stats.consecutive_losses >= self.limits.consecutive_loss_limit // 2:
            self.risk_level = RiskLevel.ELEVATED
        else:
            self.risk_level = RiskLevel.NORMAL
    
    def check_stale_positions(self) -> List[str]:
        """Check for positions that should be closed due to age."""
        stale = []
        now = int(time.time())
        max_age_seconds = self.limits.max_position_age_hours * 3600
        
        for market, pos in self.open_positions.items():
            age = now - pos.get("opened_at", now)
            if age > max_age_seconds:
                stale.append(market)
        
        return stale
    
    def reset_daily(self):
        """Reset daily statistics (call at start of new day)."""
        today = str(date.today())
        
        if self.today_stats.date != today:
            # Save yesterday's stats
            self._save_daily_stats()
            
            # Reset for new day
            self.today_stats = DailyStats(date=today)
            self.today_stats.peak_value = self.current_capital
            self.risk_level = RiskLevel.NORMAL
            
            self._save_state()
    
    def get_status(self) -> Dict:
        """Get current risk status."""
        return {
            "risk_level": self.risk_level.value,
            "can_trade": self.can_trade()[0],
            "reason": self.can_trade()[1],
            "capital": {
                "initial": self.initial_capital,
                "current": self.current_capital,
                "pnl": self.current_capital - self.initial_capital,
                "pnl_pct": (self.current_capital - self.initial_capital) / self.initial_capital
            },
            "today": self.today_stats.to_dict(),
            "open_positions": len(self.open_positions),
            "limits": {
                "max_position": self.limits.max_position_size,
                "daily_loss_limit": self.limits.daily_loss_limit,
                "daily_trade_limit": self.limits.daily_trade_limit
            }
        }
    
    def print_status(self):
        """Print risk status to console."""
        status = self.get_status()
        
        level_emoji = {
            "normal": "🟢",
            "elevated": "🟡",
            "critical": "🔴",
            "halted": "⛔"
        }
        
        print(f"\n{'='*50}")
        print(f"⚠️  RISK STATUS")
        print(f"{'='*50}")
        print(f"Level: {level_emoji.get(status['risk_level'], '❓')} {status['risk_level'].upper()}")
        print(f"Can Trade: {'✓' if status['can_trade'] else '✗'} {status['reason']}")
        print(f"{'─'*50}")
        print(f"Capital: ${status['capital']['current']:.2f} ({status['capital']['pnl_pct']:+.1%})")
        print(f"Today's P&L: ${status['today']['pnl']:.2f}")
        print(f"Trades: {status['today']['trades']} (W:{status['today']['wins']} L:{status['today']['losses']})")
        print(f"Win Rate: {status['today']['win_rate']:.1%}")
        print(f"Consecutive Losses: {status['today']['consecutive_losses']}")
        print(f"Open Positions: {status['open_positions']}")
        print(f"{'='*50}")
    
    def _save_state(self):
        """Save current state to disk."""
        state = {
            "capital": self.current_capital,
            "risk_level": self.risk_level.value,
            "open_positions": self.open_positions,
            "today_stats": self.today_stats.to_dict(),
            "saved_at": int(time.time())
        }
        
        filepath = self.data_dir / "risk_state.json"
        with open(filepath, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _load_state(self):
        """Load state from disk."""
        filepath = self.data_dir / "risk_state.json"
        
        if not filepath.exists():
            self.today_stats.peak_value = self.current_capital
            return
        
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            
            self.current_capital = state.get("capital", self.current_capital)
            self.risk_level = RiskLevel(state.get("risk_level", "normal"))
            self.open_positions = state.get("open_positions", {})
            
            # Load today's stats if same day
            saved_stats = state.get("today_stats", {})
            if saved_stats.get("date") == str(date.today()):
                self.today_stats = DailyStats(
                    date=saved_stats["date"],
                    trades=saved_stats.get("trades", 0),
                    wins=saved_stats.get("wins", 0),
                    losses=saved_stats.get("losses", 0),
                    pnl=saved_stats.get("pnl", 0),
                    errors=saved_stats.get("errors", 0),
                    consecutive_losses=saved_stats.get("consecutive_losses", 0),
                    max_drawdown=saved_stats.get("max_drawdown", 0),
                    peak_value=saved_stats.get("peak_value", self.current_capital)
                )
            else:
                self.today_stats.peak_value = self.current_capital
                
        except Exception as e:
            print(f"Warning: Could not load risk state: {e}")
    
    def _save_daily_stats(self):
        """Save daily stats to history file."""
        history_file = self.data_dir / "daily_history.json"
        
        history = []
        if history_file.exists():
            try:
                with open(history_file, 'r') as f:
                    history = json.load(f)
            except:
                pass
        
        history.append(self.today_stats.to_dict())
        
        # Keep last 90 days
        history = history[-90:]
        
        with open(history_file, 'w') as f:
            json.dump(history, f, indent=2)


# Global risk manager instance
risk_manager: Optional[RiskManager] = None


def get_risk_manager(capital: float = 300.0) -> RiskManager:
    """Get or create global risk manager."""
    global risk_manager
    if risk_manager is None:
        risk_manager = RiskManager(capital=capital)
    return risk_manager
