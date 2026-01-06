#!/usr/bin/env python3
"""
Deep Wallet Analyzer Script

Analyze a specific wallet to understand their strategy BEFORE trying to copy.

Usage:
    python run_analyze_wallet.py <username>
    python run_analyze_wallet.py Account88888
    python run_analyze_wallet.py 0x7f69983eb28245bba0...
"""
import sys
import json
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.api.gamma import GammaClient
from src.api.data_api import DataAPIClient
from src.discovery.deep_analyzer import DeepAnalyzer


def print_section(title: str, width: int = 60):
    """Print a section header."""
    print("\n" + "="*width)
    print(f" {title}")
    print("="*width)


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_analyze_wallet.py <username or address>")
        print("\nExamples:")
        print("    python run_analyze_wallet.py Account88888")
        print("    python run_analyze_wallet.py 0x7f69983eb28245bba0...")
        sys.exit(1)
    
    target = sys.argv[1]
    
    print_section(f"🔬 DEEP WALLET ANALYSIS: {target}")
    
    # Initialize APIs
    gamma = GammaClient()
    data_api = DataAPIClient()
    
    # Step 1: Resolve wallet
    print("\n📍 Resolving wallet...")
    
    wallet_address = None
    username = target
    
    if target.startswith("0x"):
        wallet_address = target
        print(f"   Address provided: {target[:20]}...")
    else:
        # Look up by username
        profile = data_api.search_profile(target)
        if profile:
            wallet_address = profile.get("proxyWallet") or profile.get("address")
            username = profile.get("name", target)
            print(f"   Found: @{username}")
            if wallet_address:
                print(f"   Wallet: {wallet_address[:20]}...")
        else:
            print(f"   ⚠️  Could not find profile for '{target}'")
            print("   Continuing with limited analysis...")
    
    # Step 2: Get all their trades
    print("\n📥 Loading trade history...")
    
    analyzer = DeepAnalyzer(wallet_address or "", username=username)
    
    trades = []
    if wallet_address:
        try:
            trades = data_api.get_all_trades(user=wallet_address, max_pages=5)
            print(f"   Loaded {len(trades)} trades")
        except Exception as e:
            print(f"   ⚠️  Could not load trades: {e}")
    else:
        print("   No trades (couldn't resolve wallet)")
    
    # Step 3: Run analysis
    print("\n🧠 Analyzing trading patterns...")
    
    if trades:
        # Convert to analyzer format and add to analyzer
        for trade in trades:
            normalized = data_api.normalize_trade(trade)
            analyzer.trades.append({
                "ts": normalized.get("ts"),
                "timestamp": normalized.get("ts"),
                "market": normalized.get("condition_id"),
                "condition_id": normalized.get("condition_id"),
                "side": normalized.get("side"),
                "price": normalized.get("price"),
                "size": normalized.get("size"),
                "amount": normalized.get("size"),
            })
        
        analysis = analyzer.analyze()
    else:
        analysis = None
    
    # Step 4: Display results
    print_section("📊 ANALYSIS RESULTS")
    
    if analysis:
        # Basic stats
        print(f"""
    📈 Performance:
       • Total trades: {analysis.total_trades}
       • Win rate: {analysis.win_rate:.1%}
       • Total P&L: ${analysis.total_pnl:,.2f}
       • Avg trade size: ${analysis.avg_position_size:.2f}
       
    ⏰ Timing:
       • Most active hours (UTC): {analysis.active_hours[:5] if analysis.active_hours else 'Unknown'}
       • Avg holding time: {analysis.avg_hold_time_minutes:.0f} minutes
       • Trade frequency: {analysis.trades_per_day:.1f} trades/day
       
    🎯 Markets:
       • Unique markets: {len(analysis.primary_markets)}
       • Top markets: {len(analysis.primary_markets[:3])} tracked
    """)
        
        # Detected patterns
        print_section("🔍 DETECTED PATTERNS")
        
        if analysis.patterns:
            for i, pattern in enumerate(analysis.patterns, 1):
                print(f"""
    Pattern {i}: {pattern.name.upper()}
       • Confidence: {pattern.confidence:.0f}%
       • Count: {pattern.occurrence_count}
       • {pattern.description}
    """)
        else:
            print("   No clear patterns detected yet (need more data)")
        
        # Copyability assessment
        print_section("📋 CAN YOU COPY THIS?")
        
        copyable = True
        issues = []
        
        if analysis.avg_position_size > 500:
            issues.append(f"Large position sizes (${analysis.avg_position_size:.0f} avg)")
            copyable = False
        
        if analysis.trades_per_day > 50:
            issues.append("Very high frequency (may need automation)")
        
        if analysis.avg_hold_time_minutes < 1 and analysis.avg_hold_time_minutes > 0:
            issues.append("Sub-minute trades (likely automated)")
            copyable = False
        
        if len(analysis.primary_markets) > 20:
            issues.append("Trades many different markets (complex)")
        
        if copyable and not issues:
            print("""
    ✅ This strategy appears COPYABLE for small accounts!
    
    Key characteristics:
    • Reasonable position sizes
    • Understandable timing patterns
    • Focused market selection
    """)
        elif issues:
            status = '⚠️  CAUTION' if copyable else '❌ NOT EASILY COPYABLE'
            print(f"""
    {status}
    
    Issues detected:
    """)
            for issue in issues:
                print(f"    • {issue}")
        
        # Understanding score
        print_section("🧩 UNDERSTANDING SCORE")
        
        understanding = analyzer.understanding_score()
        
        bar = "█" * int(understanding * 20) + "░" * (20 - int(understanding * 20))
        
        if understanding > 0.7:
            status_msg = '✅ Good understanding - ready to test'
        elif understanding > 0.4:
            status_msg = '⚠️  Partial understanding - gather more data'
        else:
            status_msg = '❌ Low understanding - need more analysis'
        
        print(f"""
    [{bar}] {understanding:.0%}
    
    {status_msg}
    """)
        
        # Recommended next steps
        print_section("📋 RECOMMENDED NEXT STEPS")
        
        if understanding > 0.7:
            print("""
    You have good understanding! Here's what to do:
    
    1. Paper Trade First
       - Watch this wallet in real-time
       - Make predictions without real money
       - Track your accuracy for 1 week
    
    2. Start Very Small
       - First real trade: $5-10 max
       - Only trade patterns you understand
       - Stop after 3 consecutive losses
    
    3. Scale Gradually
       - Double position size after 10 profitable trades
       - Never risk more than 10% of account per trade
    """)
        elif understanding > 0.4:
            print("""
    You need more data. Here's what to do:
    
    1. Monitor More Trades
       - Watch this wallet for a few more days
       - Note the CONDITIONS when they trade
       - Track what happens before each trade
    
    2. Compare to Markets
       - Look at orderbook when they trade
       - Check external prices (Binance, Chainlink)
       - See if there's a timing pattern
    
    3. Re-run Analysis
       - After 50+ more trades, run this again
    """)
        else:
            print("""
    Not enough data to understand this strategy.
    
    Options:
    1. Wait and collect more trade data
    2. Try analyzing a different wallet
    3. Look at the market structure manually
    
    For the 15-minute BTC/ETH markets specifically,
    the strategy appears to be based on:
    - Reset timing (every 15 min)
    - Binance price lags
    - Position reset mechanics
    """)
    
    else:
        print("""
    ⚠️  Could not complete analysis
    
    Reasons:
    • Wallet not found or
    • No trade history available
    
    Try:
    • Double-check the username/address
    • Use the discovery script to find valid wallets:
      python run_discovery.py
    """)
    
    # Save analysis
    print_section("💾 SAVING ANALYSIS")
    
    output_dir = Path("data/analysis")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / f"analysis_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "target": target,
        "username": username,
        "wallet_address": wallet_address,
        "trades_analyzed": len(trades) if trades else 0,
    }
    
    if analysis:
        results["analysis"] = {
            "total_trades": analysis.total_trades,
            "win_rate": analysis.win_rate,
            "total_pnl": analysis.total_pnl,
            "avg_position_size": analysis.avg_position_size,
            "trades_per_day": analysis.trades_per_day,
            "primary_markets_count": len(analysis.primary_markets),
            "active_hours": analysis.active_hours,
            "patterns": [
                {
                    "name": p.name,
                    "confidence": p.confidence,
                    "description": p.description
                }
                for p in analysis.patterns
            ],
            "understanding_score": analyzer.understanding_score()
        }
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"   Saved to: {output_file}")
    print("\n" + "="*60)

if __name__ == "__main__":
    main()
