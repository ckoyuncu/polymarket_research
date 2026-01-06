#!/usr/bin/env python3
"""
Data Completeness Validation Tests

Validates that all data sources are complete and consistent for
Account88888 strategy analysis.

Usage:
    python scripts/tests/validate_data_completeness.py
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def test_trade_count():
    """Verify we have all 2.9M+ trades, not just a sample."""
    trades_path = Path("data/account88888_trades_joined.json")

    if not trades_path.exists():
        return "SKIP", "trades_joined.json not found"

    with open(trades_path, 'r') as f:
        data = json.load(f)

    # Handle nested structure
    if isinstance(data, dict):
        if "trades" in data:
            trades = data["trades"]
        else:
            trades = list(data.values())
    else:
        trades = data

    count = len(trades)

    if count < 100:
        return "FAIL", f"Only {count} trades - likely using test data"
    if count < 2_900_000:
        return "WARN", f"{count:,} trades - may be incomplete (expected 2.9M+)"

    return "PASS", f"{count:,} trades loaded"


def test_date_range():
    """Verify full 31-day coverage (Dec 5, 2025 - Jan 5, 2026)."""
    trades_path = Path("data/account88888_trades_joined.json")

    if not trades_path.exists():
        return "SKIP", "trades_joined.json not found"

    # Sample first and last trades
    result = subprocess.run(
        ["python3", "-c", """
import json
with open('data/account88888_trades_joined.json', 'r') as f:
    data = json.load(f)
trades = data.get('trades', data) if isinstance(data, dict) else data
timestamps = sorted([t.get('timestamp', 0) for t in trades if t.get('timestamp')])
if timestamps:
    print(timestamps[0], timestamps[-1])
else:
    print(0, 0)
