#!/usr/bin/env python3
"""
Tracker Health Monitor

Monitors running trackers and reports health status:
- Process alive check
- Memory usage
- Output file growth
- Last activity timestamp

Usage:
    python scripts/reverse_engineer/tracker_health_monitor.py

Runs continuously, prints status every 30 seconds.
"""

import os
import sys
import time
import subprocess
import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent

TRACKERS = {
    "final_minute": {
        "process_name": "final_minute_tracker.py",
        "output_dir": PROJECT_ROOT / "data" / "research" / "final_minute",
    },
    "multi_exchange": {
        "process_name": "multi_exchange_tracker.py",
        "output_dir": PROJECT_ROOT / "data" / "research" / "multi_exchange",
    },
    "orderbook": {
        "process_name": "orderbook_imbalance_analyzer.py",
        "output_dir": PROJECT_ROOT / "data" / "research" / "orderbook_imbalance",
    },
}


def check_process_running(process_name: str) -> dict:
    """Check if a process is running and get its stats."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", process_name],
            capture_output=True,
            text=True
        )
        pids = result.stdout.strip().split('\n')
        pids = [p for p in pids if p]

        if not pids:
            return {"running": False, "pid": None, "memory_mb": 0}

        pid = pids[0]

        # Get memory usage
        mem_result = subprocess.run(
            ["ps", "-o", "rss=", "-p", pid],
            capture_output=True,
            text=True
        )
        memory_kb = int(mem_result.stdout.strip()) if mem_result.stdout.strip() else 0
        memory_mb = memory_kb / 1024

        return {"running": True, "pid": pid, "memory_mb": memory_mb}
    except Exception as e:
        return {"running": False, "pid": None, "memory_mb": 0, "error": str(e)}


def check_output_files(output_dir: Path) -> dict:
    """Check output directory for recent files."""
    try:
        if not output_dir.exists():
            return {"file_count": 0, "latest_file": None, "latest_age_seconds": None}

        files = list(output_dir.glob("*.json"))
        if not files:
            return {"file_count": 0, "latest_file": None, "latest_age_seconds": None}

        latest = max(files, key=lambda f: f.stat().st_mtime)
        age = time.time() - latest.stat().st_mtime

        return {
            "file_count": len(files),
            "latest_file": latest.name,
            "latest_age_seconds": int(age),
            "latest_size_kb": latest.stat().st_size / 1024,
        }
    except Exception as e:
        return {"error": str(e)}


def get_system_stats() -> dict:
    """Get system memory and CPU stats."""
    try:
        # Memory
        with open('/proc/meminfo') as f:
            meminfo = f.read()

        mem_total = mem_available = 0
        for line in meminfo.split('\n'):
            if line.startswith('MemTotal:'):
                mem_total = int(line.split()[1]) / 1024  # MB
            elif line.startswith('MemAvailable:'):
                mem_available = int(line.split()[1]) / 1024  # MB

        # Load average
        with open('/proc/loadavg') as f:
            load = f.read().split()[0]

        return {
            "memory_total_mb": int(mem_total),
            "memory_available_mb": int(mem_available),
            "memory_used_pct": int(100 * (mem_total - mem_available) / mem_total) if mem_total else 0,
            "load_avg": float(load),
        }
    except Exception as e:
        return {"error": str(e)}


def print_status():
    """Print health status of all trackers."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"\n{'='*60}")
    print(f"TRACKER HEALTH STATUS - {now}")
    print(f"{'='*60}")

    # System stats
    sys_stats = get_system_stats()
    if "error" not in sys_stats:
        print(f"\nSystem: {sys_stats['memory_available_mb']}MB free / {sys_stats['memory_total_mb']}MB total ({sys_stats['memory_used_pct']}% used), load: {sys_stats['load_avg']}")

    # Tracker stats
    all_healthy = True
    for name, config in TRACKERS.items():
        proc = check_process_running(config["process_name"])
        files = check_output_files(config["output_dir"])

        status = "✓ RUNNING" if proc["running"] else "✗ STOPPED"
        if not proc["running"]:
            all_healthy = False

        print(f"\n{name.upper()}:")
        print(f"  Status: {status}")
        if proc["running"]:
            print(f"  PID: {proc['pid']}, Memory: {proc['memory_mb']:.1f}MB")

        if files.get("file_count", 0) > 0:
            print(f"  Output: {files['file_count']} files, latest: {files['latest_file']} ({files['latest_age_seconds']}s ago, {files.get('latest_size_kb', 0):.1f}KB)")
        else:
            print(f"  Output: No files yet")

    # Summary
    print(f"\n{'='*60}")
    if all_healthy:
        print("All trackers running ✓")
    else:
        print("WARNING: Some trackers not running!")
    print(f"{'='*60}")


def main():
    """Run health monitor."""
    import argparse

    parser = argparse.ArgumentParser(description="Tracker Health Monitor")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--interval", type=int, default=30, help="Check interval in seconds")
    args = parser.parse_args()

    print("TRACKER HEALTH MONITOR")
    print("Press Ctrl+C to stop")

    try:
        while True:
            print_status()
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped")


if __name__ == "__main__":
    main()
