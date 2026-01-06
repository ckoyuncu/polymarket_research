#!/usr/bin/env python3
"""
Comprehensive Data Audit for Account88888 Strategy Analysis

This script meticulously validates ALL data and assumptions before drawing
any conclusions about the trading strategy.

Checks performed:
1. Trade count integrity
2. USDC coverage
3. Metadata coverage
4. Timestamp validity
5. Price anomalies
6. Token outcome mapping verification

Usage:
    python scripts/tests/comprehensive_data_audit.py
    python scripts/tests/comprehensive_data_audit.py --output reports/data_audit_report.json
"""

import argparse
import json
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Any
import statistics


class DataAudit:
    """Comprehensive data audit for Account88888 analysis."""

    def __init__(self):
        self.results = {
            "audit_timestamp": datetime.utcnow().isoformat(),
            "checks": {},
            "warnings": [],
            "errors": [],
            "summary": {}
        }

    def log_check(self, name: str, status: str, details: dict):
        """Log a check result."""
        self.results["checks"][name] = {
            "status": status,  # PASS, WARN, FAIL, SKIP
            "details": details
        }
        if status == "WARN":
            self.results["warnings"].append(f"{name}: {details.get('message', '')}")
        elif status == "FAIL":
            self.results["errors"].append(f"{name}: {details.get('message', '')}")

    def check_trade_count_integrity(self, trades: List[dict]) -> None:
        """CHECK 1: Trade count integrity."""
        print("\n[CHECK 1] Trade Count Integrity")
        print("-" * 50)

        # Count trades
        total_trades = len(trades)
        print(f"  Total trades: {total_trades:,}")

        # Check for duplicates
        tx_hashes = [t.get("tx_hash", "") for t in trades if t.get("tx_hash")]
        unique_hashes = len(set(tx_hashes))
        duplicates = total_trades - unique_hashes

        # Check timestamp range
        timestamps = [t.get("timestamp", 0) for t in trades if t.get("timestamp")]
        if timestamps:
            min_ts = min(timestamps)
            max_ts = max(timestamps)
            min_date = datetime.fromtimestamp(min_ts, tz=timezone.utc)
            max_date = datetime.fromtimestamp(max_ts, tz=timezone.utc)

            expected_start = datetime(2025, 12, 5, tzinfo=timezone.utc)
            expected_end = datetime(2026, 1, 6, tzinfo=timezone.utc)

            date_range_ok = min_date >= expected_start and max_date <= expected_end
        else:
            date_range_ok = False
            min_date = max_date = None

        # Determine status
        if total_trades >= 2_900_000 and duplicates == 0 and date_range_ok:
            status = "PASS"
        elif total_trades >= 2_900_000 and duplicates < 100:
            status = "WARN"
        else:
            status = "FAIL"

        details = {
            "total_trades": total_trades,
            "unique_tx_hashes": unique_hashes,
            "duplicates": duplicates,
            "min_date": str(min_date) if min_date else None,
            "max_date": str(max_date) if max_date else None,
            "date_range_valid": date_range_ok,
            "message": f"{total_trades:,} trades, {duplicates} duplicates"
        }

        print(f"  Unique tx_hashes: {unique_hashes:,}")
        print(f"  Duplicates: {duplicates:,}")
        print(f"  Date range: {min_date} to {max_date}")
        print(f"  Status: {status}")

        self.log_check("trade_count_integrity", status, details)

    def check_usdc_coverage(self, trades: List[dict]) -> None:
        """CHECK 2: USDC coverage."""
        print("\n[CHECK 2] USDC Coverage")
        print("-" * 50)

        total = len(trades)
        with_usdc = sum(1 for t in trades if t.get("usdc_amount", 0) and t["usdc_amount"] > 0)
        coverage_pct = (with_usdc / total * 100) if total > 0 else 0

        # Check price reasonableness
        prices = [t.get("price", 0) for t in trades if t.get("price", 0) > 0]
        reasonable_prices = [p for p in prices if 0 < p < 10]
        unreasonable_prices = [p for p in prices if p >= 10 or p < 0]

        price_stats = {}
        if reasonable_prices:
            price_stats = {
                "min": min(reasonable_prices),
                "max": max(reasonable_prices),
                "median": statistics.median(reasonable_prices),
                "avg": statistics.mean(reasonable_prices),
            }

        # Determine status
        if coverage_pct >= 95:
            status = "PASS"
        elif coverage_pct >= 50:
            status = "WARN"
        else:
            status = "FAIL"

        details = {
            "total_trades": total,
            "trades_with_usdc": with_usdc,
            "coverage_pct": round(coverage_pct, 2),
            "unreasonable_price_count": len(unreasonable_prices),
            "price_stats": price_stats,
            "message": f"{coverage_pct:.1f}% USDC coverage ({with_usdc:,}/{total:,})"
        }

        print(f"  Trades with USDC: {with_usdc:,} / {total:,}")
        print(f"  Coverage: {coverage_pct:.1f}%")
        print(f"  Unreasonable prices (>=10 or <0): {len(unreasonable_prices):,}")
        if price_stats:
            print(f"  Price stats: min=${price_stats['min']:.4f}, max=${price_stats['max']:.4f}, median=${price_stats['median']:.4f}")
        print(f"  Status: {status}")

        self.log_check("usdc_coverage", status, details)

    def check_metadata_coverage(self, trades: List[dict], metadata: Dict[str, dict]) -> None:
        """CHECK 3: Metadata coverage."""
        print("\n[CHECK 3] Metadata Coverage")
        print("-" * 50)

        # Get unique token IDs from trades
        trade_tokens = set(str(t.get("token_id", "")) for t in trades if t.get("token_id"))
        metadata_tokens = set(metadata.keys())

        covered = trade_tokens & metadata_tokens
        missing = trade_tokens - metadata_tokens
        coverage_pct = (len(covered) / len(trade_tokens) * 100) if trade_tokens else 0

        # Check required fields
        required_fields = ["slug", "clobTokenIds", "endDateIso"]
        fields_present = defaultdict(int)
        slug_format_valid = 0

        for token_id, market in metadata.items():
            for field in required_fields:
                if market.get(field):
                    fields_present[field] += 1

            # Check slug format
            slug = market.get("slug", "")
            if slug and "-updown-" in slug and "-15m-" in slug:
                slug_format_valid += 1

        # Determine status
        if coverage_pct >= 99 and len(missing) == 0:
            status = "PASS"
        elif coverage_pct >= 95:
            status = "WARN"
        else:
            status = "FAIL"

        details = {
            "unique_tokens_in_trades": len(trade_tokens),
            "tokens_in_metadata": len(metadata_tokens),
            "tokens_covered": len(covered),
            "tokens_missing": len(missing),
            "coverage_pct": round(coverage_pct, 2),
            "fields_present": dict(fields_present),
            "slug_format_valid_count": slug_format_valid,
            "sample_missing": list(missing)[:5],
            "message": f"{coverage_pct:.1f}% metadata coverage, {len(missing)} missing tokens"
        }

        print(f"  Unique tokens in trades: {len(trade_tokens):,}")
        print(f"  Tokens in metadata: {len(metadata_tokens):,}")
        print(f"  Coverage: {coverage_pct:.1f}%")
        print(f"  Missing tokens: {len(missing):,}")
        print(f"  Valid slug format: {slug_format_valid:,}")
        for field, count in fields_present.items():
            print(f"  Field '{field}': {count:,} ({count/len(metadata)*100:.1f}%)")
        print(f"  Status: {status}")

        self.log_check("metadata_coverage", status, details)

    def check_timestamp_validity(self, trades: List[dict], metadata: Dict[str, dict]) -> None:
        """CHECK 4: Timestamp validity."""
        print("\n[CHECK 4] Timestamp Validity")
        print("-" * 50)

        # Expected range
        expected_start = datetime(2025, 12, 5, tzinfo=timezone.utc).timestamp()
        expected_end = datetime(2026, 1, 6, tzinfo=timezone.utc).timestamp()

        # Check trade timestamps
        timestamps = [t.get("timestamp", 0) for t in trades if t.get("timestamp")]
        in_range = sum(1 for ts in timestamps if expected_start <= ts <= expected_end)
        out_of_range = len(timestamps) - in_range

        # Check resolution timestamps from metadata
        resolution_issues = []
        resolution_valid = 0

        for token_id, market in list(metadata.items())[:1000]:  # Sample for speed
            slug = market.get("slug", "")
            end_date_iso = market.get("endDateIso", "")

            # Extract timestamp from slug
            slug_ts = None
            if "-15m-" in slug:
                try:
                    slug_ts = int(slug.split("-15m-")[1])
                except:
                    pass

            # Parse endDateIso
            iso_ts = None
            if end_date_iso:
                try:
                    iso_ts = datetime.fromisoformat(end_date_iso.replace('Z', '+00:00')).timestamp()
                except:
                    pass

            # Compare
            if slug_ts and iso_ts:
                diff = abs(slug_ts - iso_ts)
                if diff > 60:  # More than 1 minute difference
                    resolution_issues.append({
                        "token_id": token_id[:20],
                        "slug_ts": slug_ts,
                        "iso_ts": iso_ts,
                        "diff_seconds": diff
                    })
                else:
                    resolution_valid += 1

        # Check timing difference (trade_ts vs resolution_ts)
        timing_diffs = []
        for trade in trades[:10000]:  # Sample
            token_id = str(trade.get("token_id", ""))
            if token_id in metadata:
                market = metadata[token_id]
                slug = market.get("slug", "")
                if "-15m-" in slug:
                    try:
                        resolution_ts = int(slug.split("-15m-")[1])
                        trade_ts = trade.get("timestamp", 0)
                        if trade_ts and resolution_ts:
                            diff = trade_ts - resolution_ts
                            if -3600 <= diff <= 3600:  # Within 1 hour
                                timing_diffs.append(diff)
                    except:
                        pass

        # Determine status
        if out_of_range == 0 and len(resolution_issues) < 10:
            status = "PASS"
        elif out_of_range < 100 and len(resolution_issues) < 100:
            status = "WARN"
        else:
            status = "FAIL"

        timing_stats = {}
        if timing_diffs:
            timing_stats = {
                "min": min(timing_diffs),
                "max": max(timing_diffs),
                "median": statistics.median(timing_diffs),
                "positive_count": sum(1 for d in timing_diffs if d > 0),  # After resolution
                "negative_count": sum(1 for d in timing_diffs if d < 0),  # Before resolution
            }

        details = {
            "timestamps_in_range": in_range,
            "timestamps_out_of_range": out_of_range,
            "resolution_valid": resolution_valid,
            "resolution_issues_count": len(resolution_issues),
            "sample_issues": resolution_issues[:5],
            "timing_diff_stats": timing_stats,
            "message": f"{out_of_range} timestamps out of range, {len(resolution_issues)} resolution mismatches"
        }

        print(f"  Timestamps in expected range: {in_range:,}")
        print(f"  Timestamps out of range: {out_of_range:,}")
        print(f"  Resolution timestamp mismatches: {len(resolution_issues):,}")
        if timing_stats:
            print(f"  Timing diff (trade - resolution): median={timing_stats['median']:.0f}s")
            print(f"  Trades BEFORE resolution: {timing_stats['negative_count']:,}")
            print(f"  Trades AFTER resolution: {timing_stats['positive_count']:,}")
        print(f"  Status: {status}")

        self.log_check("timestamp_validity", status, details)

    def check_price_anomalies(self, trades: List[dict]) -> None:
        """CHECK 5: Price anomalies."""
        print("\n[CHECK 5] Price Anomalies")
        print("-" * 50)

        prices = []
        anomalies = {
            "above_1": [],
            "negative": [],
            "extremely_high": [],
            "zero_with_amounts": [],
        }

        for i, trade in enumerate(trades):
            price = trade.get("price", 0)
            usdc = trade.get("usdc_amount", 0) or 0
            token = trade.get("token_amount", 0) or 0

            if price and price > 0:
                prices.append(price)

                if price > 1.0 and price <= 10:
                    anomalies["above_1"].append({"index": i, "price": price})
                elif price > 10:
                    anomalies["extremely_high"].append({"index": i, "price": price})
                elif price < 0:
                    anomalies["negative"].append({"index": i, "price": price})
            elif price == 0 and (usdc > 0 or token > 0):
                anomalies["zero_with_amounts"].append({"index": i, "usdc": usdc, "token": token})

        # Price distribution
        price_buckets = {
            "0-0.1": 0,
            "0.1-0.3": 0,
            "0.3-0.5": 0,
            "0.5-0.7": 0,
            "0.7-0.9": 0,
            "0.9-1.0": 0,
            ">1.0": 0,
        }
        for p in prices:
            if p < 0.1:
                price_buckets["0-0.1"] += 1
            elif p < 0.3:
                price_buckets["0.1-0.3"] += 1
            elif p < 0.5:
                price_buckets["0.3-0.5"] += 1
            elif p < 0.7:
                price_buckets["0.5-0.7"] += 1
            elif p < 0.9:
                price_buckets["0.7-0.9"] += 1
            elif p <= 1.0:
                price_buckets["0.9-1.0"] += 1
            else:
                price_buckets[">1.0"] += 1

        total_anomalies = sum(len(v) for v in anomalies.values())

        # Determine status
        if total_anomalies < 100:
            status = "PASS"
        elif total_anomalies < 1000:
            status = "WARN"
        else:
            status = "FAIL"

        details = {
            "total_with_price": len(prices),
            "price_distribution": price_buckets,
            "anomaly_counts": {k: len(v) for k, v in anomalies.items()},
            "total_anomalies": total_anomalies,
            "sample_extremely_high": anomalies["extremely_high"][:5],
            "message": f"{total_anomalies:,} price anomalies detected"
        }

        print(f"  Total trades with price: {len(prices):,}")
        print(f"  Price distribution:")
        for bucket, count in price_buckets.items():
            pct = count / len(prices) * 100 if prices else 0
            print(f"    {bucket}: {count:,} ({pct:.1f}%)")
        print(f"  Anomalies:")
        print(f"    Above $1 (but <=10): {len(anomalies['above_1']):,}")
        print(f"    Extremely high (>$10): {len(anomalies['extremely_high']):,}")
        print(f"    Negative: {len(anomalies['negative']):,}")
        print(f"    Zero with amounts: {len(anomalies['zero_with_amounts']):,}")
        print(f"  Status: {status}")

        self.log_check("price_anomalies", status, details)

    def check_token_outcome_mapping(self, metadata: Dict[str, dict]) -> None:
        """CHECK 6: Token outcome mapping verification."""
        print("\n[CHECK 6] Token Outcome Mapping (clobTokenIds Order)")
        print("-" * 50)

        markets_checked = 0
        up_first_confirmed = 0
        down_first_confirmed = 0
        inconclusive = 0
        no_clob_ids = 0

        # For each market, check if clobTokenIds[0] is UP and [1] is DOWN
        for token_id, market in metadata.items():
            clob_ids = market.get("clobTokenIds", [])
            outcomes = market.get("outcomes", [])

            if not clob_ids:
                no_clob_ids += 1
                continue

            # Handle string format
            if isinstance(clob_ids, str):
                try:
                    clob_ids = json.loads(clob_ids)
                except:
                    inconclusive += 1
                    continue

            if len(clob_ids) != 2 or len(outcomes) != 2:
                inconclusive += 1
                continue

            markets_checked += 1

            # Check outcome order
            # outcomes should be ["Up", "Down"] or similar
            outcome_lower = [o.lower() if isinstance(o, str) else "" for o in outcomes]

            if outcome_lower == ["up", "down"]:
                up_first_confirmed += 1
            elif outcome_lower == ["down", "up"]:
                down_first_confirmed += 1
            else:
                inconclusive += 1

        # Determine status
        if up_first_confirmed > 0 and down_first_confirmed == 0:
            status = "PASS"
            assumption = "CONFIRMED: clobTokenIds[0] = UP, [1] = DOWN"
        elif down_first_confirmed > 0 and up_first_confirmed == 0:
            status = "WARN"
            assumption = "INVERTED: clobTokenIds[0] = DOWN, [1] = UP"
        elif up_first_confirmed > down_first_confirmed:
            status = "WARN"
            assumption = f"MOSTLY UP FIRST ({up_first_confirmed} vs {down_first_confirmed})"
        else:
            status = "FAIL"
            assumption = "INCONSISTENT ORDERING"

        details = {
            "markets_checked": markets_checked,
            "up_first": up_first_confirmed,
            "down_first": down_first_confirmed,
            "inconclusive": inconclusive,
            "no_clob_ids": no_clob_ids,
            "assumption_status": assumption,
            "message": assumption
        }

        print(f"  Markets checked: {markets_checked:,}")
        print(f"  UP first (clobTokenIds[0]=UP): {up_first_confirmed:,}")
        print(f"  DOWN first: {down_first_confirmed:,}")
        print(f"  Inconclusive: {inconclusive:,}")
        print(f"  No clobTokenIds: {no_clob_ids:,}")
        print(f"  Assumption: {assumption}")
        print(f"  Status: {status}")

        self.log_check("token_outcome_mapping", status, details)

    def generate_summary(self) -> None:
        """Generate audit summary."""
        passed = sum(1 for c in self.results["checks"].values() if c["status"] == "PASS")
        warned = sum(1 for c in self.results["checks"].values() if c["status"] == "WARN")
        failed = sum(1 for c in self.results["checks"].values() if c["status"] == "FAIL")
        skipped = sum(1 for c in self.results["checks"].values() if c["status"] == "SKIP")

        self.results["summary"] = {
            "total_checks": len(self.results["checks"]),
            "passed": passed,
            "warnings": warned,
            "failed": failed,
            "skipped": skipped,
            "overall_status": "PASS" if failed == 0 and warned == 0 else ("WARN" if failed == 0 else "FAIL")
        }


