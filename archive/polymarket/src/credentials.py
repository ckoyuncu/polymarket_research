"""
Credential Setup and Trading Readiness

Handles Polymarket API credentials and account setup.
"""
from dataclasses import dataclass
from typing import Optional
from pathlib import Path
import os


@dataclass
class CredentialStatus:
    """Status of Polymarket credentials."""
    has_wallet: bool = False
    has_api_key: bool = False
    has_api_secret: bool = False
    has_passphrase: bool = False
    
    can_read_public: bool = True  # Always true - no auth needed
    can_read_private: bool = False
    can_trade: bool = False
    
    wallet_address: Optional[str] = None
    error_message: Optional[str] = None


class CredentialManager:
    """
    Manages Polymarket API credentials.
    
    Polymarket uses a two-layer auth system:
    - L1: Your Ethereum wallet (for signing)
    - L2: API credentials derived from L1 (for CLOB trading)
    
    For READING data (discovery, analysis): No credentials needed
    For TRADING: Need L2 API credentials
    """
    
    ENV_VARS = {
        "POLYMARKET_API_KEY": "api_key",
        "POLYMARKET_API_SECRET": "api_secret", 
        "POLYMARKET_PASSPHRASE": "passphrase",
        "POLYMARKET_WALLET": "wallet_address",
    }
    
    def __init__(self):
        self.status = self._check_status()
    
    def _check_status(self) -> CredentialStatus:
        """Check current credential status."""
        status = CredentialStatus()
        
        # Check environment variables
        api_key = os.getenv("POLYMARKET_API_KEY")
        api_secret = os.getenv("POLYMARKET_API_SECRET")
        passphrase = os.getenv("POLYMARKET_PASSPHRASE")
        wallet = os.getenv("POLYMARKET_WALLET")
        
        status.has_api_key = bool(api_key)
        status.has_api_secret = bool(api_secret)
        status.has_passphrase = bool(passphrase)
        status.has_wallet = bool(wallet)
        status.wallet_address = wallet
        
        # Determine capabilities
        status.can_read_public = True  # Always
        status.can_read_private = status.has_api_key and status.has_api_secret
        status.can_trade = (
            status.has_api_key and 
            status.has_api_secret and 
            status.has_passphrase
        )
        
        return status
    
    def print_status(self):
        """Print current credential status."""
        s = self.status
        
        print("\n" + "="*60)
        print("🔑 CREDENTIAL STATUS")
        print("="*60)
        
        print(f"\n📋 Environment Variables:")
        print(f"   POLYMARKET_API_KEY:    {'✅ Set' if s.has_api_key else '❌ Missing'}")
        print(f"   POLYMARKET_API_SECRET: {'✅ Set' if s.has_api_secret else '❌ Missing'}")
        print(f"   POLYMARKET_PASSPHRASE: {'✅ Set' if s.has_passphrase else '❌ Missing'}")
        print(f"   POLYMARKET_WALLET:     {'✅ Set' if s.has_wallet else '❌ Missing'}")
        
        if s.wallet_address:
            print(f"\n   Wallet: {s.wallet_address[:20]}...")
        
        print(f"\n🔓 Capabilities:")
        print(f"   Read public data:  ✅ Available (no auth needed)")
        print(f"   Read private data: {'✅ Available' if s.can_read_private else '❌ Need API credentials'}")
        print(f"   Place trades:      {'✅ Available' if s.can_trade else '❌ Need full credentials'}")
        
        print("="*60)
    
    def get_setup_guide(self) -> str:
        """Get step-by-step setup guide."""
        return """
╔══════════════════════════════════════════════════════════════════╗
║                  POLYMARKET CREDENTIAL SETUP                      ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  IMPORTANT: You only need credentials for TRADING.                ║
║  Discovery and analysis work without any credentials!             ║
║                                                                   ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  STEP 1: Create a Polymarket Account                              ║
║  ─────────────────────────────────────                            ║
║  1. Go to https://polymarket.com                                  ║
║  2. Click "Sign Up" or "Connect Wallet"                           ║
║  3. Connect your Ethereum wallet (MetaMask, etc.)                 ║
║  4. Complete email verification                                   ║
║                                                                   ║
║  STEP 2: Fund Your Account                                        ║
║  ─────────────────────────────────────                            ║
║  1. Go to Portfolio → Deposit                                     ║
║  2. Deposit USDC (Polygon network)                                ║
║  3. For testing: Start with $50-100                               ║
║                                                                   ║
║  STEP 3: Generate API Credentials                                 ║
║  ─────────────────────────────────────                            ║
║  1. Go to https://polymarket.com/api                              ║
║  2. Or use the Python CLOB client to derive credentials:          ║
║                                                                   ║
║     from py_clob_client.client import ClobClient                  ║
║     from py_clob_client.clob_types import ApiCreds                ║
║                                                                   ║
║     # Connect with your wallet                                    ║
║     client = ClobClient(                                          ║
║         host="https://clob.polymarket.com",                       ║
║         chain_id=137,  # Polygon                                  ║
║         key="YOUR_PRIVATE_KEY"                                    ║
║     )                                                             ║
║                                                                   ║
║     # Derive API credentials                                      ║
║     creds = client.derive_api_creds()                             ║
║     print(creds)                                                  ║
║                                                                   ║
║  STEP 4: Configure Environment                                    ║
║  ─────────────────────────────────────                            ║
║  Create a .env file with:                                         ║
║                                                                   ║
║     POLYMARKET_API_KEY=your_api_key                               ║
║     POLYMARKET_API_SECRET=your_api_secret                         ║
║     POLYMARKET_PASSPHRASE=your_passphrase                         ║
║     POLYMARKET_WALLET=0x_your_wallet_address                      ║
║                                                                   ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  🔒 SECURITY NOTES:                                               ║
║  • Never commit .env to git                                       ║
║  • Never share your API credentials                               ║
║  • Start with small amounts for testing                           ║
║  • API credentials can be revoked if compromised                  ║
║                                                                   ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  📚 RESOURCES:                                                    ║
║  • Polymarket Docs: https://docs.polymarket.com                   ║
║  • CLOB API: https://docs.polymarket.com/#clob-api                ║
║  • py_clob_client: pip install py-clob-client                     ║
║                                                                   ║
╚══════════════════════════════════════════════════════════════════╝
"""
    
    def what_you_can_do_now(self) -> str:
        """Explain what's possible without credentials."""
        return """
╔══════════════════════════════════════════════════════════════════╗
║              WHAT YOU CAN DO WITHOUT CREDENTIALS                  ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  ✅ AVAILABLE NOW (No credentials needed):                        ║
║  ─────────────────────────────────────────                        ║
║  • Discover profitable wallets across all categories              ║
║  • Analyze any wallet's trading history                           ║
║  • Download trade data for any public wallet                      ║
║  • Extract trading patterns and logic                             ║
║  • Backtest strategies against historical data                    ║
║  • Build and test your cloned strategy                            ║
║  • View live orderbooks and prices                                ║
║                                                                   ║
║  ❌ REQUIRES CREDENTIALS:                                         ║
║  ─────────────────────────────────────────                        ║
║  • Place actual trades                                            ║
║  • View your own account balance                                  ║
║  • Execute live strategies                                        ║
║                                                                   ║
║  💡 RECOMMENDATION:                                               ║
║  ─────────────────────────────────────────                        ║
║  1. Start with discovery + analysis (no credentials)              ║
║  2. Find a wallet worth copying                                   ║
║  3. Understand their strategy completely                          ║
║  4. Backtest your cloned strategy                                 ║
║  5. THEN set up credentials for live trading                      ║
║                                                                   ║
║  This way you validate the strategy BEFORE risking money.         ║
║                                                                   ║
╚══════════════════════════════════════════════════════════════════╝
"""


def check_credentials():
    """Check and print credential status."""
    manager = CredentialManager()
    manager.print_status()
    return manager.status


def show_setup_guide():
    """Show the setup guide."""
    manager = CredentialManager()
    print(manager.get_setup_guide())


def show_what_you_can_do():
    """Show what's possible without credentials."""
    manager = CredentialManager()
    print(manager.what_you_can_do_now())
