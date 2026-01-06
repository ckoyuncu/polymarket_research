"""Extract deterministic logic from wallet behavior."""
import time
from typing import Dict, List, Optional

from .trade_analyzer import TradeAnalyzer
from ..strategy import StrategySpec, Condition, Action, StrategyType


class LogicExtractor:
    """
    Converts wallet trade patterns into executable strategy specs.
    
    Takes analyzed trade patterns and creates deterministic rules.
    """
    
    def __init__(self, analyzer: TradeAnalyzer):
        self.analyzer = analyzer
    
    def extract_strategy(
        self,
        name: Optional[str] = None,
        confidence_threshold: float = 0.7
    ) -> StrategySpec:
        """
        Extract a deterministic strategy from wallet behavior.
        
        Args:
            name: Optional name for the strategy
            confidence_threshold: Minimum confidence to include a condition
        
        Returns:
            StrategySpec that mimics the wallet's logic
        """
        if not name:
            name = f"cloned_{self.analyzer.wallet_address[:8]}"
        
        # Analyze patterns
        entry_stats = self.analyzer.analyze_entry_patterns()
        exit_stats = self.analyzer.analyze_exit_patterns()
        performance = self.analyzer.calculate_performance()
        
        print(f"\n🔬 Extracting strategy from {self.analyzer.wallet_address}")
        print(f"   Performance: {performance['total_trades']} trades, "
              f"Win rate: {performance['win_rate']:.1%}")
        
        # Generate entry conditions from entry patterns
        entry_conditions = self._generate_conditions(entry_stats, is_entry=True)
        
        # Generate exit conditions from exit patterns
        exit_conditions = self._generate_conditions(exit_stats, is_entry=False)
        
        # Create strategy spec
        strategy = StrategySpec(
            name=name,
            version="1.0",
            type=StrategyType.WALLET_CLONED,
            created_at=int(time.time()),
            source={
                "wallet": self.analyzer.wallet_address,
                "trades_analyzed": len(self.analyzer.trades),
                "positions_analyzed": len(self.analyzer.positions),
            },
            entry_conditions=entry_conditions,
            exit_conditions=exit_conditions,
            entry_action=Action(
                type="buy",
                size_pct=0.1,  # Conservative default
                max_slippage_bps=100,
            ),
            exit_action=Action(type="sell"),
            metrics=performance,
        )
        
        print(f"✓ Extracted strategy with {len(entry_conditions)} entry "
              f"and {len(exit_conditions)} exit conditions")
        
        return strategy
    
    def _generate_conditions(
        self,
        feature_stats: Dict,
        is_entry: bool,
        significance_threshold: float = 0.2
    ) -> List[Condition]:
        """
        Generate conditions from feature statistics.
        
        Uses feature ranges to create thresholds.
        """
        conditions = []
        
        # Features that are interesting for conditions
        interesting_features = [
            "t_since_start",
            "cl_delta_bps",
            "spread_up",
            "spread_down",
            "mid_up",
            "mid_down",
        ]
        
        for feature in interesting_features:
            if feature not in feature_stats:
                continue
            
            stats = feature_stats[feature]
            
            # Skip if not enough data
            if stats["count"] < 5:
                continue
            
            # Calculate if feature shows meaningful variation
            feature_range = stats["max"] - stats["min"]
            if feature_range < significance_threshold:
                continue
            
            # Create condition based on mean and range
            mean = stats["mean"]
            
            # For entry conditions, use different logic than exit
            if is_entry:
                # Entry: look for values above mean (opportunity)
                if mean > 0:
                    conditions.append(Condition(
                        feature=feature,
                        operator="gt",
                        value=mean * 0.8,  # Slightly below mean
                    ))
            else:
                # Exit: look for values that indicate position should close
                if mean > 0:
                    conditions.append(Condition(
                        feature=feature,
                        operator="gt",
                        value=mean * 1.2,  # Above mean
                    ))
        
        # Always include at least one condition
        if not conditions and feature_stats:
            # Use the first available feature
            first_feature = list(feature_stats.keys())[0]
            stats = feature_stats[first_feature]
            conditions.append(Condition(
                feature=first_feature,
                operator="gt",
                value=stats["mean"],
            ))
        
        return conditions
    
    def refine_strategy(
        self,
        strategy: StrategySpec,
        validation_start: int,
        validation_end: int
    ) -> StrategySpec:
        """
        Refine strategy by testing on validation period.
        
        Adjusts thresholds to improve performance.
        """
        from ..strategy import StrategyExecutor
        
        # Test on validation period
        executor = StrategyExecutor(strategy)
        results = executor.backtest(validation_start, validation_end)
        
        # Update metrics
        strategy.metrics.update({
            "validation_pnl": results["total_pnl"],
            "validation_trades": results["num_trades"],
        })
        
        print(f"✓ Validation: {results['num_trades']} trades, "
              f"PnL: {results['total_pnl']:.2f}")
        
        return strategy
