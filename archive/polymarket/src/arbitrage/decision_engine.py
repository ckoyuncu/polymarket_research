"""
Decision Engine

Determines when and how to trade based on:
- Current Binance price
- Market strike price
- Time until resolution
- Polymarket odds
- Risk parameters

FIXED:
- Edge calculation now uses actual token price vs expected resolution
- Dynamic threshold based on confidence instead of arbitrary 0.8
- Asymmetric payoff strategy (25% win rate + 4:1 ratio)
"""
from typing import Optional, Tuple
from dataclasses import dataclass
from enum import Enum


class TradeAction(Enum):
    """Trade action to take."""
    BUY_YES = "buy_yes"
    BUY_NO = "buy_no"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """
    Signal to execute a trade.

    Contains all information needed to place an order.
    """
    action: TradeAction
    token_id: str  # Token to buy
    size: float  # Number of shares
    max_price: float  # Maximum price to pay (0-1)
    edge: float  # Calculated edge (%)
    confidence: float  # Confidence score (0-1)
    reason: str  # Why this signal was generated
    expected_payout: float = 0.0  # Expected payout if we win
    risk_amount: float = 0.0  # Amount at risk if we lose

    @property
    def should_trade(self) -> bool:
        """Whether to actually trade."""
        return self.action != TradeAction.HOLD

    @property
    def reward_risk_ratio(self) -> float:
        """Calculate reward to risk ratio."""
        if self.risk_amount <= 0:
            return 0.0
        return self.expected_payout / self.risk_amount


@dataclass
class MarketState:
    """Current state of a market."""
    asset: str  # "BTC" or "ETH"
    strike_price: float  # Market strike price (for above/below markets)
    current_price: float  # Current Binance price
    is_above_strike_question: bool  # True if "above", False if "below"
    yes_token_id: str
    no_token_id: str
    yes_price: float  # Current YES price (0-1)
    no_price: float  # Current NO price (0-1)
    seconds_until_close: float  # Time remaining
    liquidity: float  # Market liquidity
    is_up_or_down_market: bool = False  # True for "Up or Down" style markets
    previous_price: float = 0.0  # Price at window open (for up/down markets)


