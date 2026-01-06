"""
Production System

Orchestrates all components for 24/7 operation:
- Wallet monitoring
- Signal processing
- Paper/live trading
- Risk management
- Alerting
- Health checks
"""
import os
import sys
import time
import signal
import threading
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path

from ..monitor import WalletMonitor, TradeAlert
from ..paper_trading import PaperTradingEngine
from ..alerts import AlertManager, AlertPriority, Alert
from ..risk.manager import RiskManager, RiskLevel
from ..config import DATA_DIR


@dataclass
class ProductionConfig:
    """Production configuration."""
    # Wallets to monitor
    target_wallets: List[str] = None
    
    # Mode
    live_trading: bool = False  # False = paper trading only
    
    # Capital
    initial_capital: float = 300.0
    
    # Monitoring
    poll_interval: int = 10  # seconds
    
    # Risk
    max_position_size: float = 50.0
    daily_loss_limit: float = 0.10
    
    # Alerts
    enable_desktop: bool = True
    webhook_url: str = ""
    
    # Health
    heartbeat_interval: int = 60  # seconds
    
    def __post_init__(self):
        if self.target_wallets is None:
            self.target_wallets = []


class HealthCheck:
    """Health monitoring for production system."""
    
    def __init__(self):
        self.last_heartbeat = 0
        self.start_time = int(time.time())
        self.errors: List[Dict] = []
        self.status = "starting"
        
        # Metrics
        self.trades_processed = 0
        self.signals_received = 0
        self.alerts_sent = 0
    
    def heartbeat(self):
        """Record heartbeat."""
        self.last_heartbeat = int(time.time())
        self.status = "healthy"
    
    def record_error(self, error: str, component: str = "unknown"):
        """Record an error."""
        self.errors.append({
            "timestamp": int(time.time()),
            "component": component,
            "error": error
        })
        # Keep last 100 errors
        self.errors = self.errors[-100:]
    
    def get_status(self) -> Dict:
        """Get health status."""
        now = int(time.time())
        uptime = now - self.start_time
        
        # Check if healthy
        is_healthy = (now - self.last_heartbeat) < 120  # 2 min tolerance
        
        return {
            "status": "healthy" if is_healthy else "unhealthy",
            "uptime_seconds": uptime,
            "uptime_human": f"{uptime // 3600}h {(uptime % 3600) // 60}m",
            "last_heartbeat": self.last_heartbeat,
            "seconds_since_heartbeat": now - self.last_heartbeat,
            "trades_processed": self.trades_processed,
            "signals_received": self.signals_received,
            "alerts_sent": self.alerts_sent,
            "recent_errors": len([e for e in self.errors if now - e["timestamp"] < 3600])
        }


