#!/usr/bin/env python3
"""
Run Maker Rebates Bot

This script provides a command-line interface to run the Delta-Neutral Maker
Rebates Bot on Polymarket 15-minute crypto markets.

Usage:
    # Paper trading (default, safe)
    python scripts/run_maker_bot.py

    # Check status (non-blocking, shows current state)
    python scripts/run_maker_bot.py --status

    # Run for a specific duration (in minutes)
    python scripts/run_maker_bot.py --duration 60

    # Live trading (CAUTION - requires proper credentials)
    python scripts/run_maker_bot.py --live

    # Activate kill switch (emergency stop)
    python scripts/run_maker_bot.py --kill

    # Deactivate kill switch (resume trading)
    python scripts/run_maker_bot.py --resume

    # Custom position size
    python scripts/run_maker_bot.py --size 25

    # Verbose output
    python scripts/run_maker_bot.py --verbose

Safety Notes:
    - Paper mode is the default. Real money is NEVER risked unless --live is passed.
    - Kill switch: Create .kill_switch file in project root to halt all trading.
    - Always test with paper trading before going live.
    - Live mode requires POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER in .env

Environment Variables:
    POLYMARKET_PRIVATE_KEY - Private key for signing transactions
    POLYMARKET_FUNDER - Funder address for trades
    POLYMARKET_API_KEY - Optional API key
    TRADING_MODE - "paper" (default) or "live"

Example Workflow:
    1. Run paper trading for 1 hour:
       python scripts/run_maker_bot.py --duration 60

    2. Check status:
       python scripts/run_maker_bot.py --status

    3. If profitable in paper mode, consider live (with small size):
       python scripts/run_maker_bot.py --live --size 10

Author: Polymarket Research Team
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.maker.bot import MakerBot
from src.maker.risk_limits import RiskMonitor
from src.config import (
    PROJECT_ROOT,
    POLYMARKET_PRIVATE_KEY,
    POLYMARKET_FUNDER,
    TRADING_MODE,
    MAKER_POSITION_SIZE,
    MAKER_MAX_CONCURRENT,
    MAX_DAILY_LOSS,
)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for the bot."""
    level = logging.DEBUG if verbose else logging.INFO

    # Create formatters
    console_format = "%(asctime)s [%(levelname)s] %(message)s"
    file_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(logging.Formatter(console_format, datefmt="%H:%M:%S"))

    # File handler
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"maker_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(file_format))

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    # Reduce noise from external libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)

    print(f"Logs will be written to: {log_file}")


def get_clob_client():
    """
    Initialize the Polymarket CLOB client for live trading.

    Returns:
        ClobClient instance or None if credentials not configured
    """
    if not POLYMARKET_PRIVATE_KEY or not POLYMARKET_FUNDER:
        return None

    try:
        from py_clob_client.client import ClobClient
        from py_clob_client.clob_types import ApiCreds

        # Build client with API credentials
        client = ClobClient(
            host="https://clob.polymarket.com",
            chain_id=137,  # Polygon
            key=POLYMARKET_PRIVATE_KEY,
            funder=POLYMARKET_FUNDER,
        )

        return client

    except ImportError:
        print("Error: py-clob-client not installed. Run: pip install py-clob-client")
        return None
    except Exception as e:
        print(f"Error initializing CLOB client: {e}")
        return None


