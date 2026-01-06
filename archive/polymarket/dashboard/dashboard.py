"""
Polymarket Arbitrage Bot Dashboard v1.1

Real-time monitoring dashboard for the Tokyo-deployed arbitrage bot.
Supports two modes:
1. SSH Mode (local): Connects via SSH to fetch data
2. HTTP Mode (cloud): Connects to status API endpoint

Deploy to Streamlit Cloud:
1. Push to GitHub
2. Connect repo on share.streamlit.io
3. Set BOT_API_URL secret to http://YOUR_SERVER:8502/status
4. Make sure the status API is running on the bot server

Usage (local):
    streamlit run dashboard.py

Usage (with API):
    BOT_API_URL=http://18.183.215.121:8502 streamlit run dashboard.py
"""
import streamlit as st
import pandas as pd
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
import subprocess
import os
import requests

# Page config
st.set_page_config(
    page_title="Polymarket Arbitrage Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .metric-card {
        background-color: #1e1e1e;
        border-radius: 10px;
        padding: 15px;
        margin: 5px 0;
    }
    .status-running {
        color: #00ff00;
        font-weight: bold;
    }
    .status-stopped {
        color: #ff4444;
        font-weight: bold;
    }
    .warning-box {
        background-color: #ff6b0020;
        border-left: 4px solid #ff6b00;
        padding: 10px;
        margin: 10px 0;
    }
    .error-box {
        background-color: #ff000020;
        border-left: 4px solid #ff0000;
        padding: 10px;
        margin: 10px 0;
    }
    .success-box {
        background-color: #00ff0020;
        border-left: 4px solid #00ff00;
        padding: 10px;
        margin: 10px 0;
    }
    div[data-testid="stMetricValue"] {
        font-size: 28px;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================================
# DATA FETCHING
# ============================================================================

def get_connection_mode():
    """Determine connection mode (HTTP API or SSH)."""
    # Check for API URL first (preferred for cloud deployment)
    try:
        api_url = st.secrets.get("BOT_API_URL", os.getenv("BOT_API_URL", ""))
    except:
        api_url = os.getenv("BOT_API_URL", "")

    if api_url:
        return "http", api_url

    # Fall back to SSH for local development
    return "ssh", None


def get_ssh_config():
    """Get SSH configuration from secrets or environment."""
    try:
        return {
            "host": st.secrets.get("SSH_HOST", os.getenv("SSH_HOST", "18.183.215.121")),
            "user": st.secrets.get("SSH_USER", os.getenv("SSH_USER", "ubuntu")),
            "key_path": st.secrets.get("SSH_KEY_PATH", os.getenv("SSH_KEY_PATH", "~/.ssh/polymarket-bot-key-tokyo.pem")),
            "remote_path": st.secrets.get("REMOTE_PATH", os.getenv("REMOTE_PATH", "/home/ubuntu/polymarket_starter"))
        }
    except:
        return {
            "host": os.getenv("SSH_HOST", "18.183.215.121"),
            "user": os.getenv("SSH_USER", "ubuntu"),
            "key_path": os.getenv("SSH_KEY_PATH", "~/.ssh/polymarket-bot-key-tokyo.pem"),
            "remote_path": os.getenv("REMOTE_PATH", "/home/ubuntu/polymarket_starter")
        }


@st.cache_data(ttl=10)
def fetch_bot_status_http(api_url):
    """Fetch bot status via HTTP API."""
    try:
        # Handle both http://host:port and http://host:port/status formats
        base_url = api_url.rstrip('/')
        if base_url.endswith('/status'):
            url = base_url
        else:
            url = f"{base_url}/status"
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot connect to bot API - is the status server running?"}
    except requests.exceptions.Timeout:
        return {"error": "API request timeout"}
    except Exception as e:
        return {"error": f"API error: {str(e)}"}


@st.cache_data(ttl=10)
def fetch_bot_status_ssh():
    """Fetch bot status from Tokyo server via SSH."""
    config = get_ssh_config()

    ssh_cmd = [
        "ssh", "-i", os.path.expanduser(config["key_path"]),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{config['user']}@{config['host']}",
        f"cd {config['remote_path']} && python3 -c 'import sys; sys.path.insert(0, \".\"); from src.api.status_api import StatusCollector; import json; c = StatusCollector(); print(json.dumps(c.get_full_status()))'"
    ]

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            output = result.stdout.strip()
            for line in output.split('\n'):
                if line.startswith('{'):
                    return json.loads(line)
            return json.loads(output)
        else:
            return {"error": f"SSH error: {result.stderr}"}
    except subprocess.TimeoutExpired:
        return {"error": "Connection timeout - bot server may be unreachable"}
    except json.JSONDecodeError as e:
        return {"error": f"Invalid JSON response: {e}"}
    except Exception as e:
        return {"error": f"Connection failed: {str(e)}"}


def fetch_bot_status():
    """Fetch bot status using appropriate connection method."""
    mode, api_url = get_connection_mode()
    if mode == "http":
        return fetch_bot_status_http(api_url)
    else:
        return fetch_bot_status_ssh()


@st.cache_data(ttl=30)
def fetch_recent_logs(lines=100):
    """Fetch recent bot logs."""
    config = get_ssh_config()

    ssh_cmd = [
        "ssh", "-i", os.path.expanduser(config["key_path"]),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{config['user']}@{config['host']}",
        f"tail -n {lines} {config['remote_path']}/data/arbitrage/bot_output.log 2>/dev/null || tail -n {lines} {config['remote_path']}/logs/arb_bot.log 2>/dev/null || echo 'No logs found'"
    ]

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=30)
        return result.stdout if result.returncode == 0 else result.stderr
    except Exception as e:
        return f"Error fetching logs: {e}"


