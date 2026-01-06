"""Mine patterns from features to discover profitable strategies."""
from typing import List, Dict, Optional, Tuple
import time

from ..storage import db
from ..strategy import StrategySpec, Condition, Action, StrategyType
from ..strategy import StrategyExecutor


class PatternMiner:
    """
    Discovers profitable patterns in market data.
    
    Uses feature data to find conditions that correlate with profitable moves.
    """
    
    def __init__(self, min_sharpe: float = 1.0, min_trades: int = 10):
        self.min_sharpe = min_sharpe
        self.min_trades = min_trades
    
    def mine_strategies(
        self,
        start_ts: int,
        end_ts: int,
        feature_thresholds: Optional[List[Dict]] = None
    ) -> List[StrategySpec]:
        """
        Mine strategies from historical data.
        
        Args:
            start_ts: Start of training period
            end_ts: End of training period
            feature_thresholds: Optional list of feature ranges to test
        
        Returns:
            List of discovered StrategySpec objects
        """
        print(f"\n🔍 Mining strategies from {start_ts} to {end_ts}...")
        
        if not feature_thresholds:
            feature_thresholds = self._generate_default_thresholds()
        
        strategies = []
        
        # Test different combinations
        for threshold_set in feature_thresholds:
            strategy = self._test_threshold_set(threshold_set, start_ts, end_ts)
            if strategy:
                strategies.append(strategy)
        
        # Rank by performance
        strategies.sort(key=lambda s: s.metrics.get("sharpe", 0), reverse=True)
        
        print(f"✓ Discovered {len(strategies)} viable strategies")
        return strategies
    
    def _generate_default_thresholds(self) -> List[Dict]:
        """Generate default threshold combinations to test."""
        thresholds = []
        
        # Strategy 1: Wide spread entry (liquidity taker)
        thresholds.append({
            "name": "wide_spread_entry",
            "entry": [
                {"feature": "spread_up", "operator": "gt", "value": 0.05},
                {"feature": "t_since_start", "operator": "gt", "value": 300},
            ],
            "exit": [
                {"feature": "spread_down", "operator": "gt", "value": 0.02},
            ],
        })
        
        # Strategy 2: Mean reversion on CL delta
        thresholds.append({
            "name": "cl_mean_reversion",
            "entry": [
                {"feature": "cl_delta_bps", "operator": "gt", "value": 50},
            ],
            "exit": [
                {"feature": "cl_delta_bps", "operator": "lt", "value": 10},
            ],
        })
        
        # Strategy 3: Momentum following
        thresholds.append({
            "name": "momentum_follow",
            "entry": [
                {"feature": "mid_up", "operator": "gt", "value": 0.03},
                {"feature": "spread_down", "operator": "gt", "value": 0.01},
            ],
            "exit": [
                {"feature": "mid_down", "operator": "gt", "value": 0.02},
            ],
        })
        
        # Strategy 4: Early market entry
        thresholds.append({
            "name": "early_entry",
            "entry": [
                {"feature": "t_since_start", "operator": "lt", "value": 600},
                {"feature": "spread_up", "operator": "lt", "value": 0.03},
            ],
            "exit": [
                {"feature": "t_since_start", "operator": "gt", "value": 3600},
            ],
        })
        
        return thresholds
    
    def _test_threshold_set(
        self,
        threshold_set: Dict,
        start_ts: int,
        end_ts: int
    ) -> Optional[StrategySpec]:
        """Test a specific threshold combination."""
        # Create strategy spec
        strategy = StrategySpec(
            name=threshold_set["name"],
            version="1.0",
            type=StrategyType.ALPHA_MINED,
            created_at=int(time.time()),
            source={"miner": "PatternMiner", "method": "threshold_scan"},
            entry_conditions=[Condition(**c) for c in threshold_set["entry"]],
            exit_conditions=[Condition(**c) for c in threshold_set["exit"]],
            entry_action=Action(type="buy", size_pct=0.1, max_slippage_bps=100),
            exit_action=Action(type="sell"),
            backtest_period={"start_ts": start_ts, "end_ts": end_ts},
        )
        
        # Backtest
        executor = StrategyExecutor(strategy)
        results = executor.backtest(start_ts, end_ts)
        
        # Check if meets minimum criteria
        if results["num_trades"] < self.min_trades:
            return None
        
        # Calculate metrics
        total_pnl = results["total_pnl"]
        num_trades = results["num_trades"]
        
        if num_trades == 0:
            return None
        
        avg_pnl = total_pnl / num_trades
        
        # Simple Sharpe approximation
        pnls = [t.get("pnl", 0) for t in results["trades"] if "pnl" in t]
        if not pnls:
            return None
        
        pnl_std = self._std(pnls)
        sharpe = (avg_pnl / pnl_std) if pnl_std > 0 else 0
        
        if sharpe < self.min_sharpe:
            return None
        
        # Update strategy with metrics
        strategy.metrics = {
            "total_pnl": total_pnl,
            "num_trades": num_trades,
            "avg_pnl": avg_pnl,
            "sharpe": sharpe,
        }
        
        print(f"  ✓ {strategy.name}: {num_trades} trades, Sharpe={sharpe:.2f}")
        
        return strategy
    
    def _std(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5
    
    def optimize_strategy(self, strategy: StrategySpec, start_ts: int, end_ts: int) -> StrategySpec:
        """
        Optimize an existing strategy by tuning thresholds.
        
        Uses grid search to find better threshold values.
        """
        # Placeholder for future implementation
        # Would do grid search over threshold values
        return strategy
