"""
Maker Rebates Backtester for Delta-Neutral Strategy on 15-minute Crypto Markets.

This module provides backtesting capabilities for maker-only strategies that:
1. Place maker orders on BOTH sides (YES and NO) of 15-min markets
2. Earn maker rebates when orders fill
3. Track resolution P&L from position imbalance
"""

from .models import (
    BacktestConfig,
    MarketWindow,
    WindowResult,
    BacktestResults,
    OrderSide,
)
from .engine import MakerBacktestEngine
from .fill_simulator import FillSimulator
from .metrics import MakerMetrics

__all__ = [
    "BacktestConfig",
    "MarketWindow",
    "WindowResult",
    "BacktestResults",
    "OrderSide",
    "MakerBacktestEngine",
    "FillSimulator",
    "MakerMetrics",
]
