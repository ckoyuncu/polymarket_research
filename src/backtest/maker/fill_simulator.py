"""
Fill Simulator for Maker Orders.

Simulates whether maker orders would have filled based on orderbook data.
Uses a conservative approach: assumes fills only when price crosses our level.
"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from .models import OrderbookSnapshot, OrderSide


@dataclass
class FillResult:
    """Result of a fill simulation."""
    filled: bool
    fill_price: float
    fill_size: float
    fill_timestamp: Optional[int] = None
    partial_fill: bool = False
    fill_probability: float = 0.0


class FillSimulator:
    """
    Simulates fill probability and execution for maker orders.

    Uses orderbook snapshots to determine if a passive maker order
    would have been filled during a market window.
    """

    def __init__(self, conservative: bool = True):
        """
        Initialize the fill simulator.

        Args:
            conservative: If True, use conservative fill assumptions
        """
        self.conservative = conservative

    def estimate_fill_probability(
        self,
        order_price: float,
        side: OrderSide,
        orderbook: OrderbookSnapshot,
        position_size: float = 50.0
    ) -> float:
        """
        Estimate probability our maker order would fill.

        For a maker order to fill, someone must take against us:
        - YES maker order (bid): fills when taker sells YES (market sell)
        - NO maker order (bid): fills when taker sells NO

        Simple model:
        - If our price is at or better than best bid, high fill probability
        - If our price is worse than best bid, lower probability
        - Also consider depth at our price level

        Args:
            order_price: Price we're placing the maker order at
            side: OrderSide.YES or OrderSide.NO
            orderbook: Current orderbook state
            position_size: Size of our order in USD

        Returns:
            Estimated fill probability (0.0 to 1.0)
        """
        if side == OrderSide.YES:
            best_bid = orderbook.best_bid
            if best_bid is None:
                return 0.0

            # For YES side: we're bidding to buy YES
            # Fill probability based on how competitive our bid is
            if order_price >= best_bid:
                # We're at or better than best bid - high probability
                # But still depends on market activity
                base_prob = 0.8 if self.conservative else 0.95
            elif order_price >= best_bid - 0.02:
                # Within 2 cents of best bid
                base_prob = 0.5 if self.conservative else 0.7
            elif order_price >= best_bid - 0.05:
                # Within 5 cents
                base_prob = 0.2 if self.conservative else 0.4
            else:
                base_prob = 0.05

            # Adjust for depth competition
            depth_at_level = self._estimate_depth_at_price(
                order_price, orderbook.bids, tolerance=0.01
            )
            if depth_at_level > position_size * 2:
                base_prob *= 0.7  # Lots of competition at this level

        else:  # NO side
            best_no_bid = orderbook.best_no_bid
            if best_no_bid is None:
                return 0.0

            # For NO side: we're bidding to buy NO
            if order_price >= best_no_bid:
                base_prob = 0.8 if self.conservative else 0.95
            elif order_price >= best_no_bid - 0.02:
                base_prob = 0.5 if self.conservative else 0.7
            elif order_price >= best_no_bid - 0.05:
                base_prob = 0.2 if self.conservative else 0.4
            else:
                base_prob = 0.05

        return min(1.0, max(0.0, base_prob))

    def simulate_fill(
        self,
        order_price: float,
        side: OrderSide,
        orderbook_snapshots: List[OrderbookSnapshot],
        position_size: float = 50.0,
        partial_fill_enabled: bool = False
    ) -> FillResult:
        """
        Simulate whether a maker order would fill over a series of snapshots.

        Model: Check if market conditions ever become favorable enough
        for our passive order to be hit.

        For YES maker order (bid):
        - Fills if anyone market sells YES at or below our bid
        - Proxy: if best_ask ever drops to our level, we likely filled

        For NO maker order (bid):
        - Fills if anyone market sells NO at or below our bid
        - Proxy: if best_no_ask ever drops to our level, we likely filled

        Args:
            order_price: Price of our maker order
            side: OrderSide.YES or OrderSide.NO
            orderbook_snapshots: List of orderbook states during window
            position_size: Size of our order in USD
            partial_fill_enabled: Whether to simulate partial fills

        Returns:
            FillResult with fill status and details
        """
        if not orderbook_snapshots:
            return FillResult(filled=False, fill_price=0.0, fill_size=0.0)

        for snapshot in orderbook_snapshots:
            if side == OrderSide.YES:
                # Check if market moved to fill our YES bid
                # This happens when someone sells YES at our price or lower
                # Conservative proxy: best_ask dropped to or below our bid
                best_ask = snapshot.best_ask
                if best_ask is not None and best_ask <= order_price:
                    # Market crossed our level - we filled!
                    fill_size = position_size / order_price if order_price > 0 else 0
                    return FillResult(
                        filled=True,
                        fill_price=order_price,
                        fill_size=fill_size,
                        fill_timestamp=snapshot.timestamp,
                        fill_probability=1.0
                    )

                # Also check if spread collapsed significantly
                # (indicates high activity that would hit resting orders)
                if self._spread_collapse_detected(snapshot, order_price, side):
                    fill_size = position_size / order_price if order_price > 0 else 0
                    return FillResult(
                        filled=True,
                        fill_price=order_price,
                        fill_size=fill_size,
                        fill_timestamp=snapshot.timestamp,
                        fill_probability=0.9
                    )

            else:  # NO side
                # Check if market moved to fill our NO bid
                best_no_ask = snapshot.best_no_ask
                if best_no_ask is not None and best_no_ask <= order_price:
                    fill_size = position_size / order_price if order_price > 0 else 0
                    return FillResult(
                        filled=True,
                        fill_price=order_price,
                        fill_size=fill_size,
                        fill_timestamp=snapshot.timestamp,
                        fill_probability=1.0
                    )

                if self._spread_collapse_detected(snapshot, order_price, side):
                    fill_size = position_size / order_price if order_price > 0 else 0
                    return FillResult(
                        filled=True,
                        fill_price=order_price,
                        fill_size=fill_size,
                        fill_timestamp=snapshot.timestamp,
                        fill_probability=0.9
                    )

        # No fill occurred
        # Calculate final fill probability based on how close we got
        final_prob = self._calculate_final_probability(
            order_price, side, orderbook_snapshots
        )

        return FillResult(
            filled=False,
            fill_price=0.0,
            fill_size=0.0,
            fill_probability=final_prob
        )

    def simulate_fill_aggressive(
        self,
        order_price: float,
        side: OrderSide,
        orderbook_snapshots: List[OrderbookSnapshot],
        position_size: float = 50.0
    ) -> FillResult:
        """
        Aggressive fill simulation - assumes fills more readily.

        Use this for optimistic scenario analysis.
        Assumes fills if our price is ever at or better than mid price.
        """
        if not orderbook_snapshots:
            return FillResult(filled=False, fill_price=0.0, fill_size=0.0)

        for snapshot in orderbook_snapshots:
            mid = snapshot.mid_price
            if mid is None:
                continue

            if side == OrderSide.YES:
                # Aggressive: fill if we're bidding at or above mid
                if order_price >= mid:
                    fill_size = position_size / order_price if order_price > 0 else 0
                    return FillResult(
                        filled=True,
                        fill_price=order_price,
                        fill_size=fill_size,
                        fill_timestamp=snapshot.timestamp,
                        fill_probability=0.95
                    )
            else:
                # For NO side, compare to NO mid (1 - YES mid)
                no_mid = 1.0 - mid
                if order_price >= no_mid:
                    fill_size = position_size / order_price if order_price > 0 else 0
                    return FillResult(
                        filled=True,
                        fill_price=order_price,
                        fill_size=fill_size,
                        fill_timestamp=snapshot.timestamp,
                        fill_probability=0.95
                    )

        return FillResult(filled=False, fill_price=0.0, fill_size=0.0,
                         fill_probability=0.1)

    def _spread_collapse_detected(
        self,
        snapshot: OrderbookSnapshot,
        our_price: float,
        side: OrderSide
    ) -> bool:
        """
        Detect if spread collapsed in a way that suggests our order filled.

        When spread gets very tight, it often means aggressive trading
        occurred which would have filled resting orders.
        """
        spread = snapshot.spread
        if spread is None:
            return False

        # If spread is less than 1 cent, lots of activity
        if spread < 0.01:
            # Check if our price is competitive
            if side == OrderSide.YES:
                best_bid = snapshot.best_bid
                if best_bid and our_price >= best_bid - 0.01:
                    return True
            else:
                best_no_bid = snapshot.best_no_bid
                if best_no_bid and our_price >= best_no_bid - 0.01:
                    return True

        return False

    def _estimate_depth_at_price(
        self,
        price: float,
        levels: List[List[float]],
        tolerance: float = 0.01
    ) -> float:
        """Estimate total depth at or near a specific price level."""
        total_depth = 0.0
        for level_price, level_size in levels:
            if abs(level_price - price) <= tolerance:
                total_depth += level_size
        return total_depth

    def _calculate_final_probability(
        self,
        order_price: float,
        side: OrderSide,
        snapshots: List[OrderbookSnapshot]
    ) -> float:
        """
        Calculate final fill probability based on how close market got.

        Used when order didn't fill to estimate how close we were.
        """
        if not snapshots:
            return 0.0

        min_distance = float('inf')

        for snapshot in snapshots:
            if side == OrderSide.YES:
                best_ask = snapshot.best_ask
                if best_ask is not None:
                    distance = best_ask - order_price
                    min_distance = min(min_distance, distance)
            else:
                best_no_ask = snapshot.best_no_ask
                if best_no_ask is not None:
                    distance = best_no_ask - order_price
                    min_distance = min(min_distance, distance)

        if min_distance == float('inf'):
            return 0.0

        # Convert distance to probability
        # Closer distance = higher probability we almost filled
        if min_distance <= 0:
            return 0.95
        elif min_distance <= 0.01:
            return 0.6
        elif min_distance <= 0.02:
            return 0.4
        elif min_distance <= 0.05:
            return 0.2
        else:
            return 0.05


class ProbabilisticFillSimulator(FillSimulator):
    """
    Fill simulator that uses probabilistic fills instead of deterministic.

    For Monte Carlo style backtesting where we sample from fill probability
    distributions rather than using deterministic rules.
    """

    def __init__(self, seed: Optional[int] = None):
        """
        Initialize probabilistic simulator.

        Args:
            seed: Random seed for reproducibility
        """
        super().__init__(conservative=True)
        import random
        self.rng = random.Random(seed)

    def simulate_fill_probabilistic(
        self,
        order_price: float,
        side: OrderSide,
        orderbook_snapshots: List[OrderbookSnapshot],
        position_size: float = 50.0
    ) -> FillResult:
        """
        Simulate fill using probability sampling.

        Instead of deterministic fill rules, samples from
        estimated fill probability at each snapshot.
        """
        if not orderbook_snapshots:
            return FillResult(filled=False, fill_price=0.0, fill_size=0.0)

        for snapshot in orderbook_snapshots:
            prob = self.estimate_fill_probability(
                order_price, side, snapshot, position_size
            )

            # Sample from fill probability
            if self.rng.random() < prob * 0.1:  # Scale down for each snapshot
                fill_size = position_size / order_price if order_price > 0 else 0
                return FillResult(
                    filled=True,
                    fill_price=order_price,
                    fill_size=fill_size,
                    fill_timestamp=snapshot.timestamp,
                    fill_probability=prob
                )

        # Calculate final probability
        final_prob = self._calculate_final_probability(
            order_price, side, orderbook_snapshots
        )

        return FillResult(
            filled=False,
            fill_price=0.0,
            fill_size=0.0,
            fill_probability=final_prob
        )
