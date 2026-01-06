#!/usr/bin/env python3
"""
Complete Workflow Script

This is the MASTER script that guides you through the entire process:
1. Discover profitable wallets
2. Analyze their strategy
3. Understand the logic
4. Test with paper trading
5. Go live (when ready)

Run this first!
"""
import sys
from pathlib import Path

def print_banner():
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║                                                                   ║
║     🎯 POLYMARKET ALPHA MINER & WALLET CLONER                    ║
║                                                                   ║
║     Universal Strategy Discovery System                           ║
║     For Small Accounts ($100-500)                                 ║
║                                                                   ║
╚═══════════════════════════════════════════════════════════════════╝
""")

def print_menu():
    print("""
    ┌─────────────────────────────────────────────────────────────┐
    │  WORKFLOW STAGES                                            │
    ├─────────────────────────────────────────────────────────────┤
    │                                                             │
    │  [1] 🔍 DISCOVER - Find profitable wallets                  │
    │      Scans all market categories                            │
    │      No credentials needed                                  │
    │                                                             │
    │  [2] 🔬 ANALYZE - Deep dive on specific wallet              │
    │      Understand their strategy                              │
    │      No credentials needed                                  │
    │                                                             │
    │  [3] 📊 MONITOR - Watch a wallet in real-time               │
    │      See trades as they happen                              │
    │      No credentials needed                                  │
    │                                                             │
    │  [4] 📝 PAPER TRADE - Practice without real money           │
    │      Track your predictions                                 │
    │      No credentials needed                                  │
    │                                                             │
    │  [5] 🔑 SETUP CREDENTIALS - Prepare for live trading        │
    │      Guide to get API keys                                  │
    │                                                             │
    │  [6] 🚀 GO LIVE - Execute real trades                       │
    │      Requires credentials                                   │
    │                                                             │
    │  [7] ❓ HELP - Explain the strategy                         │
    │                                                             │
    │  [0] 🚪 EXIT                                                 │
    │                                                             │
    └─────────────────────────────────────────────────────────────┘
    """)

def run_discovery():
    print("\n🔍 Starting Discovery...\n")
    import subprocess
    subprocess.run([sys.executable, "run_discovery.py"])

def run_analysis():
    target = input("\n    Enter wallet username or address: ").strip()
    if target:
        import subprocess
        subprocess.run([sys.executable, "run_analyze_wallet.py", target])
    else:
        print("    No target entered.")

def run_monitor():
    print("\n📊 Starting Real-time Monitor...\n")
    import subprocess
    subprocess.run([sys.executable, "run_monitor.py"])

def run_paper_trade():
    print("\n📝 Starting Paper Trading...\n")
    import subprocess
    subprocess.run([sys.executable, "run_paper_trading.py"])

def show_credentials():
    sys.path.insert(0, str(Path(__file__).parent / "src"))
    from src.credentials import CredentialManager
    
    creds = CredentialManager()
    creds.print_setup_guide()
    creds.print_what_works_without_creds()

def show_go_live():
    print("""
    🚀 GOING LIVE
    
    Before going live, you should have:
    
    ✓ API credentials configured (.env file)
    ✓ At least 1 week of paper trading
    ✓ > 60% accuracy in paper trading
    ✓ Clear understanding of the strategy
    
    Live Trading Checklist:
    
    [ ] Start with minimum bet ($5-10)
    [ ] Set daily loss limit (10% of account)
    [ ] Only trade patterns you understand
    [ ] Never chase losses
    [ ] Take breaks after losses
    
    Ready to start?
    
    Run: python run_wallet_cloner.py <target_wallet>
    
    ⚠️  WARNING: Real money at risk!
    Only trade what you can afford to lose.
    """)

def show_help():
    print("""
    ❓ STRATEGY EXPLANATION
    
    ════════════════════════════════════════════════════════════
    
    WHAT THIS SYSTEM DOES:
    
    1. Alpha Miner
       - Finds profitable patterns in market data
       - Discovers timing edges (like reset-lag)
       - Works without looking at other wallets
    
    2. Wallet Cloner
       - Reverse-engineers a profitable wallet's strategy
       - Turns their trades into rules you can follow
       - Lets you copy their edge
    
    ════════════════════════════════════════════════════════════
    
    THE 15-MINUTE BTC/ETH STRATEGY:
    
    This is a specific strategy some wallets use:
    
    • Every 15 minutes, the Up/Down markets reset
    • The resolution price = Binance price at reset time
    • But Polymarket prices LAG behind Binance by seconds
    
    The Edge:
    • Watch Binance real-time
    • If BTC moves significantly in last 30 seconds
    • The Polymarket price hasn't adjusted yet
    • Buy the direction it will resolve to
    
    Example:
    • 12:14:45 - BTC jumps from $100,000 to $100,500
    • Market will resolve to "Up" at 12:15:00
    • Polymarket still shows "Up" at 45 cents (should be 95+)
    • Buy "Up" at 45 cents → settles at $1.00 = 122% profit
    
    ════════════════════════════════════════════════════════════
    
    WHY UNDERSTAND FIRST:
    
    Copying blindly = gambling
    Understanding first = investing
    
    When you understand the strategy:
    - You know WHEN to trade (not just follow)
    - You can adapt when conditions change
    - You won't panic during drawdowns
    - You can improve the strategy
    
    ════════════════════════════════════════════════════════════
    """)

def main():
    print_banner()
    
    while True:
        print_menu()
        
        try:
            choice = input("    Enter choice [0-7]: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\n    Goodbye! 👋\n")
            break
        
        if choice == "0":
            print("\n    Goodbye! 👋\n")
            break
        elif choice == "1":
            run_discovery()
        elif choice == "2":
            run_analysis()
        elif choice == "3":
            run_monitor()
        elif choice == "4":
            run_paper_trade()
        elif choice == "5":
            show_credentials()
        elif choice == "6":
            show_go_live()
        elif choice == "7":
            show_help()
        else:
            print("\n    Invalid choice. Please enter 0-7.\n")
        
        input("\n    Press Enter to continue...")

if __name__ == "__main__":
    main()
