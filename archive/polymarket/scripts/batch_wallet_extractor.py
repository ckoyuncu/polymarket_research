#!/usr/bin/env python3
"""
Batch Wallet Extractor for Polymarket

Extracts trade history for multiple wallets sequentially.
Designed for long-running EC2 deployment.

Features:
- Sequential extraction to respect API limits
- Progress tracking and resume capability
- Auto-saves after each wallet
- Detailed logging

Usage:
    export ETHERSCAN_API_KEY="your-key"
    python batch_wallet_extractor.py --input wallets.json
    python batch_wallet_extractor.py --resume  # Resume interrupted extraction
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
        logging.FileHandler('batch_extraction.log')
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
PROGRESS_FILE = DATA_DIR / "batch_extraction_progress.json"


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
        "User-Agent": "PolymarketBatchExtractor/1.0"
    })

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        logger.error(f"API error: {e}")
        return {"status": "0", "message": str(e), "result": []}


def get_transfers(wallet: str, transfer_type: str, start_block: int = 0, page: int = 1) -> list:
    """Get ERC1155 or ERC20 transfers."""
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


def extract_all_transfers(wallet: str, transfer_type: str) -> list:
    """Extract all transfers using block-range pagination."""
    all_transfers = []
    start_block = 0
    label = "ERC1155" if transfer_type == "erc1155" else "ERC20"

    iteration = 0
    max_iterations = 1000

    while iteration < max_iterations:
        iteration += 1
        page = 1
        chunk_transfers = []

        while page <= 10:
            transfers = get_transfers(wallet, transfer_type, start_block, page)

            if not transfers:
                break

            chunk_transfers.extend(transfers)

            if len(transfers) < MAX_RECORDS_PER_PAGE:
                break

            page += 1
            time.sleep(RATE_LIMIT_DELAY)

        if not chunk_transfers:
            break

        all_transfers.extend(chunk_transfers)

        if len(chunk_transfers) >= 10000:
            last_block = max(int(t.get("blockNumber", 0)) for t in chunk_transfers)
            start_block = last_block + 1
            logger.info(f"  {label}: {len(all_transfers):,} transfers (continuing from block {start_block})")
        else:
            break

    return all_transfers


def join_trades(erc1155_transfers: list, erc20_transfers: list, wallet: str) -> list:
    """Join ERC1155 and ERC20 transfers into trades."""
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


def extract_wallet(wallet: str, name: str) -> dict:
    """Extract all trades for a single wallet."""
    logger.info(f"Extracting {name} ({wallet[:10]}...)")
    start_time = time.time()

    # Extract transfers
    logger.info("  Phase 1: ERC1155 transfers...")
    erc1155 = extract_all_transfers(wallet, "erc1155")
    logger.info(f"  Got {len(erc1155):,} ERC1155 transfers")

    logger.info("  Phase 2: ERC20 transfers...")
    erc20 = extract_all_transfers(wallet, "erc20")
    logger.info(f"  Got {len(erc20):,} ERC20 transfers")

    # Join trades
    logger.info("  Phase 3: Joining trades...")
    trades = join_trades(erc1155, erc20, wallet)

    elapsed = time.time() - start_time

    # Calculate stats
    buys = [t for t in trades if t["side"] == "BUY"]
    sells = [t for t in trades if t["side"] == "SELL"]
    total_volume = sum(t["usdc_amount"] for t in trades)

    result = {
        "wallet": wallet,
        "name": name,
        "trades_count": len(trades),
        "buys": len(buys),
        "sells": len(sells),
        "total_volume": total_volume,
        "extraction_time_sec": elapsed,
        "trades": trades
    }

    logger.info(f"  Completed: {len(trades):,} trades, ${total_volume:,.0f} volume, {elapsed:.1f}s")

    return result


def save_progress(completed: list, current_idx: int, total: int):
    """Save extraction progress."""
    progress = {
        "completed_wallets": completed,
        "current_index": current_idx,
        "total_wallets": total,
        "last_updated": datetime.now().isoformat()
    }
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def load_progress() -> dict:
    """Load extraction progress."""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"completed_wallets": [], "current_index": 0}


def run_batch_extraction(wallets: list, resume: bool = False):
    """Run batch extraction for multiple wallets."""
    if not API_KEY:
        logger.error("ETHERSCAN_API_KEY not set!")
        sys.exit(1)

    DATA_DIR.mkdir(exist_ok=True)

    # Check for resume
    start_idx = 0
    completed = []

    if resume:
        progress = load_progress()
        start_idx = progress.get("current_index", 0)
        completed = progress.get("completed_wallets", [])
        if start_idx > 0:
            logger.info(f"Resuming from wallet {start_idx + 1} of {len(wallets)}")

    logger.info("="*60)
    logger.info("BATCH WALLET EXTRACTOR")
    logger.info("="*60)
    logger.info(f"Total wallets: {len(wallets)}")
    logger.info(f"Starting from: {start_idx + 1}")
    logger.info(f"Output dir: {DATA_DIR}")
    logger.info("")

    total_start = time.time()

    for idx in range(start_idx, len(wallets)):
        wallet_info = wallets[idx]
        wallet = wallet_info.get("wallet", "")
        name = wallet_info.get("name", wallet[:15])

        logger.info(f"\n[{idx + 1}/{len(wallets)}] Processing {name}")

        try:
            result = extract_wallet(wallet, name)

            # Save individual wallet data
            wallet_short = wallet[:10].lower()
            output_file = DATA_DIR / f"trades_{wallet_short}_{name[:20].replace(' ', '_')}.json"

            with open(output_file, 'w') as f:
                json.dump(result, f)

            logger.info(f"  Saved to {output_file.name}")

            completed.append({
                "wallet": wallet,
                "name": name,
                "trades": result["trades_count"],
                "volume": result["total_volume"]
            })

        except Exception as e:
            logger.error(f"  ERROR: {e}")
            # Continue to next wallet

        # Save progress
        save_progress(completed, idx + 1, len(wallets))

        # Small delay between wallets
        if idx < len(wallets) - 1:
            time.sleep(1)

    total_elapsed = time.time() - total_start

    # Summary
    logger.info("\n" + "="*60)
    logger.info("BATCH EXTRACTION COMPLETE")
    logger.info("="*60)
    logger.info(f"Wallets processed: {len(completed)}")
    logger.info(f"Total time: {total_elapsed/3600:.2f} hours")

    total_trades = sum(w.get("trades", 0) for w in completed)
    total_volume = sum(w.get("volume", 0) for w in completed)
    logger.info(f"Total trades: {total_trades:,}")
    logger.info(f"Total volume: ${total_volume:,.0f}")

    # Save summary
    summary = {
        "completed": completed,
        "total_trades": total_trades,
        "total_volume": total_volume,
        "total_time_hours": total_elapsed / 3600,
        "finished_at": datetime.now().isoformat()
    }

    with open(DATA_DIR / "batch_extraction_summary.json", 'w') as f:
        json.dump(summary, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Batch extract Polymarket trades")
    parser.add_argument("--input", help="JSON file with wallet list", default="data/top_50_for_extraction.json")
    parser.add_argument("--resume", action="store_true", help="Resume interrupted extraction")

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

    run_batch_extraction(wallets, resume=args.resume)


if __name__ == "__main__":
    main()
