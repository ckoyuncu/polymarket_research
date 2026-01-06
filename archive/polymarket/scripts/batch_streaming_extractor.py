#!/usr/bin/env python3
"""
Memory-Efficient Batch Wallet Extractor for Polymarket

Extracts trade history for multiple wallets with:
- Streaming writes to disk (memory-safe)
- Per-wallet checkpointing for resume
- Batch progress tracking

Usage:
    export ETHERSCAN_API_KEY="your-key"
    python batch_streaming_extractor.py --input data/top_50_for_extraction.json
    python batch_streaming_extractor.py --resume  # Resume from checkpoint
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
        logging.FileHandler('batch_streaming.log')
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
BATCH_PROGRESS_FILE = DATA_DIR / "batch_progress.json"


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
        "User-Agent": "PolymarketBatchExtractor/2.0"
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
# FILE PATHS
# =============================================================================

def get_wallet_checkpoint_path(wallet: str) -> Path:
    wallet_short = wallet[:10].lower()
    return DATA_DIR / f"checkpoint_{wallet_short}.json"


def get_transfers_path(wallet: str, transfer_type: str) -> Path:
    wallet_short = wallet[:10].lower()
    return DATA_DIR / f"transfers_{wallet_short}_{transfer_type}.jsonl"


def get_output_path(wallet: str, name: str) -> Path:
    wallet_short = wallet[:10].lower()
    name_clean = name[:20].replace(' ', '_').replace('/', '_')
    return DATA_DIR / f"trades_{wallet_short}_{name_clean}.json"


# =============================================================================
# CHECKPOINT MANAGEMENT
# =============================================================================

def load_wallet_checkpoint(wallet: str) -> dict:
    """Load checkpoint for a single wallet."""
    path = get_wallet_checkpoint_path(wallet)
    if path.exists():
        try:
            with open(path) as f:
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
    }


def save_wallet_checkpoint(checkpoint: dict):
    """Save wallet checkpoint to disk."""
    checkpoint["updated_at"] = datetime.now().isoformat()
    path = get_wallet_checkpoint_path(checkpoint["wallet"])
    with open(path, 'w') as f:
        json.dump(checkpoint, f, indent=2)


def load_batch_progress() -> dict:
    """Load batch progress."""
    if BATCH_PROGRESS_FILE.exists():
        try:
            with open(BATCH_PROGRESS_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"completed": [], "current_index": 0}


def save_batch_progress(progress: dict):
    """Save batch progress."""
    progress["updated_at"] = datetime.now().isoformat()
    with open(BATCH_PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


# =============================================================================
# STREAMING EXTRACTION
# =============================================================================

def extract_transfers_streaming(wallet: str, transfer_type: str, checkpoint: dict) -> int:
    """Extract transfers with streaming write to disk."""
    label = transfer_type.upper()
    start_block_key = f"{transfer_type}_start_block"
    count_key = f"{transfer_type}_count"
    complete_key = f"{transfer_type}_complete"

    if checkpoint.get(complete_key, False):
        logger.info(f"  {label}: Already complete ({checkpoint.get(count_key, 0):,})")
        return checkpoint.get(count_key, 0)

    output_path = get_transfers_path(wallet, transfer_type)
    start_block = checkpoint.get(start_block_key, 0)
    total_count = checkpoint.get(count_key, 0)

    mode = 'a' if start_block > 0 else 'w'

    iteration = 0
    max_iterations = 2000

    with open(output_path, mode) as f:
        while iteration < max_iterations:
            iteration += 1
            page = 1
            chunk_count = 0
            chunk_last_block = start_block

            while page <= 10:
                transfers = get_transfers(wallet, transfer_type, start_block, page)

                if not transfers:
                    break

                for tx in transfers:
                    f.write(json.dumps(tx) + "\n")
                    chunk_last_block = max(chunk_last_block, int(tx.get("blockNumber", 0)))

                chunk_count += len(transfers)
                total_count += len(transfers)

                if len(transfers) < MAX_RECORDS_PER_PAGE:
                    break

                page += 1
                time.sleep(RATE_LIMIT_DELAY)

            f.flush()

            if chunk_count == 0:
                checkpoint[complete_key] = True
                checkpoint[count_key] = total_count
                save_wallet_checkpoint(checkpoint)
                break

            if chunk_count >= 10000:
                start_block = chunk_last_block + 1
                checkpoint[start_block_key] = start_block
                checkpoint[count_key] = total_count
                save_wallet_checkpoint(checkpoint)
                logger.info(f"  {label}: {total_count:,} transfers (block {start_block:,})")
            else:
                checkpoint[complete_key] = True
                checkpoint[count_key] = total_count
                save_wallet_checkpoint(checkpoint)
                break

    logger.info(f"  {label}: Complete! {total_count:,} transfers")
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


def join_trades(wallet: str) -> list:
    """Join ERC1155 and ERC20 transfers into trades."""
    erc1155_path = get_transfers_path(wallet, "erc1155")
    erc20_path = get_transfers_path(wallet, "erc20")

    # Load ERC20 into memory for lookup
    erc20_transfers = load_transfers_from_file(erc20_path)
    erc20_by_tx = {}
    for tx in erc20_transfers:
        tx_hash = tx.get("hash", "").lower()
        if tx_hash not in erc20_by_tx:
            erc20_by_tx[tx_hash] = []
        erc20_by_tx[tx_hash].append(tx)
    del erc20_transfers

    trades = []
    wallet_lower = wallet.lower()

    with open(erc1155_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            erc1155 = json.loads(line)
            tx_hash = erc1155.get("hash", "").lower()
            from_addr = erc1155.get("from", "").lower()
            to_addr = erc1155.get("to", "").lower()

            if to_addr == wallet_lower:
                side = "BUY"
            elif from_addr == wallet_lower:
                side = "SELL"
            else:
                continue

            try:
                token_amount = float(erc1155.get("tokenValue", 0)) / 1e6
            except:
                token_amount = 0

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

            price = usdc_amount / token_amount if token_amount > 0 else 0

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

    trades.sort(key=lambda x: x["timestamp"])
    return trades


# =============================================================================
# EXTRACT SINGLE WALLET
# =============================================================================

def extract_wallet(wallet: str, name: str) -> dict:
    """Extract all trades for a single wallet using streaming."""
    logger.info(f"Extracting {name} ({wallet[:10]}...)")
    start_time = time.time()

    checkpoint = load_wallet_checkpoint(wallet)

    # Phase 1: ERC1155
    erc1155_count = extract_transfers_streaming(wallet, "erc1155", checkpoint)

    # Phase 2: ERC20
    erc20_count = extract_transfers_streaming(wallet, "erc20", checkpoint)

    # Phase 3: Join
    logger.info("  Joining trades...")
    trades = join_trades(wallet)

    elapsed = time.time() - start_time

    # Calculate stats
    buys = [t for t in trades if t["side"] == "BUY"]
    sells = [t for t in trades if t["side"] == "SELL"]
    total_volume = sum(t["usdc_amount"] for t in trades)

    result = {
        "wallet": wallet,
        "name": name,
        "extraction_date": datetime.now().isoformat(),
        "extraction_time_sec": elapsed,
        "erc1155_count": erc1155_count,
        "erc20_count": erc20_count,
        "trades_count": len(trades),
        "buys": len(buys),
        "sells": len(sells),
        "total_volume": total_volume,
        "trades": trades
    }

    # Save output
    output_path = get_output_path(wallet, name)
    with open(output_path, 'w') as f:
        json.dump(result, f)

    logger.info(f"  Complete: {len(trades):,} trades, ${total_volume:,.0f} volume, {elapsed:.1f}s")
    logger.info(f"  Saved to: {output_path.name}")

    # Clean up intermediate files
    for path in [get_wallet_checkpoint_path(wallet),
                 get_transfers_path(wallet, "erc1155"),
                 get_transfers_path(wallet, "erc20")]:
        if path.exists():
            path.unlink()

    return {
        "wallet": wallet,
        "name": name,
        "trades": len(trades),
        "volume": total_volume
    }


# =============================================================================
# BATCH EXTRACTION
# =============================================================================

def run_batch_extraction(wallets: list, resume: bool = False):
    """Run batch extraction for multiple wallets."""
    if not API_KEY:
        logger.error("ETHERSCAN_API_KEY not set!")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)

    # Load progress
    progress = load_batch_progress() if resume else {"completed": [], "current_index": 0}
    start_idx = progress.get("current_index", 0)

    logger.info("=" * 60)
    logger.info("BATCH STREAMING EXTRACTOR (Memory-Efficient)")
    logger.info("=" * 60)
    logger.info(f"Total wallets: {len(wallets)}")
    logger.info(f"Starting from: {start_idx + 1}")
    logger.info("")

    total_start = time.time()
    completed = progress.get("completed", [])

    for idx in range(start_idx, len(wallets)):
        wallet_info = wallets[idx]
        wallet = wallet_info.get("wallet", "")
        name = wallet_info.get("name", wallet[:15])

        logger.info(f"\n[{idx + 1}/{len(wallets)}] {name}")

        try:
            result = extract_wallet(wallet, name)
            completed.append(result)
        except Exception as e:
            logger.error(f"  ERROR: {e}")
            completed.append({
                "wallet": wallet,
                "name": name,
                "error": str(e)
            })

        # Save progress after each wallet
        progress["completed"] = completed
        progress["current_index"] = idx + 1
        save_batch_progress(progress)

        # Small delay between wallets
        if idx < len(wallets) - 1:
            time.sleep(1)

    total_elapsed = time.time() - total_start

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("BATCH EXTRACTION COMPLETE")
    logger.info("=" * 60)

    successful = [w for w in completed if "error" not in w]
    logger.info(f"Wallets processed: {len(successful)}/{len(wallets)}")
    logger.info(f"Total time: {total_elapsed/3600:.2f} hours")

    total_trades = sum(w.get("trades", 0) for w in successful)
    total_volume = sum(w.get("volume", 0) for w in successful)
    logger.info(f"Total trades: {total_trades:,}")
    logger.info(f"Total volume: ${total_volume:,.0f}")

    # Save final summary
    summary = {
        "completed": completed,
        "total_wallets": len(wallets),
        "successful": len(successful),
        "total_trades": total_trades,
        "total_volume": total_volume,
        "total_time_hours": total_elapsed / 3600,
        "finished_at": datetime.now().isoformat()
    }

    with open(DATA_DIR / "batch_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)


def run_batch_with_auto_resume(wallets: list):
    """
    Run batch extraction with automatic resume on crash.

    Will keep retrying from checkpoint until successful completion.
    """
    max_retries = 100  # Effectively infinite for long extractions
    retry_delay = 10  # Seconds to wait before retry

    for attempt in range(1, max_retries + 1):
        try:
            # Check if already completed
            progress = load_batch_progress()
            current_idx = progress.get("current_index", 0)

            if current_idx >= len(wallets):
                logger.info(f"Batch extraction already complete ({len(wallets)} wallets)")
                return

            if attempt > 1 or current_idx > 0:
                logger.info(f"{'Resuming' if current_idx > 0 else 'Starting'} batch extraction (attempt {attempt}, wallet {current_idx + 1}/{len(wallets)})...")

            # Always resume from checkpoint
            run_batch_extraction(wallets, resume=True)

            logger.info("Batch extraction completed successfully!")
            return

        except KeyboardInterrupt:
            logger.info("Interrupted by user. Progress saved to checkpoint.")
            sys.exit(0)

        except Exception as e:
            logger.error(f"Batch extraction failed (attempt {attempt}): {e}")

            if attempt < max_retries:
                logger.info(f"Will auto-resume in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Max retries reached. Giving up.")
                sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Batch extract Polymarket trades (streaming)")
    parser.add_argument("--input", help="JSON file with wallet list", default="data/top_50_for_extraction.json")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (deprecated, auto-resume is default)")
    parser.add_argument("--fresh", action="store_true", help="Force fresh start (delete existing batch progress)")

    args = parser.parse_args()

    # Load wallets
    input_path = Path(args.input)
    if not input_path.exists():
        input_path = Path(__file__).parent.parent / args.input

    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    with open(input_path) as f:
        wallets = json.load(f)

    logger.info(f"Loaded {len(wallets)} wallets from {input_path}")

    # If fresh start requested, delete batch progress
    if args.fresh:
        if BATCH_PROGRESS_FILE.exists():
            BATCH_PROGRESS_FILE.unlink()
            logger.info(f"Deleted: {BATCH_PROGRESS_FILE}")

    # Always use auto-resume
    run_batch_with_auto_resume(wallets)


if __name__ == "__main__":
    main()
