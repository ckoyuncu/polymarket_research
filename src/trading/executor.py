"""
Live Trading Executor

Handles order execution via the Polymarket CLOB API using py-clob-client.
Supports:
- FOK orders (Fill or Kill) for arbitrage speed
- Market orders
- Limit orders
- Order cancellation
- Balance checks

Safety Features:
- 5s timeout on all API calls
- Retry with exponential backoff (3 attempts)
- Kill switch file check (.kill_switch)
- Slippage warning logging (>1%)

IMPORTANT: Requires credentials to be configured in .env file:
- POLYMARKET_PRIVATE_KEY: Your wallet private key
- POLYMARKET_FUNDER: Your proxy wallet address (holds funds)
"""
import os
import time
import json
import logging
from typing import Dict, List, Optional, Tuple, Callable, Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from functools import wraps

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    RetryError,
)

from ..config import DATA_DIR
from .balance_checker import BalanceChecker, get_usdc_balance, check_sufficient_funds

# Set up logging
logger = logging.getLogger(__name__)

# Kill switch file path
KILL_SWITCH_FILE = Path(".kill_switch")

# API timeout in seconds
API_TIMEOUT = 5.0

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 0.5  # seconds
RETRY_MAX_WAIT = 2.0  # seconds

# Slippage threshold for warnings
SLIPPAGE_WARNING_THRESHOLD = 0.01  # 1%

# Set up logging
logger = logging.getLogger(__name__)

# Kill switch file path
KILL_SWITCH_FILE = Path(".kill_switch")

# API timeout in seconds
API_TIMEOUT = 5.0

# Retry configuration
MAX_RETRY_ATTEMPTS = 3
RETRY_MIN_WAIT = 0.5  # seconds
RETRY_MAX_WAIT = 2.0  # seconds

# Slippage threshold for warnings
SLIPPAGE_WARNING_THRESHOLD = 0.01  # 1%


class OrderType(Enum):
    """Order types."""
    MARKET = "market"
    LIMIT = "limit"
    GTC = "GTC"  # Good til cancelled
    FOK = "FOK"  # Fill or kill (entire order or cancel)
    GTD = "GTD"  # Good til date


class OrderSide(Enum):
    """Order side."""
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass
class OrderResult:
    """Result of order placement."""
    success: bool
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_size: float = 0.0
    filled_price: float = 0.0
    message: str = ""
    raw_response: Dict = None

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "order_id": self.order_id,
            "status": self.status.value,
            "filled_size": self.filled_size,
            "filled_price": self.filled_price,
            "message": self.message
        }


@dataclass
class Balance:
    """Account balance."""
    available: float = 0.0
    locked: float = 0.0
    total: float = 0.0

    @property
    def usable(self) -> float:
        """Amount available for trading."""
        return self.available


class KillSwitchError(Exception):
    """Raised when kill switch is activated."""
    pass


class APITimeoutError(Exception):
    """Raised when API call times out."""
    pass


def check_kill_switch() -> bool:
    """
    Check if kill switch file exists.

    Returns:
        True if kill switch is active (trading should stop)
    """
    return KILL_SWITCH_FILE.exists()


def _check_slippage(expected_price: float, filled_price: float, side: str) -> None:
    """
    Check for slippage and log warnings if above threshold.

    Args:
        expected_price: The price we expected to get
        filled_price: The actual price we received
        side: Order side ("BUY" or "SELL")
    """
    if expected_price <= 0 or filled_price <= 0:
        return

    slippage = abs(filled_price - expected_price) / expected_price

    if slippage > SLIPPAGE_WARNING_THRESHOLD:
        # Determine if slippage was adverse
        if side == "BUY":
            adverse = filled_price > expected_price
        else:
            adverse = filled_price < expected_price

        direction = "adverse" if adverse else "favorable"
        logger.warning(
            f"High slippage detected ({direction}): {slippage:.2%} "
            f"(expected={expected_price:.4f}, filled={filled_price:.4f}, side={side})"
        )