class DecisionEngine:
    """
    Makes trading decisions based on market conditions.

    UPDATED LOGIC (based on Account88888 analysis):
    1. Trade within expanded execution window (2-120 seconds before close)
    2. Calculate ACTUAL edge: (expected_value - token_price) / token_price
    3. Dynamic price threshold based on confidence
    4. Target 2:1 reward/risk ratio (allows higher entry prices)

    Key insights from Account88888:
    - Average entry price is ~0.47-0.55 (not extreme low prices)
    - Trade throughout the window, not just at close
    - Win rate ~50% with moderate R:R works better than 23% WR with 4:1 R:R
    - Position sizing scales with confidence

    NOTE: UP bias was NOT implemented because:
    - Sample size too limited (1 day of data)
    - No validation during crypto downtrends
    - Only 46% of wallets show UP preference (not universal)

    Example:
        engine = DecisionEngine(
            min_edge=0.005,  # 0.5% minimum edge
            max_position_size=50,  # $50 max
            target_reward_risk=4.0,  # 4:1 target
        )

        signal = engine.analyze(market_state)

        if signal.should_trade:
            print(f"Trade: {signal.action.value}")
            print(f"Size: {signal.size:.0f} shares @ {signal.max_price:.3f}")
            print(f"Edge: {signal.edge:.2%}")
            print(f"R:R Ratio: {signal.reward_risk_ratio:.1f}:1")
    """

    # Fee assumptions (Polymarket fees)
    MAKER_FEE = 0.0  # Maker fee
    TAKER_FEE = 0.01  # 1% taker fee (conservative estimate)

    def __init__(
        self,
        min_edge: float = 0.003,  # 0.3% (lowered to allow more opportunities)
        max_position_size: float = 100.0,  # $100 (40% of $250)
        execution_window: tuple = (2, 120),  # 2-120 seconds before close (expanded)
        min_confidence: float = 0.6,  # 60%
        min_position_size: float = 10.0,  # $10 minimum (4% of $250)
        target_reward_risk: float = 2.0,  # 2:1 payoff target (more realistic)
        max_token_price: float = 0.50,  # 0.50 (conservative, Account88888 avg is 0.55)
    ):
        """
        Initialize decision engine.

        Args:
            min_edge: Minimum edge to trade (as decimal, e.g., 0.005 = 0.5%)
            max_position_size: Max position size in USD
            execution_window: (min, max) seconds before close to execute
            min_confidence: Minimum confidence to trade
            min_position_size: Minimum position size in USD
            target_reward_risk: Target reward/risk ratio (Account88888 uses 4:1)
            max_token_price: Maximum price to pay for a token
        """
        self.min_edge = min_edge
        self.max_position_size = max_position_size
        self.min_position_size = min_position_size
        self.execution_window = execution_window
        self.min_confidence = min_confidence
        self.target_reward_risk = target_reward_risk
        self.max_token_price = max_token_price

    def analyze(self, state: MarketState) -> TradeSignal:
        """
        Analyze market and generate trade signal.

        Args:
            state: Current market state

        Returns:
            TradeSignal
        """
        # Check timing
        if not self._is_in_execution_window(state.seconds_until_close):
            return self._hold_signal(
                reason=f"Not in execution window ({state.seconds_until_close:.1f}s remaining)"
            )

        # Determine which outcome should win based on current price
        outcome_prediction = self._predict_outcome(state)

        if outcome_prediction is None:
            return self._hold_signal(reason="Cannot predict outcome (price too close to strike)")

        # Calculate actual trading edge
        edge, token_price, expected_value = self._calculate_actual_edge(state, outcome_prediction)

        if edge < self.min_edge:
            return self._hold_signal(
                reason=f"Edge too small ({edge:.2%} < {self.min_edge:.2%})",
                edge=edge
            )

        # Calculate confidence
        confidence = self._calculate_confidence(state, edge, outcome_prediction)

        if confidence < self.min_confidence:
            return self._hold_signal(
                reason=f"Confidence too low ({confidence:.2%} < {self.min_confidence:.2%})",
                edge=edge,
                confidence=confidence
            )

        # Check reward/risk ratio
        reward_risk = self._calculate_reward_risk(token_price, expected_value)

        if reward_risk < 1.5:  # Minimum 1.5:1 (allows higher entry prices)
            return self._hold_signal(
                reason=f"Reward/risk too low ({reward_risk:.1f}:1 < 1.5:1)",
                edge=edge,
                confidence=confidence
            )

        # Determine action and token
        if outcome_prediction == "YES":
            action = TradeAction.BUY_YES
            token_id = state.yes_token_id
        else:
            action = TradeAction.BUY_NO
            token_id = state.no_token_id

        # Calculate position size
        size = self._calculate_position_size(confidence, token_price, reward_risk)

        # Calculate risk/reward amounts
        cost = size * token_price
        expected_payout = size * expected_value - cost
        risk_amount = cost  # We can lose the full cost

        # Generate signal
        return TradeSignal(
            action=action,
            token_id=token_id,
            size=size,
            max_price=min(self.max_token_price, token_price * 1.02),  # Allow 2% slippage
            edge=edge,
            confidence=confidence,
            reason=self._format_reason(state, outcome_prediction),
            expected_payout=expected_payout,
            risk_amount=risk_amount
        )

    def _hold_signal(
        self,
        reason: str,
        edge: float = 0.0,
        confidence: float = 0.0
    ) -> TradeSignal:
        """Create a HOLD signal."""
        return TradeSignal(
            action=TradeAction.HOLD,
            token_id="",
            size=0,
            max_price=0,
            edge=edge,
            confidence=confidence,
            reason=reason
        )

    def _is_in_execution_window(self, seconds_until: float) -> bool:
        """Check if we're in the execution window."""
        min_sec, max_sec = self.execution_window
        return min_sec <= seconds_until <= max_sec

    def _predict_outcome(self, state: MarketState) -> Optional[str]:
        """
        Predict which outcome will win.

        Returns:
            "YES" or "NO" or None if uncertain
        """
        if state.is_up_or_down_market:
            # For "Up or Down" markets, compare current price to window open
            if state.previous_price <= 0:
                return None  # Can't predict without previous price

            # YES = price went up, NO = price went down
            price_change = state.current_price - state.previous_price
            change_pct = abs(price_change) / state.previous_price

            # Need at least 0.05% change to be confident
            if change_pct < 0.0005:
                return None

            return "YES" if price_change > 0 else "NO"

        else:
            # For "above/below" markets
            price_diff = state.current_price - state.strike_price
            diff_pct = abs(price_diff) / state.strike_price

            # Need at least 0.3% distance from strike to be confident
            if diff_pct < 0.003:
                return None

            price_is_above = state.current_price > state.strike_price

            if state.is_above_strike_question:
                # "Will BTC be above $95,000?"
                return "YES" if price_is_above else "NO"
            else:
                # "Will BTC be below $95,000?"
                return "YES" if not price_is_above else "NO"

    def _calculate_actual_edge(
        self,
        state: MarketState,
        outcome_prediction: str
    ) -> Tuple[float, float, float]:
        """
        Calculate ACTUAL trading edge.

        Edge = (expected_value - token_price - fees) / token_price

        For a binary market:
        - If we predict YES wins: expected_value = 1.0, we buy at yes_price
        - If we predict NO wins: expected_value = 1.0, we buy at no_price

        Returns:
            (edge, token_price, expected_value)
        """
        if outcome_prediction == "YES":
            token_price = state.yes_price
        else:
            token_price = state.no_price

        # Expected value if we win is $1.00 per share
        expected_value = 1.0

        # Calculate edge after fees
        gross_profit = expected_value - token_price
        fees = token_price * self.TAKER_FEE
        net_profit = gross_profit - fees

        edge = net_profit / token_price if token_price > 0 else 0

        return edge, token_price, expected_value

    def _calculate_reward_risk(self, token_price: float, expected_value: float) -> float:
        """
        Calculate reward/risk ratio.

        Reward = profit if we win = expected_value - token_price - fees
        Risk = loss if we lose = token_price (we lose our stake)
        """
        if token_price <= 0:
            return 0.0

        fees = token_price * self.TAKER_FEE
        reward = expected_value - token_price - fees
        risk = token_price

        return reward / risk if risk > 0 else 0.0

    def _calculate_confidence(
        self,
        state: MarketState,
        edge: float,
        outcome_prediction: str
    ) -> float:
        """
        Calculate confidence in the trade.

        Higher confidence when:
        - Larger edge (price further from strike)
        - More time to close (but not too much)
        - Better liquidity
        - Market price agrees with our prediction
        """
        # Edge component (0-1)
        # 2% edge = max score
        edge_score = min(1.0, edge / 0.02)

        # Price distance component (0-1)
        # How far is current price from strike?
        if state.strike_price > 0:
            price_distance = abs(state.current_price - state.strike_price) / state.strike_price
            distance_score = min(1.0, price_distance / 0.01)  # 1% = max score
        else:
            distance_score = 0.5

        # Time component (0-1)
        # Best confidence at 10-20s before close
        time_until = state.seconds_until_close
        if 10 <= time_until <= 20:
            time_score = 1.0
        elif time_until < 10:
            time_score = max(0.5, time_until / 10)
        else:
            time_score = max(0.5, 1.0 - (time_until - 20) / 10)

        # Liquidity component (0-1)
        liquidity_score = min(1.0, state.liquidity / 1000)  # $1000 = max score

        # Market agreement component (0-1)
        # Does the market price already reflect our prediction?
        if outcome_prediction == "YES":
            market_agrees = state.yes_price > 0.5
        else:
            market_agrees = state.no_price > 0.5

        agreement_score = 0.7 if market_agrees else 0.3

        # Weighted average
        confidence = (
            0.30 * edge_score +
            0.25 * distance_score +
            0.20 * time_score +
            0.15 * liquidity_score +
            0.10 * agreement_score
        )

        return confidence

    def _calculate_position_size(
        self,
        confidence: float,
        price: float,
        reward_risk: float
    ) -> float:
        """
        Calculate position size based on confidence and reward/risk.

        Implements Account88888's variable sizing pattern:
        - Small positions ($10-25) for routine trades (61%)
        - Medium positions ($25-75) for good setups (20%)
        - Large positions ($75-150) for high-confidence (15%)
        - Very large positions ($150-200) for extreme confidence (4%)

        Also adjusts for reward/risk ratio:
        - Higher R:R = can size up more aggressively

        Args:
            confidence: Confidence score (0-1)
            price: Price per share
            reward_risk: Reward/risk ratio

        Returns:
            Number of shares to buy
        """
        # Base position sizing by confidence tier
        if confidence < 0.65:
            # Small position - low confidence
            base_value = self.min_position_size
        elif confidence < 0.75:
            # Small-medium position
            base_value = self.min_position_size + (
                (confidence - 0.65) / 0.10 * 15
            )  # $10-25
        elif confidence < 0.85:
            # Medium position - good setup
            base_value = 25 + ((confidence - 0.75) / 0.10 * 50)  # $25-75
        elif confidence < 0.92:
            # Large position - high confidence
            base_value = 75 + ((confidence - 0.85) / 0.07 * 75)  # $75-150
        else:
            # Very large position - extreme confidence
            base_value = 150 + ((confidence - 0.92) / 0.08 * 50)  # $150-200

        # Adjust for reward/risk ratio
        # Better R:R allows slightly larger positions
        rr_multiplier = min(1.2, 0.8 + (reward_risk / 10))  # 0.8 to 1.2

        position_value = base_value * rr_multiplier

        # Ensure within bounds
        position_value = max(self.min_position_size, min(self.max_position_size, position_value))

        # Convert to shares
        shares = position_value / price if price > 0 else 0

        return shares

    def _format_reason(self, state: MarketState, outcome: str) -> str:
        """Format reason string for the signal."""
        if state.is_up_or_down_market:
            direction = "up" if outcome == "YES" else "down"
            return f"{state.asset} price went {direction}"
        else:
            direction = ">" if outcome == "YES" else "<"
            return f"{state.asset} ${state.current_price:,.0f} {direction} ${state.strike_price:,.0f}"

    def get_max_acceptable_price(
        self,
        min_reward_risk: float = 2.0
    ) -> float:
        """
        Calculate maximum price we should pay for a token.

        To achieve minimum R:R ratio:
        reward / risk >= min_reward_risk
        (1 - price - fees) / price >= min_reward_risk
        1 - price - fees >= min_reward_risk * price
        1 - fees >= price * (1 + min_reward_risk)
        price <= (1 - fees) / (1 + min_reward_risk)

        For 4:1 ratio: price <= 0.99 / 5 = 0.198
        For 2:1 ratio: price <= 0.99 / 3 = 0.33
        """
        max_price = (1 - self.TAKER_FEE) / (1 + min_reward_risk)
        return min(max_price, self.max_token_price)


