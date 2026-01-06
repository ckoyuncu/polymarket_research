#!/usr/bin/env python3
"""
Maker Bot Health Check Orchestrator

Runs parallel health checks to verify bot is operating correctly:
1. EC2 Instance - SSH connectivity, service status
2. CLOB API - Connection, credentials, rate limits
3. Orders - Live orders, recent activity
4. Balance - USDC balance, positions
5. Markets - Active markets, spreads
6. Logs - Recent errors, success rate

Usage:
    python scripts/health_check.py           # Full health check
    python scripts/health_check.py --quick   # Quick check (no logs)
    python scripts/health_check.py --watch   # Continuous monitoring
"""

import os
import sys
import json
import time
import argparse
import subprocess
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class Status(Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class CheckResult:
    name: str
    status: Status
    message: str
    details: Dict = field(default_factory=dict)
    duration_ms: float = 0


@dataclass
class HealthReport:
    timestamp: datetime
    overall_status: Status
    checks: List[CheckResult]
    summary: str

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "overall_status": self.overall_status.value,
            "summary": self.summary,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                    "duration_ms": c.duration_ms
                }
                for c in self.checks
            ]
        }


# Configuration
EC2_HOST = "13.231.67.98"
EC2_USER = "ubuntu"
EC2_KEY = os.path.expanduser("~/.ssh/polymarket-bot-key-tokyo.pem")
SERVICE_NAME = "maker-bot.service"


def run_ssh_command(cmd: str, timeout: int = 30) -> Tuple[int, str, str]:
    """Run command on EC2 via SSH."""
    ssh_cmd = [
        "ssh", "-i", EC2_KEY,
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{EC2_USER}@{EC2_HOST}",
        cmd
    ]
    try:
        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "SSH timeout"
    except Exception as e:
        return -1, "", str(e)


def check_ec2_connectivity() -> CheckResult:
    """Check if we can SSH to EC2."""
    start = time.time()

    code, out, err = run_ssh_command("echo 'connected'", timeout=15)
    duration = (time.time() - start) * 1000

    if code == 0 and "connected" in out:
        return CheckResult(
            name="EC2 Connectivity",
            status=Status.OK,
            message=f"SSH to {EC2_HOST} successful",
            details={"host": EC2_HOST, "latency_ms": round(duration)},
            duration_ms=duration
        )
    else:
        return CheckResult(
            name="EC2 Connectivity",
            status=Status.ERROR,
            message=f"Cannot SSH to {EC2_HOST}: {err}",
            details={"host": EC2_HOST, "error": err},
            duration_ms=duration
        )


def check_service_status() -> CheckResult:
    """Check if systemd service is running."""
    start = time.time()

    code, out, err = run_ssh_command(
        f"systemctl is-active {SERVICE_NAME} && systemctl show {SERVICE_NAME} --property=ActiveEnterTimestamp,MainPID,NRestarts"
    )
    duration = (time.time() - start) * 1000

    if code == 0:
        lines = out.strip().split('\n')
        is_active = lines[0] if lines else "unknown"

        details = {"service": SERVICE_NAME}
        for line in lines[1:]:
            if '=' in line:
                key, val = line.split('=', 1)
                details[key] = val

        if is_active == "active":
            return CheckResult(
                name="Service Status",
                status=Status.OK,
                message=f"{SERVICE_NAME} is active (PID: {details.get('MainPID', 'unknown')})",
                details=details,
                duration_ms=duration
            )
        else:
            return CheckResult(
                name="Service Status",
                status=Status.ERROR,
                message=f"{SERVICE_NAME} is {is_active}",
                details=details,
                duration_ms=duration
            )
    else:
        return CheckResult(
            name="Service Status",
            status=Status.ERROR,
            message=f"Cannot check service: {err}",
            details={"error": err},
            duration_ms=duration
        )