class LiveExecutor:
    """
    Live trading executor for Polymarket CLOB using py-clob-client.

    SECURITY WARNING:
    - Never commit credentials to git
    - Use environment variables or .env file
    - Start with small amounts
    - Test with paper trading first

    Required Environment Variables:
        POLYMARKET_PRIVATE_KEY: Your wallet private key (hex string)
        POLYMARKET_FUNDER: Your proxy wallet address (0x...)

    Example:
        executor = LiveExecutor()

        if executor.is_ready():
            # Place order
            result = executor.place_order(
                token_id="abc123",
                side="buy",
                size=10,
                price=0.55
            )

            if result.success:
                print(f"Order placed: {result.order_id}")
    """

    CLOB_BASE_URL = "https://clob.polymarket.com"
    CHAIN_ID = 137  # Polygon

    def __init__(self):
        # Load credentials from environment
        self.private_key = os.getenv("POLYMARKET_PRIVATE_KEY", "")
        self.funder = os.getenv("POLYMARKET_FUNDER", "")

        # State
        self._ready = False
        self._last_error = ""
        self._client = None

        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 0.1  # 100ms between requests

        # Order tracking
        self.pending_orders: Dict[str, Dict] = {}

        # Persistence
        self.data_dir = DATA_DIR / "trading"
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Balance checker for on-chain USDC queries
        self._balance_checker = BalanceChecker()

        # Initialize client
        self._init_client()

    def _init_client(self):
        """Initialize py-clob-client."""
        if not self.private_key:
            self._last_error = "POLYMARKET_PRIVATE_KEY not set"
            self._ready = False
            return

        if not self.funder:
            self._last_error = "POLYMARKET_FUNDER not set"
            self._ready = False
            return

        try:
            from py_clob_client.client import ClobClient

            # Ensure private key has 0x prefix
            key = self.private_key
            if not key.startswith("0x"):
                key = "0x" + key

            # Create client with signature_type=2 (GNOSIS_SAFE for proxy wallet)
            self._client = ClobClient(
                self.CLOB_BASE_URL,
                key=key,
                chain_id=self.CHAIN_ID,
                funder=self.funder,
                signature_type=2  # GNOSIS_SAFE
            )

            # Derive and set API credentials
            creds = self._client.create_or_derive_api_creds()
            self._client.set_api_creds(creds)

            # Verify we're at L2 auth
            if self._client.mode >= 2:
                self._ready = True
                self._last_error = ""
                print(f"LiveExecutor initialized")
                print(f"   Signing wallet: {self._client.get_address()}")
                print(f"   Funder (proxy): {self.funder}")
            else:
                self._last_error = f"Failed to reach L2 auth (mode={self._client.mode})"
                self._ready = False

        except ImportError:
            self._last_error = "py-clob-client not installed. Run: pip install py-clob-client"
            self._ready = False
        except Exception as e:
            self._last_error = f"Failed to initialize client: {str(e)}"
            self._ready = False

    def is_ready(self) -> bool:
        """Check if executor is ready."""
        return self._ready

    def get_error(self) -> str:
        """Get last error message."""
        return self._last_error

    def _rate_limit(self):
        """Apply rate limiting."""
        now = time.time()
        elapsed = now - self._last_request_time

        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)

        self._last_request_time = time.time()

    def _check_kill_switch(self) -> bool:
        """
        Check if kill switch is active.

        Returns:
            True if kill switch is active (trading should stop)
        """
        if check_kill_switch():
            logger.warning("Kill switch activated - trading halted")
            return True
        return False

    def _call_api_with_retry(
        self,
        func: Callable[..., Any],
        *args,
        operation_name: str = "API call",
        **kwargs
    ) -> Any:
        """
        Call an API function with timeout and retry logic.

        Args:
            func: The API function to call
            *args: Positional arguments for the function
            operation_name: Name of the operation for logging
            **kwargs: Keyword arguments for the function

        Returns:
            The result of the API call

        Raises:
            APITimeoutError: If all retry attempts timeout
            Exception: If the API call fails after all retries
        """
        import threading

        @retry(
            stop=stop_after_attempt(MAX_RETRY_ATTEMPTS),
            wait=wait_exponential(
                multiplier=1,
                min=RETRY_MIN_WAIT,
                max=RETRY_MAX_WAIT
            ),
            reraise=True,
        )
        def _execute_with_retry():
            # Use threading for timeout (works on all platforms)
            result = [None]
            exception = [None]

            def target():
                try:
                    result[0] = func(*args, **kwargs)
                except Exception as e:
                    exception[0] = e

            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout=API_TIMEOUT)

            if thread.is_alive():
                # Timeout occurred
                raise APITimeoutError(
                    f"{operation_name} timed out after {API_TIMEOUT}s"
                )

            if exception[0] is not None:
                raise exception[0]

            return result[0]

        try:
            return _execute_with_retry()
        except RetryError as e:
            # All retries exhausted
            logger.error(f"{operation_name} failed after {MAX_RETRY_ATTEMPTS} attempts: {e}")
            raise
        except APITimeoutError:
            raise
        except Exception as e:
            logger.error(f"{operation_name} failed: {e}")
            raise

    def get_balance(self) -> Optional[Balance]:
        """
        Get account USDC balance via on-chain query.

        Uses web3.py to query the USDC contract on Polygon since
        py-clob-client's get_balance_allowance is broken.

        Returns:
            Balance object with available, locked, and total fields.
            Returns None if executor not ready or balance query fails.
        """
        if not self._ready:
            print(f"[Executor] Not ready: {self._last_error}")
            return None

        if not self.funder:
            print("[Executor] No funder address configured")
            return None

        # Query on-chain USDC balance using the balance checker
        balance = self._balance_checker.get_balance(self.funder)
        return balance

    def has_sufficient_balance(self, required_amount: float) -> bool:
        """
        Check if account has sufficient balance for a trade.

        Args:
            required_amount: Required amount in USDC

        Returns:
            True if sufficient balance, False otherwise
        """
        if not self.funder:
            return False
        return self._balance_checker.has_sufficient_balance(self.funder, required_amount)

    def place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        order_type: OrderType = OrderType.FOK
    ) -> OrderResult:
        """
        Place an order on the CLOB.

        Args:
            token_id: Token ID to trade
            side: "buy" or "sell" (or "BUY"/"SELL")
            size: Number of shares (will be converted to proper units)
            price: Price per share (0-1)
            order_type: Order type (FOK recommended for arbitrage)

        Returns:
            OrderResult with status
        """
        # Check kill switch before any trading
        if self._check_kill_switch():
            return OrderResult(
                success=False,
                message="Kill switch activated - trading halted"
            )

        if not self._ready:
            return OrderResult(
                success=False,
                message=f"Executor not ready: {self._last_error}"
            )

        self._rate_limit()

        # Normalize side
        side_upper = side.upper()
        if side_upper not in ["BUY", "SELL"]:
            return OrderResult(success=False, message=f"Invalid side: {side}")

        # Validate inputs
        if price < 0.01 or price > 0.99:
            return OrderResult(success=False, message=f"Price {price} must be between 0.01 and 0.99")

        if size <= 0:
            return OrderResult(success=False, message="Size must be positive")

        # Pre-order balance check for BUY orders
        if side_upper == "BUY":
            required_amount = size * price
            if not self.has_sufficient_balance(required_amount):
                balance = self.get_balance()
                available = balance.available if balance else 0.0
                return OrderResult(
                    success=False,
                    message=f"Insufficient funds: need ${required_amount:.2f}, have ${available:.2f}"
                )

        try:
            from py_clob_client.order_builder.constants import BUY, SELL
            from py_clob_client.clob_types import OrderArgs, PartialCreateOrderOptions

            # Map side
            order_side = BUY if side_upper == "BUY" else SELL

            # Create OrderArgs object (new API format)
            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side
            )

            # Create options with tick size (required for proper price rounding)
            options = PartialCreateOrderOptions(
                tick_size="0.01"  # Standard tick size for Polymarket
            )

            # Create and post order with retry logic and timeout
            order = self._call_api_with_retry(
                self._client.create_and_post_order,
                order_args,
                options,
                operation_name="place_order"
            )

            # Check if order was successful
            if order:
                order_id = order.get("orderID") or order.get("id") or str(int(time.time()))

                # Extract filled price if available for slippage check
                filled_price = order.get("filledPrice") or order.get("avgFillPrice") or 0.0
                if isinstance(filled_price, str):
                    try:
                        filled_price = float(filled_price)
                    except ValueError:
                        filled_price = 0.0

                # Check for slippage if we have a filled price
                if filled_price > 0:
                    _check_slippage(price, filled_price, side_upper)

                result = OrderResult(
                    success=True,
                    order_id=order_id,
                    status=OrderStatus.OPEN,
                    filled_price=filled_price,
                    message="Order placed",
                    raw_response=order
                )

                # Track order
                self.pending_orders[order_id] = {
                    "token_id": token_id,
                    "side": side_upper,
                    "size": size,
                    "price": price,
                    "filled_price": filled_price,
                    "placed_at": int(time.time()),
                    "status": "open"
                }
                self._save_orders()

                return result
            else:
                return OrderResult(
                    success=False,
                    message="Order returned empty response"
                )

        except APITimeoutError as e:
            self._last_error = str(e)
            logger.error(f"Order timed out: {e}")
            return OrderResult(
                success=False,
                message=f"Order timed out: {str(e)}"
            )
        except Exception as e:
            self._last_error = str(e)
            return OrderResult(
                success=False,
                message=f"Order failed: {str(e)}"
            )

    def cancel_order(self, order_id: str) -> OrderResult:
        """
        Cancel an open order.

        Args:
            order_id: Order ID to cancel

        Returns:
            OrderResult with status
        """
        # Note: Cancel should work even with kill switch - we want to be able to cancel orders
        if not self._ready:
            return OrderResult(
                success=False,
                message=f"Executor not ready: {self._last_error}"
            )

        self._rate_limit()

        try:
            # Use retry wrapper for API call
            result = self._call_api_with_retry(
                self._client.cancel,
                order_id,
                operation_name="cancel_order"
            )

            # Update tracking
            if order_id in self.pending_orders:
                self.pending_orders[order_id]["status"] = "cancelled"
                self._save_orders()

            return OrderResult(
                success=True,
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                message="Order cancelled",
                raw_response=result
            )

        except APITimeoutError as e:
            self._last_error = str(e)
            logger.error(f"Cancel order timed out: {e}")
            return OrderResult(
                success=False,
                message=f"Cancel timed out: {str(e)}"
            )
        except Exception as e:
            self._last_error = str(e)
            return OrderResult(
                success=False,
                message=f"Cancel failed: {str(e)}"
            )

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get status of an order.

        Args:
            order_id: Order ID

        Returns:
            Order data or None
        """
        if not self._ready:
            return None

        try:
            return self._call_api_with_retry(
                self._client.get_order,
                order_id,
                operation_name="get_order_status"
            )
        except APITimeoutError as e:
            self._last_error = str(e)
            logger.error(f"Get order status timed out: {e}")
            return None
        except Exception as e:
            self._last_error = str(e)
            return None

    def get_open_orders(self) -> List[Dict]:
        """
        Get all open orders.

        Returns:
            List of open orders
        """
        if not self._ready:
            return []

        try:
            orders = self._call_api_with_retry(
                self._client.get_orders,
                operation_name="get_open_orders"
            )
            return orders if orders else []
        except APITimeoutError as e:
            self._last_error = str(e)
            logger.error(f"Get open orders timed out: {e}")
            return []
        except Exception as e:
            self._last_error = str(e)
            return []

    def get_trades(self) -> List[Dict]:
        """
        Get recent trades.

        Returns:
            List of trades
        """
        if not self._ready:
            return []

        try:
            trades = self._call_api_with_retry(
                self._client.get_trades,
                operation_name="get_trades"
            )
            return trades if trades else []
        except APITimeoutError as e:
            self._last_error = str(e)
            logger.error(f"Get trades timed out: {e}")
            return []
        except Exception as e:
            self._last_error = str(e)
            return []

    def cancel_all_orders(self) -> int:
        """
        Cancel all open orders.

        Returns:
            Number of orders cancelled
        """
        # Note: Cancel should work even with kill switch - we want to be able to cancel orders
        if not self._ready:
            return 0

        try:
            result = self._call_api_with_retry(
                self._client.cancel_all,
                operation_name="cancel_all_orders"
            )
            return result.get("canceled", 0) if result else 0
        except APITimeoutError as e:
            self._last_error = str(e)
            logger.error(f"Cancel all orders timed out: {e}")
            return 0
        except Exception as e:
            self._last_error = str(e)
            return 0

    def _save_orders(self):
        """Save order history."""
        filepath = self.data_dir / "order_history.json"

        # Load existing history
        history = []
        if filepath.exists():
            try:
                with open(filepath, 'r') as f:
                    history = json.load(f)
            except:
                pass

        # Add pending orders
        for order_id, order_data in self.pending_orders.items():
            order_data["order_id"] = order_id
            if order_data not in history:
                history.append(order_data)

        # Keep last 1000 orders
        history = history[-1000:]

        with open(filepath, 'w') as f:
            json.dump(history, f, indent=2)

    def get_order_history(self, limit: int = 50) -> List[Dict]:
        """Get order history from file."""
        filepath = self.data_dir / "order_history.json"

        if not filepath.exists():
            return []

        try:
            with open(filepath, 'r') as f:
                history = json.load(f)
            return history[-limit:]
        except:
            return []


class SafeExecutor:
    """
    Wrapper around LiveExecutor with additional safety checks.

    Features:
    - Dry-run mode (default)
    - Order size limits
    - Daily trade limits
    - Confirmation prompts (optional)
    - Kill switch check
    """

    def __init__(
        self,
        dry_run: bool = True,
        max_order_size: float = 50.0,
        max_daily_orders: int = 200,
        require_confirmation: bool = False  # Disabled for bot use
    ):
        self.executor = LiveExecutor() if not dry_run else None
        self.dry_run = dry_run
        self.max_order_size = max_order_size
        self.max_daily_orders = max_daily_orders
        self.require_confirmation = require_confirmation

        # Daily tracking
        self._orders_today = 0
        self._today = datetime.now().date()
        self._pnl_today = 0.0

    def _check_day_reset(self):
        """Reset daily counters if new day."""
        today = datetime.now().date()
        if today != self._today:
            self._orders_today = 0
            self._pnl_today = 0.0
            self._today = today

    def is_ready(self) -> bool:
        """Check if executor is ready."""
        if self.dry_run:
            return True  # Dry run is always ready
        return self.executor.is_ready() if self.executor else False

    def get_error(self) -> str:
        """Get last error."""
        if self.dry_run:
            return ""
        return self.executor.get_error() if self.executor else "Executor not initialized"

    def get_balance(self) -> Optional[Balance]:
        """Get balance (works in dry-run mode too)."""
        if self.dry_run:
            return Balance(available=1000.0, locked=0.0, total=1000.0)
        return self.executor.get_balance() if self.executor else None

    def place_order(
        self,
        token_id: str,
        side: str,
        size: float,
        price: float,
        order_type: OrderType = OrderType.FOK,
        skip_confirmation: bool = True  # Default skip for bot
    ) -> OrderResult:
        """
        Place an order with safety checks.

        Args:
            token_id: Token ID
            side: "buy" or "sell"
            size: Number of shares
            price: Price per share
            order_type: Order type (FOK for arbitrage)
            skip_confirmation: Skip confirmation prompt

        Returns:
            OrderResult
        """
        # Check kill switch first (applies to both dry run and live)
        if check_kill_switch():
            logger.warning("Kill switch activated - trading halted (SafeExecutor)")
            return OrderResult(
                success=False,
                message="Kill switch activated - trading halted"
            )

        self._check_day_reset()

        # Check size limit
        value = size * price
        if value > self.max_order_size:
            return OrderResult(
                success=False,
                message=f"Order value ${value:.2f} exceeds max ${self.max_order_size}"
            )

        # Check daily limit
        if self._orders_today >= self.max_daily_orders:
            return OrderResult(
                success=False,
                message=f"Daily order limit ({self.max_daily_orders}) reached"
            )

        # Dry run mode
        if self.dry_run:
            print(f"DRY RUN: {side.upper()} {size:.1f} shares @ ${price:.4f} = ${value:.2f}")
            self._orders_today += 1
            return OrderResult(
                success=True,
                order_id=f"DRY_{int(time.time()*1000)}",
                status=OrderStatus.FILLED,
                filled_size=size,
                filled_price=price,
                message="Dry run - order simulated"
            )

        # Confirmation prompt (disabled by default for bots)
        if self.require_confirmation and not skip_confirmation:
            print(f"\nLIVE ORDER: {side.upper()} {size:.1f} @ ${price:.4f} = ${value:.2f}")
            confirm = input("Confirm? (yes/no): ").strip().lower()
            if confirm != "yes":
                return OrderResult(
                    success=False,
                    message="Order cancelled by user"
                )

        # Place actual order
        result = self.executor.place_order(token_id, side, size, price, order_type)

        if result.success:
            self._orders_today += 1
            print(f"LIVE ORDER: {side.upper()} {size:.1f} @ ${price:.4f} = ${value:.2f}")

        return result

    def cancel_order(self, order_id: str) -> OrderResult:
        """Cancel order."""
        if self.dry_run:
            return OrderResult(
                success=True,
                order_id=order_id,
                status=OrderStatus.CANCELLED,
                message="Dry run - cancel simulated"
            )

        return self.executor.cancel_order(order_id) if self.executor else OrderResult(
            success=False, message="Executor not initialized"
        )

    def get_trades(self) -> List[Dict]:
        """Get trades."""
        if self.dry_run:
            return []
        return self.executor.get_trades() if self.executor else []

    def get_open_orders(self) -> List[Dict]:
        """Get open orders."""
        if self.dry_run:
            return []
        return self.executor.get_open_orders() if self.executor else []


def create_executor(
    live: bool = False,
    max_order_size: float = 50.0
) -> SafeExecutor:
    """
    Factory function to create an executor.

    Args:
        live: If True, enables live trading. If False, dry-run mode.
        max_order_size: Maximum order size in USD

    Returns:
        SafeExecutor instance
    """
    return SafeExecutor(
        dry_run=not live,
        max_order_size=max_order_size,
        require_confirmation=False  # Bots don't need confirmation
    )
