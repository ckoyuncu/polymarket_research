#!/usr/bin/env python3
"""
Block Position Analyzer

Analyzes Account88888's transaction position within blocks to detect:
1. MEV/priority ordering patterns
2. Gas price strategies (rush vs normal)
3. Transaction index patterns (early vs late in block)
4. Correlation between block position and trade success

This helps understand if they use MEV or priority gas to get better execution.

Usage:
    python scripts/reverse_engineer/block_position_analyzer.py

Note: Requires fetching transaction receipts which may take time.
"""

import json
import time
import requests
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import statistics
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class TxAnalysis:
    """Analysis of a single transaction."""
    tx_hash: str
    block_number: int
    tx_index: int  # Position in block (0 = first)
    block_tx_count: int  # Total txs in block
    gas_price_gwei: float
    gas_used: int
    timestamp: int
    trade_side: str
    usdc_amount: float
    token_id: str
    slug: str

    # Derived
    position_percentile: float  # 0-100, where in block

    def to_dict(self):
        return asdict(self)


class BlockPositionAnalyzer:
    """Analyzes transaction positions within blocks."""

    # Polygon RPC endpoints (free tier)
    RPC_ENDPOINTS = [
        "https://polygon-rpc.com",
        "https://rpc-mainnet.matic.network",
        "https://polygon-mainnet.public.blastapi.io",
    ]

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or PROJECT_ROOT / "data" / "analysis"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.rpc_index = 0
        self.tx_analyses: List[TxAnalysis] = []
        self.block_cache: Dict[int, dict] = {}

    def get_rpc(self) -> str:
        """Get current RPC endpoint with rotation."""
        return self.RPC_ENDPOINTS[self.rpc_index % len(self.RPC_ENDPOINTS)]

    def rotate_rpc(self):
        """Switch to next RPC endpoint."""
        self.rpc_index += 1
        print(f"Rotating to RPC: {self.get_rpc()}")

    def eth_call(self, method: str, params: list) -> Optional[dict]:
        """Make an RPC call with retry logic."""
        for attempt in range(3):
            try:
                response = requests.post(
                    self.get_rpc(),
                    json={
                        "jsonrpc": "2.0",
                        "method": method,
                        "params": params,
                        "id": 1
                    },
                    timeout=10
                )
                if response.ok:
                    data = response.json()
                    if "result" in data:
                        return data["result"]
                    elif "error" in data:
                        print(f"RPC error: {data['error']}")
            except Exception as e:
                print(f"RPC call failed: {e}")

            self.rotate_rpc()
            time.sleep(0.5)

        return None

    def get_tx_receipt(self, tx_hash: str) -> Optional[dict]:
        """Get transaction receipt."""
        return self.eth_call("eth_getTransactionReceipt", [tx_hash])

    def get_block(self, block_number: int) -> Optional[dict]:
        """Get block data (cached)."""
        if block_number in self.block_cache:
            return self.block_cache[block_number]

        block_hex = hex(block_number)
        result = self.eth_call("eth_getBlockByNumber", [block_hex, False])

        if result:
            self.block_cache[block_number] = result

        return result

    def analyze_transaction(self, trade: dict) -> Optional[TxAnalysis]:
        """Analyze a single transaction's block position."""
        tx_hash = trade.get("tx_hash")
        if not tx_hash:
            return None

        # Get receipt
        receipt = self.get_tx_receipt(tx_hash)
        if not receipt:
            return None

        block_number = int(receipt.get("blockNumber", "0x0"), 16)
        tx_index = int(receipt.get("transactionIndex", "0x0"), 16)
        gas_used = int(receipt.get("gasUsed", "0x0"), 16)

        # Get block for context
        block = self.get_block(block_number)
        if not block:
            return None

        block_tx_count = len(block.get("transactions", []))
        block_timestamp = int(block.get("timestamp", "0x0"), 16)

        # Get gas price from transaction
        # Note: Receipt doesn't have gas price, would need eth_getTransactionByHash
        # For now, estimate from effectiveGasPrice if available
        effective_gas_price = receipt.get("effectiveGasPrice", "0x0")
        gas_price_wei = int(effective_gas_price, 16) if effective_gas_price else 0
        gas_price_gwei = gas_price_wei / 1e9

        # Calculate position percentile
        position_percentile = (tx_index / block_tx_count * 100) if block_tx_count > 0 else 50

        return TxAnalysis(
            tx_hash=tx_hash,
            block_number=block_number,
            tx_index=tx_index,
            block_tx_count=block_tx_count,
            gas_price_gwei=gas_price_gwei,
            gas_used=gas_used,
            timestamp=block_timestamp,
            trade_side=trade.get("side", ""),
            usdc_amount=trade.get("usdc_amount", 0),
            token_id=trade.get("token_id", ""),
            slug=trade.get("slug", ""),
            position_percentile=position_percentile,
        )

    def load_trades(self, trades_file: str, sample_size: int = 1000) -> List[dict]:
        """Load trades from file."""
        print(f"Loading trades from {trades_file}...")

        with open(trades_file) as f:
            data = json.load(f)

        if isinstance(data, dict) and "trades" in data:
            trades = data["trades"]
        else:
            trades = data

        print(f"  Total trades: {len(trades):,}")

        # Sample trades with tx_hash
        trades_with_hash = [t for t in trades if t.get("tx_hash")]
        print(f"  Trades with tx_hash: {len(trades_with_hash):,}")

        # Random sample
        import random
        random.seed(42)
        if len(trades_with_hash) > sample_size:
            trades_with_hash = random.sample(trades_with_hash, sample_size)

        print(f"  Sampled: {len(trades_with_hash):,} trades")
        return trades_with_hash

    def analyze_trades(self, trades: List[dict]):
        """Analyze all trades."""
        print(f"\nAnalyzing {len(trades)} transactions...")
        print("This requires RPC calls and may take several minutes...")

        for i, trade in enumerate(trades):
            if i % 50 == 0:
                print(f"  Progress: {i}/{len(trades)} ({100*i/len(trades):.1f}%)")

            analysis = self.analyze_transaction(trade)
            if analysis:
                self.tx_analyses.append(analysis)

            # Rate limiting
            time.sleep(0.1)

        print(f"  Analyzed: {len(self.tx_analyses)} transactions")

    def compute_statistics(self) -> Dict:
        """Compute statistics on block positions."""
        if not self.tx_analyses:
            return {}

        positions = [a.position_percentile for a in self.tx_analyses]
        gas_prices = [a.gas_price_gwei for a in self.tx_analyses if a.gas_price_gwei > 0]
        tx_indices = [a.tx_index for a in self.tx_analyses]

        stats = {
            "total_analyzed": len(self.tx_analyses),

            # Position statistics
            "avg_position_percentile": statistics.mean(positions),
            "median_position_percentile": statistics.median(positions),
            "stdev_position_percentile": statistics.stdev(positions) if len(positions) > 1 else 0,

            # Position distribution
            "pct_in_first_10": sum(1 for p in positions if p < 10) / len(positions) * 100,
            "pct_in_first_25": sum(1 for p in positions if p < 25) / len(positions) * 100,
            "pct_in_last_25": sum(1 for p in positions if p > 75) / len(positions) * 100,
            "pct_in_last_10": sum(1 for p in positions if p > 90) / len(positions) * 100,

            # Gas price statistics
            "avg_gas_gwei": statistics.mean(gas_prices) if gas_prices else 0,
            "median_gas_gwei": statistics.median(gas_prices) if gas_prices else 0,
            "max_gas_gwei": max(gas_prices) if gas_prices else 0,
            "min_gas_gwei": min(gas_prices) if gas_prices else 0,

            # Transaction index
            "avg_tx_index": statistics.mean(tx_indices),
            "median_tx_index": statistics.median(tx_indices),
        }

        # Check for MEV patterns
        # MEV bots typically appear in first few positions
        first_position_count = sum(1 for a in self.tx_analyses if a.tx_index <= 2)
        stats["first_3_positions_pct"] = first_position_count / len(self.tx_analyses) * 100

        # High gas trades (potential priority)
        if gas_prices:
            high_gas_threshold = statistics.median(gas_prices) * 2
            high_gas_count = sum(1 for g in gas_prices if g > high_gas_threshold)
            stats["high_gas_trades_pct"] = high_gas_count / len(gas_prices) * 100

        return stats

    def print_analysis(self, stats: Dict):
        """Print analysis results."""
        print("\n" + "=" * 70)
        print("BLOCK POSITION ANALYSIS")
        print("=" * 70)

        print(f"\nTransactions analyzed: {stats.get('total_analyzed', 0):,}")

        print("\n--- Position in Block ---")
        print(f"Average position: {stats.get('avg_position_percentile', 0):.1f}th percentile")
        print(f"Median position: {stats.get('median_position_percentile', 0):.1f}th percentile")
        print(f"Std dev: {stats.get('stdev_position_percentile', 0):.1f}")

        print("\n--- Position Distribution ---")
        print(f"First 10% of block: {stats.get('pct_in_first_10', 0):.1f}%")
        print(f"First 25% of block: {stats.get('pct_in_first_25', 0):.1f}%")
        print(f"Last 25% of block: {stats.get('pct_in_last_25', 0):.1f}%")
        print(f"Last 10% of block: {stats.get('pct_in_last_10', 0):.1f}%")

        print("\n--- Gas Price ---")
        print(f"Average: {stats.get('avg_gas_gwei', 0):.2f} gwei")
        print(f"Median: {stats.get('median_gas_gwei', 0):.2f} gwei")
        print(f"Range: {stats.get('min_gas_gwei', 0):.2f} - {stats.get('max_gas_gwei', 0):.2f} gwei")

        print("\n--- MEV Indicators ---")
        print(f"Trades in first 3 positions: {stats.get('first_3_positions_pct', 0):.1f}%")
        print(f"High gas trades (>2x median): {stats.get('high_gas_trades_pct', 0):.1f}%")

        # Interpretation
        print("\n--- Interpretation ---")

        if stats.get('first_3_positions_pct', 0) > 10:
            print("! HIGH first-position rate - possible MEV/flashbots usage")
        else:
            print("Normal first-position rate - likely not using MEV")

        if stats.get('high_gas_trades_pct', 0) > 20:
            print("! HIGH gas trades common - using priority gas for execution")
        else:
            print("Normal gas usage - not paying premium for priority")

        avg_pos = stats.get('avg_position_percentile', 50)
        if avg_pos < 30:
            print("! Trades clustered early in blocks - possible priority execution")
        elif avg_pos > 70:
            print("Trades clustered late in blocks - normal execution")
        else:
            print("Random distribution in blocks - no special ordering")

        print("\n" + "=" * 70)

    def save_results(self, stats: Dict):
        """Save analysis results."""
        timestamp = int(time.time())

        # Save stats
        stats_file = self.output_dir / f"block_position_stats_{timestamp}.json"
        with open(stats_file, 'w') as f:
            json.dump(stats, f, indent=2)
        print(f"\nSaved stats to: {stats_file}")

        # Save detailed analyses
        details_file = self.output_dir / f"block_position_details_{timestamp}.json"
        with open(details_file, 'w') as f:
            json.dump([a.to_dict() for a in self.tx_analyses], f, indent=2)
        print(f"Saved details to: {details_file}")

    def run(self, trades_file: str, sample_size: int = 500):
        """Run the full analysis."""
        print("=" * 70)
        print("BLOCK POSITION ANALYZER")
        print("=" * 70)
        print()
        print("Analyzing transaction positions within blocks to detect:")
        print("  - MEV/priority ordering patterns")
        print("  - Gas price strategies")
        print("  - Transaction index patterns")
        print()

        # Load trades
        trades = self.load_trades(trades_file, sample_size)

        # Analyze
        self.analyze_trades(trades)

        # Compute stats
        stats = self.compute_statistics()

        # Print and save
        self.print_analysis(stats)
        self.save_results(stats)

        return stats


def main():
    """Run block position analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Block Position Analyzer")
    parser.add_argument(
        "--trades",
        type=str,
        default="data/account88888_trades_joined.json",
        help="Path to trades file"
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=500,
        help="Number of transactions to analyze (default: 500)"
    )

    args = parser.parse_args()

    analyzer = BlockPositionAnalyzer()
    trades_file = PROJECT_ROOT / args.trades
    analyzer.run(str(trades_file), args.sample)


if __name__ == "__main__":
    main()
