#!/usr/bin/env python3
"""
Wallet Cloner Runner

Reverse-engineers a wallet's trading logic.
"""
import sys
sys.path.insert(0, '.')

from src.storage import db
from src.api import DataAPIClient
from src.wallet_cloner import TradeAnalyzer, LogicExtractor
from src.audit import StrategyVerifier
from src.strategy import StrategyLoader


def ingest_wallet_trades(wallet_address: str, data_api: DataAPIClient):
    """Fetch and store wallet trades."""
    print(f"\n📥 Ingesting trades for {wallet_address[:16]}...")
    
    trades = data_api.get_all_trades(user=wallet_address, max_pages=50)
    print(f"   Fetched {len(trades)} trades")
    
    # Store in database
    for trade in trades:
        normalized = data_api.normalize_trade(trade)
        
        query = """
            INSERT OR IGNORE INTO wallet_trades 
            (wallet, ts, condition_id, token_id, side, price, size)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        db.execute(query, (
            normalized["wallet"] or wallet_address,
            normalized["ts"],
            normalized["condition_id"],
            normalized["token_id"],
            normalized["side"],
            normalized["price"],
            normalized["size"],
        ))
    
    print(f"   ✓ Stored trades in database")
    return len(trades)


def main(wallet_address: str = None):
    print("\n" + "="*60)
    print("🔍 WALLET CLONER")
    print("="*60)
    
    # Initialize
    db.initialize()
    
    # Get wallet address
    if not wallet_address:
        # Try to find from leaderboard
        print("\n📊 Fetching top crypto traders...")
        data_api = DataAPIClient()
        
        try:
            leaders = data_api.get_top_crypto_traders(limit=10)
            
            if leaders:
                print("\nTop wallets:")
                for i, leader in enumerate(leaders[:5]):
                    addr = leader.get("address", leader.get("user", "unknown"))
                    pnl = leader.get("pnl", 0)
                    print(f"  {i+1}. {addr[:16]}... PnL: ${pnl:,.2f}")
                
                wallet_address = leaders[0].get("address") or leaders[0].get("user")
            else:
                print("⚠️  No leaderboard data available")
                print("   Provide wallet address: python run_wallet_cloner.py <address>")
                return
        
        except Exception as e:
            print(f"⚠️  Could not fetch leaderboard: {e}")
            print("   Provide wallet address: python run_wallet_cloner.py <address>")
            return
    
    print(f"\n🎯 Target wallet: {wallet_address}")
    
    # Step 1: Ingest trades
    print("\n[1/4] Ingesting wallet trades...")
    data_api = DataAPIClient()
    
    try:
        trade_count = ingest_wallet_trades(wallet_address, data_api)
    except Exception as e:
        print(f"⚠️  Could not fetch trades: {e}")
        print("   Using existing database trades...")
        trade_count = db.execute(
            "SELECT COUNT(*) as c FROM wallet_trades WHERE wallet = ?",
            (wallet_address,)
        )[0]["c"]
    
    if trade_count == 0:
        print("⚠️  No trades found for this wallet")
        return
    
    # Step 2: Analyze trades
    print("\n[2/4] Analyzing trade patterns...")
    analyzer = TradeAnalyzer(wallet_address)
    analyzer.load_trades()
    analyzer.reconstruct_positions()
    
    entry_stats = analyzer.analyze_entry_patterns()
    performance = analyzer.calculate_performance()
    
    print(f"   Total trades: {performance['total_trades']}")
    print(f"   Win rate: {performance['win_rate']:.1%}")
    print(f"   Total PnL: ${performance['total_pnl']:,.2f}")
    
    # Step 3: Extract logic
    print("\n[3/4] Extracting trading logic...")
    extractor = LogicExtractor(analyzer)
    strategy = extractor.extract_strategy()
    
    print(f"   Entry conditions: {len(strategy.entry_conditions)}")
    print(f"   Exit conditions: {len(strategy.exit_conditions)}")
    
    # Step 4: Verify
    print("\n[4/4] Verifying extracted strategy...")
    
    # Get time range
    ts_query = """
        SELECT MIN(ts) as start_ts, MAX(ts) as end_ts 
        FROM wallet_trades WHERE wallet = ?
    """
    ts_result = db.execute(ts_query, (wallet_address,))[0]
    
    if ts_result["start_ts"]:
        verifier = StrategyVerifier(strategy, wallet_address)
        report = verifier.verify(ts_result["start_ts"], ts_result["end_ts"])
        
        # Save verification report
        verifier.export_report(report, f"audit_logs/verification_{strategy.name}.json")
    
    # Save strategy
    loader = StrategyLoader("strategies")
    loader.save(strategy, format="json")
    
    print("\n" + "="*60)
    print("✅ WALLET CLONING COMPLETE")
    print("="*60)
    print(f"\nStrategy saved: strategies/{strategy.name}.json")
    print(f"Verification report: audit_logs/verification_{strategy.name}.json")


if __name__ == "__main__":
    wallet = sys.argv[1] if len(sys.argv) > 1 else None
    main(wallet)
