"""
Status API for bot monitoring.

Provides endpoints for the Streamlit dashboard to fetch bot status.
Can run as a lightweight Flask server on the bot machine.
"""
import os
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
import threading

# Try to import Flask, but make it optional
try:
    from flask import Flask, jsonify
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False


@dataclass
class BotHealth:
    """Bot health status."""
    is_running: bool
    pid: Optional[int]
    uptime_seconds: float
    memory_mb: float
    cpu_percent: float
    last_heartbeat: float
    errors_last_hour: int
    warnings_last_hour: int


@dataclass
class TradingStatus:
    """Current trading status."""
    mode: str  # "live" or "paper"
    trades_today: int
    trades_total: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    daily_pnl: float
    current_bankroll: float
    starting_bankroll: float
    roi_percent: float
    drawdown_percent: float


@dataclass
class CircuitBreakerStatus:
    """Circuit breaker status."""
    triggered: bool
    reason: str
    consecutive_losses: int
    max_consecutive_losses: int
    daily_loss: float
    max_daily_loss: float
    cooldown_remaining: int


@dataclass
class MarketStatus:
    """Market connection status."""
    binance_connected: bool
    binance_latency_ms: float
    polymarket_connected: bool
    polymarket_latency_ms: float
    last_price_update: float
    btc_price: float
    eth_price: float
    markets_found: int
    active_window: str
    next_window_time: str
    seconds_until_window: int


@dataclass
class RecentTrade:
    """Recent trade record."""
    timestamp: float
    market: str
    action: str
    size: float
    price: float
    edge: float
    confidence: float
    pnl: Optional[float]
    outcome: str  # "pending", "won", "lost"


@dataclass
class ErrorLog:
    """Error log entry."""
    timestamp: float
    level: str  # "error", "warning", "info"
    message: str
    component: str


