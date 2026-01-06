"""
On-Chain USDC Balance Checker for Polymarket Trading

Implements direct on-chain balance queries using web3.py since
py-clob-client's get_balance_allowance is broken.

Features:
- Query USDC balance from Polygon chain
- 30-second caching to avoid excessive RPC calls
- Thread-safe implementation
- Fallback to zero balance on errors

USDC on Polygon: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
"""
import os
import time
import threading
from dataclasses import dataclass
from typing import Optional

from web3 import Web3
from web3.exceptions import Web3Exception


# USDC contract on Polygon (6 decimals)
USDC_CONTRACT_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
USDC_DECIMALS = 6

# Public Polygon RPC endpoint
POLYGON_RPC_URL = "https://polygon-rpc.com"

# Cache TTL in seconds
BALANCE_CACHE_TTL = 30

# Minimal ERC20 ABI for balanceOf
ERC20_BALANCE_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


@dataclass
class Balance:
    """Account balance representation."""

    available: float = 0.0
    locked: float = 0.0
    total: float = 0.0

    @property
    def usable(self) -> float:
        """Amount available for trading."""
        return self.available


class BalanceChecker:
    """
    On-chain USDC balance checker with caching.

    Uses web3.py to query the USDC token contract on Polygon.
    Caches results for 30 seconds to avoid excessive RPC calls.

    Example:
        checker = BalanceChecker()
        balance = checker.get_balance("0xYourProxyWallet...")
        print(f"Available: ${balance.available:.2f}")
    """

    def __init__(
        self,
        rpc_url: str = POLYGON_RPC_URL,
        cache_ttl: int = BALANCE_CACHE_TTL,
        usdc_address: str = USDC_CONTRACT_ADDRESS,
    ):
        """
        Initialize the balance checker.

        Args:
            rpc_url: Polygon RPC endpoint URL
            cache_ttl: Cache time-to-live in seconds (default 30)
            usdc_address: USDC contract address on Polygon
        """
        self.rpc_url = rpc_url
        self.cache_ttl = cache_ttl
        self.usdc_address = Web3.to_checksum_address(usdc_address)

        # Initialize Web3 connection
        self._web3: Optional[Web3] = None
        self._contract = None
        self._init_error: str = ""

        # Cache storage: {address: (balance, timestamp)}
        self._cache: dict[str, tuple[float, float]] = {}
        self._cache_lock = threading.Lock()

        # Initialize connection
        self._init_web3()

    def _init_web3(self):
        """Initialize Web3 connection and contract."""
        try:
            self._web3 = Web3(Web3.HTTPProvider(self.rpc_url))

            # Verify connection
            if not self._web3.is_connected():
                self._init_error = f"Failed to connect to RPC: {self.rpc_url}"
                self._web3 = None
                return

            # Initialize USDC contract
            self._contract = self._web3.eth.contract(
                address=self.usdc_address, abi=ERC20_BALANCE_ABI
            )

            self._init_error = ""

        except Exception as e:
            self._init_error = f"Web3 initialization failed: {str(e)}"
            self._web3 = None

    def is_ready(self) -> bool:
        """Check if the balance checker is ready to query balances."""
        return self._web3 is not None and self._contract is not None

    def get_error(self) -> str:
        """Get the last initialization error message."""
        return self._init_error

    def _get_cached_balance(self, address: str) -> Optional[float]:
        """
        Get cached balance if still valid.

        Args:
            address: Wallet address (checksummed)

        Returns:
            Cached balance or None if expired/missing
        """
        with self._cache_lock:
            if address in self._cache:
                balance, timestamp = self._cache[address]
                if time.time() - timestamp < self.cache_ttl:
                    return balance
        return None

    def _set_cached_balance(self, address: str, balance: float):
        """
        Set cached balance.

        Args:
            address: Wallet address (checksummed)
            balance: Balance value in USDC
        """
        with self._cache_lock:
            self._cache[address] = (balance, time.time())

    def clear_cache(self):
        """Clear all cached balances."""
        with self._cache_lock:
            self._cache.clear()

    def get_raw_balance(self, address: str) -> int:
        """
        Get raw balance from chain (no cache).

        Args:
            address: Wallet address

        Returns:
            Raw balance in smallest units (6 decimals for USDC)

        Raises:
            ValueError: If address is invalid
            Web3Exception: If RPC call fails
        """
        if not self.is_ready():
            raise Web3Exception(f"Balance checker not ready: {self._init_error}")

        # Validate and checksum address
        if not Web3.is_address(address):
            raise ValueError(f"Invalid Ethereum address: {address}")

        checksum_address = Web3.to_checksum_address(address)

        # Query balance from contract
        raw_balance = self._contract.functions.balanceOf(checksum_address).call()
        return raw_balance

    def get_balance(self, address: str) -> Balance:
        """
        Get USDC balance for an address with caching.

        Args:
            address: Wallet address (proxy wallet for Polymarket)

        Returns:
            Balance dataclass with available, locked, and total fields.
            Returns zero balance on any error.
        """
        if not address:
            return Balance(available=0.0, locked=0.0, total=0.0)

        try:
            # Validate and checksum address
            if not Web3.is_address(address):
                print(f"[BalanceChecker] Invalid address: {address}")
                return Balance(available=0.0, locked=0.0, total=0.0)

            checksum_address = Web3.to_checksum_address(address)

            # Check cache first
            cached = self._get_cached_balance(checksum_address)
            if cached is not None:
                return Balance(available=cached, locked=0.0, total=cached)

            # Query from chain
            raw_balance = self.get_raw_balance(checksum_address)

            # Convert from 6 decimals to float
            balance_usdc = raw_balance / (10**USDC_DECIMALS)

            # Cache the result
            self._set_cached_balance(checksum_address, balance_usdc)

            # Return Balance object (locked=0 since we can't determine locked amount)
            return Balance(available=balance_usdc, locked=0.0, total=balance_usdc)

        except Exception as e:
            print(f"[BalanceChecker] Error getting balance: {str(e)}")
            return Balance(available=0.0, locked=0.0, total=0.0)

    def has_sufficient_balance(self, address: str, required_amount: float) -> bool:
        """
        Check if address has sufficient balance for a trade.

        Args:
            address: Wallet address
            required_amount: Required amount in USDC

        Returns:
            True if balance >= required_amount, False otherwise
        """
        balance = self.get_balance(address)
        return balance.available >= required_amount


# Global instance for convenience
_global_checker: Optional[BalanceChecker] = None
_global_checker_lock = threading.Lock()


def get_balance_checker() -> BalanceChecker:
    """
    Get the global BalanceChecker instance (singleton pattern).

    Returns:
        BalanceChecker instance
    """
    global _global_checker
    with _global_checker_lock:
        if _global_checker is None:
            _global_checker = BalanceChecker()
        return _global_checker


def get_usdc_balance(address: str) -> Balance:
    """
    Convenience function to get USDC balance.

    Args:
        address: Wallet address

    Returns:
        Balance dataclass
    """
    return get_balance_checker().get_balance(address)


def check_sufficient_funds(address: str, required: float) -> bool:
    """
    Convenience function to check if address has sufficient funds.

    Args:
        address: Wallet address
        required: Required amount in USDC

    Returns:
        True if sufficient funds, False otherwise
    """
    return get_balance_checker().has_sufficient_balance(address, required)
