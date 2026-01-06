"""
Alert System

Sends notifications when important events occur (trades, price moves, etc).
Supports multiple notification channels: console, desktop, webhook.
"""
import os
import json
import time
import subprocess
import threading
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from urllib.request import Request, urlopen

from ..config import DATA_DIR


class AlertChannel(Enum):
    """Notification channels."""
    CONSOLE = "console"
    DESKTOP = "desktop"
    WEBHOOK = "webhook"
    LOG_FILE = "log_file"


class AlertPriority(Enum):
    """Alert priority levels."""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Alert:
    """An alert/notification."""
    title: str
    message: str
    priority: AlertPriority = AlertPriority.NORMAL
    
    # Metadata
    timestamp: int = field(default_factory=lambda: int(time.time()))
    source: str = ""
    category: str = ""  # "trade", "price", "system", etc.
    data: Dict = field(default_factory=dict)
    
    # State
    sent_via: List[str] = field(default_factory=list)
    acknowledged: bool = False
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "title": self.title,
            "message": self.message,
            "priority": self.priority.name,
            "timestamp": self.timestamp,
            "source": self.source,
            "category": self.category,
            "data": self.data,
            "sent_via": self.sent_via,
            "acknowledged": self.acknowledged
        }
    
    def __str__(self) -> str:
        dt = datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")
        return f"[{dt}] [{self.priority.name}] {self.title}: {self.message}"


