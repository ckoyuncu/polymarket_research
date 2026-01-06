#!/usr/bin/env python3
"""
Join ERC1155 and ERC20 Transfers into Trades

Reads streaming JSONL files from EC2 extraction and joins them by tx_hash
to create complete trade records with prices.

Input:
- ERC1155 transfers: token transfers (position tokens)
- ERC20 transfers: USDC payments

Output:
- Joined trades with: timestamp, tx_hash, wallet, side, token_id,
  token_amount, usdc_amount, price

Usage:
    python join_transfers_to_trades.py
    python join_transfers_to_trades.py --erc1155 data/ec2_transfers/transfers_0x7f69983e_erc1155.jsonl
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def load_jsonl_streaming(filepath: Path, progress_every: int = 100000) -> List[dict]:
    """Load JSONL file with progress reporting."""
    records = []
    with open(filepath) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if line:
                records.append(json.loads(line))
            if i % progress_every == 0:
                print(f"  Loaded {i:,} records...")
    return records


def build_erc20_index(erc20_transfers: List[dict]) -> Dict[str, List[dict]]:
    """Build index of ERC20 transfers by tx_hash for fast lookup."""
    index = {}
    for tx in erc20_transfers:
        tx_hash = tx.get("hash", "").lower()
        if tx_hash:
            if tx_hash not in index:
                index[tx_hash] = []
            index[tx_hash].append(tx)
    return index


def find_usdc_amount(erc20_list: List[dict]) -> float:
    """Find USDC amount from list of ERC20 transfers in a transaction."""
    for erc20 in erc20_list:
        symbol = erc20.get("tokenSymbol", "").upper()
        if "USDC" in symbol:
            try:
                decimals = int(erc20.get("tokenDecimal", 6))
                return float(erc20.get("value", 0)) / (10 ** decimals)
            except (ValueError, TypeError):
                pass
    return 0.0


def join_transfers(
    erc1155_transfers: List[dict],
    erc20_index: Dict[str, List[dict]],
    wallet: str
) -> List[dict]:
    """
    Join ERC1155 transfers with ERC20 transfers to create trades.

    Logic:
    - ERC1155 shows token (position) movement
    - ERC20 shows USDC payment
    - Join on tx_hash
    - side = BUY if wallet receives tokens, SELL if wallet sends tokens
    - price = usdc_amount / token_amount
    """
    trades = []
    wallet_lower = wallet.lower()
    matched = 0
    unmatched = 0

    for i, erc1155 in enumerate(erc1155_transfers, 1):
        tx_hash = erc1155.get("hash", "").lower()
        from_addr = erc1155.get("from", "").lower()
        to_addr = erc1155.get("to", "").lower()

        # Determine side
        if to_addr == wallet_lower:
            side = "BUY"
        elif from_addr == wallet_lower:
            side = "SELL"
        else:
            # Not our wallet's trade
            continue

        # Get token amount (ERC1155 uses tokenValue with 6 decimals for Polymarket)
        try:
            token_amount = float(erc1155.get("tokenValue", 0)) / 1e6
        except (ValueError, TypeError):
            token_amount = 0.0

        # Find matching USDC transfer
        usdc_amount = 0.0
        if tx_hash in erc20_index:
            usdc_amount = find_usdc_amount(erc20_index[tx_hash])
            matched += 1
        else:
            unmatched += 1

        # Calculate price
        price = usdc_amount / token_amount if token_amount > 0 else 0.0

        # Parse timestamp
        try:
            timestamp = int(erc1155.get("timeStamp", 0))
            dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            datetime_utc = dt.isoformat()
        except (ValueError, TypeError, OSError):
            timestamp = 0
            datetime_utc = ""

        trade = {
            "tx_hash": tx_hash,
            "block_number": int(erc1155.get("blockNumber", 0)),
            "timestamp": timestamp,
            "datetime_utc": datetime_utc,
            "wallet": wallet,
            "side": side,
            "token_id": erc1155.get("tokenID", ""),
            "token_amount": token_amount,
            "usdc_amount": usdc_amount,
            "price": round(price, 6),
        }
        trades.append(trade)

        if i % 100000 == 0:
            print(f"  Processed {i:,} ERC1155 transfers -> {len(trades):,} trades")

    print(f"  Matched with USDC: {matched:,}, Unmatched: {unmatched:,}")
    return trades


def main():
    parser = argparse.ArgumentParser(description="Join ERC1155 and ERC20 transfers into trades")
    parser.add_argument(
        "--erc1155",
        type=str,
        default="data/ec2_transfers/transfers_0x7f69983e_erc1155.jsonl",
        help="Path to ERC1155 transfers JSONL file"
    )
    parser.add_argument(
        "--erc20",
        type=str,
        default="data/ec2_transfers/transfers_0x7f69983e_erc20.jsonl",
        help="Path to ERC20 transfers JSONL file"
    )
    parser.add_argument(
        "--wallet",
        type=str,
        default="0x7f69983eb28245bba0d5083502a78744a8f66162",
        help="Wallet address to filter trades for"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="data/account88888_trades_joined.json",
        help="Output file for joined trades"
    )

    args = parser.parse_args()

    # Resolve paths relative to project root
    project_root = Path(__file__).parent.parent.parent
    erc1155_file = project_root / args.erc1155
    erc20_file = project_root / args.erc20
    output_file = project_root / args.output

    print("=" * 60)
    print("Join ERC1155 + ERC20 Transfers into Trades")
    print("=" * 60)
    print(f"ERC1155 file: {erc1155_file}")
    print(f"ERC20 file: {erc20_file}")
    print(f"Wallet: {args.wallet}")
    print(f"Output: {output_file}")
    print()

    # Check files exist
    if not erc1155_file.exists():
        print(f"ERROR: ERC1155 file not found: {erc1155_file}")
        sys.exit(1)
    if not erc20_file.exists():
        print(f"ERROR: ERC20 file not found: {erc20_file}")
        sys.exit(1)

    # Load ERC20 transfers first (smaller, need for indexing)
    print("Loading ERC20 transfers...")
    erc20_transfers = load_jsonl_streaming(erc20_file, progress_every=100000)
    print(f"Loaded {len(erc20_transfers):,} ERC20 transfers")
    print()

    # Build ERC20 index
    print("Building ERC20 index by tx_hash...")
    erc20_index = build_erc20_index(erc20_transfers)
    print(f"Indexed {len(erc20_index):,} unique transaction hashes")
    print()

    # Free memory from raw list
    del erc20_transfers

    # Load ERC1155 transfers
    print("Loading ERC1155 transfers...")
    erc1155_transfers = load_jsonl_streaming(erc1155_file, progress_every=500000)
    print(f"Loaded {len(erc1155_transfers):,} ERC1155 transfers")
    print()

    # Join into trades
    print("Joining transfers into trades...")
    trades = join_transfers(erc1155_transfers, erc20_index, args.wallet)
    print(f"Created {len(trades):,} trades")
    print()

    # Free memory
    del erc1155_transfers
    del erc20_index

    # Sort by timestamp
    print("Sorting trades by timestamp...")
    trades.sort(key=lambda x: x["timestamp"])

    # Calculate statistics
    buys = [t for t in trades if t["side"] == "BUY"]
    sells = [t for t in trades if t["side"] == "SELL"]
    total_volume = sum(t["usdc_amount"] for t in trades)

    # Time range
    if trades:
        min_ts = min(t["timestamp"] for t in trades if t["timestamp"] > 0)
        max_ts = max(t["timestamp"] for t in trades if t["timestamp"] > 0)
        min_dt = datetime.fromtimestamp(min_ts, tz=timezone.utc)
        max_dt = datetime.fromtimestamp(max_ts, tz=timezone.utc)
        days_span = (max_ts - min_ts) / 86400
    else:
        min_dt = max_dt = None
        days_span = 0

    # Unique tokens
    unique_tokens = set(t["token_id"] for t in trades)

    print("=" * 60)
    print("TRADE STATISTICS")
    print("=" * 60)
    print(f"Total trades: {len(trades):,}")
    print(f"  BUYs: {len(buys):,}")
    print(f"  SELLs: {len(sells):,}")
    print(f"Total volume: ${total_volume:,.2f}")
    print(f"Unique tokens: {len(unique_tokens):,}")
    if min_dt and max_dt:
        print(f"Time range: {min_dt.strftime('%Y-%m-%d %H:%M')} to {max_dt.strftime('%Y-%m-%d %H:%M')} UTC")
        print(f"Days span: {days_span:.1f} days")
    print()

    # Save output
    output_file.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "wallet": args.wallet,
            "erc1155_file": str(erc1155_file),
            "erc20_file": str(erc20_file),
            "total_trades": len(trades),
            "buy_count": len(buys),
            "sell_count": len(sells),
            "total_volume_usdc": total_volume,
            "unique_token_ids": len(unique_tokens),
            "time_range_start": min_dt.isoformat() if min_dt else None,
            "time_range_end": max_dt.isoformat() if max_dt else None,
            "days_span": days_span,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "note": "ERC20 data may be partial (Dec 5-20 only), will re-run with complete data"
        },
        "trades": trades
    }

    print(f"Saving to {output_file}...")
    with open(output_file, 'w') as f:
        json.dump(output_data, f, indent=2)

    print(f"Saved {len(trades):,} trades to {output_file}")

    # Show sample trades
    print()
    print("=" * 60)
    print("SAMPLE TRADES (first 5)")
    print("=" * 60)
    for i, trade in enumerate(trades[:5], 1):
        print(f"[{i}] {trade['datetime_utc'][:19]} | {trade['side']:4} | "
              f"${trade['usdc_amount']:.2f} @ {trade['price']:.4f}")
        print(f"    token_id: {trade['token_id'][:40]}...")


if __name__ == "__main__":
    main()
