"""
Maker strategy module for delta-neutral market making on Polymarket.

This module provides tools for:
- Main bot orchestration (MakerBot)
- Delta-neutral position tracking
- Paper trading simulation
- Synchronized YES/NO order placement
- Risk monitoring with kill switch
- 15-minute market discovery
- Rebate tracking and analytics
"""

from .delta_tracker import DeltaTracker, TrackedPosition
from .paper_simulator import MakerPaperSimulator
from .dual_order import DualOrderExecutor, OrderResult, DualOrderResult
from .risk_limits import RiskMonitor, Alert
from .market_finder import MarketFinder, Market15Min
from .bot import MakerBot, BotState

# Optional imports that may not exist
try:
    from .rebate_monitor import RebateTracker, RebateEvent, RecordedTrade, MarketStats
    _has_rebate_monitor = True
except ImportError:
    _has_rebate_monitor = False

__all__ = [
    # Main bot
    "MakerBot",
    "BotState",
    # Position tracking
    "DeltaTracker",
    "TrackedPosition",
    # Paper trading
    "MakerPaperSimulator",
    # Order execution
    "DualOrderExecutor",
    "OrderResult",
    "DualOrderResult",
    # Risk management
    "RiskMonitor",
    "Alert",
    # Market discovery
    "MarketFinder",
    "Market15Min",
]

# Add rebate monitor exports if available
if _has_rebate_monitor:
    __all__.extend([
        "RebateTracker",
        "RebateEvent",
        "RecordedTrade",
        "MarketStats",
    ])