class StatusCollector:
    """Collects status from various sources."""

    def __init__(self, data_dir: str = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(__file__).parent.parent.parent / "data"

        self.arb_dir = self.data_dir / "arbitrage"
        self.trading_dir = self.data_dir / "trading"

        # Cache for expensive operations
        self._cache = {}
        self._cache_time = {}
        self._cache_ttl = 5  # seconds

    def _get_cached(self, key: str, fetch_func, ttl: int = None):
        """Get cached value or fetch new."""
        ttl = ttl or self._cache_ttl
        now = time.time()

        if key in self._cache and now - self._cache_time.get(key, 0) < ttl:
            return self._cache[key]

        value = fetch_func()
        self._cache[key] = value
        self._cache_time[key] = now
        return value

    def get_bot_health(self) -> BotHealth:
        """Get bot health status."""
        # Check if bot process is running
        try:
            result = subprocess.run(
                ["pgrep", "-f", "run_arbitrage_bot"],
                capture_output=True, text=True
            )
            pids = result.stdout.strip().split('\n')
            is_running = bool(pids[0]) if pids else False
            pid = int(pids[0]) if is_running else None
        except:
            is_running = False
            pid = None

        # Get memory and CPU if running
        memory_mb = 0.0
        cpu_percent = 0.0
        if pid:
            try:
                result = subprocess.run(
                    ["ps", "-o", "rss=,pcpu=", "-p", str(pid)],
                    capture_output=True, text=True
                )
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    memory_mb = float(parts[0]) / 1024  # KB to MB
                    cpu_percent = float(parts[1])
            except:
                pass

        # Get uptime from state file
        uptime = 0.0
        state = self._load_state_file()
        if state and "stats" in state:
            start_time = state["stats"].get("start_time", 0)
            if start_time:
                uptime = time.time() - start_time

        # Count errors in last hour
        errors, warnings = self._count_recent_log_issues()

        return BotHealth(
            is_running=is_running,
            pid=pid,
            uptime_seconds=uptime,
            memory_mb=memory_mb,
            cpu_percent=cpu_percent,
            last_heartbeat=time.time() if is_running else 0,
            errors_last_hour=errors,
            warnings_last_hour=warnings
        )

    def get_trading_status(self) -> TradingStatus:
        """Get trading status."""
        state = self._load_state_file()

        if not state:
            return TradingStatus(
                mode="unknown",
                trades_today=0,
                trades_total=0,
                wins=0,
                losses=0,
                win_rate=0.0,
                total_pnl=0.0,
                daily_pnl=0.0,
                current_bankroll=0.0,
                starting_bankroll=0.0,
                roi_percent=0.0,
                drawdown_percent=0.0
            )

        stats = state.get("stats", {})
        bankroll = state.get("bankroll", {})

        wins = stats.get("trades_won", 0)
        losses = stats.get("trades_lost", 0)
        total = wins + losses

        starting = bankroll.get("starting", 325.0)
        current = bankroll.get("current", starting)

        return TradingStatus(
            mode="live" if not stats.get("dry_run", True) else "paper",
            trades_today=state.get("trades_today", 0),
            trades_total=stats.get("trades_executed", 0),
            wins=wins,
            losses=losses,
            win_rate=wins / total if total > 0 else 0.0,
            total_pnl=stats.get("total_pnl", 0.0),
            daily_pnl=state.get("circuit_breaker", {}).get("daily_loss", 0.0) * -1,
            current_bankroll=current,
            starting_bankroll=starting,
            roi_percent=(current / starting - 1) * 100 if starting > 0 else 0.0,
            drawdown_percent=bankroll.get("drawdown", 0.0) * 100
        )

    def get_circuit_breaker_status(self) -> CircuitBreakerStatus:
        """Get circuit breaker status."""
        state = self._load_state_file()

        if not state:
            return CircuitBreakerStatus(
                triggered=False,
                reason="",
                consecutive_losses=0,
                max_consecutive_losses=25,
                daily_loss=0.0,
                max_daily_loss=125.0,
                cooldown_remaining=0
            )

        cb = state.get("circuit_breaker", {})

        return CircuitBreakerStatus(
            triggered=cb.get("triggered", False),
            reason=cb.get("reason", ""),
            consecutive_losses=cb.get("consecutive_losses", 0),
            max_consecutive_losses=25,
            daily_loss=cb.get("daily_loss", 0.0),
            max_daily_loss=125.0,
            cooldown_remaining=cb.get("cooldown_remaining", 0)
        )

    def get_market_status(self) -> MarketStatus:
        """Get market connection status."""
        # Read from log or state
        log_data = self._parse_recent_logs()

        return MarketStatus(
            binance_connected=log_data.get("binance_connected", False),
            binance_latency_ms=log_data.get("binance_latency", 0.0),
            polymarket_connected=log_data.get("polymarket_connected", False),
            polymarket_latency_ms=log_data.get("polymarket_latency", 0.0),
            last_price_update=log_data.get("last_price_update", 0.0),
            btc_price=log_data.get("btc_price", 0.0),
            eth_price=log_data.get("eth_price", 0.0),
            markets_found=log_data.get("markets_found", 0),
            active_window=log_data.get("active_window", "unknown"),
            next_window_time=log_data.get("next_window", ""),
            seconds_until_window=log_data.get("seconds_until", 0)
        )

    def get_recent_trades(self, limit: int = 20) -> List[RecentTrade]:
        """Get recent trades."""
        state = self._load_state_file()

        if not state:
            return []

        trades = state.get("trade_history", [])[-limit:]

        return [
            RecentTrade(
                timestamp=t.get("timestamp", 0),
                market=t.get("market_id", "")[:20] + "...",
                action=t.get("action", "unknown"),
                size=t.get("size", 0),
                price=t.get("price", 0),
                edge=t.get("edge", 0),
                confidence=t.get("confidence", 0),
                pnl=t.get("pnl"),
                outcome=t.get("outcome", "pending")
            )
            for t in trades
        ]

    def get_error_logs(self, limit: int = 50) -> List[ErrorLog]:
        """Get recent error logs."""
        logs = []

        # Parse log files for errors
        log_file = self.arb_dir / "bot_output.log"
        if log_file.exists():
            try:
                with open(log_file, 'r') as f:
                    lines = f.readlines()[-500:]  # Last 500 lines

                for line in lines:
                    if "error" in line.lower() or "Error" in line:
                        logs.append(ErrorLog(
                            timestamp=time.time(),
                            level="error",
                            message=line.strip()[:200],
                            component="bot"
                        ))
                    elif "warning" in line.lower() or "⚠️" in line:
                        logs.append(ErrorLog(
                            timestamp=time.time(),
                            level="warning",
                            message=line.strip()[:200],
                            component="bot"
                        ))
            except:
                pass

        return logs[-limit:]

    def get_full_status(self) -> Dict:
        """Get complete status."""
        return {
            "timestamp": time.time(),
            "health": asdict(self.get_bot_health()),
            "trading": asdict(self.get_trading_status()),
            "circuit_breaker": asdict(self.get_circuit_breaker_status()),
            "market": asdict(self.get_market_status()),
            "recent_trades": [asdict(t) for t in self.get_recent_trades()],
            "errors": [asdict(e) for e in self.get_error_logs(20)]
        }

    def _load_state_file(self) -> Optional[Dict]:
        """Load bot state file."""
        state_file = self.arb_dir / "bot_state.json"

        if not state_file.exists():
            return None

        try:
            with open(state_file, 'r') as f:
                return json.load(f)
        except:
            return None

    def _count_recent_log_issues(self) -> tuple:
        """Count errors and warnings in last hour."""
        errors = 0
        warnings = 0

        log_file = self.arb_dir / "bot_output.log"
        if log_file.exists():
            try:
                # Get file modification time
                mtime = log_file.stat().st_mtime
                if time.time() - mtime > 3600:  # Older than 1 hour
                    return 0, 0

                with open(log_file, 'r') as f:
                    for line in f:
                        if "error" in line.lower():
                            errors += 1
                        elif "warning" in line.lower() or "⚠️" in line:
                            warnings += 1
            except:
                pass

        return errors, warnings

    def _parse_recent_logs(self) -> Dict:
        """Parse recent logs for status info."""
        data = {
            "binance_connected": False,
            "polymarket_connected": False,
            "binance_latency": 0.0,
            "polymarket_latency": 0.0,
            "btc_price": 0.0,
            "eth_price": 0.0,
            "markets_found": 0,
            "active_window": "unknown",
            "next_window": "",
            "seconds_until": 0,
            "last_price_update": 0.0
        }

        log_file = self.arb_dir / "bot_output.log"
        if not log_file.exists():
            # Try alternative locations
            for alt_file in [
                Path("/home/ubuntu/polymarket_starter/logs/arb_bot.log"),
                Path("/home/ubuntu/polymarket_starter/data/arbitrage/bot_output.log")
            ]:
                if alt_file.exists():
                    log_file = alt_file
                    break

        if not log_file.exists():
            return data

        try:
            with open(log_file, 'r') as f:
                lines = f.readlines()[-200:]

            for line in reversed(lines):
                if "Connected to Binance" in line:
                    data["binance_connected"] = True
                # Parse BTC price (handles "💹 BTC: $91,349.88" format)
                if "BTC" in line and "$" in line:
                    try:
                        # Extract price after $ sign
                        price_str = line.split("$")[1].split()[0].replace(",", "")
                        price = float(price_str)
                        if price > 0:
                            data["btc_price"] = price
                            data["last_price_update"] = time.time()
                    except:
                        pass
                # Parse ETH price (handles "💹 ETH: $3,136.67" format)
                if "ETH" in line and "$" in line:
                    try:
                        price_str = line.split("$")[1].split()[0].replace(",", "")
                        price = float(price_str)
                        if price > 0:
                            data["eth_price"] = price
                    except:
                        pass
                if "Found" in line and "arbitrage-suitable markets" in line:
                    try:
                        data["markets_found"] = int(line.split("Found")[1].split()[0])
                    except:
                        pass
                if "Window event:" in line:
                    if "watching" in line:
                        data["active_window"] = "watching"
                    elif "ready" in line:
                        data["active_window"] = "ready"
                    elif "executing" in line:
                        data["active_window"] = "executing"
                    elif "closed" in line:
                        data["active_window"] = "closed"
                    elif "idle" in line:
                        data["active_window"] = "idle"
                if "Next window:" in line:
                    try:
                        data["next_window"] = line.split("Next window:")[1].strip().split()[0]
                    except:
                        pass
                if "Time until:" in line:
                    try:
                        time_str = line.split("Time until:")[1].strip()
                        if "s" in time_str:
                            data["seconds_until"] = int(time_str.replace("s", ""))
                    except:
                        pass
        except:
            pass

        return data


def create_status_server(host: str = "0.0.0.0", port: int = 8501):
    """Create Flask server for status API."""
    if not FLASK_AVAILABLE:
        raise ImportError("Flask is required. Install with: pip install flask")

    app = Flask(__name__)
    collector = StatusCollector()

    # Enable CORS for Streamlit Cloud
    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        return response

    @app.route("/status")
    def status():
        return jsonify(collector.get_full_status())

    @app.route("/health")
    def health():
        return jsonify(asdict(collector.get_bot_health()))

    @app.route("/trading")
    def trading():
        return jsonify(asdict(collector.get_trading_status()))

    @app.route("/trades")
    def trades():
        return jsonify([asdict(t) for t in collector.get_recent_trades(50)])

    @app.route("/errors")
    def errors():
        return jsonify([asdict(e) for e in collector.get_error_logs(100)])

    return app


if __name__ == "__main__":
    # Run as standalone server
    import argparse

    parser = argparse.ArgumentParser(description="Bot Status API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8502, help="Port to listen on")
    args = parser.parse_args()

    if FLASK_AVAILABLE:
        app = create_status_server()
        print(f"Starting status API server on {args.host}:{args.port}")
        app.run(host=args.host, port=args.port, debug=False)
    else:
        # Just print status
        collector = StatusCollector()
        print(json.dumps(collector.get_full_status(), indent=2))
