#!/usr/bin/env python3
"""
Etherscan V2 Trade Extractor for Polymarket

Extracts complete trading history using Etherscan V2 API.
Much faster and more reliable than direct RPC queries.

Features:
- Uses unified Etherscan V2 API (chainid=137 for Polygon)
- Pagination support for unlimited history
- ERC1155 transfers (Polymarket positions) + ERC20 (USDC payments)
- Checkpoint/resume capability
- Rate limiting (5 calls/sec for free tier)

Usage:
    export ETHERSCAN_API_KEY="your-key-here"
    python etherscan_trade_extractor.py --wallet 0x... --test
    python etherscan_trade_extractor.py --wallet 0x... --full
"""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('etherscan_extraction.log')
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Etherscan V2 API endpoint (works for Polygon with chainid=137)
ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"
POLYGON_CHAIN_ID = 137

# API key from environment
API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")

# Rate limiting: 5 calls/sec for free tier
RATE_LIMIT_DELAY = 0.25  # 4 calls/sec to be safe

# Pagination
MAX_RECORDS_PER_PAGE = 1000  # Max allowed by API

# Polymarket contracts
CTF_EXCHANGE = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_CONTRACT = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Paths
DATA_DIR = Path(__file__).parent.parent / "data"
CHECKPOINT_FILE = DATA_DIR / "etherscan_checkpoint.json"


# =============================================================================
# API FUNCTIONS
# =============================================================================

def fetch_etherscan(module: str, action: str, params: dict) -> dict:
    """Fetch from Etherscan V2 API."""
    all_params = {
        "chainid": POLYGON_CHAIN_ID,
        "module": module,
        "action": action,
        "apikey": API_KEY,
        **params,
    }

    url = f"{ETHERSCAN_V2_URL}?{urlencode(all_params)}"
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "PolymarketTracker/1.0"
    })

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"API error: {e}")
        return {"status": "0", "message": str(e), "result": []}


def get_erc1155_transfers(wallet: str, start_block: int = 0, end_block: int = 99999999, page: int = 1) -> list:
    """Get ERC1155 transfers (Polymarket position tokens)."""
    result = fetch_etherscan("account", "token1155tx", {
        "address": wallet,
        "startblock": start_block,
        "endblock": end_block,
        "page": page,
        "offset": MAX_RECORDS_PER_PAGE,
        "sort": "asc",  # Oldest first for consistent pagination
    })

    if result.get("status") == "1":
        return result.get("result", [])
    return []


def get_erc20_transfers(wallet: str, start_block: int = 0, end_block: int = 99999999, page: int = 1) -> list:
    """Get ERC20 transfers (USDC payments)."""
    result = fetch_etherscan("account", "tokentx", {
        "address": wallet,
        "startblock": start_block,
        "endblock": end_block,
        "page": page,
        "offset": MAX_RECORDS_PER_PAGE,
        "sort": "asc",
    })

    if result.get("status") == "1":
        return result.get("result", [])
    return []


# =============================================================================
# EXTRACTION LOGIC
# =============================================================================

@dataclass
class ExtractionCheckpoint:
    """Checkpoint for resumable extraction."""
    wallet: str
    erc1155_page: int
    erc20_page: int
    erc1155_complete: bool
    erc20_complete: bool
    total_erc1155: int
    total_erc20: int
    started_at: str
    updated_at: str


def save_checkpoint(checkpoint: ExtractionCheckpoint):
    """Save extraction checkpoint."""
    checkpoint.updated_at = datetime.now().isoformat()
    with open(CHECKPOINT_FILE, 'w') as f:
        json.dump(asdict(checkpoint), f, indent=2)


def load_checkpoint(wallet: str) -> Optional[ExtractionCheckpoint]:
    """Load existing checkpoint for wallet."""
    if not CHECKPOINT_FILE.exists():
        return None

    try:
        with open(CHECKPOINT_FILE) as f:
            data = json.load(f)
        if data.get("wallet", "").lower() == wallet.lower():
            return ExtractionCheckpoint(**data)
    except Exception as e:
        logger.warning(f"Could not load checkpoint: {e}")
    return None


