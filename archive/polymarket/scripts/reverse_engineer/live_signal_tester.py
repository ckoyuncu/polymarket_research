#!/usr/bin/env python3
"""
Live Signal Tester

Paper trades multiple signal hypotheses in real-time to validate which
strategies could replicate Account88888's performance.

Strategies tested:
1. Simple Momentum - bet with Binance price direction
2. Orderbook Imbalance - bet with orderbook pressure
3. Multi-Exchange Leader - bet with exchange that moves first
4. ML Model - use trained model predictions (if available)

Usage:
    python scripts/reverse_engineer/live_signal_tester.py --duration 60

Output:
    Real-time P&L and win rate for each strategy
"""

import json
import time
import threading
import requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from collections import defaultdict
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class Signal:
    """A trading signal from a strategy."""
    timestamp: float
    strategy: str
    asset: str
    direction: str  # "up" or "down"
    confidence: float  # 0-1
    reason: str


@dataclass
class PaperTrade:
    """A paper trade."""
    signal: Signal
    entry_time: float
    slug: str
    position_size: float  # Simulated USDC
    entry_up_price: float
    entry_down_price: float

    # Filled after resolution
    resolution: Optional[str] = None  # "up" or "down"
    profit: Optional[float] = None
    closed_time: Optional[float] = None


@dataclass
class StrategyPerformance:
    """Performance metrics for a strategy."""
    name: str
    trades: int = 0
    wins: int = 0
    losses: int = 0
    total_profit: float = 0
    total_invested: float = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades > 0 else 0

    @property
    def roi(self) -> float:
        return self.total_profit / self.total_invested if self.total_invested > 0 else 0


