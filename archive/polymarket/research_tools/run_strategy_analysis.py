#!/usr/bin/env python3
"""
Deep Strategy Analysis

Analyzes the TOP 3 wallets to understand:
1. WHAT they're actually doing (strategy mechanics)
2. HOW they manage risk (drawdowns, consecutive losses)
3. WHETHER their strategy is copyable (latency requirements)
4. WHAT signals they use (timing, price patterns)

This answers: Should we copy them, or is their edge non-replicable?
"""
import sys
import os
import json
import time
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.api.data_api import DataAPIClient as DataAPI
from src.api.gamma import GammaClient as GammaAPI
from src.config import DATA_DIR


# Top 3 wallets from our analysis
TOP_WALLETS = [
    {
        "address": "0x589222a5124a96765443b97a3498d89ffd824ad2",
        "name": "Wallet_589222",
        "reported_pnl": 169000
    },
    {
        "address": "0x14ae1d1679fc048eaafadea39646755d528a0459",
        "name": "Wallet_14ae1d",
        "reported_pnl": 160000
    },
    {
        "address": "0x7f69983eb28245bba0d5083502a78744a8f66162",
        "name": "Account88888",
        "reported_pnl": 129000
    }
]


@dataclass
class TradeCluster:
    """A group of trades that happened close together."""
    start_time: int
    end_time: int
    trades: List[Dict] = field(default_factory=list)
    net_position: float = 0.0
    net_cost: float = 0.0
    outcome: str = ""  # "win", "loss", "open"
    pnl: float = 0.0


@dataclass 
class RiskMetrics:
    """Risk management metrics."""
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_daily_loss: float = 0.0
    max_daily_gain: float = 0.0
    max_drawdown: float = 0.0
    avg_win_size: float = 0.0
    avg_loss_size: float = 0.0
    win_loss_ratio: float = 0.0
    largest_position: float = 0.0
    avg_position_hold_time: float = 0.0  # seconds


@dataclass
class StrategyProfile:
    """Complete strategy profile for a wallet."""
    address: str
    name: str
    
    # Trade stats
    total_trades: int = 0
    total_volume: float = 0.0
    
    # Timing
    avg_time_between_trades: float = 0.0
    peak_trading_hours: List[int] = field(default_factory=list)
    trades_per_hour: Dict[int, int] = field(default_factory=dict)
    
    # Market focus
    markets_traded: Dict[str, int] = field(default_factory=dict)
    market_concentration: float = 0.0  # % in top market
    
    # Position sizing
    avg_position_size: float = 0.0
    median_position_size: float = 0.0
    position_size_std: float = 0.0
    max_position_size: float = 0.0
    min_position_size: float = 0.0
    
    # Entry patterns
    entry_price_patterns: Dict[str, float] = field(default_factory=dict)
    
    # Risk metrics
    risk: RiskMetrics = field(default_factory=RiskMetrics)
    
    # Strategy classification
    strategy_type: str = ""  # "arbitrage", "momentum", "mean_reversion", etc.
    copyability_score: float = 0.0  # 0-100, how easy to copy
    latency_sensitivity: str = ""  # "high", "medium", "low"
    
    # Key signals identified
    signals: List[str] = field(default_factory=list)
    
    # Warnings
    warnings: List[str] = field(default_factory=list)


