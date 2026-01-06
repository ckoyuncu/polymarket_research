#!/usr/bin/env python3
"""
Arbitrage Bot Runner

Runs the high-frequency arbitrage bot that exploits price lag
between Binance and Polymarket 15-minute resolution markets.

Usage:
    # Paper trading (safe)
    python run_arbitrage_bot.py

    # Live trading (requires credentials)
    python run_arbitrage_bot.py --live

    # Custom settings
    python run_arbitrage_bot.py --live --max-position 100 --min-edge 0.01

    # Status check
    python run_arbitrage_bot.py --status
"""
import os
import sys
import argparse
import time
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.api.data_api import DataAPIClient
from src.trading.executor import create_executor
from src.arbitrage.bot import ArbitrageBot


def load_config() -> dict:
    """Load configuration from environment or .env file."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Load Account88888 strategy config if available
    strategy_config_path = Path(__file__).parent.parent / "config" / "account88888_strategy.json"
    strategy_config = {}

    if strategy_config_path.exists():
        try:
            import json
            with open(strategy_config_path) as f:
                strategy_config = json.load(f)
                print(f"✅ Loaded Account88888 strategy configuration")
        except Exception as e:
            print(f"⚠️  Could not load strategy config: {e}")

    # Merge environment variables with strategy config defaults
    # ALIGNED WITH ACCOUNT88888 PROPORTIONS (scaled to $250 budget)
    return {
        "min_edge": float(os.getenv("ARB_MIN_EDGE", "0.005")),  # 0.5%
        "min_position_size": float(os.getenv("ARB_MIN_POSITION_SIZE", "10")),  # $10 (4% of $250)
        "max_position_size": float(os.getenv("ARB_MAX_POSITION_SIZE", "50")),  # $50 (20% of $250)
        "max_daily_trades": int(os.getenv("ARB_MAX_DAILY_TRADES", "200")),  # Account88888 does 200/day
        "execution_window": (
            int(os.getenv("ARB_EXECUTION_WINDOW_START", "2")),
            int(os.getenv("ARB_EXECUTION_WINDOW_END", "30"))
        ),
        "min_liquidity": float(os.getenv("ARB_MIN_LIQUIDITY", "500")),  # $500
        "min_confidence": float(os.getenv("ARB_MIN_CONFIDENCE", "0.6")),  # 60%
        "target_win_loss_ratio": float(os.getenv("ARB_TARGET_WIN_LOSS_RATIO", "4.0")),  # 4:1
        "starting_capital": float(os.getenv("ARB_STARTING_CAPITAL", "250")),  # $250
        "enable_compounding": os.getenv("ARB_ENABLE_COMPOUNDING", "true").lower() == "true",
        "max_risk_per_trade_pct": float(os.getenv("ARB_MAX_RISK_PCT", "0.04")),  # 4% (Account88888 pattern)
        "strategy_config": strategy_config,  # Full strategy config for reference
        # Circuit breakers - BASED ON COMPLETE 2269 TRADE ANALYSIS
        # Simulated 23% win rate: avg max streak 25.8, 95th pct 36, 99th pct 42
        "max_daily_loss": float(os.getenv("ARB_MAX_DAILY_LOSS", "125")),  # $125 (50% - let variance play out fully)
        "max_consecutive_losses": int(os.getenv("ARB_MAX_CONSECUTIVE_LOSSES", "25")),  # 25 (avg max streak at 23% WR)
        "min_bankroll": float(os.getenv("ARB_MIN_BANKROLL", "50")),  # $50 (20% - real stop)
        "cooldown_after_loss": int(os.getenv("ARB_COOLDOWN_WINDOWS", "0")),  # 0 - no cooldown, trade through
    }


def print_header():
    """Print bot header."""
    print("\n" + "="*70)
    print("🤖 POLYMARKET ARBITRAGE BOT")
    print("="*70)
    print("Strategy: Binance → Polymarket 15-minute window arbitrage")
    print("Status: Alpha - Use small amounts and monitor closely")
    print("="*70 + "\n")


def run_bot(args):
    """Run the arbitrage bot."""
    print_header()

    # Load config
    config = load_config()

    # Override with CLI args
    if args.min_edge:
        config["min_edge"] = args.min_edge
    if args.max_position:
        config["max_position_size"] = args.max_position
    if args.max_trades:
        config["max_daily_trades"] = args.max_trades
    if args.capital:
        config["starting_capital"] = args.capital
    if args.no_compound:
        config["enable_compounding"] = False

    # Circuit breaker overrides
    if args.max_daily_loss:
        config["max_daily_loss"] = args.max_daily_loss
    if args.max_losses:
        config["max_consecutive_losses"] = args.max_losses
    if args.min_bankroll:
        config["min_bankroll"] = args.min_bankroll
    if args.cooldown is not None:
        config["cooldown_after_loss"] = args.cooldown

    # Create API client
    data_api = DataAPIClient()

    # Create executor
    executor = None
    if args.live:
        print("⚠️  LIVE TRADING MODE")
        print("   Make sure you have configured API credentials in .env")
        print("   Starting in 5 seconds... (Ctrl+C to cancel)\n")
        time.sleep(5)

        executor = create_executor(
            live=True,
            max_order_size=config["max_position_size"]
        )

        if not executor.is_ready():
            print(f"❌ Executor not ready: {executor.executor.get_error()}")
            print("\nPlease configure your Polymarket API credentials:")
            print("  POLYMARKET_API_KEY=your_key")
            print("  POLYMARKET_API_SECRET=your_secret")
            print("  POLYMARKET_PASSPHRASE=your_passphrase")
            sys.exit(1)

        print("✅ Executor ready\n")
    else:
        print("📝 PAPER TRADING MODE")
        print("   No real money will be used")
        print("   Use --live flag for real trading\n")

    # Print configuration
    print("--- Configuration (Account88888 Pattern) ---")
    print(f"Starting capital: ${config['starting_capital']:.2f}")
    print(f"Compounding: {'ENABLED' if config['enable_compounding'] else 'DISABLED'}")
    print(f"Max risk/trade: {config['max_risk_per_trade_pct']:.1%}")
    print(f"Min edge: {config['min_edge']:.2%}")
    print(f"Position sizing: ${config['min_position_size']:.0f}-${config['max_position_size']:.0f} (variable)")
    print(f"Max daily trades: {config['max_daily_trades']}")
    print(f"Min liquidity: ${config['min_liquidity']:.2f}")
    print(f"Target win/loss ratio: {config['target_win_loss_ratio']:.1f}:1")
    print(f"Execution window: {config['execution_window'][0]}-{config['execution_window'][1]}s before close")
    print()

    # Create bot
    bot = ArbitrageBot(
        data_api=data_api,
        executor=executor,
        dry_run=not args.live,
        min_edge=config["min_edge"],
        max_position_size=config["max_position_size"],
        max_daily_trades=config["max_daily_trades"],
        min_liquidity=config["min_liquidity"],
        starting_capital=config["starting_capital"],
        enable_compounding=config["enable_compounding"],
        max_risk_per_trade_pct=config["max_risk_per_trade_pct"],
        # Circuit breaker safety features
        max_daily_loss=config["max_daily_loss"],
        max_consecutive_losses=config["max_consecutive_losses"],
        min_bankroll=config["min_bankroll"],
        cooldown_after_loss=config["cooldown_after_loss"],
    )

    # Start bot
    print("Starting bot...")
    print("Press Ctrl+C to stop\n")

    try:
        bot.start()
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping bot...")
        bot.stop()

    # Print final stats
    print("\n--- Final Stats ---")
    bot.print_status()

    # Save report
    stats = bot.get_stats()
    report_path = Path("data/arbitrage/session_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)

    with open(report_path, 'w') as f:
        json.dump(stats, f, indent=2)

    print(f"\nSession report saved to: {report_path}")


def show_status():
    """Show bot status from saved state."""
    state_path = Path("data/arbitrage/bot_state.json")

    if not state_path.exists():
        print("No saved state found. Bot hasn't run yet.")
        return

    with open(state_path, 'r') as f:
        state = json.load(f)

    print("\n" + "="*60)
    print("ARBITRAGE BOT - LAST SESSION")
    print("="*60)

    stats = state.get("stats", {})

    print(f"\nTrades executed: {stats.get('trades_executed', 0)}")
    print(f"Trades won: {stats.get('trades_won', 0)}")
    print(f"Trades lost: {stats.get('trades_lost', 0)}")
    print(f"Total P&L: ${stats.get('total_pnl', 0):.2f}")

    total_completed = stats.get('trades_won', 0) + stats.get('trades_lost', 0)
    if total_completed > 0:
        win_rate = stats['trades_won'] / total_completed
        print(f"Win rate: {win_rate:.1%}")

    print(f"\nSignals generated: {stats.get('signals_generated', 0)}")
    print(f"Signals traded: {stats.get('signals_traded', 0)}")

    # Bankroll info
    bankroll = state.get("bankroll", {})
    if bankroll:
        print(f"\n--- Bankroll ---")
        print(f"Starting: ${bankroll.get('starting', 0):.2f}")
        print(f"Current: ${bankroll.get('current', 0):.2f}")
        starting = bankroll.get('starting', 1)
        current = bankroll.get('current', 0)
        if starting > 0:
            roi = (current / starting - 1) * 100
            print(f"ROI: {roi:+.1f}%")
        print(f"Drawdown: {bankroll.get('drawdown', 0):.1%}")

    # Circuit breaker status
    cb = state.get("circuit_breaker", {})
    if cb:
        print(f"\n--- Circuit Breakers ---")
        if cb.get("triggered"):
            print(f"🛑 TRIGGERED: {cb.get('reason', 'Unknown')}")
        else:
            print(f"Status: ✅ Active")
        print(f"Consecutive losses: {cb.get('consecutive_losses', 0)}")
        print(f"Daily loss: ${cb.get('daily_loss', 0):.2f}")
        if cb.get('cooldown_remaining', 0) > 0:
            print(f"Cooldown: {cb['cooldown_remaining']} window(s) remaining")

    # Recent trades
    trade_history = state.get("trade_history", [])
    if trade_history:
        print(f"\n--- Recent Trades ({len(trade_history)}) ---")
        for i, trade in enumerate(trade_history[-5:], 1):
            timestamp = time.strftime('%H:%M:%S', time.localtime(trade['timestamp']))
            action = trade['action']
            edge = trade['edge']
            confidence = trade['confidence']
            print(f"{i}. {timestamp} | {action:10s} | Edge: {edge:.2%} | Conf: {confidence:.2%}")

    print("="*60 + "\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket Arbitrage Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Paper trading (default)
  python run_arbitrage_bot.py

  # Live trading with default settings
  python run_arbitrage_bot.py --live

  # Live trading with custom settings
  python run_arbitrage_bot.py --live --max-position 100 --min-edge 0.01

  # Check status
  python run_arbitrage_bot.py --status

Environment Variables:
  ARB_MIN_EDGE           Minimum edge (default: 0.005 = 0.5%)
  ARB_MAX_POSITION_SIZE  Max position size in USD (default: 25)
  ARB_MAX_DAILY_TRADES   Max trades per day (default: 100)
  ARB_MIN_LIQUIDITY      Min market liquidity (default: 500)
  ARB_STARTING_CAPITAL   Starting bankroll (default: 250)

  Circuit Breakers:
  ARB_MAX_DAILY_LOSS     Stop if daily loss exceeds this (default: 50)
  ARB_MAX_CONSECUTIVE_LOSSES  Stop after N losses in a row (default: 5)
  ARB_MIN_BANKROLL       Stop if bankroll drops below this (default: 100)
  ARB_COOLDOWN_WINDOWS   Skip N windows after a loss (default: 1)

  API Credentials (required for live trading):
  POLYMARKET_API_KEY     Your Polymarket API key
  POLYMARKET_API_SECRET  Your Polymarket API secret
  POLYMARKET_PASSPHRASE  Your Polymarket passphrase
        """
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (default: paper trading)"
    )

    parser.add_argument(
        "--min-edge",
        type=float,
        metavar="PERCENT",
        help="Minimum edge to trade (e.g., 0.01 = 1%%)"
    )

    parser.add_argument(
        "--max-position",
        type=float,
        metavar="USD",
        help="Maximum position size in USD"
    )

    parser.add_argument(
        "--max-trades",
        type=int,
        metavar="N",
        help="Maximum trades per day"
    )

    parser.add_argument(
        "--capital",
        type=float,
        metavar="USD",
        help="Starting capital in USD (default: $250)"
    )

    parser.add_argument(
        "--no-compound",
        action="store_true",
        help="Disable compounding (fixed position sizes)"
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show status from last session"
    )

    # Circuit breaker arguments
    parser.add_argument(
        "--max-daily-loss",
        type=float,
        metavar="USD",
        help="Max daily loss before stopping (default: $50)"
    )

    parser.add_argument(
        "--max-losses",
        type=int,
        metavar="N",
        help="Max consecutive losses before stopping (default: 5)"
    )

    parser.add_argument(
        "--min-bankroll",
        type=float,
        metavar="USD",
        help="Stop if bankroll drops below this (default: $100)"
    )

    parser.add_argument(
        "--cooldown",
        type=int,
        metavar="N",
        help="Windows to skip after a loss (default: 1)"
    )

    args = parser.parse_args()

    if args.status:
        show_status()
    else:
        run_bot(args)


if __name__ == "__main__":
    main()
