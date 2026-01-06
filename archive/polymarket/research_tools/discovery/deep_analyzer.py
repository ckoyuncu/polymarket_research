"""
Deep Wallet Analysis

Go beyond basic stats to truly understand what a wallet is doing.
This is the "Deconstruct Logic" step before copying.
"""
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import json

from ..storage import db
from ..api import DataAPIClient, GammaClient


@dataclass
class TradingPattern:
    """A detected pattern in the wallet's behavior."""
    name: str
    description: str
    confidence: float  # 0-100
    
    # When does this pattern occur?
    time_conditions: Dict[str, any] = field(default_factory=dict)
    
    # What market conditions?
    market_conditions: Dict[str, any] = field(default_factory=dict)
    
    # What action is taken?
    action: str = ""
    
    # Supporting evidence
    example_trades: List[Dict] = field(default_factory=list)
    occurrence_count: int = 0


@dataclass 
class WalletAnalysis:
    """Complete analysis of a wallet's trading behavior."""
    wallet_address: str
    analysis_period: Tuple[int, int]  # start_ts, end_ts
    
    # Basic stats
    total_trades: int = 0
    total_pnl: float = 0
    win_rate: float = 0
    
    # Trading style
    primary_markets: List[str] = field(default_factory=list)
    avg_position_size: float = 0
    avg_hold_time_minutes: float = 0
    trades_per_day: float = 0
    
    # Timing analysis
    active_hours: List[int] = field(default_factory=list)  # UTC hours
    entry_timing_patterns: Dict = field(default_factory=dict)
    
    # Detected patterns
    patterns: List[TradingPattern] = field(default_factory=list)
    
    # Understanding metrics
    behavior_predictability: float = 0  # Can we predict their next trade?
    rule_coverage: float = 0  # % of trades explained by detected rules
    
    # Copyability
    estimated_min_capital: float = 0
    complexity_score: float = 0  # Higher = harder to copy


