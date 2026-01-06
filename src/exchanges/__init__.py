"""
Exchange implementations for the trading system.

This module provides exchange abstractions and implementations:
- BaseExchange: Abstract base class for all exchanges
- PaperExchange: Paper trading simulator for strategy testing
- HyperliquidExchange: Hyperliquid perpetual futures (testnet/mainnet)

Usage:
    from src.exchanges import HyperliquidExchange, OrderSide, OrderType

    exchange = HyperliquidExchange(testnet=True)
    await exchange.connect()

    order = await exchange.place_order(
        symbol="BTC-PERP",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Decimal("0.1"),
    )
"""

from .base import (
    AuthenticationError,
    Balance,
    BaseExchange,
    ConnectionError,
    ExchangeError,
    InsufficientBalanceError,
    Market,
    Order,
    OrderError,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    PositionSide,
    RateLimitError,
)
from .hyperliquid import HyperliquidExchange
from .paper import PaperExchange

__all__ = [
    # Base classes and types
    "BaseExchange",
    "Order",
    "Position",
    "Balance",
    "Market",
    "OrderSide",
    "OrderType",
    "OrderStatus",
    "PositionSide",
    # Exceptions
    "ExchangeError",
    "ConnectionError",
    "AuthenticationError",
    "OrderError",
    "InsufficientBalanceError",
    "RateLimitError",
    # Implementations
    "PaperExchange",
    "HyperliquidExchange",
]