def check_bot_process():
    """Check if bot process is running on server."""
    # Try HTTP API first (works on Streamlit Cloud)
    mode, api_url = get_connection_mode()
    if mode == "http":
        try:
            # Handle both /status and base URL formats
            base_url = api_url.rstrip('/').replace('/status', '')
            url = f"{base_url}/health"
            response = requests.get(url, timeout=10)
            if response.ok:
                data = response.json()
                return data.get("is_running", False)
        except Exception as e:
            # Log error for debugging
            print(f"Health check failed: {e}")
        return None

    # Fall back to SSH for local development
    config = get_ssh_config()
    ssh_cmd = [
        "ssh", "-i", os.path.expanduser(config["key_path"]),
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{config['user']}@{config['host']}",
        "pgrep -f 'run_arbitrage_bot' && echo 'RUNNING' || echo 'STOPPED'"
    ]

    try:
        result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=15)
        return "RUNNING" in result.stdout
    except:
        return None


# ============================================================================
# DASHBOARD SECTIONS
# ============================================================================

def render_header(status_data=None):
    """Render dashboard header."""
    st.title("🤖 Polymarket Arbitrage Bot")
    st.caption("Real-time monitoring dashboard | Tokyo Server")

    # Quick status indicator
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        # Use already-fetched status data - DO NOT make a separate health check
        # as it can give inconsistent results with the main status display
        is_running = None
        if status_data:
            health = status_data.get("health", {})
            is_running = health.get("is_running")

        if is_running is True:
            st.success("🟢 Bot Running")
        elif is_running is False:
            st.error("🔴 Bot Stopped")
        else:
            st.warning("⚠️ Status Unknown")

    with col2:
        st.caption(f"Last updated: {datetime.now().strftime('%H:%M:%S UTC')}")

    with col3:
        if st.button("🔄 Refresh"):
            st.cache_data.clear()
            st.rerun()


