"""
Universal Wallet Discovery

Finds profitable wallets across ALL market categories on Polymarket.
Not limited to crypto - discovers in politics, sports, entertainment, etc.
"""
from typing import List, Dict, Optional
from dataclasses import dataclass
from enum import Enum

from ..api import DataAPIClient, GammaClient


class MarketCategory(Enum):
    """All Polymarket market categories."""
    CRYPTO = "CRYPTO"
    POLITICS = "POLITICS"  
    SPORTS = "SPORTS"
    POP_CULTURE = "POP_CULTURE"
    BUSINESS = "BUSINESS"
    SCIENCE = "SCIENCE"
    ALL = "ALL"


class TimePeriod(Enum):
    """Time periods for analysis."""
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    ALL_TIME = "ALL"


@dataclass
class WalletProfile:
    """Profile of a discovered wallet."""
    address: str
    display_name: Optional[str]
    
    # Performance metrics
    pnl: float
    pnl_percent: float
    num_trades: int
    volume: float
    win_rate: float
    
    # Trading style
    avg_trade_size: float
    avg_hold_time_hours: float
    trades_per_day: float
    
    # Focus
    primary_category: str
    market_types: List[str]
    
    # Quality scores (0-100)
    consistency_score: float  # How repeatable is their edge?
    frequency_score: float    # How often do they trade?
    copyability_score: float  # Can we realistically copy them?
    
    # For small accounts
    min_capital_needed: float
    suitable_for_small_account: bool