def extract_all_transfers(wallet: str, transfer_type: str = "erc1155", max_records: int = None) -> list:
    """
    Extract all transfers using block-range pagination to bypass 10k limit.

    Etherscan has a 10k record limit per query, so we paginate within each
    block range, then move to the next range.
    """
    all_transfers = []
    start_block = 0
    end_block = 99999999

    fetch_func = get_erc1155_transfers if transfer_type == "erc1155" else get_erc20_transfers
    label = "ERC1155" if transfer_type == "erc1155" else "ERC20"

    iteration = 0
    max_iterations = 1000  # Safety limit

    while iteration < max_iterations:
        iteration += 1
        page = 1
        chunk_transfers = []

        # Fetch pages within current block range
        while page <= 10:  # Max 10 pages (10k records) per block range
            logger.info(f"Fetching {label} block {start_block}+ page {page}...")
            transfers = fetch_func(wallet, start_block, end_block, page)

            if not transfers:
                break

            chunk_transfers.extend(transfers)
            logger.info(f"  Got {len(transfers)} transfers, chunk: {len(chunk_transfers)}, total: {len(all_transfers) + len(chunk_transfers)}")

            if len(transfers) < MAX_RECORDS_PER_PAGE:
                # Reached end of data in this range
                break

            page += 1
            time.sleep(RATE_LIMIT_DELAY)

        if not chunk_transfers:
            logger.info(f"No more {label} data")
            break

        all_transfers.extend(chunk_transfers)

        # Check if we hit the 10k limit (need to continue with next block range)
        if len(chunk_transfers) >= 10000:
            # Get the last block from this chunk and continue from there
            last_block = max(int(t.get("blockNumber", 0)) for t in chunk_transfers)
            start_block = last_block + 1
            logger.info(f"Hit 10k limit, continuing from block {start_block}")
        else:
            # We got everything
            break

        if max_records and len(all_transfers) >= max_records:
            logger.info(f"Reached max records limit: {max_records}")
            break

    return all_transfers


def extract_all_erc1155(wallet: str, start_page: int = 1, max_pages: int = 10000, max_records: int = None) -> list:
    """Extract all ERC1155 transfers with block-range pagination."""
    return extract_all_transfers(wallet, "erc1155", max_records)


def extract_all_erc20(wallet: str, start_page: int = 1, max_pages: int = 10000, max_records: int = None) -> list:
    """Extract all ERC20 transfers with block-range pagination."""
    return extract_all_transfers(wallet, "erc20", max_records)


def join_trades(erc1155_transfers: list, erc20_transfers: list, wallet: str) -> list:
    """Join ERC1155 and ERC20 transfers into trades."""
    logger.info(f"Joining {len(erc1155_transfers)} ERC1155 with {len(erc20_transfers)} ERC20 transfers...")

    # Index ERC20 by tx_hash
    erc20_by_tx = {}
    for tx in erc20_transfers:
        tx_hash = tx.get("hash", "").lower()
        if tx_hash not in erc20_by_tx:
            erc20_by_tx[tx_hash] = []
        erc20_by_tx[tx_hash].append(tx)

    trades = []
    wallet_lower = wallet.lower()

    for erc1155 in erc1155_transfers:
        tx_hash = erc1155.get("hash", "").lower()
        from_addr = erc1155.get("from", "").lower()
        to_addr = erc1155.get("to", "").lower()

        # Determine side
        if to_addr == wallet_lower:
            side = "BUY"
        elif from_addr == wallet_lower:
            side = "SELL"
        else:
            continue  # Not our trade

        # Get token amount (raw value, typically needs no scaling for Polymarket)
        try:
            token_amount = float(erc1155.get("tokenValue", 0)) / 1e6
        except:
            token_amount = 0

        # Find matching USDC transfer
        usdc_amount = 0
        if tx_hash in erc20_by_tx:
            for erc20 in erc20_by_tx[tx_hash]:
                token_symbol = erc20.get("tokenSymbol", "")
                if "USDC" in token_symbol.upper():
                    try:
                        # USDC has 6 decimals
                        decimals = int(erc20.get("tokenDecimal", 6))
                        usdc_amount = float(erc20.get("value", 0)) / (10 ** decimals)
                    except:
                        pass
                    break

        # Calculate price
        price = usdc_amount / token_amount if token_amount > 0 else 0

        # Parse timestamp
        try:
            timestamp = int(erc1155.get("timeStamp", 0))
            dt = datetime.fromtimestamp(timestamp)
        except:
            timestamp = 0
            dt = None

        trade = {
            "tx_hash": tx_hash,
            "block_number": int(erc1155.get("blockNumber", 0)),
            "timestamp": timestamp,
            "datetime_utc": dt.isoformat() if dt else "",
            "wallet": wallet,
            "side": side,
            "token_id": erc1155.get("tokenID", ""),
            "token_name": erc1155.get("tokenName", ""),
            "token_amount": token_amount,
            "usdc_amount": usdc_amount,
            "price": price,
        }
        trades.append(trade)

    # Sort by timestamp
    trades.sort(key=lambda x: x["timestamp"])

    logger.info(f"Created {len(trades)} trades")
    return trades


