"""
Small Account Risk Management

Position sizing and risk rules for $100-500 accounts.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskConfig:
    """Risk configuration for small accounts."""
    
    # Account settings
    starting_capital: float = 200.0
    
    # Position sizing
    max_position_pct: float = 10.0      # Max 10% per trade
    max_position_usd: float = 50.0       # Hard cap per trade
    
    # Risk limits
    max_daily_loss_pct: float = 10.0    # Stop trading after 10% daily loss
    max_open_positions: int = 3          # Max concurrent positions
    
    # Trade filters
    min_edge_estimate: float = 0.05     # Only trade if estimated edge > 5%
    max_spread_pct: float = 5.0          # Don't trade if spread > 5%
    
    # Execution
    use_limit_orders: bool = True        # Prefer limit orders
    max_slippage_pct: float = 2.0        # Max acceptable slippage


class SmallAccountRiskManager:
    """
    Risk management for $100-500 accounts.
    
    Key principles:
    1. Never risk more than you can lose
    2. Size positions conservatively
    3. High frequency beats big bets
    4. Compound gains, cut losses
    """
    
    PRESETS = {
        "ultra_conservative": RiskConfig(
            starting_capital=100,
            max_position_pct=5.0,
            max_position_usd=10.0,
            max_daily_loss_pct=5.0,
            max_open_positions=2,
        ),
        "conservative": RiskConfig(
            starting_capital=200,
            max_position_pct=10.0,
            max_position_usd=25.0,
            max_daily_loss_pct=10.0,
            max_open_positions=3,
        ),
        "moderate": RiskConfig(
            starting_capital=500,
            max_position_pct=10.0,
            max_position_usd=50.0,
            max_daily_loss_pct=15.0,
            max_open_positions=5,
        ),
    }
    
    def __init__(self, config: RiskConfig = None, preset: str = "conservative"):
        if config:
            self.config = config
        else:
            self.config = self.PRESETS.get(preset, self.PRESETS["conservative"])
        
        self.current_capital = self.config.starting_capital
        self.daily_pnl = 0.0
        self.open_positions = 0
    
    def calculate_position_size(
        self,
        price: float,
        confidence: float = 0.5
    ) -> float:
        """
        Calculate appropriate position size.
        
        Args:
            price: Current market price (0-1)
            confidence: Confidence in the trade (0-1)
        
        Returns:
            Position size in USD
        """
        # Base size from percentage
        pct_size = self.current_capital * (self.config.max_position_pct / 100)
        
        # Apply hard cap
        base_size = min(pct_size, self.config.max_position_usd)
        
        # Scale by confidence
        confidence_multiplier = 0.5 + (confidence * 0.5)  # 0.5x to 1x
        scaled_size = base_size * confidence_multiplier
        
        # Ensure we have enough capital
        final_size = min(scaled_size, self.current_capital * 0.9)
        
        return round(final_size, 2)
    
    def can_trade(self) -> tuple[bool, str]:
        """Check if we can take a new trade."""
        # Check daily loss limit
        if self.daily_pnl < 0:
            daily_loss_pct = abs(self.daily_pnl) / self.config.starting_capital * 100
            if daily_loss_pct >= self.config.max_daily_loss_pct:
                return False, f"Daily loss limit reached ({daily_loss_pct:.1f}%)"
        
        # Check position count
        if self.open_positions >= self.config.max_open_positions:
            return False, f"Max open positions ({self.config.max_open_positions})"
        
        # Check remaining capital
        min_trade = 5.0
        if self.current_capital < min_trade:
            return False, f"Insufficient capital (${self.current_capital:.2f})"
        
        return True, "OK"
    
    def should_take_trade(
        self,
        estimated_edge: float,
        spread: float,
        price: float
    ) -> tuple[bool, str]:
        """
        Decide if a specific trade should be taken.
        
        Args:
            estimated_edge: Estimated edge (e.g., 0.05 = 5%)
            spread: Current bid-ask spread
            price: Current price
        """
        # Check basic permission
        can, reason = self.can_trade()
        if not can:
            return False, reason
        
        # Check edge requirement
        if estimated_edge < self.config.min_edge_estimate:
            return False, f"Edge too low ({estimated_edge:.1%} < {self.config.min_edge_estimate:.1%})"
        
        # Check spread
        spread_pct = spread / price * 100 if price > 0 else 100
        if spread_pct > self.config.max_spread_pct:
            return False, f"Spread too wide ({spread_pct:.1f}% > {self.config.max_spread_pct:.1f}%)"
        
        return True, "OK"
    
    def record_trade(self, pnl: float):
        """Record a completed trade."""
        self.current_capital += pnl
        self.daily_pnl += pnl
        
        if pnl >= 0:
            self.open_positions = max(0, self.open_positions - 1)
    
    def reset_daily(self):
        """Reset daily counters (call at start of each day)."""
        self.daily_pnl = 0.0
    
    def get_status(self) -> dict:
        """Get current risk status."""
        daily_loss_pct = abs(self.daily_pnl) / self.config.starting_capital * 100 if self.daily_pnl < 0 else 0
        
        return {
            "current_capital": self.current_capital,
            "starting_capital": self.config.starting_capital,
            "pnl_total": self.current_capital - self.config.starting_capital,
            "pnl_total_pct": (self.current_capital - self.config.starting_capital) / self.config.starting_capital * 100,
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": daily_loss_pct,
            "open_positions": self.open_positions,
            "max_position_size": self.calculate_position_size(0.5),
            "can_trade": self.can_trade()[0],
        }
    
    def print_status(self):
        """Print formatted status."""
        s = self.get_status()
        
        print("\n" + "="*50)
        print("💰 ACCOUNT STATUS")
        print("="*50)
        print(f"   Capital: ${s['current_capital']:.2f} (started: ${s['starting_capital']:.2f})")
        print(f"   Total P&L: ${s['pnl_total']:.2f} ({s['pnl_total_pct']:+.1f}%)")
        print(f"   Today's P&L: ${s['daily_pnl']:.2f}")
        print(f"   Open positions: {s['open_positions']}/{self.config.max_open_positions}")
        print(f"   Max trade size: ${s['max_position_size']:.2f}")
        print(f"   Can trade: {'✅ Yes' if s['can_trade'] else '❌ No'}")
        print("="*50)


def get_recommended_config(capital: float) -> RiskConfig:
    """Get recommended risk config based on capital."""
    if capital <= 100:
        return SmallAccountRiskManager.PRESETS["ultra_conservative"]
    elif capital <= 300:
        return SmallAccountRiskManager.PRESETS["conservative"]
    else:
        return SmallAccountRiskManager.PRESETS["moderate"]