class DeepAnalyzer:
    """
    Deep analysis of wallet trading behavior.
    
    Goal: Truly understand what they're doing before attempting to copy.
    """
    
    def __init__(self, wallet_address: str, username: str = None):
        self.wallet_address = wallet_address
        self.username = username or wallet_address[:20] if wallet_address else "Unknown"
        self.data_api = DataAPIClient()
        self.gamma = GammaClient()
        
        self.trades: List[Dict] = []
        self.positions: List[Dict] = []
        self.market_cache: Dict[str, Dict] = {}
        
        self.analysis: Optional[WalletAnalysis] = None
    
    def load_data(self, max_trades: int = 1000) -> int:
        """Load all available data for this wallet."""
        print(f"\n📥 Loading data for {self.wallet_address[:20]}...")
        
        # Fetch trades
        self.trades = self.data_api.get_all_trades(
            user=self.wallet_address,
            max_pages=max_trades // 100
        )
        
        print(f"   Loaded {len(self.trades)} trades")
        
        # Normalize and store
        for trade in self.trades:
            normalized = self.data_api.normalize_trade(trade)
            self._store_trade(normalized)
        
        return len(self.trades)
    
    def _store_trade(self, trade: Dict):
        """Store trade in database."""
        query = """
            INSERT OR IGNORE INTO wallet_trades 
            (wallet, ts, condition_id, token_id, side, price, size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        db.execute(query, (
            self.wallet_address,
            trade["ts"],
            trade["condition_id"],
            trade["token_id"],
            trade["side"],
            trade["price"],
            trade["size"],
        ))
    
    def analyze(self) -> WalletAnalysis:
        """Run comprehensive analysis."""
        print(f"\n🔬 Analyzing {self.wallet_address[:20]}...")
        
        if not self.trades:
            self.load_data()
        
        # Get time range
        timestamps = [t.get("ts", t.get("timestamp", 0)) for t in self.trades]
        if isinstance(timestamps[0], str):
            timestamps = [int(t) if t.isdigit() else 0 for t in timestamps]
        
        start_ts = min(timestamps) if timestamps else 0
        end_ts = max(timestamps) if timestamps else 0
        
        self.analysis = WalletAnalysis(
            wallet_address=self.wallet_address,
            analysis_period=(start_ts, end_ts)
        )
        
        # Run analysis steps
        self._analyze_basic_stats()
        self._analyze_market_focus()
        self._analyze_timing()
        self._analyze_position_sizing()
        self._detect_patterns()
        self._calculate_understanding_metrics()
        
        return self.analysis
    
    def _analyze_basic_stats(self):
        """Calculate basic trading statistics."""
        if not self.trades:
            return
        
        self.analysis.total_trades = len(self.trades)
        
        # Approximate PnL (would need more data for exact)
        buys = [t for t in self.trades if t.get("side", "").lower() == "buy"]
        sells = [t for t in self.trades if t.get("side", "").lower() == "sell"]
        
        # Win rate approximation
        profitable_trades = 0
        for trade in self.trades:
            # This is a simplification - real calculation needs position matching
            price = float(trade.get("price", 0.5))
            if trade.get("side", "").lower() == "buy" and price < 0.5:
                profitable_trades += 1
            elif trade.get("side", "").lower() == "sell" and price > 0.5:
                profitable_trades += 1
        
        self.analysis.win_rate = profitable_trades / len(self.trades) if self.trades else 0
        
        # Trades per day
        if self.analysis.analysis_period[1] > self.analysis.analysis_period[0]:
            days = (self.analysis.analysis_period[1] - self.analysis.analysis_period[0]) / 86400000
            self.analysis.trades_per_day = len(self.trades) / max(1, days)
        
        print(f"   Total trades: {self.analysis.total_trades}")
        print(f"   Trades/day: {self.analysis.trades_per_day:.1f}")
    
    def _analyze_market_focus(self):
        """Analyze which markets the wallet trades."""
        market_counts = defaultdict(int)
        
        for trade in self.trades:
            market_id = trade.get("market") or trade.get("condition_id") or trade.get("conditionId")
            if market_id:
                market_counts[market_id] += 1
        
        # Sort by frequency
        sorted_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)
        self.analysis.primary_markets = [m[0] for m in sorted_markets[:10]]
        
        # Categorize market types
        market_types = defaultdict(int)
        for market_id, count in sorted_markets[:20]:
            try:
                # Try to get market info
                market_info = self.gamma.get_market(market_id)
                if market_info:
                    question = market_info.get("question", "").lower()
                    if "btc" in question or "bitcoin" in question or "eth" in question:
                        market_types["crypto_15m"] += count
                    elif "president" in question or "election" in question:
                        market_types["politics"] += count
                    else:
                        market_types["other"] += count
            except Exception:
                market_types["unknown"] += count
        
        print(f"   Primary markets: {len(self.analysis.primary_markets)}")
    
    def _analyze_timing(self):
        """Analyze when the wallet trades."""
        from datetime import datetime
        
        hour_counts = defaultdict(int)
        
        for trade in self.trades:
            ts = trade.get("ts") or trade.get("timestamp")
            if ts:
                if isinstance(ts, str):
                    ts = int(ts)
                # Convert to hour (assuming ms)
                try:
                    dt = datetime.utcfromtimestamp(ts / 1000)
                    hour_counts[dt.hour] += 1
                except Exception:
                    pass
        
        # Find most active hours
        sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
        self.analysis.active_hours = [h[0] for h in sorted_hours[:6]]
        
        print(f"   Most active hours (UTC): {self.analysis.active_hours[:3]}")
    
    def _analyze_position_sizing(self):
        """Analyze position sizing patterns."""
        sizes = []
        
        for trade in self.trades:
            size = trade.get("size") or trade.get("amount")
            if size:
                sizes.append(float(size))
        
        if sizes:
            self.analysis.avg_position_size = sum(sizes) / len(sizes)
            
            # Estimate minimum capital needed
            max_size = max(sizes)
            self.analysis.estimated_min_capital = max_size * 2  # 2x max trade for safety
        
        print(f"   Avg position size: ${self.analysis.avg_position_size:.2f}")
        print(f"   Est. min capital: ${self.analysis.estimated_min_capital:.0f}")
    
    def _detect_patterns(self):
        """Detect repeatable patterns in trading behavior."""
        patterns = []
        
        # Pattern 1: Consistent timing
        if self.analysis.trades_per_day >= 5:
            patterns.append(TradingPattern(
                name="high_frequency",
                description="Trades frequently (5+ times per day)",
                confidence=90,
                occurrence_count=int(self.analysis.trades_per_day * 7)
            ))
        
        # Pattern 2: Market focus
        if len(self.analysis.primary_markets) <= 5:
            patterns.append(TradingPattern(
                name="market_specialist",
                description="Focuses on a small set of markets",
                confidence=80,
                occurrence_count=len(self.analysis.primary_markets)
            ))
        
        # Pattern 3: Consistent sizing
        sizes = [float(t.get("size", 0)) for t in self.trades if t.get("size")]
        if sizes:
            avg = sum(sizes) / len(sizes)
            variance = sum((s - avg)**2 for s in sizes) / len(sizes)
            std = variance ** 0.5
            cv = std / avg if avg > 0 else 0
            
            if cv < 0.3:  # Low coefficient of variation
                patterns.append(TradingPattern(
                    name="consistent_sizing",
                    description="Uses consistent position sizes (flat sizing)",
                    confidence=85,
                    occurrence_count=len(sizes)
                ))
        
        self.analysis.patterns = patterns
        
        print(f"   Detected patterns: {len(patterns)}")
        for p in patterns:
            print(f"      - {p.name}: {p.description}")
    
    def _calculate_understanding_metrics(self):
        """Calculate how well we understand this wallet's behavior."""
        # Behavior predictability: higher if patterns are consistent
        pattern_confidence = sum(p.confidence for p in self.analysis.patterns)
        max_confidence = len(self.analysis.patterns) * 100
        
        self.analysis.behavior_predictability = (
            pattern_confidence / max_confidence * 100
            if max_confidence > 0 else 0
        )
        
        # Rule coverage: what % of trades do our patterns explain?
        explained_trades = sum(p.occurrence_count for p in self.analysis.patterns)
        self.analysis.rule_coverage = min(100, (
            explained_trades / self.analysis.total_trades * 100
            if self.analysis.total_trades > 0 else 0
        ))
        
        # Complexity score: higher = harder to copy
        complexity = 0
        if self.analysis.trades_per_day > 50:
            complexity += 30  # Very high frequency is hard
        if self.analysis.avg_position_size > 5000:
            complexity += 30  # Large sizes need capital
        if len(self.analysis.primary_markets) > 20:
            complexity += 20  # Many markets is complex
        
        self.analysis.complexity_score = min(100, complexity)
        
        print(f"\n📊 Understanding Metrics:")
        print(f"   Predictability: {self.analysis.behavior_predictability:.0f}%")
        print(f"   Rule coverage: {self.analysis.rule_coverage:.0f}%")
        print(f"   Complexity: {self.analysis.complexity_score:.0f}%")
    
    def get_understanding_report(self) -> Dict:
        """Generate a report on our understanding of this wallet."""
        if not self.analysis:
            self.analyze()
        
        return {
            "wallet": self.wallet_address,
            "summary": {
                "total_trades": self.analysis.total_trades,
                "trades_per_day": self.analysis.trades_per_day,
                "avg_position_size": self.analysis.avg_position_size,
                "primary_markets": self.analysis.primary_markets[:5],
            },
            "patterns": [
                {
                    "name": p.name,
                    "description": p.description,
                    "confidence": p.confidence,
                }
                for p in self.analysis.patterns
            ],
            "understanding": {
                "predictability": self.analysis.behavior_predictability,
                "rule_coverage": self.analysis.rule_coverage,
                "ready_to_copy": self.analysis.behavior_predictability >= 70,
            },
            "copyability": {
                "min_capital_needed": self.analysis.estimated_min_capital,
                "complexity": self.analysis.complexity_score,
                "suitable_for_small_account": self.analysis.estimated_min_capital <= 500,
            },
        }
    
    def print_report(self):
        """Print a formatted analysis report."""
        if not self.analysis:
            self.analyze()
        
        a = self.analysis
        
        print("\n" + "="*70)
        print(f"📊 DEEP ANALYSIS: {self.wallet_address[:30]}...")
        print("="*70)
        
        print(f"\n📈 TRADING ACTIVITY")
        print(f"   Total trades: {a.total_trades}")
        print(f"   Trades/day: {a.trades_per_day:.1f}")
        print(f"   Avg size: ${a.avg_position_size:.2f}")
        print(f"   Win rate: {a.win_rate:.1%}")
        
        print(f"\n🎯 MARKET FOCUS")
        print(f"   Primary markets: {len(a.primary_markets)}")
        for m in a.primary_markets[:3]:
            print(f"      - {m[:40]}...")
        
        print(f"\n⏰ TIMING")
        print(f"   Active hours (UTC): {a.active_hours[:5]}")
        
        print(f"\n🔍 DETECTED PATTERNS")
        for p in a.patterns:
            print(f"   [{p.confidence:.0f}%] {p.name}: {p.description}")
        
        print(f"\n✅ UNDERSTANDING METRICS")
        print(f"   Predictability: {a.behavior_predictability:.0f}%")
        print(f"   Rule coverage: {a.rule_coverage:.0f}%")
        
        ready = a.behavior_predictability >= 70
        print(f"\n   Ready to copy: {'✅ YES' if ready else '❌ Need more analysis'}")
        
        print(f"\n💰 COPYABILITY")
        print(f"   Min capital: ${a.estimated_min_capital:.0f}")
        print(f"   Complexity: {a.complexity_score:.0f}%")
        
        suitable = a.estimated_min_capital <= 500
        print(f"   Small account OK: {'✅ YES' if suitable else '❌ NO (needs more capital)'}")
        
        print("="*70)
    
    def understanding_score(self) -> float:
        """
        Calculate overall understanding score (0-1).
        
        Combines predictability and rule coverage.
        """
        if not self.analysis:
            return 0.0
        
        # Weight predictability more than coverage
        score = (
            self.analysis.behavior_predictability * 0.6 +
            self.analysis.rule_coverage * 0.4
        ) / 100
        
        return min(1.0, max(0.0, score))
