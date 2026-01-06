#!/usr/bin/env python3
"""
Blockchain Trade Extractor for Polymarket

Extracts historical trade data directly from Polygon blockchain via RPC.
This is similar to what Dune Analytics does - querying indexed blockchain logs.

Data extracted:
- ERC1155 TransferSingle events (Polymarket position tokens)
- ERC20 Transfer events (USDC payments)
- Joined by tx_hash to get complete trade picture

Designed for EC2 deployment with:
- Checkpoint/resume capability for multi-hour runs
- Progress tracking and logging
- Multiple RPC endpoint fallback

Usage:
    # Extract trades for a single wallet (test mode - last 10k blocks)
    python blockchain_trade_extractor.py --wallet 0x7f69983eb28245bba0d5083502a78744a8f66162 --test

    # Full extraction (will take hours)
    python blockchain_trade_extractor.py --wallet 0x... --full

    # Resume interrupted extraction
    python blockchain_trade_extractor.py --wallet 0x... --resume

Estimated time:
    - Test mode (10k blocks): ~2 minutes
    - Full history (~60M blocks): 4-8 hours depending on RPC speed
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('extraction.log')
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Public Polygon RPC endpoints (no API key needed)
# These are the most reliable free endpoints
POLYGON_RPC_URLS = [
    "https://polygon-bor-rpc.publicnode.com",  # PublicNode - very reliable
    "https://polygon.drpc.org",  # dRPC - reliable
    "https://polygon-rpc.com",  # Official Polygon
]

# Polymarket CTF Exchange contract (ERC1155 position tokens)
CTF_EXCHANGE = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# USDC on Polygon
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Event signatures (keccak256 hashes)
# Transfer(address,address,uint256) for ERC20
ERC20_TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
# TransferSingle(address,address,address,uint256,uint256) for ERC1155
ERC1155_TRANSFER_SINGLE_TOPIC = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"

# Block ranges
# Public RPCs typically limit to 2000-3000 blocks per getLogs query
BLOCKS_PER_QUERY = 2000  # Safe limit for public RPCs
POLYGON_BLOCKS_PER_DAY = 43200  # ~2 second block time

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
CHECKPOINT_FILE = DATA_DIR / "extraction_checkpoint.json"

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ExtractionProgress:
    """Checkpoint for resumable extraction."""
    wallet: str
    current_block: int
    end_block: int
    total_erc1155: int
    total_erc20: int
    total_trades: int
    started_at: str
    last_update: str
    erc1155_raw: list = field(default_factory=list)
    erc20_raw: list = field(default_factory=list)

@dataclass
class Trade:
    """Complete trade record."""
    tx_hash: str
    block_number: int
    timestamp: int
    datetime_utc: str
    wallet: str
    side: str  # BUY or SELL
    token_id: str
    token_amount: float
    usdc_amount: float
    price: float
    log_index: int

# =============================================================================
# RPC CLIENT
# =============================================================================

class PolygonRPC:
    """Direct Polygon RPC client for blockchain queries."""

    def __init__(self, rpc_urls: list[str] = None):
        self.rpc_urls = rpc_urls or POLYGON_RPC_URLS
        self.current_rpc_idx = 0
        self.call_count = 0
        self.last_call_time = 0
        self.rate_delay = 0.1  # 10 calls/sec max

    @property
    def current_rpc(self) -> str:
        return self.rpc_urls[self.current_rpc_idx]

    def rotate_rpc(self):
        """Rotate to next RPC endpoint."""
        self.current_rpc_idx = (self.current_rpc_idx + 1) % len(self.rpc_urls)
        logger.info(f"Switched to RPC: {self.current_rpc}")

    def _rate_limit(self):
        """Enforce rate limiting."""
        elapsed = time.time() - self.last_call_time
        if elapsed < self.rate_delay:
            time.sleep(self.rate_delay - elapsed)
        self.last_call_time = time.time()
        self.call_count += 1

    def _call(self, method: str, params: list, retries: int = 3) -> dict:
        """Make JSON-RPC call with retries and fallback."""
        self._rate_limit()

        payload = {
            "jsonrpc": "2.0",
            "id": self.call_count,
            "method": method,
            "params": params,
        }

        for attempt in range(retries):
            try:
                req = Request(
                    self.current_rpc,
                    data=json.dumps(payload).encode(),
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    }
                )

                with urlopen(req, timeout=30) as resp:
                    result = json.loads(resp.read().decode())

                if "error" in result:
                    error_msg = result["error"].get("message", str(result["error"]))
                    logger.warning(f"RPC error: {error_msg}")
                    if attempt < retries - 1:
                        self.rotate_rpc()
                        time.sleep(1)
                        continue
                    return {"error": error_msg}

                return result

            except Exception as e:
                logger.warning(f"RPC call failed (attempt {attempt+1}): {e}")
                if attempt < retries - 1:
                    self.rotate_rpc()
                    time.sleep(2)
                else:
                    return {"error": str(e)}

        return {"error": "All retries failed"}

    def get_block_number(self) -> int:
        """Get current block number."""
        result = self._call("eth_blockNumber", [])
        if "result" in result:
            return int(result["result"], 16)
        logger.error(f"Failed to get block number: {result}")
        return 0

    def get_block_timestamp(self, block_number: int) -> int:
        """Get timestamp for a block."""
        result = self._call("eth_getBlockByNumber", [hex(block_number), False])
        if "result" in result and result["result"]:
            return int(result["result"]["timestamp"], 16)
        return 0

    def get_logs(
        self,
        from_block: int,
        to_block: int,
        address: str = None,
        topics: list = None
    ) -> list:
        """Get event logs for block range."""
        params = {
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
        }

        if address:
            params["address"] = address
        if topics:
            params["topics"] = topics

        result = self._call("eth_getLogs", [params])

        if "result" in result:
            return result["result"]
        else:
            logger.warning(f"getLogs failed: {result.get('error', 'Unknown error')}")
            return []

# =============================================================================
# TRADE EXTRACTOR
# =============================================================================

class TradeExtractor:
    """Extract Polymarket trades from blockchain logs."""

    def __init__(self, rpc: PolygonRPC, output_dir: Path = DATA_DIR):
        self.rpc = rpc
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def pad_address(self, address: str) -> str:
        """Pad address to 32 bytes for topic filtering."""
        return "0x" + address[2:].lower().zfill(64)

    def load_checkpoint(self) -> Optional[ExtractionProgress]:
        """Load extraction checkpoint if exists."""
        if CHECKPOINT_FILE.exists():
            try:
                with open(CHECKPOINT_FILE) as f:
                    data = json.load(f)
                    return ExtractionProgress(**data)
            except Exception as e:
                logger.warning(f"Failed to load checkpoint: {e}")
        return None

    def save_checkpoint(self, progress: ExtractionProgress):
        """Save extraction checkpoint."""
        progress.last_update = datetime.now(timezone.utc).isoformat()
        with open(CHECKPOINT_FILE, 'w') as f:
            json.dump(asdict(progress), f)
        logger.debug(f"Checkpoint saved at block {progress.current_block}")

    def clear_checkpoint(self):
        """Clear checkpoint after successful completion."""
        if CHECKPOINT_FILE.exists():
            CHECKPOINT_FILE.unlink()
            logger.info("Checkpoint cleared")

    def find_first_activity_block(self, wallet: str, end_block: int) -> int:
        """Binary search to find first block with wallet activity.

        This dramatically speeds up extraction by finding where the wallet
        first appears on-chain instead of scanning from block 0.
        """
        logger.info("Finding first activity block (binary search)...")

        wallet_topic = self.pad_address(wallet)

        # Start from reasonable Polymarket launch date
        # Polymarket on Polygon started around block 25M (early 2022)
        left = 25_000_000
        right = end_block
        first_block = end_block

        while left <= right:
            mid = (left + right) // 2

            # Check for any ERC1155 activity in a small range
            logs = self.rpc.get_logs(
                from_block=mid,
                to_block=min(mid + 100000, right),
                address=CTF_EXCHANGE,
                topics=[
                    ERC1155_TRANSFER_SINGLE_TOPIC,
                    None,  # operator
                    None,  # from (any)
                    wallet_topic,  # to (our wallet = buys)
                ]
            )

            # Also check sells (from our wallet)
            logs2 = self.rpc.get_logs(
                from_block=mid,
                to_block=min(mid + 100000, right),
                address=CTF_EXCHANGE,
                topics=[
                    ERC1155_TRANSFER_SINGLE_TOPIC,
                    None,  # operator
                    wallet_topic,  # from (our wallet = sells)
                    None,  # to (any)
                ]
            )

            if logs or logs2:
                # Found activity, search earlier
                first_block = min(first_block, mid)
                right = mid - 1
            else:
                # No activity, search later
                left = mid + 100001

            logger.debug(f"  Binary search: block {mid}, found: {len(logs) + len(logs2)}")

        logger.info(f"First activity found around block {first_block}")
        return max(first_block - 10000, 25_000_000)  # Buffer for safety

    def fetch_erc1155_logs(
        self,
        wallet: str,
        from_block: int,
        to_block: int,
        progress_callback=None
    ) -> list[dict]:
        """Fetch all ERC1155 TransferSingle events for wallet."""
        wallet_topic = self.pad_address(wallet)
        all_logs = []

        current = from_block
        total_blocks = to_block - from_block
        last_progress_log = 0

        while current <= to_block:
            chunk_end = min(current + BLOCKS_PER_QUERY - 1, to_block)

            # Get BUYS (wallet is recipient)
            buy_logs = self.rpc.get_logs(
                from_block=current,
                to_block=chunk_end,
                address=CTF_EXCHANGE,
                topics=[
                    ERC1155_TRANSFER_SINGLE_TOPIC,
                    None,  # operator
                    None,  # from (any)
                    wallet_topic,  # to (our wallet)
                ]
            )

            for log in buy_logs:
                log["_side"] = "BUY"
            all_logs.extend(buy_logs)

            # Get SELLS (wallet is sender)
            sell_logs = self.rpc.get_logs(
                from_block=current,
                to_block=chunk_end,
                address=CTF_EXCHANGE,
                topics=[
                    ERC1155_TRANSFER_SINGLE_TOPIC,
                    None,  # operator
                    wallet_topic,  # from (our wallet)
                    None,  # to (any)
                ]
            )

            for log in sell_logs:
                log["_side"] = "SELL"
            all_logs.extend(sell_logs)

            # Log progress periodically
            blocks_done = current - from_block
            if buy_logs or sell_logs or blocks_done - last_progress_log >= 50000:
                pct = (blocks_done / total_blocks * 100) if total_blocks > 0 else 100
                logger.info(f"  [{pct:5.1f}%] Blocks {current:,}-{chunk_end:,}: {len(buy_logs)} buys, {len(sell_logs)} sells (total: {len(all_logs):,})")
                last_progress_log = blocks_done

            # Call progress callback for checkpointing
            if progress_callback:
                progress_callback(current, len(all_logs))

            current = chunk_end + 1

        return all_logs

    def fetch_erc20_logs(
        self,
        wallet: str,
        from_block: int,
        to_block: int
    ) -> list[dict]:
        """Fetch all USDC Transfer events for wallet."""
        wallet_topic = self.pad_address(wallet)
        all_logs = []

        current = from_block
        while current <= to_block:
            chunk_end = min(current + BLOCKS_PER_QUERY - 1, to_block)

            # Get incoming USDC (wallet is recipient)
            in_logs = self.rpc.get_logs(
                from_block=current,
                to_block=chunk_end,
                address=USDC_CONTRACT,
                topics=[
                    ERC20_TRANSFER_TOPIC,
                    None,  # from (any)
                    wallet_topic,  # to (our wallet)
                ]
            )

            for log in in_logs:
                log["_direction"] = "IN"
            all_logs.extend(in_logs)

            # Get outgoing USDC (wallet is sender)
            out_logs = self.rpc.get_logs(
                from_block=current,
                to_block=chunk_end,
                address=USDC_CONTRACT,
                topics=[
                    ERC20_TRANSFER_TOPIC,
                    wallet_topic,  # from (our wallet)
                    None,  # to (any)
                ]
            )

            for log in out_logs:
                log["_direction"] = "OUT"
            all_logs.extend(out_logs)

            if (in_logs or out_logs):
                logger.debug(f"  USDC Blocks {current:,}-{chunk_end:,}: {len(in_logs)} in, {len(out_logs)} out")

            current = chunk_end + 1

        return all_logs

    def parse_erc1155_log(self, log: dict) -> dict:
        """Parse ERC1155 TransferSingle log."""
        # Data contains: id (uint256) + value (uint256)
        data = log.get("data", "0x")
        if len(data) >= 130:  # 0x + 64 + 64 chars
            token_id = int(data[2:66], 16)
            token_value = int(data[66:130], 16)
        else:
            token_id = 0
            token_value = 0

        return {
            "tx_hash": log.get("transactionHash", ""),
            "block_number": int(log.get("blockNumber", "0x0"), 16),
            "log_index": int(log.get("logIndex", "0x0"), 16),
            "token_id": str(token_id),
            "token_value": token_value,
            "side": log.get("_side", "UNKNOWN"),
        }

    def parse_erc20_log(self, log: dict) -> dict:
        """Parse ERC20 Transfer log."""
        # Data contains value (uint256)
        data = log.get("data", "0x")
        if len(data) >= 66:
            value = int(data[2:66], 16)
        else:
            value = 0

        return {
            "tx_hash": log.get("transactionHash", ""),
            "block_number": int(log.get("blockNumber", "0x0"), 16),
            "log_index": int(log.get("logIndex", "0x0"), 16),
            "value": value,  # Raw value, 6 decimals for USDC
            "direction": log.get("_direction", "UNKNOWN"),
        }

    def join_trades(
        self,
        wallet: str,
        erc1155_logs: list[dict],
        erc20_logs: list[dict]
    ) -> list[Trade]:
        """Join ERC1155 and ERC20 logs into complete trades."""
        # Parse logs
        erc1155_parsed = [self.parse_erc1155_log(log) for log in erc1155_logs]
        erc20_parsed = [self.parse_erc20_log(log) for log in erc20_logs]

        # Index USDC by tx_hash
        usdc_by_tx = {}
        for tx in erc20_parsed:
            tx_hash = tx["tx_hash"].lower()
            if tx_hash not in usdc_by_tx:
                usdc_by_tx[tx_hash] = []
            usdc_by_tx[tx_hash].append(tx)

        # Create trades
        trades = []
        for erc1155 in erc1155_parsed:
            tx_hash = erc1155["tx_hash"].lower()

            # Get token amount
            # Polymarket uses 1e6 scaling for share amounts (like USDC)
            # The raw value is the number of "shares" in smallest unit
            raw_token_value = erc1155["token_value"]
            token_amount = raw_token_value / 1e6  # Convert to human-readable shares

            # Find matching USDC transfer
            usdc_amount = 0.0
            if tx_hash in usdc_by_tx:
                for usdc_tx in usdc_by_tx[tx_hash]:
                    usdc_amount += usdc_tx["value"] / 1e6  # USDC has 6 decimals

            # Calculate price (USDC per share)
            # Price should be between 0 and 1 for binary markets
            price = usdc_amount / token_amount if token_amount > 0 else 0

            trade = Trade(
                tx_hash=tx_hash,
                block_number=erc1155["block_number"],
                timestamp=0,  # Will populate later if needed
                datetime_utc="",
                wallet=wallet,
                side=erc1155["side"],
                token_id=erc1155["token_id"],
                token_amount=token_amount,
                usdc_amount=usdc_amount,
                price=price,
                log_index=erc1155["log_index"],
            )
            trades.append(trade)

        # Sort by block and log index
        trades.sort(key=lambda t: (t.block_number, t.log_index))

        return trades

    def extract_wallet(
        self,
        wallet: str,
        test_mode: bool = False,
        resume: bool = False
    ) -> list[Trade]:
        """Extract all trades for a wallet."""
        logger.info(f"\n{'='*60}")
        logger.info(f"EXTRACTING TRADES FOR WALLET")
        logger.info(f"{'='*60}")
        logger.info(f"Wallet: {wallet}")

        # Get current block
        current_block = self.rpc.get_block_number()
        logger.info(f"Current block: {current_block:,}")

        # Determine block range
        if test_mode:
            # Last 10k blocks only (~5.5 hours of data)
            start_block = current_block - 10000
            logger.info(f"TEST MODE: Scanning last 10,000 blocks only")
        else:
            # Find first activity (binary search)
            start_block = self.find_first_activity_block(wallet, current_block)

        end_block = current_block

        # Check for checkpoint
        progress = None
        if resume:
            progress = self.load_checkpoint()
            if progress and progress.wallet.lower() == wallet.lower():
                start_block = progress.current_block
                logger.info(f"Resuming from block {start_block:,}")
            else:
                progress = None

        if not progress:
            progress = ExtractionProgress(
                wallet=wallet,
                current_block=start_block,
                end_block=end_block,
                total_erc1155=0,
                total_erc20=0,
                total_trades=0,
                started_at=datetime.now(timezone.utc).isoformat(),
                last_update=datetime.now(timezone.utc).isoformat(),
            )

        blocks_to_scan = end_block - start_block
        logger.info(f"Block range: {start_block:,} to {end_block:,} ({blocks_to_scan:,} blocks)")
        logger.info(f"Estimated time: {blocks_to_scan / BLOCKS_PER_QUERY * 0.3 / 60:.1f} minutes")

        # Fetch ERC1155 logs
        logger.info(f"\nStep 1: Fetching ERC1155 transfers (position tokens)")
        erc1155_logs = self.fetch_erc1155_logs(wallet, start_block, end_block)
        progress.total_erc1155 = len(erc1155_logs)
        logger.info(f"Found {len(erc1155_logs):,} ERC1155 transfers")

        # Fetch ERC20 logs
        logger.info(f"\nStep 2: Fetching ERC20 transfers (USDC)")
        erc20_logs = self.fetch_erc20_logs(wallet, start_block, end_block)
        progress.total_erc20 = len(erc20_logs)
        logger.info(f"Found {len(erc20_logs):,} ERC20 transfers")

        # Join into trades
        logger.info(f"\nStep 3: Joining into trades")
        trades = self.join_trades(wallet, erc1155_logs, erc20_logs)
        progress.total_trades = len(trades)

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info(f"EXTRACTION COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"ERC1155 transfers: {progress.total_erc1155:,}")
        logger.info(f"ERC20 transfers: {progress.total_erc20:,}")
        logger.info(f"Total trades: {progress.total_trades:,}")
        logger.info(f"RPC calls: {self.rpc.call_count}")

        # Clear checkpoint on success
        self.clear_checkpoint()

        return trades

    def save_trades(self, trades: list[Trade], filename: str) -> Path:
        """Save trades to JSON file."""
        output_path = self.output_dir / filename

        trade_dicts = [asdict(t) for t in trades]

        with open(output_path, 'w') as f:
            json.dump(trade_dicts, f, indent=2)

        logger.info(f"Saved {len(trades):,} trades to {output_path}")
        return output_path

# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Extract Polymarket trades from Polygon blockchain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test mode - last 10k blocks only (~5 hours of data)
  python blockchain_trade_extractor.py --wallet 0x7f69983eb28245bba0d5083502a78744a8f66162 --test

  # Full extraction (can take hours)
  python blockchain_trade_extractor.py --wallet 0x... --full

  # Resume interrupted extraction
  python blockchain_trade_extractor.py --wallet 0x... --full --resume
        """
    )

    parser.add_argument(
        "--wallet",
        type=str,
        required=True,
        help="Wallet address to extract trades for"
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode - only scan last 10,000 blocks"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full extraction - scan from first activity"
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from checkpoint if available"
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output filename (default: blockchain_trades_<wallet>.json)"
    )

    args = parser.parse_args()

    if not args.test and not args.full:
        parser.error("Must specify --test or --full")

    logger.info(f"\n{'='*60}")
    logger.info("BLOCKCHAIN TRADE EXTRACTOR")
    logger.info(f"{'='*60}")
    logger.info(f"Mode: {'TEST' if args.test else 'FULL'}")
    logger.info(f"Wallet: {args.wallet}")
    logger.info(f"Resume: {args.resume}")

    # Initialize
    rpc = PolygonRPC()
    extractor = TradeExtractor(rpc)

    # Extract trades
    trades = extractor.extract_wallet(
        args.wallet,
        test_mode=args.test,
        resume=args.resume
    )

    # Save
    wallet_short = args.wallet[:10]
    output_file = args.output or f"blockchain_trades_{wallet_short}.json"
    extractor.save_trades(trades, output_file)

    # Summary
    logger.info(f"\n{'='*60}")
    logger.info("DONE")
    logger.info(f"{'='*60}")
    logger.info(f"Total trades: {len(trades):,}")
    logger.info(f"Output: data/{output_file}")


if __name__ == "__main__":
    main()