def analyze_wallet(address: str, name: str, limit: int = 1000) -> StrategyProfile:
    """
    Deep analysis of a wallet's trading strategy.
    """
    print(f"\n{'='*60}")
    print(f"🔍 Analyzing: {name}")
    print(f"   Address: {address[:10]}...{address[-6:]}")
    print(f"{'='*60}")
    
    profile = StrategyProfile(address=address, name=name)
    data_api = DataAPI()
    
    # Fetch trades using get_trades with user parameter
    print(f"\n📥 Fetching last {limit} trades...")
    trades = data_api.get_trades(user=address, limit=limit)
    
    if not trades:
        # Try get_all_trades as fallback
        print("   Trying paginated fetch...")
        trades = data_api.get_all_trades(user=address, max_pages=10)
    
    if not trades:
        print("❌ No trades found")
        profile.warnings.append("No trade data available")
        return profile
    
    print(f"   Found {len(trades)} trades")
    profile.total_trades = len(trades)
    
    # Sort by timestamp
    trades.sort(key=lambda x: x.get("timestamp", 0))
    
    # === TIMING ANALYSIS ===
    print("\n⏱️  Analyzing timing patterns...")
    analyze_timing(trades, profile)
    
    # === POSITION SIZING ANALYSIS ===
    print("\n💰 Analyzing position sizing...")
    analyze_position_sizing(trades, profile)
    
    # === MARKET FOCUS ===
    print("\n🎯 Analyzing market focus...")
    analyze_market_focus(trades, profile)
    
    # === ENTRY PATTERNS ===
    print("\n📊 Analyzing entry patterns...")
    analyze_entry_patterns(trades, profile)
    
    # === RISK METRICS ===
    print("\n⚠️  Analyzing risk management...")
    analyze_risk_metrics(trades, profile)
    
    # === STRATEGY CLASSIFICATION ===
    print("\n🧠 Classifying strategy...")
    classify_strategy(trades, profile)
    
    return profile


def analyze_timing(trades: List[Dict], profile: StrategyProfile):
    """Analyze when trades happen."""
    timestamps = [t.get("timestamp", 0) for t in trades if t.get("timestamp")]
    
    if len(timestamps) < 2:
        return
    
    # Time between trades
    gaps = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
    profile.avg_time_between_trades = sum(gaps) / len(gaps) if gaps else 0
    
    # Trades per hour
    hour_counts = defaultdict(int)
    for ts in timestamps:
        hour = datetime.fromtimestamp(ts).hour
        hour_counts[hour] += 1
    
    profile.trades_per_hour = dict(hour_counts)
    
    # Peak hours (top 3)
    sorted_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)
    profile.peak_trading_hours = [h for h, c in sorted_hours[:3]]
    
    print(f"   Avg time between trades: {profile.avg_time_between_trades:.1f}s")
    print(f"   Peak trading hours (UTC): {profile.peak_trading_hours}")
    
    # Check if trading happens at specific times (like 15-min boundaries)
    minute_counts = defaultdict(int)
    for ts in timestamps:
        minute = datetime.fromtimestamp(ts).minute
        minute_counts[minute % 15] += 1  # Check 15-min cycle
    
    # If >60% of trades are in first 2 minutes of 15-min window
    early_trades = minute_counts[0] + minute_counts[1]
    total = sum(minute_counts.values())
    if total > 0 and early_trades / total > 0.6:
        profile.signals.append(f"⚡ TIMING: {early_trades/total*100:.0f}% of trades in first 2 mins of 15-min window")
        profile.latency_sensitivity = "high"


