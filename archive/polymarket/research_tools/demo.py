#!/usr/bin/env python3
"""
Demo Script - Test APIs without WebSocket

Tests the Polymarket APIs and shows available data.
"""
import sys
sys.path.insert(0, '.')

from src.storage import db
from src.api import GammaClient, DataAPIClient


def main():
    print("\n" + "="*60)
    print("🧪 TRADING LAB - API DEMO")
    print("="*60)
    
    # Initialize database
    db.initialize()
    
    # Test Gamma API
    print("\n[1] Testing Gamma API (Market Discovery)...")
    gamma = GammaClient()
    
    try:
        markets = gamma.search_markets("Bitcoin Up or Down", limit=5)
        print(f"   ✓ Found {len(markets)} markets")
        
        if markets:
            print("\n   Sample markets:")
            for m in markets[:3]:
                info = gamma.extract_market_info(m)
                print(f"   - {info['slug']}")
                print(f"     Condition: {info['condition_id'][:20]}...")
                print(f"     Tokens: {len(info.get('clob_token_ids', []))}")
    
    except Exception as e:
        print(f"   ⚠️  Gamma API error: {e}")
    
    # Test Data API
    print("\n[2] Testing Data API (Leaderboard)...")
    data_api = DataAPIClient()
    
    try:
        leaders = data_api.get_top_crypto_traders(limit=5)
        print(f"   ✓ Fetched {len(leaders)} leaders")
        
        if leaders:
            print("\n   Top crypto traders (this week):")
            for i, l in enumerate(leaders[:5]):
                addr = l.get("address", l.get("user", "?"))[:20]
                pnl = l.get("pnl", 0)
                trades = l.get("numTrades", l.get("num_trades", 0))
                print(f"   {i+1}. {addr}... | PnL: ${pnl:,.0f} | Trades: {trades}")
    
    except Exception as e:
        print(f"   ⚠️  Data API error: {e}")
    
    # Test profile search
    print("\n[3] Testing Profile Search...")
    
    try:
        profiles = gamma.search_profiles("Account88888", limit=3)
        print(f"   ✓ Found {len(profiles)} profiles")
        
        if profiles:
            for p in profiles[:2]:
                name = p.get("name", p.get("username", "?"))
                proxy = p.get("proxyWallet", "?")[:20]
                print(f"   - {name}: {proxy}...")
    
    except Exception as e:
        print(f"   ⚠️  Profile search error: {e}")
    
    # Check database
    print("\n[4] Database Status...")
    tables = ["markets", "orderbook_snapshots", "price_ticks", "wallet_trades", "features"]
    
    for table in tables:
        try:
            count = db.execute(f"SELECT COUNT(*) as c FROM {table}")[0]["c"]
            print(f"   {table}: {count} rows")
        except Exception:
            print(f"   {table}: (not created)")
    
    print("\n" + "="*60)
    print("✅ API DEMO COMPLETE")
    print("="*60)
    print("\nNext steps:")
    print("  1. Run collector:    python run_collector.py 300")
    print("  2. Run alpha miner:  python run_alpha_miner.py")
    print("  3. Clone a wallet:   python run_wallet_cloner.py <address>")


if __name__ == "__main__":
    main()
