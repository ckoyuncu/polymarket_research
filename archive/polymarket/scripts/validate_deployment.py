#!/usr/bin/env python3
"""
Pre-Deployment Validation Script

Runs comprehensive tests to ensure the arbitrage bot environment
is correctly configured and all components work properly.

Usage:
    python scripts/validate_deployment.py
    python scripts/validate_deployment.py --verbose
"""
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


class ValidationTest:
    """Base class for validation tests."""

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.passed = False
        self.error_message = ""

    def run(self, verbose: bool = False) -> bool:
        """Run the test. Override in subclasses."""
        raise NotImplementedError


class PythonVersionTest(ValidationTest):
    """Check Python version is 3.10+"""

    def __init__(self):
        super().__init__(
            "Python Version",
            "Verify Python version is 3.10 or higher"
        )

    def run(self, verbose: bool = False) -> bool:
        version = sys.version_info
        if verbose:
            print(f"  Found: Python {version.major}.{version.minor}.{version.micro}")

        if version.major == 3 and version.minor >= 10:
            self.passed = True
            return True
        else:
            self.error_message = f"Python {version.major}.{version.minor} is too old, need 3.10+"
            return False


class DependencyTest(ValidationTest):
    """Check all required dependencies are installed."""

    def __init__(self):
        super().__init__(
            "Dependencies",
            "Verify all required packages are installed"
        )

    def run(self, verbose: bool = False) -> bool:
        required = [
            ('websocket', 'websocket-client'),
            ('dotenv', 'python-dotenv'),
            ('pydantic', 'pydantic'),
            ('sqlalchemy', 'sqlalchemy'),
        ]

        missing = []
        for module_name, package_name in required:
            try:
                __import__(module_name)
                if verbose:
                    print(f"  ✓ {package_name}")
            except ImportError:
                missing.append(package_name)
                if verbose:
                    print(f"  ✗ {package_name} - MISSING")

        if missing:
            self.error_message = f"Missing packages: {', '.join(missing)}"
            return False

        self.passed = True
        return True


class BinanceFeedTest(ValidationTest):
    """Test Binance WebSocket connection."""

    def __init__(self):
        super().__init__(
            "Binance Feed",
            "Test real-time price feed from Binance"
        )

    def run(self, verbose: bool = False) -> bool:
        try:
            from src.feeds.binance_feed import BinanceFeed

            if verbose:
                print("  Starting Binance feed...")

            feed = BinanceFeed()
            prices_received = []

            def on_price(tick):
                prices_received.append(tick)

            feed.subscribe(on_price)
            feed.start()

            # Wait up to 5 seconds for prices
            timeout = 5
            start = time.time()
            while time.time() - start < timeout:
                if len(prices_received) >= 2:
                    break
                time.sleep(0.1)

            feed.stop()

            btc = feed.get_price('BTC')
            eth = feed.get_price('ETH')

            if verbose:
                print(f"  BTC: ${btc:,.2f}" if btc else "  BTC: Not received")
                print(f"  ETH: ${eth:,.2f}" if eth else "  ETH: Not received")
                print(f"  Updates: {len(prices_received)}")

            if btc and eth and len(prices_received) > 0:
                self.passed = True
                return True
            else:
                self.error_message = "Failed to receive price updates"
                return False

        except Exception as e:
            self.error_message = f"Error: {str(e)}"
            return False


class MarketCalendarTest(ValidationTest):
    """Test market calendar timing logic."""

    def __init__(self):
        super().__init__(
            "Market Calendar",
            "Verify 15-minute window tracking"
        )

    def run(self, verbose: bool = False) -> bool:
        try:
            from src.arbitrage.market_calendar import MarketCalendar, WindowPhase

            calendar = MarketCalendar()
            calendar.update()

            phase = calendar.get_phase()
            seconds_until = calendar.get_seconds_until_next()
            next_window = calendar.get_next_window()

            if verbose:
                print(f"  Current phase: {phase.value}")
                print(f"  Next window: {next_window.strftime('%H:%M:%S')} UTC")
                print(f"  Time until: {seconds_until:.1f}s")

            # Verify we got valid values
            if phase and seconds_until >= 0 and next_window:
                self.passed = True
                return True
            else:
                self.error_message = "Invalid calendar state"
                return False

        except Exception as e:
            self.error_message = f"Error: {str(e)}"
            return False


class DecisionEngineTest(ValidationTest):
    """Test decision engine logic."""

    def __init__(self):
        super().__init__(
            "Decision Engine",
            "Verify trade decision logic"
        )

    def run(self, verbose: bool = False) -> bool:
        try:
            from src.arbitrage.decision_engine import DecisionEngine, MarketState, TradeAction
            from datetime import datetime, timedelta

            engine = DecisionEngine(min_edge=0.005)

            # Test case: BTC above strike
            state = MarketState(
                asset="BTC",
                strike_price=95000,
                current_price=96000,  # 1000 above
                is_above_strike_question=True,
                yes_token_id="test_yes_token",
                no_token_id="test_no_token",
                yes_price=0.40,
                no_price=0.60,
                seconds_until_close=15.0,
                liquidity=1000,
            )

            signal = engine.analyze(state)

            if verbose:
                print(f"  Test case: BTC @ $96,000 vs $95,000 strike")
                print(f"  Action: {signal.action.value}")
                print(f"  Edge: {signal.edge*100:.2f}%" if signal.edge else "  Edge: N/A")

            # Should recommend buying YES
            if signal.action in [TradeAction.BUY_YES, TradeAction.HOLD]:
                self.passed = True
                return True
            else:
                self.error_message = f"Unexpected action: {signal.action}"
                return False

        except Exception as e:
            self.error_message = f"Error: {str(e)}"
            return False