def analyze_position_sizing(trades: List[Dict], profile: StrategyProfile):
    """Analyze position sizes."""
    sizes = []
    for t in trades:
        size = t.get("size", 0) or t.get("amount", 0)
        price = t.get("price", 0.5)
        if size > 0:
            value = float(size) * float(price)
            sizes.append(value)
            profile.total_volume += value
    
    if not sizes:
        return
    
    sizes.sort()
    profile.avg_position_size = sum(sizes) / len(sizes)
    profile.median_position_size = sizes[len(sizes)//2]
    profile.max_position_size = max(sizes)
    profile.min_position_size = min(sizes)
    
    # Standard deviation
    mean = profile.avg_position_size
    variance = sum((x - mean) ** 2 for x in sizes) / len(sizes)
    profile.position_size_std = variance ** 0.5
    
    print(f"   Avg position: ${profile.avg_position_size:.2f}")
    print(f"   Median position: ${profile.median_position_size:.2f}")
    print(f"   Range: ${profile.min_position_size:.2f} - ${profile.max_position_size:.2f}")
    print(f"   Std Dev: ${profile.position_size_std:.2f}")
    
    # Check for consistent sizing (suggests automated)
    if profile.position_size_std < profile.avg_position_size * 0.1:
        profile.signals.append("🤖 SIZING: Very consistent position sizes (likely automated)")


def analyze_market_focus(trades: List[Dict], profile: StrategyProfile):
    """Analyze which markets are traded."""
    market_counts = defaultdict(int)
    
    for t in trades:
        market = t.get("market", "unknown")
        if not market or market == "unknown":
            market = t.get("condition_id", "unknown")[:20]
        market_counts[market] += 1
    
    profile.markets_traded = dict(market_counts)
    
    # Concentration in top market
    if market_counts:
        top_count = max(market_counts.values())
        total = sum(market_counts.values())
        profile.market_concentration = (top_count / total) * 100
    
    print(f"   Markets traded: {len(market_counts)}")
    print(f"   Concentration in top market: {profile.market_concentration:.1f}%")
    
    # Show top 3 markets
    sorted_markets = sorted(market_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    for market, count in sorted_markets:
        pct = count / sum(market_counts.values()) * 100
        print(f"   - {market[:30]}: {count} trades ({pct:.1f}%)")


def analyze_entry_patterns(trades: List[Dict], profile: StrategyProfile):
    """Analyze entry price patterns."""
    buy_prices = []
    sell_prices = []
    
    for t in trades:
        price = float(t.get("price", 0.5))
        side = t.get("side", "").lower()
        
        if side == "buy":
            buy_prices.append(price)
        elif side == "sell":
            sell_prices.append(price)
    
    if buy_prices:
        profile.entry_price_patterns["avg_buy_price"] = sum(buy_prices) / len(buy_prices)
        profile.entry_price_patterns["buy_near_50"] = sum(1 for p in buy_prices if 0.45 <= p <= 0.55) / len(buy_prices)
        profile.entry_price_patterns["buy_extremes"] = sum(1 for p in buy_prices if p < 0.2 or p > 0.8) / len(buy_prices)
    
    if sell_prices:
        profile.entry_price_patterns["avg_sell_price"] = sum(sell_prices) / len(sell_prices)
    
    print(f"   Buy count: {len(buy_prices)}, Sell count: {len(sell_prices)}")
    
    if buy_prices:
        near_50_pct = profile.entry_price_patterns.get("buy_near_50", 0) * 100
        extreme_pct = profile.entry_price_patterns.get("buy_extremes", 0) * 100
        print(f"   Buys near 50%: {near_50_pct:.1f}%")
        print(f"   Buys at extremes (<20% or >80%): {extreme_pct:.1f}%")
        
        if near_50_pct > 70:
            profile.signals.append("📈 ENTRY: Buys heavily concentrated near 50% (arbitrage indicator)")


def analyze_risk_metrics(trades: List[Dict], profile: StrategyProfile):
    """Analyze risk management patterns."""
    # Group trades by day
    daily_pnl = defaultdict(float)
    
    for t in trades:
        ts = t.get("timestamp", 0)
        if ts:
            day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
            # Estimate PnL (simplified - actual would need outcome data)
            size = float(t.get("size", 0) or t.get("amount", 0))
            price = float(t.get("price", 0.5))
            side = t.get("side", "").lower()
            
            # For now, we can't calculate actual PnL without outcomes
            # Just track activity
    
    # Check for consecutive trading patterns
    timestamps = sorted([t.get("timestamp", 0) for t in trades if t.get("timestamp")])
    
    if len(timestamps) > 10:
        # Look for rapid-fire trading (potential scalping/arbitrage)
        rapid_clusters = 0
        for i in range(len(timestamps) - 1):
            if timestamps[i+1] - timestamps[i] < 60:  # Within 1 minute
                rapid_clusters += 1
        
        rapid_pct = rapid_clusters / len(timestamps) * 100
        if rapid_pct > 50:
            profile.signals.append(f"⚡ SPEED: {rapid_pct:.0f}% of trades within 60s of previous (speed-dependent)")
            profile.latency_sensitivity = "high"
    
    # Track max position
    profile.risk.largest_position = profile.max_position_size
    
    print(f"   Largest position: ${profile.risk.largest_position:.2f}")


def classify_strategy(trades: List[Dict], profile: StrategyProfile):
    """Classify the strategy type and copyability."""
    
    # Collect evidence
    evidence = {
        "arbitrage": 0,
        "momentum": 0,
        "mean_reversion": 0,
        "market_making": 0
    }
    
    # Check timing patterns
    if profile.latency_sensitivity == "high":
        evidence["arbitrage"] += 3
    
    # Check price entry patterns
    near_50 = profile.entry_price_patterns.get("buy_near_50", 0)
    if near_50 > 0.7:
        evidence["arbitrage"] += 2
        evidence["market_making"] += 1
    
    # Check market concentration
    if profile.market_concentration > 80:
        evidence["arbitrage"] += 1  # Focused on specific market
    
    # Check position consistency
    if profile.position_size_std < profile.avg_position_size * 0.1:
        evidence["arbitrage"] += 1  # Automated
    
    # Determine primary strategy
    primary = max(evidence, key=evidence.get)
    profile.strategy_type = primary
    
    # Copyability score (0-100)
    # Lower if latency-sensitive
    copyability = 80
    
    if profile.latency_sensitivity == "high":
        copyability -= 40
        profile.warnings.append("⚠️ HIGH LATENCY SENSITIVITY: Strategy may require sub-second execution")
    
    # Lower if very high frequency
    if profile.avg_time_between_trades < 60:
        copyability -= 20
        profile.warnings.append("⚠️ HIGH FREQUENCY: Trades every minute - hard to follow manually")
    
    # Lower if concentrated in specific market windows
    if any("first 2 mins" in s for s in profile.signals):
        copyability -= 20
        profile.warnings.append("⚠️ TIME-CRITICAL: Strategy depends on trading at exact times")
    
    profile.copyability_score = max(0, copyability)
    
    print(f"\n   Strategy Type: {primary.upper()}")
    print(f"   Copyability Score: {profile.copyability_score}/100")
    print(f"   Latency Sensitivity: {profile.latency_sensitivity or 'medium'}")


def print_full_report(profiles: List[StrategyProfile]):
    """Print comprehensive analysis report."""
    print("\n")
    print("=" * 80)
    print("                    STRATEGY ANALYSIS REPORT")
    print("=" * 80)
    
    for p in profiles:
        print(f"\n{'─'*80}")
        print(f"📊 {p.name}")
        print(f"{'─'*80}")
        
        print(f"\n📈 TRADING PROFILE")
        print(f"   Total Trades Analyzed: {p.total_trades}")
        print(f"   Total Volume: ${p.total_volume:,.2f}")
        print(f"   Avg Position Size: ${p.avg_position_size:.2f}")
        print(f"   Peak Hours (UTC): {p.peak_trading_hours}")
        
        print(f"\n🎯 STRATEGY CLASSIFICATION")
        print(f"   Type: {p.strategy_type.upper()}")
        print(f"   Copyability: {p.copyability_score}/100")
        print(f"   Latency Sensitivity: {p.latency_sensitivity or 'medium'}")
        
        if p.signals:
            print(f"\n📡 KEY SIGNALS IDENTIFIED")
            for signal in p.signals:
                print(f"   {signal}")
        
        if p.warnings:
            print(f"\n⚠️  WARNINGS")
            for warning in p.warnings:
                print(f"   {warning}")
    
    # Overall recommendation
    print("\n")
    print("=" * 80)
    print("                    RECOMMENDATIONS")
    print("=" * 80)
    
    avg_copyability = sum(p.copyability_score for p in profiles) / len(profiles) if profiles else 0
    
    print(f"\n📊 Average Copyability Score: {avg_copyability:.0f}/100")
    
    if avg_copyability < 40:
        print("""
🚨 CRITICAL FINDING: Low Copyability

These wallets appear to be running LATENCY-SENSITIVE ARBITRAGE strategies.
Their edge likely comes from:

1. SPEED: They trade within seconds of market events
2. INFRASTRUCTURE: Likely using co-located servers or fast APIs
3. AUTOMATION: Fully automated systems, not manual trading

⚠️  COPYING THEM DIRECTLY WILL NOT WORK because:
- By the time you see their trade, the opportunity is gone
- Your execution will always be slower
- You're competing against them, not alongside them

✅ ALTERNATIVE APPROACHES:

1. BUILD YOUR OWN EDGE (Recommended)
   - Identify the PATTERN they're exploiting (15-min reset lag)
   - Build your own detection system
   - Execute independently, not by copying

2. FIND SLOWER STRATEGIES
   - Look for wallets with longer hold times (hours/days)
   - These are more copyable as timing is less critical

3. USE SIGNALS, NOT COPIES
   - Treat their trades as confirmation signals
   - Develop your own entry logic
   - Accept you'll capture a smaller edge
""")
    elif avg_copyability < 70:
        print("""
⚠️  MODERATE COPYABILITY

The strategies show some latency sensitivity but may be partially copyable.

RECOMMENDED APPROACH:
1. Paper trade for 2 weeks minimum
2. Measure your execution lag vs their trades
3. If lag > 30 seconds, look for different wallets
4. Focus on trades where timing is less critical
""")
    else:
        print("""
✅ GOOD COPYABILITY

These strategies appear to be copyable with reasonable infrastructure.

RECOMMENDED APPROACH:
1. Paper trade for 1 week to validate
2. Start with 10% of intended capital
3. Monitor execution quality closely
4. Scale up if win rate matches paper trading
""")


def save_analysis(profiles: List[StrategyProfile]):
    """Save analysis to file."""
    output_dir = DATA_DIR / "strategy_analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = output_dir / f"top3_analysis_{timestamp}.json"
    
    data = {
        "timestamp": datetime.now().isoformat(),
        "profiles": [
            {
                "address": p.address,
                "name": p.name,
                "total_trades": p.total_trades,
                "total_volume": p.total_volume,
                "avg_position_size": p.avg_position_size,
                "strategy_type": p.strategy_type,
                "copyability_score": p.copyability_score,
                "latency_sensitivity": p.latency_sensitivity,
                "signals": p.signals,
                "warnings": p.warnings,
                "peak_hours": p.peak_trading_hours,
                "market_concentration": p.market_concentration
            }
            for p in profiles
        ]
    }
    
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n📁 Analysis saved to: {filepath}")


def main():
    """Main entry point."""
    print("""
╔══════════════════════════════════════════════════════════════════╗
║           DEEP STRATEGY ANALYSIS - TOP 3 WALLETS                 ║
║                                                                  ║
║  Questions we're answering:                                      ║
║  1. What strategy are they using?                                ║
║  2. Can we copy them, or is their edge non-replicable?           ║
║  3. What are their risk management patterns?                     ║
║  4. What signals do they use?                                    ║
╚══════════════════════════════════════════════════════════════════╝
    """)
    
    profiles = []
    
    for wallet in TOP_WALLETS:
        try:
            profile = analyze_wallet(
                wallet["address"],
                wallet["name"],
                limit=500
            )
            profiles.append(profile)
            time.sleep(1)  # Rate limiting
        except Exception as e:
            print(f"❌ Error analyzing {wallet['name']}: {e}")
    
    # Print full report
    print_full_report(profiles)
    
    # Save results
    save_analysis(profiles)
    
    return profiles


if __name__ == "__main__":
    main()