def show_status() -> None:
    """Show current bot status without starting the bot."""
    print("\n" + "=" * 70)
    print("Maker Rebates Bot Status")
    print("=" * 70)

    # Check kill switch
    risk_monitor = RiskMonitor(project_root=PROJECT_ROOT)
    kill_switch_active = risk_monitor.check_kill_switch()

    print(f"\nKill Switch: {'ACTIVE (trading halted)' if kill_switch_active else 'Inactive'}")
    print(f"Kill Switch Path: {PROJECT_ROOT / '.kill_switch'}")

    # Check configuration
    print("\nConfiguration:")
    print(f"  Trading Mode: {TRADING_MODE}")
    print(f"  Position Size: ${MAKER_POSITION_SIZE}")
    print(f"  Max Concurrent: {MAKER_MAX_CONCURRENT}")
    print(f"  Max Daily Loss: ${MAX_DAILY_LOSS}")

    # Check credentials
    print("\nCredentials:")
    has_key = bool(POLYMARKET_PRIVATE_KEY)
    has_funder = bool(POLYMARKET_FUNDER)
    print(f"  Private Key: {'Configured' if has_key else 'NOT CONFIGURED'}")
    print(f"  Funder Address: {'Configured' if has_funder else 'NOT CONFIGURED'}")
    print(f"  Live Trading: {'Ready' if (has_key and has_funder) else 'NOT AVAILABLE'}")

    # Check paper trading log
    paper_log = PROJECT_ROOT / "data" / "maker_bot_trades.jsonl"
    if paper_log.exists():
        try:
            with open(paper_log) as f:
                trades = [json.loads(line) for line in f]

            print("\nPaper Trading History:")
            print(f"  Total trades logged: {len(trades)}")

            if trades:
                last_trade = trades[-1]
                print(f"  Last trade: {last_trade.get('timestamp', 'Unknown')}")
                print(f"  Last event: {last_trade.get('event', 'Unknown')}")
        except Exception as e:
            print(f"\nError reading paper trading log: {e}")
    else:
        print("\nPaper Trading History: No trades yet")

    # Try to find active markets
    print("\nMarket Discovery:")
    try:
        from src.maker.market_finder import MarketFinder

        finder = MarketFinder(assets=["btc", "eth"])
        markets = finder.find_active_markets()

        print(f"  Active 15-minute markets: {len(markets)}")
        for market in markets:
            print(f"    - {market.slug}")
            print(f"      UP: {market.yes_price:.3f} | DOWN: {market.no_price:.3f}")
            print(f"      Time left: {market.seconds_to_resolution}s")
    except Exception as e:
        print(f"  Error finding markets: {e}")

    print("\n" + "=" * 70)


def activate_kill_switch(reason: str = "CLI activation") -> None:
    """Activate the kill switch to halt all trading."""
    risk_monitor = RiskMonitor(project_root=PROJECT_ROOT)
    risk_monitor.activate_kill_switch(reason)
    print(f"\nKill switch ACTIVATED: {reason}")
    print(f"Kill switch file: {PROJECT_ROOT / '.kill_switch'}")
    print("\nAll trading has been halted.")
    print("To resume, run: python scripts/run_maker_bot.py --resume")


def deactivate_kill_switch() -> None:
    """Deactivate the kill switch to allow trading."""
    risk_monitor = RiskMonitor(project_root=PROJECT_ROOT)
    if risk_monitor.deactivate_kill_switch():
        print("\nKill switch DEACTIVATED")
        print("Trading is now allowed.")
    else:
        print("\nFailed to deactivate kill switch.")
        print(f"Try manually removing: {PROJECT_ROOT / '.kill_switch'}")


