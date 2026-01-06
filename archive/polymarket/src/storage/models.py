"""Data models for trading-lab."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Market:
    """Market representation."""
    condition_id: str
    slug: str
    start_ts: int
    end_ts: int
    base_symbol: str


@dataclass
class OrderbookSnapshot:
    """Order book snapshot."""
    ts: int
    condition_id: str
    token_id: str
    best_bid: float
    best_ask: float
    mid: float
    spread: float
    id: Optional[int] = None


@dataclass
class PriceTick:
    """External price feed tick."""
    ts: int
    symbol: str
    source: str
    price: float
    id: Optional[int] = None


@dataclass
class WalletTrade:
    """Wallet trade for cloning."""
    wallet: str
    ts: int
    condition_id: str
    token_id: str
    side: str  # 'buy' or 'sell'
    price: float
    size: float
    id: Optional[int] = None


@dataclass
class Feature:
    """Derived feature for strategy discovery."""
    ts: int
    condition_id: str
    t_since_start: int
    cl_delta: float
    cl_delta_bps: float
    mid_up: float
    mid_down: float
    spread_up: float
    spread_down: float
    id: Optional[int] = None
