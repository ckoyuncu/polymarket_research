"""
Daily P&L Reporting

Automated daily summaries of trading performance.
Can be scheduled to run at end of day.
"""
import json
import time
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path

from ..config import DATA_DIR
from ..alerts import AlertManager, AlertPriority


@dataclass
class DailySummary:
    """Daily trading summary."""
    date: str  # YYYY-MM-DD
    
    # P&L
    starting_capital: float = 0.0
    ending_capital: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    total_pnl: float = 0.0
    pnl_percent: float = 0.0
    
    # Trading activity
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    # Volume
    total_volume: float = 0.0
    fees_paid: float = 0.0
    
    # Risk metrics
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # Positions
    open_positions: int = 0
    closed_positions: int = 0
    
    # Wallets tracked
    wallets_monitored: int = 0
    wallets_with_activity: int = 0
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "date": self.date,
            "starting_capital": self.starting_capital,
            "ending_capital": self.ending_capital,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "total_pnl": self.total_pnl,
            "pnl_percent": self.pnl_percent,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_volume": self.total_volume,
            "fees_paid": self.fees_paid,
            "max_drawdown": self.max_drawdown,
            "largest_win": self.largest_win,
            "largest_loss": self.largest_loss,
            "open_positions": self.open_positions,
            "closed_positions": self.closed_positions,
            "wallets_monitored": self.wallets_monitored,
            "wallets_with_activity": self.wallets_with_activity
        }