def check_recent_logs() -> CheckResult:
    """Check recent logs for errors."""
    start = time.time()

    code, out, err = run_ssh_command(
        f"journalctl -u {SERVICE_NAME} --no-pager -n 100 --since '10 minutes ago'"
    )
    duration = (time.time() - start) * 1000

    if code != 0:
        return CheckResult(
            name="Recent Logs",
            status=Status.WARNING,
            message=f"Cannot fetch logs: {err}",
            details={"error": err},
            duration_ms=duration
        )

    lines = out.strip().split('\n') if out.strip() else []

    # Count different log types
    errors = [l for l in lines if 'ERROR' in l or 'Error' in l]
    warnings = [l for l in lines if 'WARNING' in l or 'Warning' in l]
    orders_placed = [l for l in lines if 'Order placed' in l and 'success' in l.lower()]
    order_successes = [l for l in lines if 'HTTP/2 200 OK' in l and 'order' in l.lower()]
    cloudflare_blocks = [l for l in lines if ('Cloudflare' in l or 'HTTP/2 403' in l) and 'order' in l.lower()]
    markets_found = [l for l in lines if 'Found' in l and 'market' in l]

    details = {
        "total_lines": len(lines),
        "errors": len(errors),
        "warnings": len(warnings),
        "orders_placed": len(orders_placed),
        "order_successes": len(order_successes),
        "cloudflare_blocks": len(cloudflare_blocks),
        "recent_errors": errors[-3:] if errors else []
    }

    # Extract latest market count
    for line in reversed(markets_found):
        if "Found" in line and "active market" in line:
            details["last_market_check"] = line.split(" - ")[-1] if " - " in line else line
            break

    # Only error if recent Cloudflare blocks AND no successful orders
    if cloudflare_blocks and not order_successes:
        return CheckResult(
            name="Recent Logs",
            status=Status.ERROR,
            message=f"Cloudflare blocking orders ({len(cloudflare_blocks)} blocks, 0 successes)",
            details=details,
            duration_ms=duration
        )
    elif cloudflare_blocks and order_successes:
        # Some blocks but also successes - warning only
        return CheckResult(
            name="Recent Logs",
            status=Status.WARNING,
            message=f"{len(order_successes)} orders OK, {len(cloudflare_blocks)} blocks (intermittent)",
            details=details,
            duration_ms=duration
        )
    elif errors:
        return CheckResult(
            name="Recent Logs",
            status=Status.WARNING,
            message=f"{len(errors)} errors in last 10 min, {len(orders_placed)} orders placed",
            details=details,
            duration_ms=duration
        )
    else:
        return CheckResult(
            name="Recent Logs",
            status=Status.OK,
            message=f"No errors, {len(orders_placed)} orders placed in last 10 min",
            details=details,
            duration_ms=duration
        )


def check_clob_api() -> CheckResult:
    """Check CLOB API connectivity and credentials."""
    start = time.time()

    try:
        from py_clob_client.client import ClobClient

        key = os.getenv('POLYMARKET_PRIVATE_KEY')
        if not key:
            return CheckResult(
                name="CLOB API",
                status=Status.ERROR,
                message="POLYMARKET_PRIVATE_KEY not set",
                details={},
                duration_ms=(time.time() - start) * 1000
            )

        client = ClobClient(
            'https://clob.polymarket.com',
            key=key,
            chain_id=137,
            signature_type=2
        )
        client.set_api_creds(client.derive_api_key())

        # Test API call
        orders = client.get_orders()

        duration = (time.time() - start) * 1000
        return CheckResult(
            name="CLOB API",
            status=Status.OK,
            message=f"Connected, {len(orders)} live orders",
            details={"live_orders": len(orders)},
            duration_ms=duration
        )

    except Exception as e:
        duration = (time.time() - start) * 1000
        error_msg = str(e)

        if "403" in error_msg or "Cloudflare" in error_msg:
            status = Status.ERROR
            msg = "Cloudflare blocking API (run from different IP)"
        else:
            status = Status.ERROR
            msg = f"API error: {error_msg[:100]}"

        return CheckResult(
            name="CLOB API",
            status=status,
            message=msg,
            details={"error": error_msg[:200]},
            duration_ms=duration
        )