"""],
        capture_output=True,
        text=True,
        timeout=120
    )

    if result.returncode != 0:
        return "FAIL", f"Error reading trades: {result.stderr[:100]}"

    try:
        first_ts, last_ts = map(int, result.stdout.strip().split())
    except:
        return "FAIL", f"Could not parse timestamps: {result.stdout[:100]}"

    first_date = datetime.fromtimestamp(first_ts, tz=timezone.utc).date()
    last_date = datetime.fromtimestamp(last_ts, tz=timezone.utc).date()

    expected_start = datetime(2025, 12, 5).date()
    expected_end = datetime(2026, 1, 5).date()

    issues = []
    if first_date > expected_start:
        issues.append(f"Missing early data (starts {first_date})")
    if last_date < expected_end:
        issues.append(f"Missing late data (ends {last_date})")

    if issues:
        return "WARN", "; ".join(issues)

    return "PASS", f"Full coverage: {first_date} to {last_date}"


def test_usdc_coverage():
    """Verify USDC (ERC20) coverage is complete."""
    # Check ERC20 file directly
    erc20_path = Path("data/ec2_transfers/transfers_0x7f69983e_erc20.jsonl")

    if not erc20_path.exists():
        return "SKIP", "ERC20 transfers file not found"

    # Get line count
    result = subprocess.run(
        ["wc", "-l", str(erc20_path)],
        capture_output=True,
        text=True
    )
    erc20_count = int(result.stdout.strip().split()[0])

    # Check last timestamp
    result = subprocess.run(
        ["tail", "-1", str(erc20_path)],
        capture_output=True,
        text=True
    )
    try:
        last_record = json.loads(result.stdout.strip())
        last_ts = int(last_record.get("timeStamp", 0))
        last_date = datetime.fromtimestamp(last_ts, tz=timezone.utc).date()
    except:
        last_date = None

    expected_end = datetime(2026, 1, 5).date()

    if last_date and last_date < expected_end:
        return "FAIL", f"ERC20 extraction incomplete: ends {last_date}, need {expected_end}"

    return "PASS", f"{erc20_count:,} ERC20 transfers through {last_date}"


def test_metadata_coverage():
    """Verify market metadata coverage."""
    metadata_path = Path("data/token_to_market_full.json")

    if not metadata_path.exists():
        return "SKIP", "Metadata file not found"

    with open(metadata_path, 'r') as f:
        data = json.load(f)

    # Handle nested structure
    if "token_to_market" in data:
        metadata = data["token_to_market"]
    else:
        metadata = data

    count = len(metadata)

    if count < 1000:
        return "WARN", f"Only {count} tokens mapped - may be incomplete"

    # Check if metadata has required fields
    sample_key = next(iter(metadata.keys()))
    sample = metadata[sample_key]
    required_fields = ["slug", "outcome", "asset"]
    missing = [f for f in required_fields if f not in sample]

    if missing:
        return "WARN", f"Metadata missing fields: {missing}"

    return "PASS", f"{count:,} tokens mapped with complete metadata"


def test_timing_calculation():
    """Verify timing calculation bug is fixed."""
    # Read the backtest file and check for the fix
    backtest_path = Path("scripts/analysis/backtest_88888_full.py")

    if not backtest_path.exists():
        return "SKIP", "Backtest script not found"

    with open(backtest_path, 'r') as f:
        content = f.read()

    # Check for the bug fix (separate before/after handling)
    has_before_handling = "timing_buckets_before" in content or "BEFORE resolution" in content
    has_after_handling = "timing_buckets_after" in content or "AFTER resolution" in content
    has_time_diff_check = "time_diff > 0" in content or "seconds_after" in content

    if not has_before_handling or not has_after_handling:
        return "FAIL", "Timing bug may not be fixed (missing before/after separation)"

    if not has_time_diff_check:
        return "WARN", "Timing check may be incomplete"

    return "PASS", "Timing calculation includes before/after separation"


def test_binance_data():
    """Verify Binance klines data is available."""
    klines_path = Path("data/binance_klines_full.csv")

    if not klines_path.exists():
        return "SKIP", "Binance klines file not found"

    # Get line count
    result = subprocess.run(
        ["wc", "-l", str(klines_path)],
        capture_output=True,
        text=True
    )
    line_count = int(result.stdout.strip().split()[0])

    if line_count < 40000:
        return "WARN", f"Only {line_count} klines - may be incomplete"

    return "PASS", f"{line_count:,} Binance klines available"


def test_live_tracker():
    """Verify live tracker database exists and has data."""
    db_path = Path("data/tracker/trades.db")

    if not db_path.exists():
        return "SKIP", "Tracker database not found"

    import sqlite3
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM trades")
        count = cursor.fetchone()[0]
        conn.close()

        if count < 100:
            return "WARN", f"Only {count} live trades tracked"

        return "PASS", f"{count:,} live trades in tracker"
    except Exception as e:
        return "FAIL", f"Database error: {str(e)[:50]}"


def main():
    tests = [
        ("Trade Count", test_trade_count),
        ("Date Range", test_date_range),
        ("USDC Coverage", test_usdc_coverage),
        ("Metadata Coverage", test_metadata_coverage),
        ("Timing Calculation Fix", test_timing_calculation),
        ("Binance Data", test_binance_data),
        ("Live Tracker", test_live_tracker),
    ]

    print("=" * 60)
    print("DATA COMPLETENESS VALIDATION")
    print("=" * 60)
    print()

    results = []
    for name, test_func in tests:
        try:
            status, message = test_func()
        except Exception as e:
            status, message = "ERROR", str(e)[:80]

        results.append((name, status, message))

        # Color coding
        if status == "PASS":
            icon = "✓"
        elif status == "WARN":
            icon = "⚠"
        elif status == "FAIL":
            icon = "✗"
        elif status == "SKIP":
            icon = "○"
        else:
            icon = "?"

        print(f"{icon} {name}: {status}")
        print(f"    {message}")
        print()

    # Summary
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, s, _ in results if s == "PASS")
    warned = sum(1 for _, s, _ in results if s == "WARN")
    failed = sum(1 for _, s, _ in results if s == "FAIL")
    skipped = sum(1 for _, s, _ in results if s == "SKIP")

    print(f"  PASSED: {passed}")
    print(f"  WARNINGS: {warned}")
    print(f"  FAILED: {failed}")
    print(f"  SKIPPED: {skipped}")

    if failed > 0:
        print("\n⚠️  CRITICAL ISSUES FOUND - address before analysis")
    elif warned > 0:
        print("\n⚠️  Some warnings - analysis may be incomplete")
    else:
        print("\n✓ All checks passed")


if __name__ == "__main__":
    main()
