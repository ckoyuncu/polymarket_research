#!/usr/bin/env python3
"""
Gas Pattern Analyzer

Analyzes Account88888's gas usage patterns to detect:
1. Priority gas usage (paying premium for faster execution)
2. Rush trades (high gas in time-sensitive situations)
3. Correlation between gas spent and trade success
4. MEV protection strategies

Usage:
    python scripts/reverse_engineer/gas_pattern_analyzer.py --sample 500

Note: Fetches transaction data from Polygon RPC.
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
class GasAnalysis:
    """Gas analysis for a single transaction."""
    tx_hash: str
    block_number: int
    timestamp: int

    # Gas metrics
    gas_price_gwei: float
    gas_used: int
    gas_cost_matic: float

    # Trade info
    side: str
    usdc_amount: float
    token_id: str
    slug: str

    # Timing context
    seconds_to_resolution: Optional[int] = None
    is_final_minute: bool = False

    # Comparison
    block_avg_gas: Optional[float] = None
    gas_percentile_in_block: Optional[float] = None
    paid_premium: bool = False


class GasPatternAnalyzer:
    """Analyzes gas usage patterns."""

    RPC_ENDPOINTS = [
        "https://polygon-rpc.com",
        "https://rpc-mainnet.matic.network",
        "https://polygon-mainnet.public.blastapi.io",
    ]

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or PROJECT_ROOT / "data" / "analysis"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.rpc_index = 0
        self.analyses: List[GasAnalysis] = []
        self.block_cache: Dict[int, dict] = {}

    def get_rpc(self) -> str:
        return self.RPC_ENDPOINTS[self.rpc_index % len(self.RPC_ENDPOINTS)]

    def rotate_rpc(self):
        self.rpc_index += 1

    def eth_call(self, method: str, params: list) -> Optional[dict]:
        """Make RPC call with retry."""
        for _ in range(3):
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
            except:
                pass
            self.rotate_rpc()
            time.sleep(0.3)
        return None

    def get_tx_details(self, tx_hash: str) -> Optional[Tuple[dict, dict]]:
        """Get transaction and receipt."""
        tx = self.eth_call("eth_getTransactionByHash", [tx_hash])
        receipt = self.eth_call("eth_getTransactionReceipt", [tx_hash])
        return (tx, receipt) if tx and receipt else None

    def get_block(self, block_number: int) -> Optional[dict]:
        """Get block data (cached)."""
        if block_number in self.block_cache:
            return self.block_cache[block_number]

        block = self.eth_call("eth_getBlockByNumber", [hex(block_number), True])
        if block:
            self.block_cache[block_number] = block
        return block

    def analyze_transaction(self, trade: dict, token_mapping: Dict) -> Optional[GasAnalysis]:
        """Analyze gas usage for a trade."""
        tx_hash = trade.get("tx_hash")
        if not tx_hash:
            return None

        result = self.get_tx_details(tx_hash)
        if not result:
            return None

        tx, receipt = result

        # Extract gas info
        gas_price = int(tx.get("gasPrice", "0x0"), 16)
        gas_used = int(receipt.get("gasUsed", "0x0"), 16)
        gas_price_gwei = gas_price / 1e9
        gas_cost_wei = gas_price * gas_used
        gas_cost_matic = gas_cost_wei / 1e18

        block_number = int(receipt.get("blockNumber", "0x0"), 16)

        # Get block for context
        block = self.get_block(block_number)
        timestamp = int(block.get("timestamp", "0x0"), 16) if block else 0

        # Calculate block average gas
        block_avg_gas = None
        gas_percentile = None
        if block:
            block_txs = block.get("transactions", [])
            if block_txs and isinstance(block_txs[0], dict):
                gas_prices = [
                    int(t.get("gasPrice", "0x0"), 16) / 1e9
                    for t in block_txs
                    if t.get("gasPrice")
                ]
                if gas_prices:
                    block_avg_gas = statistics.mean(gas_prices)
                    # Calculate percentile
                    below = sum(1 for g in gas_prices if g < gas_price_gwei)
                    gas_percentile = below / len(gas_prices) * 100

        # Get market timing info
        token_id = trade.get("token_id", "")
        market_info = token_mapping.get(token_id, {})
        slug = market_info.get("slug", trade.get("slug", ""))

        seconds_to_resolution = None
        is_final_minute = False

        if slug:
            try:
                parts = slug.split("-")
                window_start = int(parts[-1])
                window_end = window_start + 900
                seconds_to_resolution = window_end - timestamp
                is_final_minute = 0 < seconds_to_resolution <= 60
            except:
                pass

        # Determine if paid premium
        paid_premium = False
        if block_avg_gas:
            paid_premium = gas_price_gwei > block_avg_gas * 1.5

        return GasAnalysis(
            tx_hash=tx_hash,
            block_number=block_number,
            timestamp=timestamp,
            gas_price_gwei=gas_price_gwei,
            gas_used=gas_used,
            gas_cost_matic=gas_cost_matic,
            side=trade.get("side", ""),
            usdc_amount=trade.get("usdc_amount", 0),
            token_id=token_id,
            slug=slug,
            seconds_to_resolution=seconds_to_resolution,
            is_final_minute=is_final_minute,
            block_avg_gas=block_avg_gas,
            gas_percentile_in_block=gas_percentile,
            paid_premium=paid_premium,
        )

    def load_trades(self, trades_file: str, sample_size: int = 500) -> List[dict]:
        """Load trades from file."""
        print(f"Loading trades from {trades_file}...")

        with open(trades_file) as f:
            data = json.load(f)

        trades = data.get("trades", data) if isinstance(data, dict) else data

        # Filter to trades with tx_hash
        trades_with_hash = [t for t in trades if t.get("tx_hash")]

        # Random sample
        import random
        random.seed(42)
        if len(trades_with_hash) > sample_size:
            trades_with_hash = random.sample(trades_with_hash, sample_size)

        print(f"  Sampled: {len(trades_with_hash)} trades")
        return trades_with_hash

    def load_token_mapping(self, mapping_file: str) -> Dict:
        """Load token to market mapping."""
        try:
            with open(mapping_file) as f:
                data = json.load(f)
            return data.get("token_to_market", data)
        except:
            return {}

    def analyze_trades(self, trades: List[dict], token_mapping: Dict):
        """Analyze all trades."""
        print(f"\nAnalyzing {len(trades)} transactions...")

        for i, trade in enumerate(trades):
            if i % 50 == 0:
                print(f"  Progress: {i}/{len(trades)}")

            analysis = self.analyze_transaction(trade, token_mapping)
            if analysis:
                self.analyses.append(analysis)

            time.sleep(0.15)  # Rate limiting

        print(f"  Analyzed: {len(self.analyses)} transactions")

    def compute_statistics(self) -> Dict:
        """Compute gas usage statistics."""
        if not self.analyses:
            return {}

        gas_prices = [a.gas_price_gwei for a in self.analyses]
        gas_costs = [a.gas_cost_matic for a in self.analyses]
        percentiles = [a.gas_percentile_in_block for a in self.analyses if a.gas_percentile_in_block]

        stats = {
            "total_analyzed": len(self.analyses),

            # Gas price stats
            "avg_gas_gwei": statistics.mean(gas_prices),
            "median_gas_gwei": statistics.median(gas_prices),
            "min_gas_gwei": min(gas_prices),
            "max_gas_gwei": max(gas_prices),

            # Cost stats
            "total_gas_cost_matic": sum(gas_costs),
            "avg_gas_cost_matic": statistics.mean(gas_costs),

            # Premium usage
            "premium_trades_pct": sum(1 for a in self.analyses if a.paid_premium) / len(self.analyses) * 100,
            "avg_percentile_in_block": statistics.mean(percentiles) if percentiles else 50,

            # Final minute analysis
            "final_minute_trades": sum(1 for a in self.analyses if a.is_final_minute),
        }

        # Compare final minute vs normal gas
        final_min_gas = [a.gas_price_gwei for a in self.analyses if a.is_final_minute]
        normal_gas = [a.gas_price_gwei for a in self.analyses if not a.is_final_minute]

        if final_min_gas and normal_gas:
            stats["final_min_avg_gas"] = statistics.mean(final_min_gas)
            stats["normal_avg_gas"] = statistics.mean(normal_gas)
            stats["final_min_gas_premium"] = (
                (stats["final_min_avg_gas"] - stats["normal_avg_gas"]) /
                stats["normal_avg_gas"] * 100
            )

        return stats

    def print_analysis(self, stats: Dict):
        """Print analysis results."""
        print("\n" + "=" * 70)
        print("GAS PATTERN ANALYSIS")
        print("=" * 70)

        print(f"\nTransactions analyzed: {stats.get('total_analyzed', 0):,}")

        print("\n--- Gas Price ---")
        print(f"Average: {stats.get('avg_gas_gwei', 0):.2f} gwei")
        print(f"Median: {stats.get('median_gas_gwei', 0):.2f} gwei")
        print(f"Range: {stats.get('min_gas_gwei', 0):.2f} - {stats.get('max_gas_gwei', 0):.2f} gwei")

        print("\n--- Gas Cost ---")
        print(f"Total spent: {stats.get('total_gas_cost_matic', 0):.4f} MATIC")
        print(f"Average per trade: {stats.get('avg_gas_cost_matic', 0):.6f} MATIC")

        print("\n--- Priority Analysis ---")
        print(f"Trades with premium gas (>1.5x block avg): {stats.get('premium_trades_pct', 0):.1f}%")
        print(f"Average position in block: {stats.get('avg_percentile_in_block', 50):.1f}th percentile")

        print("\n--- Final Minute Analysis ---")
        final_min = stats.get('final_minute_trades', 0)
        print(f"Trades in final minute: {final_min}")

        if stats.get('final_min_avg_gas'):
            print(f"Final minute avg gas: {stats.get('final_min_avg_gas', 0):.2f} gwei")
            print(f"Normal avg gas: {stats.get('normal_avg_gas', 0):.2f} gwei")
            premium = stats.get('final_min_gas_premium', 0)
            print(f"Final minute premium: {premium:+.1f}%")

        # Interpretation
        print("\n--- Interpretation ---")

        if stats.get('premium_trades_pct', 0) > 20:
            print("! HIGH premium gas usage - paying for priority execution")
        else:
            print("Normal gas usage - not paying for priority")

        if stats.get('avg_percentile_in_block', 50) > 70:
            print("Trades typically near end of block - normal ordering")
        elif stats.get('avg_percentile_in_block', 50) < 30:
            print("! Trades typically near START of block - possible MEV/priority")

        if stats.get('final_min_gas_premium', 0) > 50:
            print("! MUCH higher gas in final minute - rushing time-sensitive trades")
        elif stats.get('final_min_gas_premium', 0) > 0:
            print("Slightly higher gas in final minute - normal urgency")

        print("\n" + "=" * 70)

    def save_results(self, stats: Dict):
        """Save results to file."""
        timestamp = int(time.time())

        filepath = self.output_dir / f"gas_analysis_{timestamp}.json"
        with open(filepath, 'w') as f:
            json.dump({
                "stats": stats,
                "analyses": [asdict(a) for a in self.analyses],
            }, f, indent=2)

        print(f"\nSaved results to: {filepath}")

    def run(self, trades_file: str, mapping_file: str, sample_size: int = 500):
        """Run the analysis."""
        print("=" * 70)
        print("GAS PATTERN ANALYZER")
        print("=" * 70)
        print()

        trades = self.load_trades(trades_file, sample_size)
        token_mapping = self.load_token_mapping(mapping_file)

        self.analyze_trades(trades, token_mapping)

        stats = self.compute_statistics()
        self.print_analysis(stats)
        self.save_results(stats)

        return stats


def main():
    """Run gas pattern analyzer."""
    import argparse

    parser = argparse.ArgumentParser(description="Gas Pattern Analyzer")
    parser.add_argument("--sample", type=int, default=500, help="Sample size")
    parser.add_argument(
        "--trades",
        default="data/account88888_trades_joined.json",
        help="Trades file"
    )
    parser.add_argument(
        "--mapping",
        default="data/token_to_market.json",
        help="Token mapping file"
    )

    args = parser.parse_args()

    analyzer = GasPatternAnalyzer()
    analyzer.run(
        str(PROJECT_ROOT / args.trades),
        str(PROJECT_ROOT / args.mapping),
        args.sample
    )


if __name__ == "__main__":
    main()