class AlertManager:
    """
    Central alert management system.
    
    Features:
    - Multiple notification channels
    - Priority-based filtering
    - Rate limiting to prevent spam
    - Alert history
    - Webhook integration (Discord, Slack, Telegram bots)
    
    Example:
        alerts = AlertManager()
        alerts.enable_desktop()
        alerts.add_webhook("https://discord.com/api/webhooks/...")
        alerts.send("Trade Alert", "Account88888 bought $50 YES")
    """
    
    def __init__(self):
        # Enabled channels
        self._channels: Dict[AlertChannel, bool] = {
            AlertChannel.CONSOLE: True,
            AlertChannel.DESKTOP: False,
            AlertChannel.WEBHOOK: False,
            AlertChannel.LOG_FILE: True
        }
        
        # Webhook URLs
        self._webhooks: List[Dict] = []
        
        # Rate limiting
        self._rate_limit_window = 60  # seconds
        self._rate_limit_max = 10  # max alerts per window
        self._recent_alerts: List[int] = []
        
        # Minimum priority for each channel
        self._min_priority: Dict[AlertChannel, AlertPriority] = {
            AlertChannel.CONSOLE: AlertPriority.LOW,
            AlertChannel.DESKTOP: AlertPriority.NORMAL,
            AlertChannel.WEBHOOK: AlertPriority.HIGH,
            AlertChannel.LOG_FILE: AlertPriority.LOW
        }
        
        # History
        self._history: List[Alert] = []
        self._max_history = 1000
        
        # Log file
        self._log_dir = DATA_DIR / "alerts"
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_file = self._log_dir / f"alerts_{datetime.now().strftime('%Y%m%d')}.log"
        
        # Custom handlers
        self._custom_handlers: List[Callable[[Alert], None]] = []
    
    def enable_channel(self, channel: AlertChannel, min_priority: AlertPriority = None):
        """Enable a notification channel."""
        self._channels[channel] = True
        if min_priority:
            self._min_priority[channel] = min_priority
        return self
    
    def disable_channel(self, channel: AlertChannel):
        """Disable a notification channel."""
        self._channels[channel] = False
        return self
    
    def enable_desktop(self, min_priority: AlertPriority = AlertPriority.NORMAL):
        """Enable desktop notifications (macOS)."""
        return self.enable_channel(AlertChannel.DESKTOP, min_priority)
    
    def enable_console(self, min_priority: AlertPriority = AlertPriority.LOW):
        """Enable console output."""
        return self.enable_channel(AlertChannel.CONSOLE, min_priority)
    
    def add_webhook(
        self,
        url: str,
        name: str = "webhook",
        format: str = "discord",
        min_priority: AlertPriority = AlertPriority.HIGH
    ):
        """
        Add a webhook for notifications.
        
        Args:
            url: Webhook URL
            name: Identifier for this webhook
            format: "discord", "slack", or "generic"
            min_priority: Minimum priority to trigger webhook
        """
        self._webhooks.append({
            "url": url,
            "name": name,
            "format": format,
            "min_priority": min_priority
        })
        self._channels[AlertChannel.WEBHOOK] = True
        return self
    
    def add_handler(self, handler: Callable[[Alert], None]):
        """Add custom alert handler."""
        self._custom_handlers.append(handler)
        return self
    
    def set_rate_limit(self, max_alerts: int, window_seconds: int = 60):
        """Set rate limiting parameters."""
        self._rate_limit_max = max_alerts
        self._rate_limit_window = window_seconds
        return self
    
    def _is_rate_limited(self) -> bool:
        """Check if we're rate limited."""
        now = int(time.time())
        cutoff = now - self._rate_limit_window
        
        # Remove old timestamps
        self._recent_alerts = [ts for ts in self._recent_alerts if ts > cutoff]
        
        return len(self._recent_alerts) >= self._rate_limit_max
    
    def _should_send(self, alert: Alert, channel: AlertChannel) -> bool:
        """Check if alert should be sent via channel."""
        if not self._channels.get(channel, False):
            return False
        
        min_priority = self._min_priority.get(channel, AlertPriority.LOW)
        return alert.priority.value >= min_priority.value
    
    def _send_console(self, alert: Alert):
        """Send to console."""
        emoji_map = {
            AlertPriority.LOW: "ℹ️",
            AlertPriority.NORMAL: "📢",
            AlertPriority.HIGH: "⚠️",
            AlertPriority.CRITICAL: "🚨"
        }
        emoji = emoji_map.get(alert.priority, "📢")
        print(f"\n{emoji} {alert}")
    
    def _send_desktop(self, alert: Alert):
        """Send desktop notification (macOS)."""
        try:
            # Use osascript for macOS notifications
            script = f'''
            display notification "{alert.message}" with title "{alert.title}"
            '''
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5
            )
            alert.sent_via.append("desktop")
        except Exception as e:
            print(f"Desktop notification error: {e}")
    
    def _send_webhook(self, alert: Alert, webhook: Dict):
        """Send to webhook."""
        try:
            url = webhook["url"]
            format_type = webhook.get("format", "generic")
            
            # Format payload based on webhook type
            if format_type == "discord":
                payload = {
                    "content": None,
                    "embeds": [{
                        "title": alert.title,
                        "description": alert.message,
                        "color": self._get_discord_color(alert.priority),
                        "timestamp": datetime.utcfromtimestamp(alert.timestamp).isoformat(),
                        "footer": {"text": alert.source or "Polymarket Alert"}
                    }]
                }
            elif format_type == "slack":
                payload = {
                    "text": f"*{alert.title}*\n{alert.message}",
                    "attachments": [{
                        "color": self._get_slack_color(alert.priority),
                        "text": alert.message,
                        "footer": alert.source or "Polymarket Alert"
                    }]
                }
            else:  # generic
                payload = alert.to_dict()
            
            # Send request
            data = json.dumps(payload).encode("utf-8")
            req = Request(url, data=data, headers={"Content-Type": "application/json"})
            
            with urlopen(req, timeout=10) as response:
                if response.status < 300:
                    alert.sent_via.append(webhook["name"])
        
        except Exception as e:
            print(f"Webhook error ({webhook['name']}): {e}")
    
    def _get_discord_color(self, priority: AlertPriority) -> int:
        """Get Discord embed color based on priority."""
        colors = {
            AlertPriority.LOW: 0x3498db,      # Blue
            AlertPriority.NORMAL: 0x2ecc71,   # Green
            AlertPriority.HIGH: 0xf1c40f,     # Yellow
            AlertPriority.CRITICAL: 0xe74c3c  # Red
        }
        return colors.get(priority, 0x95a5a6)
    
    def _get_slack_color(self, priority: AlertPriority) -> str:
        """Get Slack attachment color based on priority."""
        colors = {
            AlertPriority.LOW: "#3498db",
            AlertPriority.NORMAL: "#2ecc71",
            AlertPriority.HIGH: "#f1c40f",
            AlertPriority.CRITICAL: "#e74c3c"
        }
        return colors.get(priority, "#95a5a6")
    
    def _write_log(self, alert: Alert):
        """Write alert to log file."""
        try:
            log_line = f"{datetime.fromtimestamp(alert.timestamp).isoformat()} | " \
                       f"{alert.priority.name:8} | {alert.category:10} | " \
                       f"{alert.title}: {alert.message}\n"
            
            with open(self._log_file, "a") as f:
                f.write(log_line)
        except Exception as e:
            print(f"Log file error: {e}")
    
    def send(
        self,
        title: str,
        message: str,
        priority: AlertPriority = AlertPriority.NORMAL,
        category: str = "general",
        source: str = "",
        data: Dict = None
    ) -> Optional[Alert]:
        """
        Send an alert through enabled channels.
        
        Args:
            title: Alert title
            message: Alert message
            priority: Alert priority
            category: Category (trade, price, system, etc.)
            source: Source of the alert
            data: Additional data
        
        Returns:
            Alert object if sent, None if rate limited
        """
        # Check rate limit
        if self._is_rate_limited():
            return None
        
        # Create alert
        alert = Alert(
            title=title,
            message=message,
            priority=priority,
            category=category,
            source=source,
            data=data or {}
        )
        
        # Record for rate limiting
        self._recent_alerts.append(alert.timestamp)
        
        # Send to console
        if self._should_send(alert, AlertChannel.CONSOLE):
            self._send_console(alert)
            alert.sent_via.append("console")
        
        # Send desktop notification
        if self._should_send(alert, AlertChannel.DESKTOP):
            threading.Thread(
                target=self._send_desktop,
                args=(alert,),
                daemon=True
            ).start()
        
        # Send to webhooks
        if self._channels.get(AlertChannel.WEBHOOK):
            for webhook in self._webhooks:
                if alert.priority.value >= webhook["min_priority"].value:
                    threading.Thread(
                        target=self._send_webhook,
                        args=(alert, webhook),
                        daemon=True
                    ).start()
        
        # Write to log file
        if self._should_send(alert, AlertChannel.LOG_FILE):
            self._write_log(alert)
            alert.sent_via.append("log_file")
        
        # Call custom handlers
        for handler in self._custom_handlers:
            try:
                handler(alert)
            except Exception as e:
                print(f"Handler error: {e}")
        
        # Add to history
        self._history.append(alert)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        return alert
    
    def trade_alert(
        self,
        wallet: str,
        side: str,
        value: float,
        market: str = "",
        price: float = 0.0,
        priority: AlertPriority = AlertPriority.NORMAL
    ) -> Optional[Alert]:
        """
        Send a trade alert.
        
        Args:
            wallet: Wallet name or address
            side: "buy" or "sell"
            value: Trade value in USD
            market: Market name
            price: Trade price
        """
        action = "bought" if side.lower() == "buy" else "sold"
        message = f"{wallet} {action} ${value:.2f}"
        if market:
            message += f" in {market[:50]}"
        if price > 0:
            message += f" @ {price:.4f}"
        
        return self.send(
            title="Trade Alert",
            message=message,
            priority=priority,
            category="trade",
            source=wallet,
            data={
                "wallet": wallet,
                "side": side,
                "value": value,
                "market": market,
                "price": price
            }
        )
    
    def price_alert(
        self,
        market: str,
        current_price: float,
        threshold_price: float,
        direction: str = "above"
    ) -> Optional[Alert]:
        """Send a price threshold alert."""
        message = f"{market} is now {direction} ${threshold_price:.4f} (current: ${current_price:.4f})"
        
        return self.send(
            title="Price Alert",
            message=message,
            priority=AlertPriority.HIGH,
            category="price",
            data={
                "market": market,
                "current_price": current_price,
                "threshold_price": threshold_price,
                "direction": direction
            }
        )
    
    def system_alert(
        self,
        message: str,
        priority: AlertPriority = AlertPriority.NORMAL
    ) -> Optional[Alert]:
        """Send a system alert."""
        return self.send(
            title="System",
            message=message,
            priority=priority,
            category="system"
        )
    
    def get_history(
        self,
        limit: int = 100,
        category: str = None,
        min_priority: AlertPriority = None
    ) -> List[Alert]:
        """Get alert history."""
        result = self._history[-limit:]
        
        if category:
            result = [a for a in result if a.category == category]
        
        if min_priority:
            result = [a for a in result if a.priority.value >= min_priority.value]
        
        return result
    
    def clear_history(self):
        """Clear alert history."""
        self._history = []


# Global alert manager instance
alerts = AlertManager()


def setup_alerts(
    desktop: bool = True,
    webhook_url: str = None,
    webhook_format: str = "discord"
) -> AlertManager:
    """
    Quick setup for alert system.
    
    Example:
        setup_alerts(desktop=True, webhook_url="https://discord.com/...")
    """
    if desktop:
        alerts.enable_desktop()
    
    if webhook_url:
        alerts.add_webhook(webhook_url, format=webhook_format)
    
    return alerts


def send_alert(title: str, message: str, priority: str = "NORMAL"):
    """Quick function to send an alert."""
    p = AlertPriority[priority.upper()] if isinstance(priority, str) else priority
    return alerts.send(title, message, priority=p)
