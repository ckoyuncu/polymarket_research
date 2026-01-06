#!/usr/bin/env python3
"""
Post-Resolution Bot Runner

CLI interface for the post-resolution spread capture bot.

Usage:
    # Paper trading (safe, default)
    python scripts/run_post_resolution_bot.py

    # Live trading
    python scripts/run_post_resolution_bot.py --live --capital 250

    # Check status
    python scripts/run_post_resolution_bot.py --status

    # Single cycle (for testing)
    python scripts/run_post_resolution_bot.py --single
"""

import os
import sys
import time
import signal
import argparse
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.arbitrage.post_resolution_bot import PostResolutionBot, BotConfig


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    print("\nShutting down...")
    global bot
    if bot:
        bot.stop()
    sys.exit(0)


bot = None


def run_bot(args):
    """Run the bot."""
    global bot

    # Create config
    config = BotConfig(
        starting_capital=args.capital,
        min_edge_pct=args.min_edge / 100,
        target_edge_pct=args.target_edge / 100,
        max_position_pct=args.max_position / 100,
        max_daily_loss=args.capital * 0.5,  # 50% daily loss limit
    )

    # Create bot
    bot = PostResolutionBot(
        config=config,
        live=args.live,
    )

    # Load previous state
    bot.load_state()

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Print startup info
    print("=" * 60)
    print("POST-RESOLUTION SPREAD CAPTURE BOT")
    print("=" * 60)
    print(f"Mode: {'LIVE' if args.live else 'PAPER'}")
    print(f"Capital: ${args.capital:.2f}")
    print(f"Min Edge: {args.min_edge:.2f}%")
    print(f"Target Edge: {args.target_edge:.2f}%")
    print(f"Max Position: {args.max_position:.0f}%")
    print(f"Cycle Interval: {args.interval}s")
    print("=" * 60)

    if args.live:
        print("\n** LIVE TRADING MODE **")
        print("Real money will be used!")
        if not args.yes:
            confirm = input("Type 'yes' to confirm: ")
            if confirm.lower() != "yes":
                print("Aborted.")
                return 1

    # Start bot
    bot.start()

    if args.single:
        # Single cycle mode
        print("\nRunning single cycle...")
        bot.run_cycle()
        bot.print_status()
        bot.stop()
        return 0

    # Main loop
    print(f"\nStarted at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print("Press Ctrl+C to stop\n")

    cycle_count = 0
    last_status_time = 0

    try:
        while True:
            cycle_count += 1

            # Run cycle
            try:
                bot.run_cycle()
            except Exception as e:
                print(f"Cycle error: {e}")

            # Print status every 5 minutes
            now = time.time()
            if now - last_status_time > 300:
                bot.print_status()
                last_status_time = now

            # Save state every cycle
            bot.save_state()

            # Wait for next cycle
            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nInterrupted")
    finally:
        bot.stop()

    return 0


def show_status():
    """Show bot status."""
    data_dir = Path("data/post_resolution")
    state_file = data_dir / "bot_state.json"

    if not state_file.exists():
        print("No bot state found. Bot has not run yet.")
        return 1

    import json
    with open(state_file) as f:
        state = json.load(f)

    print("=" * 60)
    print("BOT STATUS (from saved state)")
    print("=" * 60)
    print(f"Last updated: {state.get('timestamp', 'Unknown')}")
    print(f"Mode: {'LIVE' if state.get('live') else 'PAPER'}")
    print(f"\nCapital: ${state.get('capital', 0):.2f}")
    print(f"Daily P&L: ${state.get('daily_pnl', 0):.2f}")

    positions = state.get("positions", {})
    print(f"Open positions: {len(positions)}")

    if positions:
        for pid, pos in positions.items():
            print(f"  {pos['outcome']}: ${pos['entry_price'] * pos['size']:.2f}")

    stats = state.get("stats", {})
    print(f"\nTrading Stats:")
    print(f"  Total trades: {stats.get('total_trades', 0)}")
    total = stats.get('total_trades', 0)
    wins = stats.get('winning_trades', 0)
    print(f"  Win rate: {wins/total*100:.1f}%" if total > 0 else "  Win rate: N/A")
    print(f"  Volume: ${stats.get('total_volume', 0):.2f}")
    net = stats.get('total_profit', 0) - stats.get('total_fees', 0)
    print(f"  Net P&L: ${net:.2f}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Post-Resolution Spread Capture Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Paper trading (safe)
    python scripts/run_post_resolution_bot.py

    # Live trading with $250
    python scripts/run_post_resolution_bot.py --live --capital 250 --yes

    # Check status
    python scripts/run_post_resolution_bot.py --status

    # Test single cycle
    python scripts/run_post_resolution_bot.py --single
        """
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help="Enable live trading (default: paper)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=250.0,
        help="Starting capital in USD (default: 250)"
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=0.3,
        help="Minimum edge to trade in %% (default: 0.3)"
    )
    parser.add_argument(
        "--target-edge",
        type=float,
        default=0.5,
        help="Target edge for exit in %% (default: 0.5)"
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=10.0,
        help="Max position size as %% of capital (default: 10)"
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Seconds between cycles (default: 10)"
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Run single cycle and exit"
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and exit"
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation for live trading"
    )

    args = parser.parse_args()

    if args.status:
        return show_status()

    return run_bot(args)


if __name__ == "__main__":
    sys.exit(main())
