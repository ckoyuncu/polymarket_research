#!/usr/bin/env python3
"""
Spread Calculator for Post-Resolution Trading

Calculates trading opportunities based on orderbook spreads.
Key metrics:
- Buy/sell spread
- Net profit after fees
- Position sizing
- Edge calculation
"""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TradingOpportunity:
    """Represents a potential trade opportunity."""
    token_id: str
    outcome: str  # "Up" or "Down"
    side: str  # "buy" or "sell"

    # Prices
    entry_price: float
    exit_price: float

    # Sizes
    available_size: float
    recommended_size: float

    # Profitability
    gross_spread: float
    net_spread: float  # After fees
    edge_pct: float

    # Risk
    is_winner: bool  # Based on price level

    def to_dict(self) -> Dict:
        return {
            "token_id": self.token_id[:30] + "...",
            "outcome": self.outcome,
            "side": self.side,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "available_size": self.available_size,
            "recommended_size": self.recommended_size,
            "gross_spread": self.gross_spread,
            "net_spread": self.net_spread,
            "edge_pct": self.edge_pct,
            "is_winner": self.is_winner,
        }


class SpreadCalculator:
    """
    Calculates spread opportunities on resolved markets.

    Account88888's Strategy Pattern:
    - Buys both UP and DOWN tokens at ~$0.32
    - Sells at ~$0.32 (slightly higher)
    - Captures ~$0.0046 spread per token

    Key insight: After resolution, one token is worth $1 (winner)
    and one is worth $0 (loser). But prices don't instantly adjust.
    """

    # Fee structure (Polymarket)
    TAKER_FEE = 0.01  # 1%
    MAKER_FEE = 0.0   # 0%

    # Strategy parameters
    MIN_EDGE = 0.003  # 0.3% minimum spread after fees
    MIN_LIQUIDITY = 10  # Minimum available size

    def __init__(
        self,
        min_edge: float = 0.003,
        min_liquidity: float = 10,
        max_position: float = 50.0,
    ):
        self.min_edge = min_edge
        self.min_liquidity = min_liquidity
        self.max_position = max_position

    def analyze_orderbook(
        self,
        token_id: str,
        outcome: str,
        orderbook: Dict
    ) -> List[TradingOpportunity]:
        """
        Analyze orderbook for trading opportunities.

        Returns list of opportunities (buy and sell).
        """
        opportunities = []

        bids = orderbook.get("bids", [])
        asks = orderbook.get("asks", [])

        if not bids and not asks:
            return opportunities

        # Get best prices
        best_bid = float(bids[0]["price"]) if bids else 0
        best_ask = float(asks[0]["price"]) if asks else 1

        # Get available liquidity
        bid_size = sum(float(b["size"]) for b in bids[:5]) if bids else 0
        ask_size = sum(float(a["size"]) for a in asks[:5]) if asks else 0

        # Determine if this is likely the winner based on price
        # Winner tokens trade near $1, losers near $0
        is_winner = best_bid > 0.5 or (best_ask > 0.5 and not bids)

        # Calculate potential profit scenarios
        # Scenario 1: Buy from asks, sell to bids (market making)
        if asks and bids and best_ask < best_bid:
            # Arbitrage opportunity
            gross_spread = best_bid - best_ask
            fee_cost = best_ask * self.TAKER_FEE + best_bid * self.TAKER_FEE
            net_spread = gross_spread - fee_cost
            edge_pct = net_spread / best_ask if best_ask > 0 else 0

            if edge_pct >= self.min_edge and min(bid_size, ask_size) >= self.min_liquidity:
                opportunities.append(TradingOpportunity(
                    token_id=token_id,
                    outcome=outcome,
                    side="buy",
                    entry_price=best_ask,
                    exit_price=best_bid,
                    available_size=min(bid_size, ask_size),
                    recommended_size=min(min(bid_size, ask_size), self.max_position / best_ask),
                    gross_spread=gross_spread,
                    net_spread=net_spread,
                    edge_pct=edge_pct,
                    is_winner=is_winner,
                ))

        # Scenario 2: Buy winner token at discount, redeem at $1
        if is_winner and asks:
            redemption_value = 1.0
            entry_price = best_ask

            if entry_price < 0.99:  # Discount available
                gross_spread = redemption_value - entry_price
                fee_cost = entry_price * self.TAKER_FEE
                net_spread = gross_spread - fee_cost
                edge_pct = net_spread / entry_price

                if edge_pct >= self.min_edge and ask_size >= self.min_liquidity:
                    opportunities.append(TradingOpportunity(
                        token_id=token_id,
                        outcome=outcome,
                        side="buy",
                        entry_price=entry_price,
                        exit_price=redemption_value,
                        available_size=ask_size,
                        recommended_size=min(ask_size, self.max_position / entry_price),
                        gross_spread=gross_spread,
                        net_spread=net_spread,
                        edge_pct=edge_pct,
                        is_winner=True,
                    ))

        # Scenario 3: Account88888 pattern - buy at mid-range prices
        # They buy both winners and losers at ~$0.32 and capture spread
        if asks and bids:
            mid_price = (best_bid + best_ask) / 2

            if 0.2 < mid_price < 0.8:  # Mid-range price
                # Calculate spread capture potential
                spread = best_bid - best_ask if best_bid > best_ask else 0

                if spread > 0:
                    fee_cost = (best_ask + best_bid) * self.TAKER_FEE
                    net_spread = spread - fee_cost
                    edge_pct = net_spread / best_ask if best_ask > 0 else 0

                    if edge_pct >= self.min_edge / 2:  # Lower threshold for spread capture
                        opportunities.append(TradingOpportunity(
                            token_id=token_id,
                            outcome=outcome,
                            side="buy",
                            entry_price=best_ask,
                            exit_price=best_bid,
                            available_size=min(bid_size, ask_size),
                            recommended_size=min(min(bid_size, ask_size), self.max_position / best_ask),
                            gross_spread=spread,
                            net_spread=net_spread,
                            edge_pct=edge_pct,
                            is_winner=is_winner,
                        ))

        return opportunities

    def find_opportunities(
        self,
        markets: List[Tuple],  # (market, up_book, down_book)
    ) -> List[TradingOpportunity]:
        """
        Find all trading opportunities across markets.

        Returns sorted list by edge (highest first).
        """
        all_opportunities = []

        for market, up_book, down_book in markets:
            # Analyze UP token
            up_opps = self.analyze_orderbook(
                market.token_up,
                "Up",
                up_book
            )
            all_opportunities.extend(up_opps)

            # Analyze DOWN token
            down_opps = self.analyze_orderbook(
                market.token_down,
                "Down",
                down_book
            )
            all_opportunities.extend(down_opps)

        # Sort by edge (highest first)
        all_opportunities.sort(key=lambda x: x.edge_pct, reverse=True)

        return all_opportunities

    def calculate_position_size(
        self,
        opportunity: TradingOpportunity,
        available_capital: float,
        max_risk_pct: float = 0.10
    ) -> float:
        """
        Calculate optimal position size.

        Constraints:
        - Max risk per trade (default 10% of capital)
        - Available liquidity
        - Maximum position limit
        """
        # Cost of position
        cost_per_unit = opportunity.entry_price

        # Max based on capital risk
        max_by_capital = (available_capital * max_risk_pct) / cost_per_unit

        # Max based on liquidity
        max_by_liquidity = opportunity.available_size

        # Max based on position limit
        max_by_limit = self.max_position / cost_per_unit

        # Take minimum of all constraints
        size = min(max_by_capital, max_by_liquidity, max_by_limit)

        # Round to reasonable precision
        return round(size, 2)

    def estimate_profit(
        self,
        opportunity: TradingOpportunity,
        size: float
    ) -> Dict:
        """Estimate profit for a trade."""
        entry_cost = size * opportunity.entry_price
        exit_value = size * opportunity.exit_price

        gross_profit = exit_value - entry_cost
        fees = entry_cost * self.TAKER_FEE + exit_value * self.TAKER_FEE
        net_profit = gross_profit - fees

        return {
            "size": size,
            "entry_cost": entry_cost,
            "exit_value": exit_value,
            "gross_profit": gross_profit,
            "fees": fees,
            "net_profit": net_profit,
            "roi_pct": (net_profit / entry_cost) * 100 if entry_cost > 0 else 0,
        }