async def run_bot(
    paper_mode: bool,
    duration_minutes: int,
    position_size: float,
    max_concurrent: int,
    verbose: bool,
) -> None:
    """
    Run the maker bot.

    Args:
        paper_mode: If True, run in paper trading mode
        duration_minutes: How long to run (0 = unlimited)
        position_size: Position size per leg in USD
        max_concurrent: Maximum concurrent positions
        verbose: Enable verbose logging
    """
    mode_str = "PAPER" if paper_mode else "LIVE"

    print("\n" + "=" * 70)
    print(f"Starting Maker Rebates Bot ({mode_str} MODE)")
    print("=" * 70)

    if not paper_mode:
        print("\n" + "!" * 70)
        print("WARNING: LIVE TRADING MODE")
        print("Real money will be at risk!")
        print("!" * 70)

        # Confirm live trading
        confirm = input("\nType 'LIVE' to confirm live trading: ")
        if confirm != "LIVE":
            print("Live trading cancelled.")
            return

    print(f"\nConfiguration:")
    print(f"  Mode: {mode_str}")
    print(f"  Position Size: ${position_size}")
    print(f"  Max Concurrent: {max_concurrent}")
    print(f"  Duration: {duration_minutes} minutes" if duration_minutes > 0 else "  Duration: Unlimited")
    print(f"\nPress Ctrl+C to stop\n")

    # Get CLOB client for live mode
    clob_client = None
    if not paper_mode:
        clob_client = get_clob_client()
        if clob_client is None:
            print("Error: Could not initialize CLOB client for live trading.")
            print("Check that POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER are set.")
            return

    # Create bot
    bot = MakerBot(
        paper_mode=paper_mode,
        clob_client=clob_client,
        position_size=position_size,
        max_concurrent=max_concurrent,
    )

    # Run bot
    try:
        if duration_minutes > 0:
            # Run for specified duration
            duration_seconds = duration_minutes * 60
            bot_task = bot.start()

            try:
                await asyncio.wait_for(bot_task, timeout=duration_seconds)
            except asyncio.TimeoutError:
                print(f"\nDuration limit reached ({duration_minutes} minutes)")
        else:
            # Run indefinitely
            await bot.run()

    except KeyboardInterrupt:
        print("\nShutdown requested by user...")
    finally:
        bot.stop()

        # Print final status
        print("\n" + "=" * 70)
        print("Final Status")
        print("=" * 70)

        status = bot.get_status()
        bot_state = status["bot_state"]

        print(f"\nSession Summary:")
        print(f"  Mode: {mode_str}")
        print(f"  Cycles completed: {bot_state['cycle_count']}")
        print(f"  Positions opened: {bot_state['positions_opened']}")
        print(f"  Positions closed: {bot_state['positions_closed']}")
        print(f"  Total P&L: ${bot_state['total_pnl']}")
        print(f"  Total Rebates: ${bot_state['total_rebates']}")
        print(f"  Uptime: {bot_state['uptime_seconds']} seconds")

        if bot_state.get("last_error"):
            print(f"\nLast Error: {bot_state['last_error']}")

        if paper_mode:
            paper_stats = status.get("paper_stats")
            if paper_stats:
                print(f"\nPaper Trading Stats:")
                print(f"  Balance: ${paper_stats['current_balance']}")
                print(f"  Return: {paper_stats['return_pct']}%")
                print(f"  Win Rate: {paper_stats['win_rate']}")

        print("\n" + "=" * 70)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Run the Delta-Neutral Maker Rebates Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_maker_bot.py                    # Paper trading (default)
  python scripts/run_maker_bot.py --status           # Check status
  python scripts/run_maker_bot.py --duration 60      # Run for 60 minutes
  python scripts/run_maker_bot.py --live             # Live trading (CAUTION)
  python scripts/run_maker_bot.py --kill             # Activate kill switch
  python scripts/run_maker_bot.py --resume           # Deactivate kill switch
        """,
    )

    # Mode arguments
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (CAUTION: real money at risk)",
    )
    mode_group.add_argument(
        "--status",
        action="store_true",
        help="Show current bot status and exit",
    )
    mode_group.add_argument(
        "--kill",
        action="store_true",
        help="Activate kill switch to halt all trading",
    )
    mode_group.add_argument(
        "--resume",
        action="store_true",
        help="Deactivate kill switch to allow trading",
    )

    # Configuration arguments
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        metavar="MINUTES",
        help="How long to run in minutes (0 = unlimited, default: 0)",
    )
    parser.add_argument(
        "--size",
        type=float,
        default=MAKER_POSITION_SIZE,
        metavar="USD",
        help=f"Position size per leg in USD (default: {MAKER_POSITION_SIZE})",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=MAKER_MAX_CONCURRENT,
        metavar="N",
        help=f"Maximum concurrent positions (default: {MAKER_MAX_CONCURRENT})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Handle status command
    if args.status:
        show_status()
        return

    # Handle kill switch commands
    if args.kill:
        activate_kill_switch("CLI --kill flag")
        return

    if args.resume:
        deactivate_kill_switch()
        return

    # Setup logging
    setup_logging(verbose=args.verbose)

    # Determine mode
    paper_mode = not args.live

    # Run bot
    try:
        asyncio.run(
            run_bot(
                paper_mode=paper_mode,
                duration_minutes=args.duration,
                position_size=args.size,
                max_concurrent=args.max_concurrent,
                verbose=args.verbose,
            )
        )
    except Exception as e:
        print(f"\nFatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