class ProductionSystem:
    """
    Main production orchestrator.
    
    Brings together:
    - WalletMonitor (signal source)
    - RiskManager (protection)
    - PaperTradingEngine or LiveTrader (execution)
    - AlertManager (notifications)
    - HealthCheck (monitoring)
    
    Example:
        config = ProductionConfig(
            target_wallets=["Account88888"],
            initial_capital=300,
            enable_desktop=True
        )
        system = ProductionSystem(config)
        system.start()
    """
    
    def __init__(self, config: ProductionConfig):
        self.config = config
        
        # Components
        self.monitor: Optional[WalletMonitor] = None
        self.risk: Optional[RiskManager] = None
        self.paper_trader: Optional[PaperTradingEngine] = None
        self.alerts: Optional[AlertManager] = None
        self.health = HealthCheck()
        
        # State
        self._running = False
        self._shutdown_requested = False
        self._threads: List[threading.Thread] = []
        
        # Callbacks
        self._on_signal_callbacks: List[Callable] = []
        
        # Initialize components
        self._setup()
    
    def _setup(self):
        """Initialize all components."""
        print("\n🔧 Initializing Production System...")
        
        # Risk Manager
        self.risk = RiskManager(capital=self.config.initial_capital)
        print(f"   ✓ Risk Manager (capital: ${self.config.initial_capital})")
        
        # Alert Manager
        self.alerts = AlertManager()
        self.alerts.enable_console()
        if self.config.enable_desktop:
            self.alerts.enable_desktop()
        if self.config.webhook_url:
            self.alerts.add_webhook(self.config.webhook_url)
        print(f"   ✓ Alert Manager (desktop: {self.config.enable_desktop})")
        
        # Paper Trading Engine
        self.paper_trader = PaperTradingEngine(
            initial_capital=self.config.initial_capital,
            name="production"
        )
        print(f"   ✓ Paper Trader")
        
        # Wallet Monitor
        self.monitor = WalletMonitor(poll_interval=self.config.poll_interval)
        for wallet in self.config.target_wallets:
            if wallet.startswith("0x"):
                self.monitor.add_wallet(wallet)
            else:
                self.monitor.add_wallet_by_name(wallet)
        print(f"   ✓ Wallet Monitor ({len(self.monitor.wallets)} wallets)")
        
        # Wire up signal handler
        self.monitor.on_trade(self._on_wallet_trade)
        
        print("   ✓ Components wired\n")
    
    def _on_wallet_trade(self, trade: TradeAlert):
        """Handle incoming trade signal from monitored wallet."""
        self.health.signals_received += 1
        
        # Log the signal
        print(f"\n📡 Signal: {trade}")
        
        # Check if we can trade
        can_trade, reason = self.risk.can_trade()
        
        if not can_trade:
            self.alerts.send(
                title="Signal Blocked",
                message=f"Cannot trade: {reason}",
                priority=AlertPriority.NORMAL,
                category="risk"
            )
            return
        
        # Calculate position size
        position_size = self.risk.calculate_position_size(signal_strength=0.7)
        
        # Scale the signal's trade to our size
        original_value = trade.value_usd
        if original_value > 0:
            scale_factor = position_size / original_value
        else:
            scale_factor = 1.0
        
        # Cap scale factor
        scale_factor = min(scale_factor, 1.0)
        
        # Approve the trade
        approved, approval_reason = self.risk.approve_trade(
            size=position_size,
            market=trade.market,
            side=trade.side,
            price=trade.price
        )
        
        if not approved:
            print(f"   ⚠️ Trade not approved: {approval_reason}")
            return
        
        # Execute paper trade
        if self.config.live_trading:
            # TODO: Live trading integration
            self.alerts.send(
                title="Live Trading Not Implemented",
                message="Falling back to paper trade",
                priority=AlertPriority.HIGH
            )
        
        # Paper trade
        paper_trade = self.paper_trader.clone_trade(
            wallet_trade={
                "side": trade.side,
                "size": trade.trade_data.get("size", 0),
                "price": trade.price,
                "outcome": trade.trade_data.get("outcome", "yes"),
                "market": trade.market,
                "conditionId": trade.market,
                "wallet": trade.wallet_address
            },
            scale_factor=scale_factor,
            max_position=position_size
        )
        
        if paper_trade:
            self.health.trades_processed += 1
            
            # Record in risk manager
            self.risk.record_trade_open(
                trade_id=paper_trade.id,
                market=trade.market,
                side=trade.side,
                size=paper_trade.value,
                price=trade.price
            )
            
            # Send alert
            self.alerts.trade_alert(
                wallet=f"CLONE:{trade.wallet_name or 'target'}",
                side=trade.side,
                value=paper_trade.value,
                market=trade.market[:30],
                price=trade.price,
                priority=AlertPriority.HIGH
            )
            self.health.alerts_sent += 1
        
        # Call custom callbacks
        for callback in self._on_signal_callbacks:
            try:
                callback(trade, paper_trade)
            except Exception as e:
                self.health.record_error(str(e), "callback")
    
    def on_signal(self, callback: Callable):
        """Register callback for trade signals."""
        self._on_signal_callbacks.append(callback)
        return self
    
    def _heartbeat_loop(self):
        """Background heartbeat thread."""
        while self._running and not self._shutdown_requested:
            self.health.heartbeat()
            
            # Check for stale positions
            stale = self.risk.check_stale_positions()
            if stale:
                self.alerts.send(
                    title="Stale Positions",
                    message=f"{len(stale)} position(s) exceeded max age",
                    priority=AlertPriority.HIGH
                )
            
            # Reset daily stats at midnight
            self.risk.reset_daily()
            
            time.sleep(self.config.heartbeat_interval)
    
    def _status_loop(self):
        """Periodic status output."""
        while self._running and not self._shutdown_requested:
            # Print status every 5 minutes
            time.sleep(300)
            
            if self._running:
                self._print_status()
    
    def _print_status(self):
        """Print current system status."""
        health = self.health.get_status()
        risk = self.risk.get_status()
        
        print(f"\n{'─'*50}")
        print(f"📊 STATUS UPDATE ({datetime.now().strftime('%H:%M:%S')})")
        print(f"{'─'*50}")
        print(f"Uptime: {health['uptime_human']}")
        print(f"Signals: {health['signals_received']} | Trades: {health['trades_processed']}")
        print(f"Risk Level: {risk['risk_level'].upper()}")
        print(f"Capital: ${risk['capital']['current']:.2f} ({risk['capital']['pnl_pct']:+.1%})")
        print(f"Today: {risk['today']['trades']} trades, ${risk['today']['pnl']:.2f} P&L")
        print(f"{'─'*50}\n")
    
    def start(self, blocking: bool = True):
        """
        Start the production system.
        
        Args:
            blocking: If True, blocks main thread. If False, runs in background.
        """
        if not self.config.target_wallets:
            print("⚠️ No target wallets configured!")
            return
        
        self._running = True
        self._shutdown_requested = False
        
        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Send startup alert
        self.alerts.system_alert(
            f"Production system starting with {len(self.config.target_wallets)} wallet(s)",
            priority=AlertPriority.NORMAL
        )
        
        # Start heartbeat thread
        heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        self._threads.append(heartbeat_thread)
        
        # Start status thread
        status_thread = threading.Thread(target=self._status_loop, daemon=True)
        status_thread.start()
        self._threads.append(status_thread)
        
        print("\n" + "="*50)
        print("🚀 PRODUCTION SYSTEM STARTED")
        print("="*50)
        print(f"Mode: {'LIVE' if self.config.live_trading else 'PAPER'} Trading")
        print(f"Capital: ${self.config.initial_capital}")
        print(f"Wallets: {len(self.config.target_wallets)}")
        print(f"Poll Interval: {self.config.poll_interval}s")
        print("="*50)
        print("\nPress Ctrl+C to stop\n")
        
        # Start monitoring (this blocks if blocking=True)
        try:
            self.monitor.start(blocking=blocking)
        except Exception as e:
            self.health.record_error(str(e), "monitor")
            self.alerts.system_alert(f"Monitor error: {e}", AlertPriority.CRITICAL)
    
    def stop(self):
        """Stop the production system."""
        print("\n\n⏹ Shutting down...")
        self._shutdown_requested = True
        self._running = False
        
        # Stop monitor
        if self.monitor:
            self.monitor.stop()
        
        # Wait for threads
        for thread in self._threads:
            thread.join(timeout=2)
        
        # Send shutdown alert
        self.alerts.system_alert(
            "Production system stopped",
            priority=AlertPriority.NORMAL
        )
        
        # Print final status
        self._print_status()
        self.risk.print_status()
        self.paper_trader.print_summary()
        
        print("\n✓ Shutdown complete")
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        self.stop()
        sys.exit(0)
    
    def get_status(self) -> Dict:
        """Get complete system status."""
        return {
            "health": self.health.get_status(),
            "risk": self.risk.get_status(),
            "paper_portfolio": self.paper_trader.get_portfolio_summary(),
            "monitor": self.monitor.get_status() if self.monitor else {}
        }


def create_production_system(
    wallets: List[str],
    capital: float = 300.0,
    enable_desktop: bool = True,
    webhook_url: str = "",
    poll_interval: int = 10
) -> ProductionSystem:
    """
    Factory function to create production system.
    
    Example:
        system = create_production_system(
            wallets=["Account88888", "0x123..."],
            capital=300,
            enable_desktop=True
        )
        system.start()
    """
    config = ProductionConfig(
        target_wallets=wallets,
        initial_capital=capital,
        enable_desktop=enable_desktop,
        webhook_url=webhook_url,
        poll_interval=poll_interval
    )
    
    return ProductionSystem(config)
