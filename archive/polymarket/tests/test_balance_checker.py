"""
Tests for the on-chain USDC balance checker.

These tests verify:
1. Balance dataclass functionality
2. BalanceChecker initialization
3. Address validation
4. Caching behavior (30-second TTL)
5. Error handling
6. Thread safety
7. Convenience functions

Note: Some tests mock the web3 calls to avoid actual RPC requests.
"""
import time
import threading
from unittest.mock import Mock, patch, MagicMock

import pytest

from src.trading.balance_checker import (
    Balance,
    BalanceChecker,
    USDC_DECIMALS,
    USDC_CONTRACT_ADDRESS,
    POLYGON_RPC_URL,
    BALANCE_CACHE_TTL,
    get_balance_checker,
    get_usdc_balance,
    check_sufficient_funds,
)


# ============================================================================
# Balance Dataclass Tests
# ============================================================================

class TestBalanceDataclass:
    """Tests for the Balance dataclass."""

    def test_balance_default_values(self):
        """Test Balance default values are zero."""
        balance = Balance()
        assert balance.available == 0.0
        assert balance.locked == 0.0
        assert balance.total == 0.0

    def test_balance_custom_values(self):
        """Test Balance with custom values."""
        balance = Balance(available=100.0, locked=25.0, total=125.0)
        assert balance.available == 100.0
        assert balance.locked == 25.0
        assert balance.total == 125.0

    def test_balance_usable_property(self):
        """Test usable property returns available."""
        balance = Balance(available=50.0, locked=10.0, total=60.0)
        assert balance.usable == 50.0
        assert balance.usable == balance.available


# ============================================================================
# BalanceChecker Initialization Tests
# ============================================================================

class TestBalanceCheckerInit:
    """Tests for BalanceChecker initialization."""

    def test_default_config(self):
        """Test default configuration values."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = MagicMock()
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            assert checker.rpc_url == POLYGON_RPC_URL
            assert checker.cache_ttl == BALANCE_CACHE_TTL

    def test_custom_config(self):
        """Test custom configuration values."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = MagicMock()
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker(
                rpc_url="https://custom-rpc.com",
                cache_ttl=60,
            )
            assert checker.rpc_url == "https://custom-rpc.com"
            assert checker.cache_ttl == 60

    def test_connection_failure_sets_error(self):
        """Test that connection failure sets init error."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = False
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            assert not checker.is_ready()
            assert "Failed to connect" in checker.get_error()


# ============================================================================
# Address Validation Tests
# ============================================================================

class TestAddressValidation:
    """Tests for address validation."""

    def test_invalid_address_returns_zero_balance(self):
        """Test that invalid address returns zero balance."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = MagicMock()
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = False
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            balance = checker.get_balance("invalid_address")
            assert balance.available == 0.0
            assert balance.total == 0.0

    def test_empty_address_returns_zero_balance(self):
        """Test that empty address returns zero balance."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = MagicMock()
            mock_web3_class.return_value = mock_web3
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            balance = checker.get_balance("")
            assert balance.available == 0.0
            assert balance.total == 0.0

    def test_none_address_returns_zero_balance(self):
        """Test that None address returns zero balance."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = MagicMock()
            mock_web3_class.return_value = mock_web3
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            balance = checker.get_balance(None)
            assert balance.available == 0.0
            assert balance.total == 0.0


# ============================================================================
# Balance Query Tests
# ============================================================================

class TestBalanceQuery:
    """Tests for balance querying."""

    def test_get_balance_converts_decimals(self):
        """Test that balance is correctly converted from 6 decimals."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            # Return 100 USDC (100 * 10^6 raw units)
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            balance = checker.get_balance("0x1234567890123456789012345678901234567890")

            assert balance.available == 100.0
            assert balance.total == 100.0
            assert balance.locked == 0.0

    def test_get_balance_handles_fractional(self):
        """Test that fractional balances are handled correctly."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            # Return 123.456789 USDC
            mock_contract.functions.balanceOf.return_value.call.return_value = 123456789

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            balance = checker.get_balance("0x1234567890123456789012345678901234567890")

            assert abs(balance.available - 123.456789) < 0.000001


# ============================================================================
# Caching Tests
# ============================================================================