def check_usdc_balance() -> CheckResult:
    """Check USDC balance on Polymarket via EC2."""
    start = time.time()

    # Check balance via EC2 to avoid local Cloudflare issues
    code, out, err = run_ssh_command(
        """cd ~/polymarket_starter && source venv/bin/activate && python3 -c "
from py_clob_client.client import ClobClient
from dotenv import load_dotenv
import os
load_dotenv()
key = os.getenv('POLYMARKET_PRIVATE_KEY')
client = ClobClient('https://clob.polymarket.com', key=key, chain_id=137, signature_type=2)
client.set_api_creds(client.derive_api_key())
bal = client.get_balance_allowance()
print(float(bal.get('balance', 0)) / 1e6)
" 2>/dev/null""",
        timeout=30
    )
    duration = (time.time() - start) * 1000

    if code != 0:
        return CheckResult(
            name="USDC Balance",
            status=Status.UNKNOWN,
            message=f"Cannot check via EC2",
            details={"error": err[:100] if err else "unknown"},
            duration_ms=duration
        )

    try:
        balance = float(out.strip())

        if balance < 10:
            status = Status.WARNING
            msg = f"Low balance: ${balance:.2f}"
        else:
            status = Status.OK
            msg = f"Balance: ${balance:.2f}"

        return CheckResult(
            name="USDC Balance",
            status=status,
            message=msg,
            details={"balance_usd": balance},
            duration_ms=duration
        )

    except ValueError:
        return CheckResult(
            name="USDC Balance",
            status=Status.UNKNOWN,
            message=f"Cannot parse balance: {out[:30]}",
            details={"output": out[:100]},
            duration_ms=duration
        )


