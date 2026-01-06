"""
Performance Metrics for Maker Rebates Backtester.

Calculates comprehensive metrics from backtest results including:
- P&L breakdown (resolution vs rebates)
- Risk metrics (Sharpe, Sortino, max drawdown)
- Entry/fill statistics
"""

import math
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from .models import WindowResult


@dataclass
class RiskMetrics:
    """Risk-adjusted performance metrics."""
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    max_drawdown_duration: int  # Number of windows
    calmar_ratio: float  # Annual return / Max drawdown
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float


@dataclass
class FillMetrics:
    """Fill rate and execution statistics."""
    total_windows: int
    windows_entered: int
    entry_rate: float
    yes_fill_rate: float
    no_fill_rate: float
    both_fill_rate: float
    single_fill_rate: float
    avg_fill_price_yes: float
    avg_fill_price_no: float


@dataclass
class PnLBreakdown:
    """P&L breakdown by source."""
    total_pnl: float
    resolution_pnl: float
    rebate_revenue: float
    avg_pnl_per_window: float
    avg_pnl_per_entry: float
    pnl_std_dev: float
    positive_pnl_windows: int
    negative_pnl_windows: int


class MakerMetrics:
    """
    Calculate comprehensive performance metrics for maker strategy backtests.
    """

    @staticmethod
    def calculate(results: List[WindowResult]) -> Dict[str, Any]:
        """
        Calculate all metrics from a list of window results.

        Args:
            results: List of WindowResult from backtest

        Returns:
            Dictionary containing all computed metrics
        """
        if not results:
            return {
                "total_windows": 0,
                "error": "No results to analyze"
            }

        # Filter to entered windows for most calculations
        entered = [r for r in results if r.entered]

        metrics = {
            "summary": MakerMetrics._calculate_summary(results, entered),
            "pnl": MakerMetrics._calculate_pnl_breakdown(results, entered),
            "fills": MakerMetrics._calculate_fill_metrics(results, entered),
            "risk": MakerMetrics._calculate_risk_metrics(entered),
            "distribution": MakerMetrics._calculate_distribution(entered),
        }

        return metrics

    @staticmethod
    def _calculate_summary(
        all_results: List[WindowResult],
        entered: List[WindowResult]
    ) -> Dict[str, Any]:
        """Calculate summary statistics."""
        total_pnl = sum(r.total_pnl for r in entered)
        total_rebates = sum(r.rebate_earned for r in entered)
        total_resolution = sum(r.resolution_pnl for r in entered)

        return {
            "total_windows": len(all_results),
            "windows_entered": len(entered),
            "entry_rate": len(entered) / len(all_results) if all_results else 0,
            "total_pnl": round(total_pnl, 4),
            "total_rebates": round(total_rebates, 4),
            "total_resolution_pnl": round(total_resolution, 4),
            "avg_pnl_per_entry": round(total_pnl / len(entered), 4) if entered else 0,
            "rebate_pct_of_total": round(
                total_rebates / total_pnl * 100, 2
            ) if total_pnl != 0 else 0,
        }

    @staticmethod
    def _calculate_pnl_breakdown(
        all_results: List[WindowResult],
        entered: List[WindowResult]
    ) -> Dict[str, Any]:
        """Calculate P&L breakdown."""
        pnl_values = [r.total_pnl for r in entered]

        if not pnl_values:
            return {
                "total_pnl": 0,
                "resolution_pnl": 0,
                "rebate_revenue": 0,
                "avg_pnl_per_window": 0,
                "avg_pnl_per_entry": 0,
                "pnl_std_dev": 0,
                "positive_pnl_windows": 0,
                "negative_pnl_windows": 0,
            }

        total_pnl = sum(pnl_values)
        mean_pnl = total_pnl / len(pnl_values)

        # Standard deviation
        variance = sum((p - mean_pnl) ** 2 for p in pnl_values) / len(pnl_values)
        std_dev = math.sqrt(variance)

        positive = sum(1 for p in pnl_values if p > 0)
        negative = sum(1 for p in pnl_values if p < 0)

        return {
            "total_pnl": round(total_pnl, 4),
            "resolution_pnl": round(sum(r.resolution_pnl for r in entered), 4),
            "rebate_revenue": round(sum(r.rebate_earned for r in entered), 4),
            "avg_pnl_per_window": round(total_pnl / len(all_results), 4) if all_results else 0,
            "avg_pnl_per_entry": round(mean_pnl, 4),
            "pnl_std_dev": round(std_dev, 4),
            "positive_pnl_windows": positive,
            "negative_pnl_windows": negative,
            "breakeven_windows": len(entered) - positive - negative,
        }

    @staticmethod
    def _calculate_fill_metrics(
        all_results: List[WindowResult],
        entered: List[WindowResult]
    ) -> Dict[str, Any]:
        """Calculate fill rate statistics."""
        yes_fills = sum(1 for r in entered if r.yes_filled)
        no_fills = sum(1 for r in entered if r.no_filled)
        both_fills = sum(1 for r in entered if r.yes_filled and r.no_filled)
        single_fills = sum(
            1 for r in entered
            if (r.yes_filled and not r.no_filled) or (r.no_filled and not r.yes_filled)
        )

        # Average fill prices
        yes_prices = [r.yes_fill_price for r in entered if r.yes_filled and r.yes_fill_price > 0]
        no_prices = [r.no_fill_price for r in entered if r.no_filled and r.no_fill_price > 0]

        return {
            "total_windows": len(all_results),
            "windows_entered": len(entered),
            "entry_rate": round(len(entered) / len(all_results), 4) if all_results else 0,
            "yes_fill_count": yes_fills,
            "no_fill_count": no_fills,
            "yes_fill_rate": round(yes_fills / len(entered), 4) if entered else 0,
            "no_fill_rate": round(no_fills / len(entered), 4) if entered else 0,
            "both_fill_rate": round(both_fills / len(entered), 4) if entered else 0,
            "single_fill_rate": round(single_fills / len(entered), 4) if entered else 0,
            "avg_fill_price_yes": round(sum(yes_prices) / len(yes_prices), 4) if yes_prices else 0,
            "avg_fill_price_no": round(sum(no_prices) / len(no_prices), 4) if no_prices else 0,
            "delta_neutral_windows": both_fills,
            "delta_neutral_rate": round(both_fills / len(entered), 4) if entered else 0,
        }

    @staticmethod
    def _calculate_risk_metrics(entered: List[WindowResult]) -> Dict[str, Any]:
        """Calculate risk-adjusted metrics."""
        if not entered:
            return {
                "sharpe_ratio": 0,
                "sortino_ratio": 0,
                "max_drawdown": 0,
                "max_drawdown_pct": 0,
                "win_rate": 0,
                "profit_factor": 0,
                "avg_win": 0,
                "avg_loss": 0,
                "largest_win": 0,
                "largest_loss": 0,
            }

        pnl_values = [r.total_pnl for r in entered]

        # Win rate
        wins = [p for p in pnl_values if p > 0]
        losses = [p for p in pnl_values if p < 0]
        win_rate = len(wins) / len(pnl_values) if pnl_values else 0

        # Profit factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Average win/loss
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        # Max drawdown
        cumulative = []
        running = 0
        for pnl in pnl_values:
            running += pnl
            cumulative.append(running)

        max_drawdown = 0
        peak = cumulative[0] if cumulative else 0
        for value in cumulative:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        # Sharpe ratio (assuming daily windows, annualize with sqrt(252 * 96) for 15-min windows)
        # But for simplicity, just compute raw Sharpe
        mean_pnl = sum(pnl_values) / len(pnl_values)
        variance = sum((p - mean_pnl) ** 2 for p in pnl_values) / len(pnl_values)
        std_dev = math.sqrt(variance) if variance > 0 else 0

        sharpe = mean_pnl / std_dev if std_dev > 0 else 0

        # Sortino ratio (only downside deviation)
        downside_returns = [p for p in pnl_values if p < 0]
        if downside_returns:
            downside_variance = sum(p ** 2 for p in downside_returns) / len(pnl_values)
            downside_dev = math.sqrt(downside_variance)
            sortino = mean_pnl / downside_dev if downside_dev > 0 else 0
        else:
            sortino = float('inf') if mean_pnl > 0 else 0

        return {
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4) if sortino != float('inf') else "inf",
            "max_drawdown": round(max_drawdown, 4),
            "max_drawdown_pct": round(max_drawdown / peak * 100, 2) if peak > 0 else 0,
            "win_rate": round(win_rate, 4),
            "profit_factor": round(profit_factor, 4) if profit_factor != float('inf') else "inf",
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "largest_win": round(max(wins), 4) if wins else 0,
            "largest_loss": round(min(losses), 4) if losses else 0,
            "win_count": len(wins),
            "loss_count": len(losses),
            "expectancy": round(mean_pnl, 4),
        }

    @staticmethod
    def _calculate_distribution(entered: List[WindowResult]) -> Dict[str, Any]:
        """Calculate P&L distribution statistics."""
        if not entered:
            return {
                "min": 0, "max": 0, "median": 0,
                "percentile_25": 0, "percentile_75": 0,
                "skewness": 0, "kurtosis": 0,
            }

        pnl_values = sorted([r.total_pnl for r in entered])
        n = len(pnl_values)

        # Percentiles
        def percentile(data: List[float], p: float) -> float:
            k = (len(data) - 1) * p / 100
            f = math.floor(k)
            c = math.ceil(k)
            if f == c:
                return data[int(k)]
            return data[int(f)] * (c - k) + data[int(c)] * (k - f)

        median = percentile(pnl_values, 50)
        p25 = percentile(pnl_values, 25)
        p75 = percentile(pnl_values, 75)

        # Skewness and kurtosis
        mean = sum(pnl_values) / n
        variance = sum((x - mean) ** 2 for x in pnl_values) / n
        std = math.sqrt(variance) if variance > 0 else 1

        if std > 0:
            skewness = sum((x - mean) ** 3 for x in pnl_values) / (n * std ** 3)
            kurtosis = sum((x - mean) ** 4 for x in pnl_values) / (n * std ** 4) - 3
        else:
            skewness = 0
            kurtosis = 0

        return {
            "min": round(min(pnl_values), 4),
            "max": round(max(pnl_values), 4),
            "median": round(median, 4),
            "percentile_25": round(p25, 4),
            "percentile_75": round(p75, 4),
            "iqr": round(p75 - p25, 4),
            "skewness": round(skewness, 4),
            "kurtosis": round(kurtosis, 4),
        }

    @staticmethod
    def format_report(metrics: Dict[str, Any]) -> str:
        """
        Format metrics as a human-readable report.

        Args:
            metrics: Dictionary of computed metrics

        Returns:
            Formatted string report
        """
        lines = [
            "=" * 60,
            "MAKER REBATES BACKTEST REPORT",
            "=" * 60,
            "",
            "SUMMARY",
            "-" * 40,
        ]

        summary = metrics.get("summary", {})
        lines.extend([
            f"Total Windows:        {summary.get('total_windows', 0)}",
            f"Windows Entered:      {summary.get('windows_entered', 0)}",
            f"Entry Rate:           {summary.get('entry_rate', 0):.1%}",
            f"Total P&L:            ${summary.get('total_pnl', 0):.2f}",
            f"  - Resolution P&L:   ${summary.get('total_resolution_pnl', 0):.2f}",
            f"  - Rebate Revenue:   ${summary.get('total_rebates', 0):.2f}",
            f"Avg P&L per Entry:    ${summary.get('avg_pnl_per_entry', 0):.4f}",
            "",
            "FILL STATISTICS",
            "-" * 40,
        ])

        fills = metrics.get("fills", {})
        lines.extend([
            f"YES Fill Rate:        {fills.get('yes_fill_rate', 0):.1%}",
            f"NO Fill Rate:         {fills.get('no_fill_rate', 0):.1%}",
            f"Both Sides Rate:      {fills.get('both_fill_rate', 0):.1%}",
            f"Avg YES Fill Price:   ${fills.get('avg_fill_price_yes', 0):.4f}",
            f"Avg NO Fill Price:    ${fills.get('avg_fill_price_no', 0):.4f}",
            "",
            "RISK METRICS",
            "-" * 40,
        ])

        risk = metrics.get("risk", {})
        lines.extend([
            f"Win Rate:             {risk.get('win_rate', 0):.1%}",
            f"Profit Factor:        {risk.get('profit_factor', 0)}",
            f"Sharpe Ratio:         {risk.get('sharpe_ratio', 0):.3f}",
            f"Sortino Ratio:        {risk.get('sortino_ratio', 0)}",
            f"Max Drawdown:         ${risk.get('max_drawdown', 0):.2f}",
            f"Avg Win:              ${risk.get('avg_win', 0):.4f}",
            f"Avg Loss:             ${risk.get('avg_loss', 0):.4f}",
            f"Largest Win:          ${risk.get('largest_win', 0):.4f}",
            f"Largest Loss:         ${risk.get('largest_loss', 0):.4f}",
            "",
            "P&L DISTRIBUTION",
            "-" * 40,
        ])

        dist = metrics.get("distribution", {})
        lines.extend([
            f"Min:                  ${dist.get('min', 0):.4f}",
            f"25th Percentile:      ${dist.get('percentile_25', 0):.4f}",
            f"Median:               ${dist.get('median', 0):.4f}",
            f"75th Percentile:      ${dist.get('percentile_75', 0):.4f}",
            f"Max:                  ${dist.get('max', 0):.4f}",
            f"Skewness:             {dist.get('skewness', 0):.3f}",
            "",
            "=" * 60,
        ])

        return "\n".join(lines)