class DailyReporter:
    """
    Generates and sends daily trading summaries.
    
    Example:
        reporter = DailyReporter()
        
        # Generate summary for today
        summary = reporter.generate_summary()
        print(f"Today's P&L: ${summary.total_pnl:.2f}")
        
        # Send via alerts
        reporter.send_daily_alert()
    """
    
    def __init__(self, alerts: AlertManager = None):
        self.alerts = alerts or AlertManager()
        self.data_dir = DATA_DIR / "reports"
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_summary(self, date: str = None) -> DailySummary:
        """
        Generate summary for a given date.
        
        Args:
            date: Date in YYYY-MM-DD format. Defaults to today.
        
        Returns:
            DailySummary object
        """
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        summary = DailySummary(date=date)
        
        # Load paper trading data
        self._load_paper_trades(summary, date)
        
        # Load position data
        self._load_positions(summary, date)
        
        # Load wallet monitoring data
        self._load_wallet_activity(summary, date)
        
        # Calculate derived metrics
        self._calculate_metrics(summary)
        
        # Save summary
        self._save_summary(summary)
        
        return summary
    
    def _load_paper_trades(self, summary: DailySummary, date: str):
        """Load paper trades for the date."""
        try:
            # Try loading from paper trading file
            paper_file = DATA_DIR / "paper_trading" / "paper_trades.json"
            
            if paper_file.exists():
                with open(paper_file, 'r') as f:
                    trades = json.load(f)
                
                # Filter trades for this date
                date_start = datetime.strptime(date, "%Y-%m-%d")
                date_end = date_start + timedelta(days=1)
                start_ts = int(date_start.timestamp())
                end_ts = int(date_end.timestamp())
                
                day_trades = [
                    t for t in trades
                    if start_ts <= t.get("timestamp", 0) < end_ts
                ]
                
                summary.total_trades = len(day_trades)
                
                # Calculate P&L from trades
                for trade in day_trades:
                    pnl = trade.get("pnl", 0)
                    size = trade.get("size", 0)
                    price = trade.get("price", 0)
                    
                    summary.total_volume += size * price
                    
                    if trade.get("status") == "closed":
                        summary.realized_pnl += pnl
                        if pnl > 0:
                            summary.winning_trades += 1
                            summary.largest_win = max(summary.largest_win, pnl)
                        elif pnl < 0:
                            summary.losing_trades += 1
                            summary.largest_loss = min(summary.largest_loss, pnl)
                    else:
                        summary.unrealized_pnl += pnl
        
        except Exception as e:
            print(f"Error loading paper trades: {e}")
    
    def _load_positions(self, summary: DailySummary, date: str):
        """Load position data."""
        try:
            pos_file = DATA_DIR / "trading" / "positions.json"
            
            if pos_file.exists():
                with open(pos_file, 'r') as f:
                    positions = json.load(f)
                
                for pos in positions:
                    status = pos.get("status", "")
                    if status == "open":
                        summary.open_positions += 1
                    elif status == "closed":
                        summary.closed_positions += 1
        
        except Exception as e:
            print(f"Error loading positions: {e}")
    
    def _load_wallet_activity(self, summary: DailySummary, date: str):
        """Load wallet monitoring activity."""
        try:
            # From alerts log
            alert_file = DATA_DIR / "alerts" / f"alerts_{date.replace('-', '')}.log"
            
            if alert_file.exists():
                with open(alert_file, 'r') as f:
                    lines = f.readlines()
                
                # Count unique wallets with trade alerts
                wallets_active = set()
                for line in lines:
                    if "trade" in line.lower():
                        # Extract wallet from line (simplified)
                        for word in line.split():
                            if word.startswith("0x") or word.startswith("Account"):
                                wallets_active.add(word)
                
                summary.wallets_with_activity = len(wallets_active)
            
            # Count monitored wallets
            wallet_file = DATA_DIR / "wallets" / "monitored.json"
            if wallet_file.exists():
                with open(wallet_file, 'r') as f:
                    wallets = json.load(f)
                summary.wallets_monitored = len(wallets) if isinstance(wallets, list) else 0
        
        except Exception as e:
            print(f"Error loading wallet activity: {e}")
    
    def _calculate_metrics(self, summary: DailySummary):
        """Calculate derived metrics."""
        # Total P&L
        summary.total_pnl = summary.realized_pnl + summary.unrealized_pnl
        
        # P&L percent
        if summary.starting_capital > 0:
            summary.pnl_percent = (summary.total_pnl / summary.starting_capital) * 100
        
        # Win rate
        total_closed = summary.winning_trades + summary.losing_trades
        if total_closed > 0:
            summary.win_rate = (summary.winning_trades / total_closed) * 100
        
        # Estimate fees (0.5% of volume)
        summary.fees_paid = summary.total_volume * 0.005
    
    def _save_summary(self, summary: DailySummary):
        """Save summary to file."""
        filepath = self.data_dir / f"daily_{summary.date}.json"
        
        with open(filepath, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2)
    
    def format_summary(self, summary: DailySummary) -> str:
        """Format summary as readable text."""
        pnl_emoji = "📈" if summary.total_pnl >= 0 else "📉"
        
        lines = [
            f"═══ Daily Report: {summary.date} ═══",
            "",
            f"{pnl_emoji} P&L Summary",
            f"  Realized:   ${summary.realized_pnl:+.2f}",
            f"  Unrealized: ${summary.unrealized_pnl:+.2f}",
            f"  Total:      ${summary.total_pnl:+.2f} ({summary.pnl_percent:+.1f}%)",
            "",
            f"📊 Trading Activity",
            f"  Total Trades: {summary.total_trades}",
            f"  Winners:      {summary.winning_trades}",
            f"  Losers:       {summary.losing_trades}",
            f"  Win Rate:     {summary.win_rate:.1f}%",
            "",
            f"💰 Volume & Fees",
            f"  Volume: ${summary.total_volume:.2f}",
            f"  Fees:   ${summary.fees_paid:.2f}",
            "",
            f"📋 Positions",
            f"  Open:   {summary.open_positions}",
            f"  Closed: {summary.closed_positions}",
            "",
            f"👁️ Monitoring",
            f"  Wallets Active: {summary.wallets_with_activity}",
        ]
        
        # Add extremes if any trades
        if summary.total_trades > 0:
            lines.extend([
                "",
                f"🎯 Best/Worst",
                f"  Best Trade:  ${summary.largest_win:+.2f}",
                f"  Worst Trade: ${summary.largest_loss:+.2f}",
            ])
        
        return "\n".join(lines)
    
    def send_daily_alert(self, date: str = None) -> DailySummary:
        """
        Generate and send daily summary as an alert.
        
        Args:
            date: Date to report on. Defaults to today.
        
        Returns:
            DailySummary object
        """
        summary = self.generate_summary(date)
        
        # Format message
        title = f"Daily Report - {summary.date}"
        message = self.format_summary(summary)
        
        # Determine priority based on P&L
        if summary.total_pnl < -50:
            priority = AlertPriority.CRITICAL
        elif summary.total_pnl < 0:
            priority = AlertPriority.HIGH
        elif summary.total_pnl > 50:
            priority = AlertPriority.NORMAL
        else:
            priority = AlertPriority.LOW
        
        # Send alert
        self.alerts.send(
            title=title,
            message=message,
            priority=priority,
            category="daily_report",
            source="DailyReporter",
            data=summary.to_dict()
        )
        
        return summary
    
    def get_history(self, days: int = 7) -> List[DailySummary]:
        """
        Get historical daily summaries.
        
        Args:
            days: Number of days to look back
        
        Returns:
            List of DailySummary objects
        """
        summaries = []
        
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            filepath = self.data_dir / f"daily_{date}.json"
            
            if filepath.exists():
                try:
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    
                    summary = DailySummary(**data)
                    summaries.append(summary)
                except Exception:
                    pass
        
        return summaries
    
    def print_weekly_summary(self):
        """Print summary of last 7 days."""
        summaries = self.get_history(7)
        
        if not summaries:
            print("No historical data available")
            return
        
        total_pnl = sum(s.total_pnl for s in summaries)
        total_trades = sum(s.total_trades for s in summaries)
        total_volume = sum(s.total_volume for s in summaries)
        
        print("\n═══ Weekly Summary ═══")
        print(f"Days with data: {len(summaries)}")
        print(f"Total P&L:      ${total_pnl:+.2f}")
        print(f"Total Trades:   {total_trades}")
        print(f"Total Volume:   ${total_volume:.2f}")
        print()
        
        # Daily breakdown
        print("Daily Breakdown:")
        for s in sorted(summaries, key=lambda x: x.date):
            emoji = "✅" if s.total_pnl >= 0 else "❌"
            print(f"  {s.date}: {emoji} ${s.total_pnl:+.2f} ({s.total_trades} trades)")


def run_daily_report():
    """CLI function to run daily report."""
    from ..alerts import AlertManager
    
    alerts = AlertManager()
    alerts.enable_desktop()
    alerts.enable_console()
    
    reporter = DailyReporter(alerts)
    summary = reporter.send_daily_alert()
    
    print("\n" + reporter.format_summary(summary))
    
    # Also show weekly
    reporter.print_weekly_summary()


if __name__ == "__main__":
    run_daily_report()