class TestCaching:
    """Tests for balance caching."""

    def test_cache_hit_returns_cached_value(self):
        """Test that cached value is returned within TTL."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x.upper() if x else x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker(cache_ttl=30)
            address = "0x1234567890123456789012345678901234567890"

            # First call - hits RPC
            balance1 = checker.get_balance(address)
            call_count_1 = mock_contract.functions.balanceOf.call_count

            # Second call - should hit cache
            balance2 = checker.get_balance(address)
            call_count_2 = mock_contract.functions.balanceOf.call_count

            assert balance1.available == balance2.available
            assert call_count_1 == call_count_2  # No new RPC call

    def test_cache_miss_after_ttl(self):
        """Test that cache is refreshed after TTL expires."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x.upper() if x else x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            # Use very short TTL for test
            checker = BalanceChecker(cache_ttl=1)
            address = "0x1234567890123456789012345678901234567890"

            # First call
            checker.get_balance(address)
            call_count_1 = mock_contract.functions.balanceOf.call_count

            # Wait for cache to expire
            time.sleep(1.1)

            # Second call - should miss cache
            checker.get_balance(address)
            call_count_2 = mock_contract.functions.balanceOf.call_count

            assert call_count_2 > call_count_1  # New RPC call made

    def test_clear_cache(self):
        """Test that clear_cache clears all cached values."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x.upper() if x else x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker(cache_ttl=300)  # Long TTL
            address = "0x1234567890123456789012345678901234567890"

            # First call
            checker.get_balance(address)
            call_count_1 = mock_contract.functions.balanceOf.call_count

            # Clear cache
            checker.clear_cache()

            # Second call - should miss cache
            checker.get_balance(address)
            call_count_2 = mock_contract.functions.balanceOf.call_count

            assert call_count_2 > call_count_1


# ============================================================================
# Sufficient Balance Tests
# ============================================================================

class TestSufficientBalance:
    """Tests for has_sufficient_balance method."""

    def test_sufficient_balance_returns_true(self):
        """Test that sufficient balance returns True."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            result = checker.has_sufficient_balance(
                "0x1234567890123456789012345678901234567890", 50.0
            )
            assert result is True

    def test_insufficient_balance_returns_false(self):
        """Test that insufficient balance returns False."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            result = checker.has_sufficient_balance(
                "0x1234567890123456789012345678901234567890", 150.0
            )
            assert result is False

    def test_exact_balance_returns_true(self):
        """Test that exact balance returns True."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            result = checker.has_sufficient_balance(
                "0x1234567890123456789012345678901234567890", 100.0
            )
            assert result is True


# ============================================================================
# Error Handling Tests
# ============================================================================

class TestErrorHandling:
    """Tests for error handling."""

    def test_rpc_error_returns_zero_balance(self):
        """Test that RPC errors return zero balance."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.side_effect = Exception(
                "RPC error"
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            balance = checker.get_balance("0x1234567890123456789012345678901234567890")

            assert balance.available == 0.0
            assert balance.total == 0.0

    def test_not_ready_returns_zero_balance(self):
        """Test that not ready checker returns zero balance on get_raw_balance."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = False
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            assert not checker.is_ready()

            # get_raw_balance should raise
            from web3.exceptions import Web3Exception

            with pytest.raises(Web3Exception):
                checker.get_raw_balance("0x1234567890123456789012345678901234567890")


# ============================================================================
# Thread Safety Tests
# ============================================================================

class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_cache_access(self):
        """Test that concurrent cache access is thread-safe."""
        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker = BalanceChecker()
            address = "0x1234567890123456789012345678901234567890"
            results = []
            errors = []

            def get_balance_thread():
                try:
                    balance = checker.get_balance(address)
                    results.append(balance.available)
                except Exception as e:
                    errors.append(str(e))

            # Create multiple threads
            threads = [threading.Thread(target=get_balance_thread) for _ in range(10)]

            # Start all threads
            for t in threads:
                t.start()

            # Wait for all threads
            for t in threads:
                t.join()

            # Verify no errors and all results are correct
            assert len(errors) == 0
            assert len(results) == 10
            assert all(r == 100.0 for r in results)


# ============================================================================
# Convenience Function Tests
# ============================================================================

class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_get_balance_checker_returns_singleton(self):
        """Test that get_balance_checker returns the same instance."""
        # Reset the global instance
        import src.trading.balance_checker as bc_module

        bc_module._global_checker = None

        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = MagicMock()
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            checker1 = get_balance_checker()
            checker2 = get_balance_checker()

            assert checker1 is checker2

    def test_get_usdc_balance_function(self):
        """Test get_usdc_balance convenience function."""
        import src.trading.balance_checker as bc_module

        bc_module._global_checker = None

        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                50 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            balance = get_usdc_balance("0x1234567890123456789012345678901234567890")
            assert balance.available == 50.0

    def test_check_sufficient_funds_function(self):
        """Test check_sufficient_funds convenience function."""
        import src.trading.balance_checker as bc_module

        bc_module._global_checker = None

        with patch("src.trading.balance_checker.Web3") as mock_web3_class:
            mock_contract = MagicMock()
            mock_contract.functions.balanceOf.return_value.call.return_value = (
                100 * 10**USDC_DECIMALS
            )

            mock_web3 = MagicMock()
            mock_web3.is_connected.return_value = True
            mock_web3.eth.contract.return_value = mock_contract
            mock_web3_class.return_value = mock_web3
            mock_web3_class.to_checksum_address = lambda x: x
            mock_web3_class.is_address.return_value = True
            mock_web3_class.HTTPProvider.return_value = MagicMock()

            result = check_sufficient_funds(
                "0x1234567890123456789012345678901234567890", 50.0
            )
            assert result is True

            result = check_sufficient_funds(
                "0x1234567890123456789012345678901234567890", 150.0
            )
            assert result is False


# ============================================================================
# Constants Verification
# ============================================================================

class TestConstants:
    """Tests for module constants."""

    def test_usdc_contract_address(self):
        """Test USDC contract address is correct for Polygon."""
        assert USDC_CONTRACT_ADDRESS == "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

    def test_usdc_decimals(self):
        """Test USDC decimals is 6."""
        assert USDC_DECIMALS == 6

    def test_polygon_rpc_url(self):
        """Test default Polygon RPC URL."""
        assert POLYGON_RPC_URL == "https://polygon-rpc.com"

    def test_cache_ttl(self):
        """Test default cache TTL is 30 seconds."""
        assert BALANCE_CACHE_TTL == 30
