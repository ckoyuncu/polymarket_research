#!/usr/bin/env python3
"""
Alpha Miner Runner

Discovers profitable strategies from market structure.
"""
import sys
import time
sys.path.insert(0, '.')

from src.storage import db
from src.alpha_miner import FeatureExtractor, PatternMiner
from src.strategy import StrategyLoader


def main():
    print("\n" + "="*60)
    print("🔬 ALPHA MINER")
    print("="*60)
    
    # Initialize
    db.initialize()
    
    # Check for data
    ob_count = db.execute("SELECT COUNT(*) as c FROM orderbook_snapshots")[0]["c"]
    price_count = db.execute("SELECT COUNT(*) as c FROM price_ticks")[0]["c"]
    
    print(f"\n📊 Data available:")
    print(f"   Orderbook snapshots: {ob_count}")
    print(f"   Price ticks: {price_count}")
    
    if ob_count < 100:
        print("\n⚠️  Insufficient data for mining.")
        print("   Run the collector first: python run_collector.py")
        return
    
    # Get time range
    ts_query = "SELECT MIN(ts) as start_ts, MAX(ts) as end_ts FROM orderbook_snapshots"
    ts_result = db.execute(ts_query)[0]
    start_ts = ts_result["start_ts"]
    end_ts = ts_result["end_ts"]
    
    print(f"\n⏱️  Time range: {start_ts} → {end_ts}")
    
    # Step 1: Extract features
    print("\n[1/3] Extracting features...")
    extractor = FeatureExtractor(auto_subscribe=False)
    extractor.backfill_features(start_ts, end_ts)
    
    feature_count = db.execute("SELECT COUNT(*) as c FROM features")[0]["c"]
    print(f"   ✓ Generated {feature_count} feature rows")
    
    # Step 2: Mine strategies
    print("\n[2/3] Mining strategies...")
    miner = PatternMiner(min_sharpe=0.5, min_trades=5)
    strategies = miner.mine_strategies(start_ts, end_ts)
    
    print(f"   ✓ Found {len(strategies)} viable strategies")
    
    # Step 3: Save winning strategies
    if strategies:
        print("\n[3/3] Saving strategies...")
        loader = StrategyLoader("strategies")
        
        for strategy in strategies[:5]:  # Top 5
            filepath = loader.save(strategy, format="json")
            print(f"   ✓ Saved: {strategy.name}")
    
    print("\n" + "="*60)
    print("✅ ALPHA MINING COMPLETE")
    print("="*60)
    print(f"\nStrategies saved to: strategies/")
    print("Next: Run backtest or deploy to paper trading")


if __name__ == "__main__":
    main()