def render_trading_status(data):
    """Render trading status section."""
    st.subheader("📊 Trading Status")

    trading = data.get("trading", {})

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        mode = trading.get("mode", "unknown").upper()
        mode_color = "🟢" if mode == "LIVE" else "🟡"
        st.metric("Mode", f"{mode_color} {mode}")

    with col2:
        st.metric(
            "Win Rate",
            f"{trading.get('win_rate', 0):.1%}",
            help="Wins / Total completed trades"
        )

    with col3:
        pnl = trading.get("total_pnl", 0)
        st.metric(
            "Total P&L",
            f"${pnl:+.2f}",
            delta=f"${trading.get('daily_pnl', 0):+.2f} today"
        )

    with col4:
        roi = trading.get("roi_percent", 0)
        st.metric(
            "ROI",
            f"{roi:+.1f}%",
            help="Return on starting capital"
        )

    # Second row
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Trades Today", trading.get("trades_today", 0))

    with col2:
        st.metric(
            "W/L",
            f"{trading.get('wins', 0)}/{trading.get('losses', 0)}"
        )

    with col3:
        st.metric(
            "Bankroll",
            f"${trading.get('current_bankroll', 0):.2f}",
            delta=f"${trading.get('current_bankroll', 0) - trading.get('starting_bankroll', 0):+.2f}"
        )

    with col4:
        drawdown = trading.get("drawdown_percent", 0)
        st.metric(
            "Drawdown",
            f"{drawdown:.1f}%",
            delta_color="inverse"
        )


def render_circuit_breakers(data):
    """Render circuit breaker status."""
    st.subheader("🛡️ Circuit Breakers")

    cb = data.get("circuit_breaker", {})

    if cb.get("triggered"):
        st.error(f"⚠️ CIRCUIT BREAKER TRIGGERED: {cb.get('reason', 'Unknown')}")
    else:
        st.success("✅ All circuit breakers OK")

    col1, col2, col3 = st.columns(3)

    with col1:
        consec = cb.get("consecutive_losses", 0)
        max_consec = cb.get("max_consecutive_losses", 25)
        progress = min(consec / max_consec, 1.0)
        st.metric("Consecutive Losses", f"{consec} / {max_consec}")
        st.progress(progress)

    with col2:
        daily_loss = cb.get("daily_loss", 0)
        max_daily = cb.get("max_daily_loss", 125)
        progress = min(daily_loss / max_daily, 1.0) if max_daily > 0 else 0
        st.metric("Daily Loss", f"${daily_loss:.2f} / ${max_daily:.2f}")
        st.progress(progress)

    with col3:
        cooldown = cb.get("cooldown_remaining", 0)
        if cooldown > 0:
            st.warning(f"⏸️ Cooldown: {cooldown} windows")
        else:
            st.info("No cooldown active")


def render_market_status(data):
    """Render market connection status."""
    st.subheader("📡 Market Connections")

    market = data.get("market", {})

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Binance WebSocket**")
        if market.get("binance_connected"):
            st.success("🟢 Connected")
            st.caption(f"Latency: {market.get('binance_latency_ms', 0):.0f}ms")
        else:
            st.error("🔴 Disconnected")

        # Price display
        btc = market.get("btc_price", 0)
        eth = market.get("eth_price", 0)
        if btc > 0:
            st.metric("BTC", f"${btc:,.2f}")
        if eth > 0:
            st.metric("ETH", f"${eth:,.2f}")

    with col2:
        st.markdown("**Window Status**")
        window = market.get("active_window", "unknown")
        window_emoji = {
            "watching": "👀",
            "ready": "🎯",
            "executing": "⚡",
            "closed": "✅",
            "idle": "😴"
        }.get(window, "❓")

        st.info(f"{window_emoji} {window.upper()}")

        next_window = market.get("next_window_time", "")
        seconds_until = market.get("seconds_until_window", 0)

        if next_window:
            st.caption(f"Next: {next_window}")
            if seconds_until > 0:
                st.caption(f"In: {seconds_until}s")

        markets_found = market.get("markets_found", 0)
        st.metric("Markets Found", markets_found)