def check_active_markets() -> CheckResult:
    """Check for active 15-min markets."""
    start = time.time()

    try:
        import requests

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "application/json",
        }

        now = int(time.time())
        markets_found = []

        for asset in ["btc", "eth"]:
            # Check next few 15-min boundaries
            for i in range(3):
                boundary = ((now // 900) + i + 1) * 900
                secs_left = boundary - now
                slug = f"{asset}-updown-15m-{boundary}"

                try:
                    resp = requests.get(
                        f"https://gamma-api.polymarket.com/markets?slug={slug}",
                        headers=headers,
                        timeout=10
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        if data:
                            markets_found.append({
                                "slug": slug,
                                "seconds_left": secs_left,
                                "in_window": 120 <= secs_left <= 840
                            })
                except:
                    pass

        duration = (time.time() - start) * 1000

        in_window = [m for m in markets_found if m["in_window"]]

        if in_window:
            return CheckResult(
                name="Active Markets",
                status=Status.OK,
                message=f"{len(in_window)} markets in trading window",
                details={"markets": markets_found[:4], "in_window": len(in_window)},
                duration_ms=duration
            )
        elif markets_found:
            next_market = min(markets_found, key=lambda m: m["seconds_left"])
            return CheckResult(
                name="Active Markets",
                status=Status.OK,
                message=f"Next market in {next_market['seconds_left']}s",
                details={"markets": markets_found[:4], "in_window": 0},
                duration_ms=duration
            )
        else:
            return CheckResult(
                name="Active Markets",
                status=Status.WARNING,
                message="No markets found",
                details={},
                duration_ms=duration
            )

    except Exception as e:
        duration = (time.time() - start) * 1000
        return CheckResult(
            name="Active Markets",
            status=Status.WARNING,
            message=f"Cannot check: {str(e)[:50]}",
            details={"error": str(e)[:100]},
            duration_ms=duration
        )


def check_bot_state() -> CheckResult:
    """Check bot state file on EC2."""
    start = time.time()

    code, out, err = run_ssh_command(
        "cat ~/polymarket_starter/maker_bot_state.json 2>/dev/null || echo '{}'",
        timeout=15
    )
    duration = (time.time() - start) * 1000

    if code != 0:
        return CheckResult(
            name="Bot State",
            status=Status.WARNING,
            message="Cannot read state file",
            details={"error": err},
            duration_ms=duration
        )

    try:
        state = json.loads(out)

        details = {
            "total_pnl": state.get("total_pnl", 0),
            "daily_pnl": state.get("daily_pnl", 0),
            "orders_placed": state.get("orders_placed", 0),
            "orders_filled": state.get("orders_filled", 0),
            "active_orders": len(state.get("active_orders", {})),
            "consecutive_losses": state.get("consecutive_losses", 0)
        }

        daily_pnl = details["daily_pnl"]

        if daily_pnl < -15:
            status = Status.WARNING
            msg = f"Daily P&L: ${daily_pnl:.2f} (near limit)"
        elif daily_pnl < 0:
            status = Status.OK
            msg = f"Daily P&L: ${daily_pnl:.2f}"
        else:
            status = Status.OK
            msg = f"Daily P&L: ${daily_pnl:.2f}, {details['orders_placed']} orders"

        return CheckResult(
            name="Bot State",
            status=status,
            message=msg,
            details=details,
            duration_ms=duration
        )

    except json.JSONDecodeError:
        return CheckResult(
            name="Bot State",
            status=Status.OK,
            message="No state file (fresh start)",
            details={},
            duration_ms=duration
        )


def run_health_check(quick: bool = False) -> HealthReport:
    """Run all health checks in parallel."""
    checks_to_run = [
        check_ec2_connectivity,
        check_service_status,
        check_active_markets,
        check_bot_state,
    ]

    if not quick:
        checks_to_run.extend([
            check_recent_logs,
            check_clob_api,
            check_usdc_balance,
        ])

    results = []

    with ThreadPoolExecutor(max_workers=len(checks_to_run)) as executor:
        future_to_check = {executor.submit(check): check.__name__ for check in checks_to_run}

        for future in as_completed(future_to_check):
            check_name = future_to_check[future]
            try:
                result = future.result(timeout=60)
                results.append(result)
            except Exception as e:
                results.append(CheckResult(
                    name=check_name,
                    status=Status.ERROR,
                    message=f"Check failed: {str(e)[:50]}",
                    details={"error": str(e)}
                ))

    # Sort by status (errors first)
    status_order = {Status.ERROR: 0, Status.WARNING: 1, Status.UNKNOWN: 2, Status.OK: 3}
    results.sort(key=lambda r: status_order.get(r.status, 99))

    # Determine overall status
    if any(r.status == Status.ERROR for r in results):
        overall = Status.ERROR
    elif any(r.status == Status.WARNING for r in results):
        overall = Status.WARNING
    else:
        overall = Status.OK

    # Create summary
    ok_count = sum(1 for r in results if r.status == Status.OK)
    warn_count = sum(1 for r in results if r.status == Status.WARNING)
    err_count = sum(1 for r in results if r.status == Status.ERROR)

    summary = f"{ok_count} OK, {warn_count} warnings, {err_count} errors"

    return HealthReport(
        timestamp=datetime.now(timezone.utc),
        overall_status=overall,
        checks=results,
        summary=summary
    )


def print_report(report: HealthReport):
    """Print health report to console."""
    status_icons = {
        Status.OK: "✅",
        Status.WARNING: "⚠️ ",
        Status.ERROR: "❌",
        Status.UNKNOWN: "❓"
    }

    overall_icon = status_icons[report.overall_status]

    print("\n" + "=" * 60)
    print(f"  MAKER BOT HEALTH CHECK - {report.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 60)
    print(f"\n  Overall: {overall_icon} {report.overall_status.value} ({report.summary})\n")
    print("-" * 60)

    for check in report.checks:
        icon = status_icons[check.status]
        print(f"  {icon} {check.name}")
        print(f"     {check.message}")
        if check.details and check.status != Status.OK:
            for key, val in list(check.details.items())[:3]:
                if key not in ['error', 'recent_errors']:
                    print(f"     • {key}: {val}")
        print()

    print("=" * 60)

    if report.overall_status == Status.ERROR:
        print("\n  ⚠️  ACTION REQUIRED: Check errors above\n")
    elif report.overall_status == Status.WARNING:
        print("\n  ℹ️  Some warnings detected - monitor closely\n")
    else:
        print("\n  ✅ All systems operational\n")


def watch_mode(interval: int = 60):
    """Continuous monitoring mode."""
    print(f"Starting watch mode (checking every {interval}s). Press Ctrl+C to stop.\n")

    while True:
        try:
            report = run_health_check(quick=True)

            # Clear screen and print
            print("\033[2J\033[H", end="")  # Clear screen
            print_report(report)

            # Countdown
            for remaining in range(interval, 0, -1):
                print(f"\r  Next check in {remaining}s...  ", end="", flush=True)
                time.sleep(1)

        except KeyboardInterrupt:
            print("\n\nWatch mode stopped.")
            break


def main():
    parser = argparse.ArgumentParser(description="Maker Bot Health Check")
    parser.add_argument("--quick", action="store_true", help="Quick check (skip slow checks)")
    parser.add_argument("--watch", action="store_true", help="Continuous monitoring")
    parser.add_argument("--interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    args = parser.parse_args()

    if args.watch:
        watch_mode(args.interval)
    else:
        report = run_health_check(quick=args.quick)

        if args.json:
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print_report(report)

        # Exit code based on status
        sys.exit(0 if report.overall_status == Status.OK else 1)


if __name__ == "__main__":
    main()
