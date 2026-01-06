"""
Data models for the Maker Rebates Backtester.

Defines all the dataclasses used for configuration, market data, and results.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class OrderSide(Enum):
    """Side of the order - YES or NO outcome."""
    YES = "YES"
    NO = "NO"


class Outcome(Enum):
    """Market resolution outcome."""
    UP = "UP"
    DOWN = "DOWN"


@dataclass
class BacktestConfig:
    """
    Configuration for the maker rebates backtest.

    Attributes:
        position_size: USD amount to deploy per side (YES and NO each)
        spread_from_mid: Price offset from mid price for maker orders (e.g., 0.01 = 1 cent)
        rebate_rate: Estimated maker rebate as fraction of volume (conservative: 0.5%)
        min_spread_to_enter: Minimum market spread required to enter (skip thin spreads)
        max_position_imbalance: Maximum allowed imbalance between YES and NO fills (0-1)
        slippage_model: Type of slippage model ("none", "fixed", "proportional")
        slippage_bps: Slippage in basis points for fixed model
        partial_fill_model: Whether to simulate partial fills ("all_or_nothing", "pro_rata")
    """
    position_size: float = 50.0  # USD per side
    spread_from_mid: float = 0.01  # 1 cent from mid
    rebate_rate: float = 0.005  # 0.5% conservative
    min_spread_to_enter: float = 0.02  # Don't enter if spread < 2%
    max_position_imbalance: float = 0.5  # Max 50% imbalance
    slippage_model: str = "none"
    slippage_bps: float = 0.0
    partial_fill_model: str = "all_or_nothing"

    def validate(self) -> bool:
        """Validate configuration parameters."""
        if self.position_size <= 0:
            raise ValueError("position_size must be positive")
        if not 0 <= self.spread_from_mid <= 0.5:
            raise ValueError("spread_from_mid must be between 0 and 0.5")
        if not 0 <= self.rebate_rate <= 0.1:
            raise ValueError("rebate_rate must be between 0 and 10%")
        if not 0 <= self.min_spread_to_enter <= 0.5:
            raise ValueError("min_spread_to_enter must be between 0 and 0.5")
        return True


@dataclass
class OrderbookSnapshot:
    """
    A snapshot of the orderbook at a point in time.

    Attributes:
        timestamp: Unix timestamp in seconds
        bids: List of [price, size] for YES bids
        asks: List of [price, size] for YES asks
        no_bids: List of [price, size] for NO bids (optional, derived from asks)
        no_asks: List of [price, size] for NO asks (optional, derived from bids)
    """
    timestamp: int
    bids: List[List[float]]  # [[price, size], ...]
    asks: List[List[float]]  # [[price, size], ...]
    no_bids: Optional[List[List[float]]] = None
    no_asks: Optional[List[List[float]]] = None

    @property
    def best_bid(self) -> Optional[float]:
        """Best YES bid price."""
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        """Best YES ask price."""
        return self.asks[0][0] if self.asks else None

    @property
    def mid_price(self) -> Optional[float]:
        """Mid price for YES side."""
        if self.best_bid and self.best_ask:
            return (self.best_bid + self.best_ask) / 2
        return None

    @property
    def spread(self) -> Optional[float]:
        """Spread between best bid and ask."""
        if self.best_bid and self.best_ask:
            return self.best_ask - self.best_bid
        return None

    @property
    def best_no_bid(self) -> Optional[float]:
        """Best NO bid price (derived from YES ask: NO_bid = 1 - YES_ask)."""
        if self.no_bids:
            return self.no_bids[0][0]
        # In Polymarket, NO bid = 1 - YES ask
        return 1.0 - self.best_ask if self.best_ask else None

    @property
    def best_no_ask(self) -> Optional[float]:
        """Best NO ask price (derived from YES bid: NO_ask = 1 - YES_bid)."""
        if self.no_asks:
            return self.no_asks[0][0]
        # In Polymarket, NO ask = 1 - YES bid
        return 1.0 - self.best_bid if self.best_bid else None

    def bid_depth(self, levels: int = 5) -> float:
        """Total size available at top N bid levels."""
        return sum(size for _, size in self.bids[:levels])

    def ask_depth(self, levels: int = 5) -> float:
        """Total size available at top N ask levels."""
        return sum(size for _, size in self.asks[:levels])


@dataclass
class MarketWindow:
    """
    Data for a single 15-minute market window.

    Attributes:
        market_id: Unique identifier for the market
        window_start: Unix timestamp when window opens
        window_end: Unix timestamp when window closes/resolves
        outcome: The resolution outcome ("UP" or "DOWN")
        orderbook_snapshots: List of orderbook snapshots during the window
        binance_start: BTC/ETH price at window start (for reference)
        binance_end: BTC/ETH price at window end (for reference)
        asset: Underlying asset (BTC, ETH, etc.)
    """
    market_id: str
    window_start: int
    window_end: int
    outcome: str  # "UP" or "DOWN"
    orderbook_snapshots: List[OrderbookSnapshot]
    binance_start: float
    binance_end: float
    asset: str = "BTC"

    @property
    def duration_seconds(self) -> int:
        """Window duration in seconds."""
        return self.window_end - self.window_start

    @property
    def price_change_pct(self) -> float:
        """Percentage change in underlying price."""
        if self.binance_start > 0:
            return (self.binance_end - self.binance_start) / self.binance_start * 100
        return 0.0

    @property
    def num_snapshots(self) -> int:
        """Number of orderbook snapshots."""
        return len(self.orderbook_snapshots)

    def get_snapshot_at(self, timestamp: int) -> Optional[OrderbookSnapshot]:
        """Get the orderbook snapshot closest to the given timestamp."""
        if not self.orderbook_snapshots:
            return None
        # Find closest snapshot
        closest = min(self.orderbook_snapshots,
                      key=lambda s: abs(s.timestamp - timestamp))
        return closest

    @property
    def initial_snapshot(self) -> Optional[OrderbookSnapshot]:
        """First orderbook snapshot in the window."""
        return self.orderbook_snapshots[0] if self.orderbook_snapshots else None

    @property
    def final_snapshot(self) -> Optional[OrderbookSnapshot]:
        """Last orderbook snapshot in the window."""
        return self.orderbook_snapshots[-1] if self.orderbook_snapshots else None


@dataclass
class WindowResult:
    """
    Results from backtesting a single 15-minute window.

    Attributes:
        market_id: Market identifier
        window_start: Window start timestamp
        entered: Whether we entered this market
        skip_reason: Reason for skipping entry (if applicable)
        yes_fill_price: Price at which YES order filled
        no_fill_price: Price at which NO order filled
        yes_filled: Whether YES order filled
        no_filled: Whether NO order filled
        yes_size: Size of YES position
        no_size: Size of NO position
        resolution_pnl: P&L from resolution (winning side - cost)
        rebate_earned: Maker rebate earned
        total_pnl: Total P&L for this window
        outcome: Actual market outcome
        initial_mid: Initial mid price when entering
        initial_spread: Initial spread when entering
    """
    market_id: str
    window_start: int = 0
    entered: bool = False
    skip_reason: Optional[str] = None
    yes_fill_price: float = 0.0
    no_fill_price: float = 0.0
    yes_filled: bool = False
    no_filled: bool = False
    yes_size: float = 0.0
    no_size: float = 0.0
    resolution_pnl: float = 0.0
    rebate_earned: float = 0.0
    total_pnl: float = 0.0
    outcome: str = ""
    initial_mid: float = 0.0
    initial_spread: float = 0.0

    @property
    def is_delta_neutral(self) -> bool:
        """Check if position is roughly delta neutral (both sides filled)."""
        return self.yes_filled and self.no_filled

    @property
    def cost_basis(self) -> float:
        """Total cost of entering both positions."""
        yes_cost = self.yes_fill_price * self.yes_size if self.yes_filled else 0
        no_cost = self.no_fill_price * self.no_size if self.no_filled else 0
        return yes_cost + no_cost

    @property
    def imbalance(self) -> float:
        """Position imbalance (0 = perfectly balanced)."""
        if self.yes_size + self.no_size == 0:
            return 0.0
        return abs(self.yes_size - self.no_size) / (self.yes_size + self.no_size)


@dataclass
class BacktestResults:
    """
    Aggregated results from a complete backtest run.

    Attributes:
        config: Configuration used for this backtest
        window_results: List of individual window results
        metrics: Computed performance metrics
        start_time: Backtest start timestamp
        end_time: Backtest end timestamp
    """
    config: BacktestConfig
    window_results: List[WindowResult]
    metrics: Dict[str, Any] = field(default_factory=dict)
    start_time: Optional[int] = None
    end_time: Optional[int] = None

    @property
    def total_windows(self) -> int:
        """Total number of windows processed."""
        return len(self.window_results)

    @property
    def windows_entered(self) -> int:
        """Number of windows where we entered."""
        return sum(1 for r in self.window_results if r.entered)

    @property
    def total_pnl(self) -> float:
        """Total P&L across all windows."""
        return sum(r.total_pnl for r in self.window_results)

    @property
    def total_rebates(self) -> float:
        """Total rebates earned."""
        return sum(r.rebate_earned for r in self.window_results)

    @property
    def total_resolution_pnl(self) -> float:
        """Total resolution P&L (excluding rebates)."""
        return sum(r.resolution_pnl for r in self.window_results)

    def get_pnl_series(self) -> List[float]:
        """Get list of P&L values for each entered window."""
        return [r.total_pnl for r in self.window_results if r.entered]

    def get_cumulative_pnl(self) -> List[float]:
        """Get cumulative P&L series."""
        pnl_series = self.get_pnl_series()
        cumulative = []
        running_total = 0.0
        for pnl in pnl_series:
            running_total += pnl
            cumulative.append(running_total)
        return cumulative