def render_health_status(data):
    """Render bot health status."""
    st.subheader("💚 Bot Health")

    health = data.get("health", {})

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if health.get("is_running"):
            st.success(f"🟢 Running (PID: {health.get('pid', '?')})")
        else:
            st.error("🔴 Not Running")

    with col2:
        uptime = health.get("uptime_seconds", 0)
        hours = int(uptime // 3600)
        minutes = int((uptime % 3600) // 60)
        st.metric("Uptime", f"{hours}h {minutes}m")

    with col3:
        st.metric("Memory", f"{health.get('memory_mb', 0):.1f} MB")

    with col4:
        st.metric("CPU", f"{health.get('cpu_percent', 0):.1f}%")

    # Error/warning counts
    col1, col2 = st.columns(2)
    with col1:
        errors = health.get("errors_last_hour", 0)
        if errors > 0:
            st.warning(f"⚠️ {errors} errors in last hour")
        else:
            st.success("✅ No recent errors")

    with col2:
        warnings = health.get("warnings_last_hour", 0)
        if warnings > 0:
            st.info(f"ℹ️ {warnings} warnings in last hour")


def render_recent_trades(data):
    """Render recent trades table."""
    st.subheader("📜 Recent Trades")

    trades = data.get("recent_trades", [])

    if not trades:
        st.info("No trades yet")
        return

    # Convert to DataFrame
    df = pd.DataFrame(trades)

    # Format columns
    if "timestamp" in df.columns:
        df["time"] = pd.to_datetime(df["timestamp"], unit='s').dt.strftime('%H:%M:%S')

    if "edge" in df.columns:
        df["edge"] = df["edge"].apply(lambda x: f"{x:.2%}")

    if "confidence" in df.columns:
        df["confidence"] = df["confidence"].apply(lambda x: f"{x:.1%}")

    if "pnl" in df.columns:
        df["pnl"] = df["pnl"].apply(lambda x: f"${x:+.2f}" if x is not None else "pending")

    if "outcome" in df.columns:
        df["outcome"] = df["outcome"].apply(lambda x: {
            "won": "✅ Won",
            "lost": "❌ Lost",
            "pending": "⏳ Pending"
        }.get(x, x))

    # Select and order columns
    display_cols = ["time", "action", "size", "price", "edge", "confidence", "outcome", "pnl"]
    display_cols = [c for c in display_cols if c in df.columns]

    st.dataframe(df[display_cols], use_container_width=True, hide_index=True)


def render_error_logs(data):
    """Render error log section."""
    st.subheader("🔴 Error Log")

    errors = data.get("errors", [])

    if not errors:
        st.success("No errors recorded")
        return

    # Filter by level
    error_level = st.selectbox("Filter", ["All", "Errors Only", "Warnings Only"])

    filtered = errors
    if error_level == "Errors Only":
        filtered = [e for e in errors if e.get("level") == "error"]
    elif error_level == "Warnings Only":
        filtered = [e for e in errors if e.get("level") == "warning"]

    for err in filtered[-20:]:  # Last 20
        level = err.get("level", "info")
        msg = err.get("message", "")

        if level == "error":
            st.error(f"🔴 {msg}")
        elif level == "warning":
            st.warning(f"🟡 {msg}")
        else:
            st.info(f"ℹ️ {msg}")


def render_performance_analysis(data):
    """Render performance analysis vs Account88888 pattern."""
    st.subheader("📈 Performance vs Plan")

    trading = data.get("trading", {})

    # Expected vs Actual
    st.markdown("**Account88888 Pattern Comparison**")

    col1, col2, col3 = st.columns(3)

    with col1:
        actual_wr = trading.get("win_rate", 0)
        expected_wr = 0.23  # Account88888 pattern
        diff = actual_wr - expected_wr
        st.metric(
            "Win Rate",
            f"{actual_wr:.1%}",
            delta=f"{diff:+.1%} vs expected 23%",
            delta_color="normal" if diff >= 0 else "inverse"
        )

    with col2:
        trades = trading.get("trades_total", 0)
        expected_daily = 200  # Account88888 does ~200/day
        st.metric(
            "Trade Volume",
            trades,
            help=f"Expected ~{expected_daily}/day"
        )

    with col3:
        # Calculate actual R:R if we have wins/losses
        wins = trading.get("wins", 0)
        losses = trading.get("losses", 0)
        if losses > 0 and wins > 0:
            # Rough R:R estimate
            pnl = trading.get("total_pnl", 0)
            avg_win = pnl / wins if pnl > 0 else 0
            avg_loss = abs(pnl) / losses if pnl < 0 else 0
            rr = avg_win / avg_loss if avg_loss > 0 else 0
            st.metric("R:R Ratio", f"{rr:.1f}:1", help="Target: 4:1")
        else:
            st.metric("R:R Ratio", "N/A", help="Need more trades")

    # Alerts for deviation
    st.markdown("**Alerts**")

    alerts = []

    # Win rate alert
    if trading.get("trades_total", 0) >= 20:  # Only after 20 trades
        if actual_wr < 0.15:
            alerts.append(("error", "Win rate significantly below expected (< 15%)"))
        elif actual_wr < 0.20:
            alerts.append(("warning", "Win rate below expected (< 20%)"))

    # Drawdown alert
    drawdown = trading.get("drawdown_percent", 0)
    if drawdown > 30:
        alerts.append(("error", f"High drawdown: {drawdown:.1f}%"))
    elif drawdown > 20:
        alerts.append(("warning", f"Elevated drawdown: {drawdown:.1f}%"))

    # Circuit breaker proximity
    cb = data.get("circuit_breaker", {})
    consec = cb.get("consecutive_losses", 0)
    if consec >= 20:
        alerts.append(("warning", f"Approaching loss limit: {consec}/25"))

    if not alerts:
        st.success("✅ All metrics within expected range")
    else:
        for level, msg in alerts:
            if level == "error":
                st.error(f"🚨 {msg}")
            else:
                st.warning(f"⚠️ {msg}")


def render_raw_logs():
    """Render raw log viewer."""
    st.subheader("📋 Raw Logs")

    with st.expander("View Recent Logs"):
        logs = fetch_recent_logs(200)
        st.code(logs, language="text")


def render_sidebar():
    """Render sidebar with controls and info."""
    with st.sidebar:
        st.header("⚙️ Controls")

        # Auto-refresh toggle
        auto_refresh = st.toggle("Auto-refresh (30s)", value=True)

        if auto_refresh:
            time.sleep(0.1)  # Small delay
            # This will cause periodic refresh via streamlit's built-in rerun
            st.empty()

        st.divider()

        # Server info
        st.header("🖥️ Server Info")
        config = get_ssh_config()
        st.caption(f"Host: {config['host']}")
        st.caption("Region: Tokyo (ap-northeast-1)")
        st.caption("Purpose: Low-latency arbitrage")

        st.divider()

        # Quick actions
        st.header("🚀 Quick Actions")

        if st.button("📊 Check Process"):
            is_running = check_bot_process()
            if is_running:
                st.success("Bot is running")
            else:
                st.error("Bot is NOT running")

        st.divider()

        # Strategy info
        st.header("📖 Strategy")
        st.markdown("""
        **Account88888 Pattern**
        - Win Rate: ~23%
        - R:R Target: 4:1
        - Position: $10-$50
        - 15-min windows
        - BTC/ETH Up/Down
        """)

        st.divider()
        st.caption("Dashboard v1.1")
        st.caption(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main dashboard entry point."""
    render_sidebar()

    # Fetch data first so we can use it in header
    with st.spinner("Fetching bot status..."):
        data = fetch_bot_status()

    # Now render header with the fetched data
    render_header(status_data=data)

    # Check for errors
    if "error" in data:
        st.error(f"⚠️ Could not fetch bot status: {data['error']}")
        st.info("The bot may be offline or there may be a connection issue.")

        # Still show raw logs if possible
        with st.expander("View Available Logs"):
            logs = fetch_recent_logs()
            st.code(logs)
        return

    # Main content in tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 Performance", "🔴 Errors", "📋 Logs"])

    with tab1:
        render_trading_status(data)
        st.divider()

        col1, col2 = st.columns(2)
        with col1:
            render_market_status(data)
        with col2:
            render_circuit_breakers(data)

        st.divider()
        render_health_status(data)

    with tab2:
        render_performance_analysis(data)
        st.divider()
        render_recent_trades(data)

    with tab3:
        render_error_logs(data)

    with tab4:
        render_raw_logs()

    # Auto-refresh
    if st.sidebar.toggle("Enable Auto-Refresh", value=False, key="auto_refresh_main"):
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