class WalletDiscovery:
    """
    Universal wallet discovery across all Polymarket categories.
    
    Finds wallets that are:
    1. Consistently profitable
    2. High frequency (more data = better understanding)
    3. Copyable (not relying on massive capital or inside info)
    4. Suitable for small accounts ($100-500)
    """
    
    def __init__(self):
        self.data_api = DataAPIClient()
        self.gamma = GammaClient()
        self.discovered_wallets: List[WalletProfile] = []
    
    def get_markets_by_category(self, category: MarketCategory) -> List[Dict]:
        """Get active markets for a category."""
        try:
            # Use gamma API to search markets by category keywords
            search_terms = {
                MarketCategory.CRYPTO: ["Bitcoin", "Ethereum", "BTC", "ETH", "crypto"],
                MarketCategory.POLITICS: ["election", "president", "congress", "vote"],
                MarketCategory.SPORTS: ["NBA", "NFL", "soccer", "championship", "game"],
                MarketCategory.POP_CULTURE: ["movie", "Grammy", "Oscar", "celebrity"],
                MarketCategory.BUSINESS: ["stock", "company", "earnings", "CEO"],
                MarketCategory.SCIENCE: ["NASA", "climate", "science", "space"],
                MarketCategory.ALL: [""],
            }
            
            terms = search_terms.get(category, [""])
            all_markets = []
            
            for term in terms[:2]:  # Limit to first 2 terms per category
                try:
                    markets = self.gamma.search_markets(query=term, limit=20, active=True)
                    all_markets.extend(markets)
                except Exception:
                    continue
            
            # Deduplicate
            seen = set()
            unique = []
            for m in all_markets:
                cid = m.get("conditionId") or m.get("condition_id") or m.get("id")
                if cid and cid not in seen:
                    seen.add(cid)
                    unique.append(m)
            
            return unique
        except Exception as e:
            print(f"   Error fetching markets: {e}")
            return []
    
    def scan_all_categories(
        self,
        min_pnl: float = 1000,
        min_trades: int = 0,  # Set to 0 - leaderboard doesn't return trade counts
        time_period: TimePeriod = TimePeriod.WEEK
    ) -> List[WalletProfile]:
        """
        Scan all market categories for profitable wallets.
        
        Args:
            min_pnl: Minimum profit to consider
            min_trades: Minimum trades (more = better for analysis)
            time_period: Time window to analyze
        """
        print("\n" + "="*60)
        print("🔍 UNIVERSAL WALLET DISCOVERY")
        print("="*60)
        
        all_wallets = []
        
        categories = [
            MarketCategory.CRYPTO,
            MarketCategory.POLITICS,
            MarketCategory.SPORTS,
            MarketCategory.POP_CULTURE,
            MarketCategory.BUSINESS,
        ]
        
        for category in categories:
            print(f"\n📊 Scanning {category.value}...")
            
            try:
                wallets = self._scan_category(
                    category=category,
                    time_period=time_period,
                    limit=20
                )
                
                # Filter by criteria (min_trades disabled since API doesn't return it)
                qualified = [
                    w for w in wallets
                    if w.pnl >= min_pnl
                ]
                
                print(f"   Found {len(qualified)} qualifying wallets")
                all_wallets.extend(qualified)
                
            except Exception as e:
                print(f"   ⚠️  Error: {e}")
        
        # Sort by copyability (best for small accounts first)
        all_wallets.sort(key=lambda w: w.copyability_score, reverse=True)
        
        self.discovered_wallets = all_wallets
        
        print(f"\n✓ Total discovered: {len(all_wallets)} wallets")
        
        return all_wallets
    
    def _scan_category(
        self,
        category: MarketCategory,
        time_period: TimePeriod,
        limit: int = 50
    ) -> List[WalletProfile]:
        """Scan a single category."""
        wallets = []
        
        # Get leaderboard
        try:
            leaders = self.data_api.get_leaderboard(
                category=category.value,
                time_period=time_period.value,
                order_by="PNL",
                limit=limit
            )
        except Exception:
            return []
        
        for leader in leaders:
            try:
                profile = self._build_profile(leader, category)
                if profile:
                    wallets.append(profile)
            except Exception:
                continue
        
        return wallets
    
    def _build_profile(self, leader: Dict, category: MarketCategory) -> Optional[WalletProfile]:
        """Build a wallet profile from leaderboard data."""
        address = leader.get("address") or leader.get("user") or leader.get("proxyWallet")
        
        if not address:
            return None
        
        pnl = float(leader.get("pnl", 0))
        num_trades = int(leader.get("numTrades", leader.get("num_trades", 0)))
        volume = float(leader.get("volume", 0))
        
        # Calculate derived metrics
        avg_trade_size = volume / num_trades if num_trades > 0 else 0
        win_rate = float(leader.get("winRate", leader.get("win_rate", 0.5)))
        
        # Estimate trading frequency (trades per day based on period)
        trades_per_day = num_trades / 7  # Assuming WEEK
        
        # Calculate scores
        consistency_score = self._calculate_consistency(pnl, num_trades, win_rate)
        frequency_score = min(100, trades_per_day * 10)  # Higher frequency = better
        copyability_score = self._calculate_copyability(avg_trade_size, trades_per_day, pnl)
        
        # Minimum capital estimate
        min_capital = max(50, avg_trade_size * 2)
        suitable_for_small = avg_trade_size <= 500 and min_capital <= 500
        
        return WalletProfile(
            address=address,
            display_name=leader.get("name", leader.get("username")),
            pnl=pnl,
            pnl_percent=float(leader.get("pnlPercent", leader.get("roi", 0))),
            num_trades=num_trades,
            volume=volume,
            win_rate=win_rate,
            avg_trade_size=avg_trade_size,
            avg_hold_time_hours=0,  # Need to calculate from trades
            trades_per_day=trades_per_day,
            primary_category=category.value,
            market_types=[],  # Will be populated during analysis
            consistency_score=consistency_score,
            frequency_score=frequency_score,
            copyability_score=copyability_score,
            min_capital_needed=min_capital,
            suitable_for_small_account=suitable_for_small,
        )
    
    def _calculate_consistency(self, pnl: float, num_trades: int, win_rate: float) -> float:
        """Score how consistent/repeatable the edge appears."""
        score = 0
        
        # High win rate is good
        score += win_rate * 40
        
        # More trades = more confidence it's not luck
        if num_trades >= 100:
            score += 30
        elif num_trades >= 50:
            score += 20
        elif num_trades >= 20:
            score += 10
        
        # Positive PnL with many trades = real edge
        if pnl > 0 and num_trades >= 50:
            score += 30
        
        return min(100, score)
    
    def _calculate_copyability(self, avg_trade_size: float, trades_per_day: float, pnl: float) -> float:
        """Score how copyable this strategy is for small accounts."""
        score = 0
        
        # Small trade sizes = more copyable
        if avg_trade_size <= 100:
            score += 40
        elif avg_trade_size <= 500:
            score += 30
        elif avg_trade_size <= 1000:
            score += 20
        elif avg_trade_size <= 5000:
            score += 10
        
        # High frequency = more opportunities
        if trades_per_day >= 10:
            score += 30
        elif trades_per_day >= 5:
            score += 20
        elif trades_per_day >= 1:
            score += 10
        
        # Profitable = actually works
        if pnl > 10000:
            score += 30
        elif pnl > 1000:
            score += 20
        elif pnl > 0:
            score += 10
        
        return min(100, score)
    
    def find_small_account_friendly(self, max_capital: float = 500) -> List[WalletProfile]:
        """Filter to wallets suitable for small accounts."""
        return [
            w for w in self.discovered_wallets
            if w.suitable_for_small_account and w.min_capital_needed <= max_capital
        ]
    
    def find_high_frequency(self, min_trades_per_day: float = 5) -> List[WalletProfile]:
        """Filter to high-frequency wallets (more data to analyze)."""
        return [
            w for w in self.discovered_wallets
            if w.trades_per_day >= min_trades_per_day
        ]
    
    def get_best_candidates(self, top_n: int = 10) -> List[WalletProfile]:
        """Get the best candidates for copying."""
        # Score = copyability * consistency * frequency
        def composite_score(w):
            return (w.copyability_score * w.consistency_score * w.frequency_score) / 10000
        
        sorted_wallets = sorted(
            self.discovered_wallets,
            key=composite_score,
            reverse=True
        )
        
        return sorted_wallets[:top_n]
    
    def print_report(self, wallets: List[WalletProfile] = None):
        """Print a formatted report of discovered wallets."""
        wallets = wallets or self.discovered_wallets
        
        print("\n" + "="*80)
        print("📊 WALLET DISCOVERY REPORT")
        print("="*80)
        
        print(f"\n{'Address':<20} {'Category':<12} {'PnL':>10} {'Trades':>8} {'$/Trade':>10} {'Copy Score':>10}")
        print("-"*80)
        
        for w in wallets[:20]:
            addr = w.address[:18] + ".." if len(w.address) > 18 else w.address
            print(f"{addr:<20} {w.primary_category:<12} ${w.pnl:>9,.0f} {w.num_trades:>8} ${w.avg_trade_size:>9,.0f} {w.copyability_score:>10.0f}")
        
        # Summary
        small_account = [w for w in wallets if w.suitable_for_small_account]
        high_freq = [w for w in wallets if w.trades_per_day >= 5]
        
        print("\n" + "-"*80)
        print(f"Total wallets: {len(wallets)}")
        print(f"Small account friendly (<$500): {len(small_account)}")
        print(f"High frequency (5+ trades/day): {len(high_freq)}")
        print("="*80)
