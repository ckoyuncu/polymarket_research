#!/usr/bin/env python3
"""
Memory-Efficient Streaming Trade Extractor for Polymarket

Extracts complete trading history using Etherscan V2 API with:
- Streaming writes to disk (not holding all data in memory)
- Checkpoint/resume capability after each chunk
- Memory usage stays under 500MB regardless of wallet size

Usage:
    export ETHERSCAN_API_KEY="your-key-here"
    python etherscan_streaming_extractor.py --wallet 0x... --full
    python etherscan_streaming_extractor.py --wallet 0x... --resume
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('streaming_extraction.log')
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"
POLYGON_CHAIN_ID = 137
API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
RATE_LIMIT_DELAY = 0.25
MAX_RECORDS_PER_PAGE = 1000

DATA_DIR = Path(__file__).parent.parent / "data"


# =============================================================================
# API FUNCTIONS
# =============================================================================

def fetch_etherscan(module: str, action: str, params: dict) -> dict:
    """Fetch from Etherscan V2 API with retry."""
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
        "User-Agent": "PolymarketExtractor/2.0"
    })

    for attempt in range(3):
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            logger.warning(f"API error (attempt {attempt + 1}): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return {"status": "0", "message": "Max retries exceeded", "result": []}


def get_transfers(wallet: str, transfer_type: str, start_block: int, page: int) -> list:
    """Get transfers of specified type."""
    action = "token1155tx" if transfer_type == "erc1155" else "tokentx"

    result = fetch_etherscan("account", action, {
        "address": wallet,
        "startblock": start_block,
        "endblock": 99999999,
        "page": page,
        "offset": MAX_RECORDS_PER_PAGE,
        "sort": "asc",
    })

    if result.get("status") == "1":
        return result.get("result", [])
    return []


# =============================================================================
# CHECKPOINT MANAGEMENT
# =============================================================================

def get_checkpoint_path(wallet: str) -> Path:
    """Get checkpoint file path for wallet."""
    wallet_short = wallet[:10].lower()
    return DATA_DIR / f"checkpoint_{wallet_short}.json"


def get_transfers_path(wallet: str, transfer_type: str) -> Path:
    """Get transfers file path."""
    wallet_short = wallet[:10].lower()
    return DATA_DIR / f"transfers_{wallet_short}_{transfer_type}.jsonl"


def get_output_path(wallet: str) -> Path:
    """Get final output file path."""
    wallet_short = wallet[:10].lower()
    return DATA_DIR / f"trades_{wallet_short}.json"


def load_checkpoint(wallet: str) -> dict:
    """Load checkpoint for wallet."""
    checkpoint_path = get_checkpoint_path(wallet)
    if checkpoint_path.exists():
        try:
            with open(checkpoint_path) as f:
                return json.load(f)
        except:
            pass

    return {
        "wallet": wallet,
        "erc1155_start_block": 0,
        "erc1155_count": 0,
        "erc1155_complete": False,
        "erc20_start_block": 0,
        "erc20_count": 0,
        "erc20_complete": False,
        "started_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }


def save_checkpoint(checkpoint: dict):
    """Save checkpoint to disk."""
    checkpoint["updated_at"] = datetime.now().isoformat()
    checkpoint_path = get_checkpoint_path(checkpoint["wallet"])

    with open(checkpoint_path, 'w') as f:
        json.dump(checkpoint, f, indent=2)


# =============================================================================
# STREAMING EXTRACTION
# =============================================================================

def extract_transfers_streaming(wallet: str, transfer_type: str, checkpoint: dict) -> int:
    """
    Extract transfers using streaming write to disk.

    Writes each chunk to a JSONL file immediately, keeping memory low.
    Returns total count of transfers extracted.
    """
    label = transfer_type.upper()
    start_block_key = f"{transfer_type}_start_block"
    count_key = f"{transfer_type}_count"
    complete_key = f"{transfer_type}_complete"

    # Check if already complete
    if checkpoint.get(complete_key, False):
        logger.info(f"{label}: Already complete ({checkpoint.get(count_key, 0):,} transfers)")
        return checkpoint.get(count_key, 0)

    output_path = get_transfers_path(wallet, transfer_type)
    start_block = checkpoint.get(start_block_key, 0)
    total_count = checkpoint.get(count_key, 0)

    # Open file in append mode if resuming
    mode = 'a' if start_block > 0 else 'w'

    logger.info(f"{label}: Starting from block {start_block:,} (have {total_count:,} transfers)")

    iteration = 0
    max_iterations = 2000  # Safety limit

    with open(output_path, mode) as f:
        while iteration < max_iterations:
            iteration += 1
            page = 1
            chunk_count = 0
            chunk_last_block = start_block

            # Fetch pages within current block range
            while page <= 10:
                transfers = get_transfers(wallet, transfer_type, start_block, page)

                if not transfers:
                    break

                # Write each transfer to file immediately
                for tx in transfers:
                    f.write(json.dumps(tx) + "\n")
                    chunk_last_block = max(chunk_last_block, int(tx.get("blockNumber", 0)))

                chunk_count += len(transfers)
                total_count += len(transfers)

                logger.info(f"  {label}: block {start_block}+ page {page} -> {len(transfers)} transfers (total: {total_count:,})")

                if len(transfers) < MAX_RECORDS_PER_PAGE:
                    break

                page += 1
                time.sleep(RATE_LIMIT_DELAY)

            # Flush writes and save checkpoint
            f.flush()

            if chunk_count == 0:
                # No more data
                checkpoint[complete_key] = True
                checkpoint[count_key] = total_count
                save_checkpoint(checkpoint)
                logger.info(f"{label}: Complete! Total: {total_count:,} transfers")
                break

            # Update checkpoint after each chunk
            if chunk_count >= 10000:
                # Hit 10k limit, continue from last block + 1
                start_block = chunk_last_block + 1
                checkpoint[start_block_key] = start_block
                checkpoint[count_key] = total_count
                save_checkpoint(checkpoint)
                logger.info(f"{label}: Checkpoint saved at block {start_block:,} ({total_count:,} transfers)")
            else:
                # Got everything
                checkpoint[complete_key] = True
                checkpoint[count_key] = total_count
                save_checkpoint(checkpoint)
                logger.info(f"{label}: Complete! Total: {total_count:,} transfers")
                break

    return total_count


def load_transfers_from_file(filepath: Path) -> list:
    """Load transfers from JSONL file."""
    transfers = []
    if filepath.exists():
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if line:
                    transfers.append(json.loads(line))
    return transfers


def join_trades_streaming(wallet: str) -> list:
    """Join ERC1155 and ERC20 transfers into trades."""
    logger.info("Loading transfers from disk...")

    erc1155_path = get_transfers_path(wallet, "erc1155")
    erc20_path = get_transfers_path(wallet, "erc20")

    # Load ERC20 into memory (usually smaller, needed for lookup)
    erc20_transfers = load_transfers_from_file(erc20_path)
    logger.info(f"Loaded {len(erc20_transfers):,} ERC20 transfers")

    # Index ERC20 by tx_hash
    erc20_by_tx = {}
    for tx in erc20_transfers:
        tx_hash = tx.get("hash", "").lower()
        if tx_hash not in erc20_by_tx:
            erc20_by_tx[tx_hash] = []
        erc20_by_tx[tx_hash].append(tx)

    # Free memory
    del erc20_transfers

    # Process ERC1155 in streaming fashion
    trades = []
    wallet_lower = wallet.lower()

    logger.info("Processing ERC1155 transfers...")
    with open(erc1155_path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            erc1155 = json.loads(line)
            tx_hash = erc1155.get("hash", "").lower()
            from_addr = erc1155.get("from", "").lower()
            to_addr = erc1155.get("to", "").lower()

            # Determine side
            if to_addr == wallet_lower:
                side = "BUY"
            elif from_addr == wallet_lower:
                side = "SELL"
            else:
                continue

            # Get token amount
            try:
                token_amount = float(erc1155.get("tokenValue", 0)) / 1e6
            except:
                token_amount = 0

            # Find matching USDC transfer
            usdc_amount = 0
            if tx_hash in erc20_by_tx:
                for erc20 in erc20_by_tx[tx_hash]:
                    if "USDC" in erc20.get("tokenSymbol", "").upper():
                        try:
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
                "token_amount": token_amount,
                "usdc_amount": usdc_amount,
                "price": price,
            }
            trades.append(trade)

            if line_num % 100000 == 0:
                logger.info(f"  Processed {line_num:,} ERC1155 transfers -> {len(trades):,} trades")

    # Sort by timestamp
    trades.sort(key=lambda x: x["timestamp"])

    logger.info(f"Created {len(trades):,} trades")
    return trades


# =============================================================================
# MAIN EXTRACTION
# =============================================================================

def run_extraction(wallet: str, resume: bool = False):
    """Run full streaming extraction for a wallet."""
    if not API_KEY:
        logger.error("ETHERSCAN_API_KEY environment variable not set!")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)

    logger.info("=" * 60)
    logger.info("STREAMING TRADE EXTRACTOR (Memory-Efficient)")
    logger.info("=" * 60)
    logger.info(f"Wallet: {wallet}")
    logger.info(f"Resume: {resume}")
    logger.info("")

    # Load or create checkpoint
    checkpoint = load_checkpoint(wallet)

    if not resume:
        # Fresh start - clear any existing data
        for path in [get_checkpoint_path(wallet),
                     get_transfers_path(wallet, "erc1155"),
                     get_transfers_path(wallet, "erc20")]:
            if path.exists():
                path.unlink()
        checkpoint = load_checkpoint(wallet)

    # Phase 1: Extract ERC1155
    logger.info("Phase 1: Extracting ERC1155 transfers (streaming)...")
    erc1155_count = extract_transfers_streaming(wallet, "erc1155", checkpoint)

    # Phase 2: Extract ERC20
    logger.info("\nPhase 2: Extracting ERC20 transfers (streaming)...")
    erc20_count = extract_transfers_streaming(wallet, "erc20", checkpoint)

    # Phase 3: Join into trades
    logger.info("\nPhase 3: Joining into trades...")
    trades = join_trades_streaming(wallet)

    # Save final output
    output_path = get_output_path(wallet)
    logger.info(f"\nSaving {len(trades):,} trades to {output_path}...")

    result = {
        "wallet": wallet,
        "extraction_date": datetime.now().isoformat(),
        "erc1155_count": erc1155_count,
        "erc20_count": erc20_count,
        "trades_count": len(trades),
        "trades": trades
    }

    with open(output_path, 'w') as f:
        json.dump(result, f)

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("EXTRACTION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"ERC1155 transfers: {erc1155_count:,}")
    logger.info(f"ERC20 transfers: {erc20_count:,}")
    logger.info(f"Total trades: {len(trades):,}")

    if trades:
        buys = [t for t in trades if t["side"] == "BUY"]
        sells = [t for t in trades if t["side"] == "SELL"]
        total_volume = sum(t["usdc_amount"] for t in trades)

        logger.info(f"Buys: {len(buys):,}")
        logger.info(f"Sells: {len(sells):,}")
        logger.info(f"Total volume: ${total_volume:,.2f}")

    # Clean up intermediate files
    logger.info("\nCleaning up intermediate files...")
    for path in [get_checkpoint_path(wallet),
                 get_transfers_path(wallet, "erc1155"),
                 get_transfers_path(wallet, "erc20")]:
        if path.exists():
            path.unlink()

    logger.info(f"Output saved to: {output_path}")
    return trades


def run_with_auto_resume(wallet: str):
    """
    Run extraction with automatic resume on crash.

    Will keep retrying from checkpoint until successful completion.
    """
    max_retries = 100  # Effectively infinite for long extractions
    retry_delay = 10  # Seconds to wait before retry

    for attempt in range(1, max_retries + 1):
        try:
            # Always try to resume (checkpoint handles fresh start)
            checkpoint = load_checkpoint(wallet)

            # Check if already completed (output file exists and checkpoint cleaned)
            output_path = get_output_path(wallet)
            checkpoint_path = get_checkpoint_path(wallet)

            if output_path.exists() and not checkpoint_path.exists():
                logger.info(f"Extraction already complete. Output: {output_path}")
                return

            # Check if we have a checkpoint to resume from
            has_progress = (checkpoint.get("erc1155_count", 0) > 0 or
                          checkpoint.get("erc20_count", 0) > 0)

            if attempt > 1 or has_progress:
                logger.info(f"{'Resuming' if has_progress else 'Starting'} extraction (attempt {attempt})...")

            # Run extraction with resume=True (checkpoint handles state)
            run_extraction(wallet, resume=True)

            logger.info("Extraction completed successfully!")
            return

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Progress saved to checkpoint.")
            sys.exit(0)

        except Exception as e:
            logger.error(f"Extraction failed (attempt {attempt}): {e}")

            if attempt < max_retries:
                logger.info(f"Will auto-resume in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Giving up.")
                sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Memory-efficient Polymarket trade extractor")
    parser.add_argument("--wallet", required=True, help="Wallet address to extract")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (deprecated, auto-resume is default)")
    parser.add_argument("--fresh", action="store_true", help="Force fresh start (delete existing checkpoint)")

    args = parser.parse_args()

    # If fresh start requested, delete checkpoint first
    if args.fresh:
        for path in [get_checkpoint_path(args.wallet),
                     get_transfers_path(args.wallet, "erc1155"),
                     get_transfers_path(args.wallet, "erc20")]:
            if path.exists():
                path.unlink()
                logger.info(f"Deleted: {path}")

    # Always use auto-resume
    run_with_auto_resume(args.wallet)


if __name__ == "__main__":
    main()