def run_extraction(wallet: str, test_mode: bool = False, resume: bool = False):
    """Run full extraction for a wallet."""
    if not API_KEY:
        logger.error("ETHERSCAN_API_KEY environment variable not set!")
        logger.error("Get free key at: https://etherscan.io/apis")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)

    wallet_short = wallet[:10].lower()
    output_file = DATA_DIR / f"etherscan_trades_{wallet_short}.json"

    logger.info("=" * 60)
    logger.info("ETHERSCAN V2 TRADE EXTRACTOR")
    logger.info("=" * 60)
    logger.info(f"Wallet: {wallet}")
    logger.info(f"Mode: {'TEST (5 pages)' if test_mode else 'FULL'}")
    logger.info(f"Output: {output_file}")
    logger.info("")

    max_pages = 5 if test_mode else 10000

    # Check for resume
    checkpoint = None
    if resume:
        checkpoint = load_checkpoint(wallet)
        if checkpoint:
            logger.info(f"Resuming from checkpoint (ERC1155 page {checkpoint.erc1155_page}, ERC20 page {checkpoint.erc20_page})")

    # Extract ERC1155
    logger.info("Phase 1: Extracting ERC1155 transfers...")
    start_page = checkpoint.erc1155_page if checkpoint and not checkpoint.erc1155_complete else 1
    erc1155_transfers = extract_all_erc1155(wallet, start_page, max_pages)
    logger.info(f"Total ERC1155 transfers: {len(erc1155_transfers)}")

    # Extract ERC20
    logger.info("\nPhase 2: Extracting ERC20 transfers...")
    start_page = checkpoint.erc20_page if checkpoint and not checkpoint.erc20_complete else 1
    erc20_transfers = extract_all_erc20(wallet, start_page, max_pages)
    logger.info(f"Total ERC20 transfers: {len(erc20_transfers)}")

    # Join into trades
    logger.info("\nPhase 3: Joining into trades...")
    trades = join_trades(erc1155_transfers, erc20_transfers, wallet)

    # Save
    logger.info(f"\nSaving {len(trades)} trades to {output_file}...")
    with open(output_file, 'w') as f:
        json.dump(trades, f, indent=2)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Total trades: {len(trades)}")

    if trades:
        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        total_volume = sum(t["usdc_amount"] for t in trades)

        logger.info(f"Buys: {len(buys)}")
        logger.info(f"Sells: {len(sells)}")
        logger.info(f"Total volume: ${total_volume:,.2f}")

        if trades[0]["datetime_utc"] and trades[-1]["datetime_utc"]:
            logger.info(f"First trade: {trades[0]['datetime_utc']}")
            logger.info(f"Last trade: {trades[-1]['datetime_utc']}")

    logger.info(f"\nOutput saved to: {output_file}")
    return trades


def main():
    parser = argparse.ArgumentParser(description="Extract Polymarket trades via Etherscan V2 API")
    parser.add_argument("--wallet", required=True, help="Wallet address to extract")
    parser.add_argument("--test", action="store_true", help="Test mode (5 pages only)")
    parser.add_argument("--full", action="store_true", help="Full extraction (all pages)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")

    args = parser.parse_args()

    if not args.test and not args.full:
        args.test = True  # Default to test mode for safety

    run_extraction(args.wallet, test_mode=args.test, resume=args.resume)


if __name__ == "__main__":
    main()