def main():
    """Test the spread calculator."""
    from resolution_monitor import ResolutionMonitor

    print("=" * 60)
    print("SPREAD CALCULATOR TEST")
    print("=" * 60)

    # Get tradeable markets
    monitor = ResolutionMonitor()
    monitor.discover_markets(hours_ahead=1, hours_behind=1)
    monitor.check_resolutions()

    tradeable = monitor.get_tradeable_markets()
    print(f"\nFound {len(tradeable)} tradeable markets")

    if not tradeable:
        print("No tradeable markets found")
        return

    # Calculate opportunities
    calculator = SpreadCalculator(
        min_edge=0.002,  # 0.2%
        min_liquidity=5,
        max_position=50
    )

    opportunities = calculator.find_opportunities(tradeable)
    print(f"Found {len(opportunities)} opportunities")

    for opp in opportunities[:10]:
        print(f"\n{opp.outcome} token:")
        print(f"  Entry: ${opp.entry_price:.4f}")
        print(f"  Exit: ${opp.exit_price:.4f}")
        print(f"  Net spread: ${opp.net_spread:.4f}")
        print(f"  Edge: {opp.edge_pct*100:.2f}%")
        print(f"  Available: {opp.available_size:.1f}")
        print(f"  Recommended: {opp.recommended_size:.1f}")
        print(f"  Winner: {opp.is_winner}")

        # Estimate profit
        profit = calculator.estimate_profit(opp, opp.recommended_size)
        print(f"  Est profit: ${profit['net_profit']:.2f} ({profit['roi_pct']:.2f}%)")


if __name__ == "__main__":
    main()