class BotStartupTest(ValidationTest):
    """Test bot can start without errors."""

    def __init__(self):
        super().__init__(
            "Bot Startup",
            "Verify bot initializes correctly"
        )

    def run(self, verbose: bool = False) -> bool:
        try:
            # Import will fail if there are syntax errors
            from src.arbitrage.bot import ArbitrageBot
            from src.api.data_api import DataAPIClient

            if verbose:
                print("  Creating bot instance...")

            data_api = DataAPIClient()
            bot = ArbitrageBot(
                data_api=data_api,
                executor=None,  # Paper trading
                dry_run=True,
                min_edge=0.005,
            )

            if verbose:
                print("  ✓ Bot initialized successfully")

            self.passed = True
            return True

        except Exception as e:
            self.error_message = f"Error: {str(e)}"
            return False


class FileStructureTest(ValidationTest):
    """Verify all required files exist."""

    def __init__(self):
        super().__init__(
            "File Structure",
            "Check all required files are present"
        )

    def run(self, verbose: bool = False) -> bool:
        root = Path(__file__).parent.parent

        required_files = [
            "src/feeds/__init__.py",
            "src/feeds/binance_feed.py",
            "src/arbitrage/__init__.py",
            "src/arbitrage/market_calendar.py",
            "src/arbitrage/market_scanner.py",
            "src/arbitrage/decision_engine.py",
            "src/arbitrage/bot.py",
            "src/api/data_api.py",
            "src/trading/executor.py",
            "scripts/run_arbitrage_bot.py",
            ".env.example",
        ]

        missing = []
        for file_path in required_files:
            full_path = root / file_path
            if full_path.exists():
                if verbose:
                    print(f"  ✓ {file_path}")
            else:
                missing.append(file_path)
                if verbose:
                    print(f"  ✗ {file_path} - MISSING")

        if missing:
            self.error_message = f"Missing files: {', '.join(missing)}"
            return False

        self.passed = True
        return True


class DirectoriesTest(ValidationTest):
    """Verify required directories exist."""

    def __init__(self):
        super().__init__(
            "Directories",
            "Check data and log directories exist"
        )

    def run(self, verbose: bool = False) -> bool:
        root = Path(__file__).parent.parent

        required_dirs = ["data", "logs"]
        created = []

        for dir_name in required_dirs:
            dir_path = root / dir_name
            if not dir_path.exists():
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    created.append(dir_name)
                    if verbose:
                        print(f"  + Created {dir_name}/")
                except Exception as e:
                    self.error_message = f"Failed to create {dir_name}/: {e}"
                    return False
            else:
                if verbose:
                    print(f"  ✓ {dir_name}/")

        if created and not verbose:
            print(f"  Created: {', '.join(created)}")

        self.passed = True
        return True


def run_all_tests(verbose: bool = False) -> Tuple[int, int]:
    """Run all validation tests."""

    tests = [
        PythonVersionTest(),
        DependencyTest(),
        FileStructureTest(),
        DirectoriesTest(),
        BinanceFeedTest(),
        MarketCalendarTest(),
        DecisionEngineTest(),
        BotStartupTest(),
    ]

    print(f"\n{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}🔍 ARBITRAGE BOT DEPLOYMENT VALIDATION{RESET}")
    print(f"{BLUE}{'='*70}{RESET}\n")

    passed = 0
    failed = 0

    for i, test in enumerate(tests, 1):
        print(f"{i}. {test.name}: {test.description}")

        try:
            result = test.run(verbose=verbose)

            if result:
                print(f"   {GREEN}✅ PASSED{RESET}")
                passed += 1
            else:
                print(f"   {RED}❌ FAILED: {test.error_message}{RESET}")
                failed += 1

        except Exception as e:
            print(f"   {RED}❌ EXCEPTION: {str(e)}{RESET}")
            failed += 1

        print()

    return passed, failed


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate arbitrage bot deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed output for each test"
    )

    args = parser.parse_args()

    passed, failed = run_all_tests(verbose=args.verbose)

    # Print summary
    print(f"{BLUE}{'='*70}{RESET}")
    print(f"{BLUE}SUMMARY{RESET}")
    print(f"{BLUE}{'='*70}{RESET}")
    print(f"Total tests: {passed + failed}")
    print(f"{GREEN}Passed: {passed}{RESET}")
    if failed > 0:
        print(f"{RED}Failed: {failed}{RESET}")
    else:
        print(f"Failed: {failed}")
    print()

    if failed == 0:
        print(f"{GREEN}✅ ALL TESTS PASSED - Ready for deployment!{RESET}\n")
        sys.exit(0)
    else:
        print(f"{RED}❌ SOME TESTS FAILED - Fix issues before deploying{RESET}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