def load_trades(path: str) -> List[dict]:
    """Load trades from JSON file."""
    print(f"Loading trades from {path}...")
    with open(path, 'r') as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "trades" in data:
            trades = data["trades"]
            return list(trades.values()) if isinstance(trades, dict) else trades
        return list(data.values())
    return data


def load_metadata(path: str) -> Dict[str, dict]:
    """Load metadata from JSON file."""
    print(f"Loading metadata from {path}...")
    with open(path, 'r') as f:
        data = json.load(f)

    if isinstance(data, dict):
        if "token_to_market" in data:
            return data["token_to_market"]
        first_key = next(iter(data.keys()), "")
        if len(first_key) > 50:
            return data
    return data


def main():
    parser = argparse.ArgumentParser(description="Comprehensive Data Audit")
    parser.add_argument("--trades", type=str, default="data/account88888_trades_joined.json")
    parser.add_argument("--metadata", type=str, default="data/token_to_market_full.json")
    parser.add_argument("--output", type=str, help="Output JSON file for results")
    args = parser.parse_args()

    print("=" * 70)
    print("COMPREHENSIVE DATA AUDIT - Account88888 Strategy Analysis")
    print("=" * 70)

    # Load data
    trades = load_trades(args.trades)
    metadata = load_metadata(args.metadata)

    print(f"\nLoaded {len(trades):,} trades and {len(metadata):,} token mappings")

    # Run audit
    audit = DataAudit()

    audit.check_trade_count_integrity(trades)
    audit.check_usdc_coverage(trades)
    audit.check_metadata_coverage(trades, metadata)
    audit.check_timestamp_validity(trades, metadata)
    audit.check_price_anomalies(trades)
    audit.check_token_outcome_mapping(metadata)

    # Generate summary
    audit.generate_summary()

    # Print summary
    print("\n" + "=" * 70)
    print("AUDIT SUMMARY")
    print("=" * 70)
    summary = audit.results["summary"]
    print(f"\nTotal checks: {summary['total_checks']}")
    print(f"  PASSED:  {summary['passed']}")
    print(f"  WARNINGS: {summary['warnings']}")
    print(f"  FAILED:  {summary['failed']}")
    print(f"  SKIPPED: {summary['skipped']}")
    print(f"\nOverall Status: {summary['overall_status']}")

    if audit.results["errors"]:
        print("\nERRORS:")
        for err in audit.results["errors"]:
            print(f"  - {err}")

    if audit.results["warnings"]:
        print("\nWARNINGS:")
        for warn in audit.results["warnings"]:
            print(f"  - {warn}")

    # Save results
    if args.output:
        Path(args.output).parent.mkdir(exist_ok=True)
        with open(args.output, 'w') as f:
            json.dump(audit.results, f, indent=2, default=str)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