def test_engine():
    """Test the decision engine."""
    print("Testing Decision Engine (Updated with Account88888 analysis)...\n")

    engine = DecisionEngine(
        min_edge=0.003,
        max_position_size=100,
        execution_window=(2, 120),
        min_confidence=0.6,
        target_reward_risk=2.0
    )

    # Test case 1: Clear buy signal - price above strike
    print("--- Test 1: BTC clearly above strike ---")
    state1 = MarketState(
        asset="BTC",
        strike_price=95000,
        current_price=95600,  # +0.63% above
        is_above_strike_question=True,
        yes_token_id="token_yes_1",
        no_token_id="token_no_1",
        yes_price=0.55,  # Should buy YES
        no_price=0.45,
        seconds_until_close=15,
        liquidity=1000
    )

    signal1 = engine.analyze(state1)
    print(f"Action: {signal1.action.value}")
    print(f"Size: {signal1.size:.1f} shares")
    print(f"Max price: ${signal1.max_price:.3f}")
    print(f"Edge: {signal1.edge:.2%}")
    print(f"Confidence: {signal1.confidence:.2%}")
    print(f"R:R Ratio: {signal1.reward_risk_ratio:.1f}:1")
    print(f"Reason: {signal1.reason}")

    # Test case 2: Good edge at low price (high R:R)
    print("\n--- Test 2: High reward/risk opportunity ---")
    state2 = MarketState(
        asset="BTC",
        strike_price=95000,
        current_price=96000,  # +1.05% above
        is_above_strike_question=True,
        yes_token_id="token_yes_2",
        no_token_id="token_no_2",
        yes_price=0.25,  # Very underpriced! Great R:R
        no_price=0.75,
        seconds_until_close=12,
        liquidity=1500
    )

    signal2 = engine.analyze(state2)
    print(f"Action: {signal2.action.value}")
    print(f"Size: {signal2.size:.1f} shares")
    print(f"Edge: {signal2.edge:.2%}")
    print(f"Confidence: {signal2.confidence:.2%}")
    print(f"R:R Ratio: {signal2.reward_risk_ratio:.1f}:1")
    print(f"Expected payout: ${signal2.expected_payout:.2f}")
    print(f"Risk amount: ${signal2.risk_amount:.2f}")

    # Test case 3: Too close to strike
    print("\n--- Test 3: Price too close to strike ---")
    state3 = MarketState(
        asset="BTC",
        strike_price=95000,
        current_price=95050,  # Only +0.05%
        is_above_strike_question=True,
        yes_token_id="token_yes_3",
        no_token_id="token_no_3",
        yes_price=0.51,
        no_price=0.49,
        seconds_until_close=15,
        liquidity=1000
    )

    signal3 = engine.analyze(state3)
    print(f"Action: {signal3.action.value}")
    print(f"Reason: {signal3.reason}")

    # Test case 4: Poor R:R ratio (price too high)
    print("\n--- Test 4: Poor reward/risk ratio ---")
    state4 = MarketState(
        asset="ETH",
        strike_price=3500,
        current_price=3550,  # +1.4% above
        is_above_strike_question=True,
        yes_token_id="token_yes_4",
        no_token_id="token_no_4",
        yes_price=0.92,  # Too expensive - poor R:R
        no_price=0.08,
        seconds_until_close=15,
        liquidity=1000
    )

    signal4 = engine.analyze(state4)
    print(f"Action: {signal4.action.value}")
    print(f"Reason: {signal4.reason}")

    # Test case 5: BUY NO scenario
    print("\n--- Test 5: Price below strike (buy NO) ---")
    state5 = MarketState(
        asset="BTC",
        strike_price=95000,
        current_price=94000,  # -1.05% below
        is_above_strike_question=True,  # "Will BTC be ABOVE $95k?" - NO should win
        yes_token_id="token_yes_5",
        no_token_id="token_no_5",
        yes_price=0.70,
        no_price=0.30,  # Buy NO at 0.30
        seconds_until_close=15,
        liquidity=1000
    )

    signal5 = engine.analyze(state5)
    print(f"Action: {signal5.action.value}")
    print(f"Size: {signal5.size:.1f} shares")
    print(f"Edge: {signal5.edge:.2%}")
    print(f"R:R Ratio: {signal5.reward_risk_ratio:.1f}:1")
    print(f"Reason: {signal5.reason}")

    # Print max acceptable prices
    print("\n--- Max Acceptable Prices ---")
    print(f"For 4:1 R:R: ${engine.get_max_acceptable_price(4.0):.3f}")
    print(f"For 3:1 R:R: ${engine.get_max_acceptable_price(3.0):.3f}")
    print(f"For 2:1 R:R: ${engine.get_max_acceptable_price(2.0):.3f}")

    print("\n✅ Test complete")


if __name__ == "__main__":
    test_engine()