class LiveSignalTester:
    """Tests trading signals in real-time."""

    CLOB_API = "https://clob.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    def __init__(self, position_size: float = 100):
        self.position_size = position_size  # USDC per trade

        # Market state
        self.binance_prices: Dict[str, float] = {}
        self.orderbook_state: Dict[str, dict] = {}

        # Trades
        self.open_trades: List[PaperTrade] = []
        self.closed_trades: List[PaperTrade] = []

        # Performance by strategy
        self.performance: Dict[str, StrategyPerformance] = {
            "momentum": StrategyPerformance(name="Simple Momentum"),
            "orderbook": StrategyPerformance(name="Orderbook Imbalance"),
            "combined": StrategyPerformance(name="Momentum + Orderbook"),
        }

        # Control
        self._running = False
        self._lock = threading.Lock()

    def fetch_binance_price(self, symbol: str) -> Optional[float]:
        """Fetch current price from Binance.US."""
        try:
            pair = f"{symbol}USD"
            for base_url in ["https://api.binance.us", "https://api.binance.com"]:
                try:
                    response = requests.get(
                        f"{base_url}/api/v3/ticker/price",
                        params={"symbol": pair},
                        timeout=2
                    )
                    if response.ok:
                        return float(response.json()["price"])
                except:
                    continue
        except:
            pass
        return None

    def fetch_orderbook(self, token_id: str) -> Optional[dict]:
        """Fetch orderbook for a token."""
        try:
            response = requests.get(
                f"{self.CLOB_API}/book",
                params={"token_id": token_id},
                timeout=5
            )
            if response.ok:
                return response.json()
        except:
            pass
        return None

    def get_market_info(self, asset: str) -> Optional[dict]:
        """Get current 15-min market info."""
        now = int(time.time())
        current_slot = now - (now % 900) + 900
        slug = f"{asset.lower()}-updown-15m-{current_slot - 900}"

        try:
            response = requests.get(
                f"{self.GAMMA_API}/markets/slug/{slug}",
                timeout=10
            )
            if response.ok:
                data = response.json()
                clob_ids = data.get("clobTokenIds", [])
                outcomes = data.get("outcomes", [])

                if isinstance(clob_ids, str):
                    clob_ids = json.loads(clob_ids)
                if isinstance(outcomes, str):
                    outcomes = json.loads(outcomes)

                token_up = token_down = None
                for i, outcome in enumerate(outcomes):
                    if outcome.lower() == "up" and i < len(clob_ids):
                        token_up = clob_ids[i]
                    elif outcome.lower() == "down" and i < len(clob_ids):
                        token_down = clob_ids[i]

                return {
                    "slug": slug,
                    "window_start": current_slot - 900,
                    "window_end": current_slot,
                    "token_up": token_up,
                    "token_down": token_down,
                    "asset": asset,
                }
        except:
            pass
        return None

    def momentum_signal(self, asset: str, market: dict) -> Optional[Signal]:
        """Generate signal based on Binance price momentum."""
        window_start = market.get("window_start")
        if not window_start:
            return None

        # Get current price
        current_price = self.binance_prices.get(asset)
        if not current_price:
            return None

        # Get start price (approximation - would need historical)
        # For now, assume we've been tracking
        start_price = self.binance_prices.get(f"{asset}_start_{window_start}")

        if not start_price:
            # First time seeing this window, record start price
            self.binance_prices[f"{asset}_start_{window_start}"] = current_price
            return None

        # Calculate momentum
        momentum = (current_price - start_price) / start_price

        if abs(momentum) < 0.0001:  # Less than 0.01%
            return None  # No signal

        direction = "up" if momentum > 0 else "down"
        confidence = min(abs(momentum) * 100, 1.0)  # Scale to 0-1

        return Signal(
            timestamp=time.time(),
            strategy="momentum",
            asset=asset,
            direction=direction,
            confidence=confidence,
            reason=f"Momentum: {momentum*100:.3f}%",
        )

    def orderbook_signal(self, asset: str, market: dict) -> Optional[Signal]:
        """Generate signal based on orderbook imbalance."""
        token_up = market.get("token_up")
        token_down = market.get("token_down")

        if not token_up or not token_down:
            return None

        # Get orderbooks
        book_up = self.fetch_orderbook(token_up)
        book_down = self.fetch_orderbook(token_down)

        if not book_up or not book_down:
            return None

        # Calculate imbalance
        def calc_imbalance(book: dict) -> float:
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            bid_depth = sum(float(b.get("size", 0)) for b in bids[:3])
            ask_depth = sum(float(a.get("size", 0)) for a in asks[:3])
            total = bid_depth + ask_depth
            return (bid_depth - ask_depth) / total if total > 0 else 0

        up_imbalance = calc_imbalance(book_up)
        down_imbalance = calc_imbalance(book_down)

        # Strong bid for UP and strong ask for DOWN = bet UP
        # Strong bid for DOWN and strong ask for UP = bet DOWN
        net_signal = up_imbalance - down_imbalance

        if abs(net_signal) < 0.05:  # Less than 5% imbalance
            return None

        direction = "up" if net_signal > 0 else "down"
        confidence = min(abs(net_signal), 1.0)

        return Signal(
            timestamp=time.time(),
            strategy="orderbook",
            asset=asset,
            direction=direction,
            confidence=confidence,
            reason=f"UP imbal: {up_imbalance:.2f}, DOWN imbal: {down_imbalance:.2f}",
        )

    def combined_signal(self, asset: str, market: dict) -> Optional[Signal]:
        """Generate signal combining momentum and orderbook."""
        mom_signal = self.momentum_signal(asset, market)
        ob_signal = self.orderbook_signal(asset, market)

        if not mom_signal and not ob_signal:
            return None

        if mom_signal and ob_signal:
            # Both agree
            if mom_signal.direction == ob_signal.direction:
                return Signal(
                    timestamp=time.time(),
                    strategy="combined",
                    asset=asset,
                    direction=mom_signal.direction,
                    confidence=(mom_signal.confidence + ob_signal.confidence) / 2,
                    reason=f"Momentum + Orderbook agree: {mom_signal.direction.upper()}",
                )
            else:
                return None  # Conflicting signals

        # Only one signal
        return mom_signal or ob_signal

    def get_entry_prices(self, market: dict) -> Tuple[float, float]:
        """Get current entry prices for UP and DOWN tokens."""
        token_up = market.get("token_up")
        token_down = market.get("token_down")

        up_price = down_price = 0.5

        if token_up:
            book = self.fetch_orderbook(token_up)
            if book:
                asks = book.get("asks", [])
                if asks:
                    up_price = float(asks[0]["price"])

        if token_down:
            book = self.fetch_orderbook(token_down)
            if book:
                asks = book.get("asks", [])
                if asks:
                    down_price = float(asks[0]["price"])

        return up_price, down_price

    def execute_paper_trade(self, signal: Signal, market: dict):
        """Execute a paper trade based on signal."""
        up_price, down_price = self.get_entry_prices(market)

        trade = PaperTrade(
            signal=signal,
            entry_time=time.time(),
            slug=market["slug"],
            position_size=self.position_size,
            entry_up_price=up_price,
            entry_down_price=down_price,
        )

        with self._lock:
            self.open_trades.append(trade)
            self.performance[signal.strategy].trades += 1
            self.performance[signal.strategy].total_invested += self.position_size

        print(f"\n📝 PAPER TRADE: {signal.strategy}")
        print(f"   Asset: {signal.asset}, Direction: {signal.direction.upper()}")
        print(f"   Confidence: {signal.confidence:.1%}")
        print(f"   Entry: UP=${up_price:.3f}, DOWN=${down_price:.3f}")

    def check_resolutions(self):
        """Check if any open trades have resolved."""
        now = time.time()

        for trade in list(self.open_trades):
            # Parse window end from slug
            try:
                slug_parts = trade.slug.split("-")
                window_start = int(slug_parts[-1])
                window_end = window_start + 900
            except:
                continue

            # Check if resolved
            if now < window_end + 30:  # Wait 30s after close for resolution
                continue

            # Determine outcome from Binance
            asset = trade.signal.asset
            start_price = self.binance_prices.get(f"{asset}_start_{window_start}")
            end_price = self.binance_prices.get(asset)

            if not start_price or not end_price:
                continue

            resolution = "up" if end_price > start_price else "down"
            trade.resolution = resolution
            trade.closed_time = now

            # Calculate P&L
            bet_direction = trade.signal.direction
            if bet_direction == resolution:
                # Win - simplified P&L
                entry_price = trade.entry_up_price if bet_direction == "up" else trade.entry_down_price
                payout = trade.position_size / entry_price  # Tokens bought
                trade.profit = payout - trade.position_size  # Profit = payout - cost
            else:
                # Loss
                trade.profit = -trade.position_size

            # Update performance
            with self._lock:
                perf = self.performance[trade.signal.strategy]
                if trade.profit > 0:
                    perf.wins += 1
                else:
                    perf.losses += 1
                perf.total_profit += trade.profit

                self.open_trades.remove(trade)
                self.closed_trades.append(trade)

            result = "✅ WIN" if trade.profit > 0 else "❌ LOSS"
            print(f"\n{result}: {trade.signal.strategy}")
            print(f"   Market: {trade.slug}")
            print(f"   Bet: {bet_direction.upper()}, Outcome: {resolution.upper()}")
            print(f"   P&L: ${trade.profit:.2f}")

    def update_prices(self):
        """Update Binance prices."""
        for asset in ["BTC", "ETH"]:
            price = self.fetch_binance_price(asset)
            if price:
                self.binance_prices[asset] = price

    def print_status(self):
        """Print current status."""
        print(f"\n{'='*60}")
        print(f"LIVE SIGNAL TESTER - {datetime.now().strftime('%H:%M:%S')}")
        print(f"{'='*60}")

        print("\n--- Current Prices ---")
        for asset in ["BTC", "ETH"]:
            price = self.binance_prices.get(asset, 0)
            print(f"  {asset}: ${price:,.2f}")

        print(f"\n--- Open Trades: {len(self.open_trades)} ---")

        print("\n--- Strategy Performance ---")
        print(f"{'Strategy':<20} {'Trades':>8} {'Win Rate':>10} {'P&L':>12} {'ROI':>8}")
        print("-" * 60)

        for name, perf in self.performance.items():
            print(f"{perf.name:<20} {perf.trades:>8} {perf.win_rate:>9.1%} ${perf.total_profit:>10.2f} {perf.roi:>7.1%}")

    def run(self, duration_minutes: int = 60):
        """Run live signal testing."""
        print("=" * 60)
        print("LIVE SIGNAL TESTER")
        print("=" * 60)
        print()
        print("Paper trading multiple strategies in real-time.")
        print(f"Position size: ${self.position_size} per trade")
        print(f"Duration: {duration_minutes} minutes")
        print()
        print("Press Ctrl+C to stop")
        print()

        self._running = True
        end_time = time.time() + (duration_minutes * 60)
        last_signal_check = 0
        last_status = 0

        try:
            while time.time() < end_time and self._running:
                now = time.time()

                # Update prices
                self.update_prices()

                # Check for signals every 30 seconds
                if now - last_signal_check > 30:
                    for asset in ["BTC", "ETH"]:
                        market = self.get_market_info(asset)
                        if not market:
                            continue

                        # Check time remaining
                        time_left = market["window_end"] - now
                        if time_left < 60 or time_left > 780:  # Skip if <1min or >13min left
                            continue

                        # Check if we already have a trade for this market
                        existing = any(
                            t.slug == market["slug"]
                            for t in self.open_trades + self.closed_trades
                        )
                        if existing:
                            continue

                        # Generate signals
                        for strategy in ["momentum", "orderbook", "combined"]:
                            if strategy == "momentum":
                                signal = self.momentum_signal(asset, market)
                            elif strategy == "orderbook":
                                signal = self.orderbook_signal(asset, market)
                            else:
                                signal = self.combined_signal(asset, market)

                            if signal and signal.confidence > 0.3:
                                self.execute_paper_trade(signal, market)

                    last_signal_check = now

                # Check resolutions
                self.check_resolutions()

                # Print status every 60 seconds
                if now - last_status > 60:
                    self.print_status()
                    last_status = now

                time.sleep(5)

        except KeyboardInterrupt:
            print("\nStopped by user")

        self._running = False

        # Final summary
        print("\n" + "=" * 60)
        print("FINAL RESULTS")
        print("=" * 60)
        self.print_status()

        print(f"\nTotal closed trades: {len(self.closed_trades)}")
        print(f"Open trades (unresolved): {len(self.open_trades)}")


def main():
    """Run live signal tester."""
    import argparse

    parser = argparse.ArgumentParser(description="Live Signal Tester")
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duration in minutes (default: 60)"
    )
    parser.add_argument(
        "--size",
        type=float,
        default=100,
        help="Position size in USDC (default: 100)"
    )

    args = parser.parse_args()

    tester = LiveSignalTester(position_size=args.size)
    tester.run(duration_minutes=args.duration)


if __name__ == "__main__":
    main()
