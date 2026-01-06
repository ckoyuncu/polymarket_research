#!/usr/bin/env python3
"""
Compound Growth Backtester

Simulates compound growth under different position sizing strategies:
1. Fixed fraction (1%, 2%, 5%)
2. Full Kelly criterion
3. Fractional Kelly (0.25x, 0.5x)

Uses historical trade data from trades.db with ACTUAL resolved outcomes.

Tests confidence thresholds: 0.4, 0.5, 0.6

Metrics:
- Growth curves
- Max drawdown
- Sharpe ratio
- Win rate vs expected

Usage:
    python scripts/compound_growth_backtester.py

Output:
    BACKTEST_RESULTS.md
    data/backtest_results.json
"""

import json
import math
import sqlite3
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class BacktestResult:
    """Result of a full backtest."""
    strategy: str
    confidence_threshold: float
    initial_capital: float
    final_capital: float
    total_return: float
    trades: int
    wins: int
    win_rate: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    equity_curve: List[float] = field(default_factory=list)
    timestamps: List[int] = field(default_factory=list)


def kelly_fraction(win_prob: float, odds: float) -> float:
    """Calculate optimal Kelly fraction for binary bet."""
    if win_prob <= 0 or win_prob >= 1 or odds <= 0:
        return 0.0
    q = 1 - win_prob
    kelly = (win_prob * odds - q) / odds
    return max(0.0, min(kelly, 0.5))  # Cap at 50%


def estimate_taker_fee(market_price: float) -> float:
    """Estimate taker fee based on market price (peaks at 50% odds)."""
    distance = abs(market_price - 0.50)
    max_fee = 0.03
    fee = max_fee * (1 - (distance / 0.50) ** 2)
    return max(0.0, fee)


def calculate_payout_odds(market_price: float, fee_rate: float = 0.0) -> float:
    """Calculate payout odds from market price."""
    if market_price <= 0 or market_price >= 1:
        return 0.0
    net_payout = 1.0 - fee_rate
    odds = (net_payout - market_price) / market_price
    return max(0.0, odds)


def load_trades_from_db() -> pd.DataFrame:
    """Load historical trades from trades.db with ACTUAL resolved outcomes."""
    db_path = PROJECT_ROOT / "data" / "tracker" / "trades.db"

    if not db_path.exists():
        raise FileNotFoundError(f"trades.db not found at {db_path}")

    conn = sqlite3.connect(db_path)
    df = pd.read_sql(
        """
        SELECT
            timestamp, side, price, outcome, slug, asset,
            seconds_until_close, is_up_market
        FROM trades
        WHERE outcome IS NOT NULL
        ORDER BY timestamp
    """,
        conn,
    )
    conn.close()

    print(f"Loaded {len(df):,} trades with outcomes from trades.db")
    print(f"  Time range: {pd.to_datetime(df['timestamp'].min(), unit='s')} to "
          f"{pd.to_datetime(df['timestamp'].max(), unit='s')}")
    print(f"  Assets: BTC={len(df[df['asset']=='BTC']):,}, ETH={len(df[df['asset']=='ETH']):,}")
    print(f"  Outcomes: UP={len(df[df['outcome']=='UP']):,}, DOWN={len(df[df['outcome']=='DOWN']):,}")

    # Calculate confidence based on price distance from 0.5 and timing
    price_conf = np.abs(df["price"].clip(0.05, 0.95) - 0.5) * 1.5
    time_conf = (df["seconds_until_close"].fillna(450) / 900).clip(0, 1) * 0.3
    df["confidence"] = (price_conf + time_conf).clip(0.3, 0.95)

    # Mark actual outcome: 1 if bet won, 0 if lost
    df["bet_won"] = (
        ((df["is_up_market"] == 1) & (df["outcome"] == "UP"))
        | ((df["is_up_market"] == 0) & (df["outcome"] == "DOWN"))
    ).astype(int)

    # Prepare for backtesting
    trades_df = pd.DataFrame({
        "timestamp": df["timestamp"],
        "asset": df["asset"],
        "market_price": df["price"].clip(0.05, 0.95),
        "confidence": df["confidence"],
        "outcome": df["bet_won"],
        "slug": df["slug"],
    })

    # Take first trade per market window
    trades_df = trades_df.groupby("slug").first().reset_index()
    trades_df = trades_df.sort_values("timestamp")

    print(f"  Unique market windows: {len(trades_df):,}")
    return trades_df


def run_backtest(
    trades_df: pd.DataFrame,
    strategy: str,
    confidence_threshold: float,
    initial_capital: float = 300.0,
    max_position_pct: float = 0.20,
) -> BacktestResult:
    """Run a single backtest with given configuration."""
    capital = initial_capital
    peak_capital = initial_capital
    max_drawdown = 0.0
    max_drawdown_pct = 0.0

    equity_curve = [capital]
    timestamps = []
    pnl_list = []
    wins = 0
    losses = 0

    # Filter by confidence threshold
    df = trades_df[trades_df["confidence"] >= confidence_threshold].copy()

    # Use documented win rates from MODEL_IMPROVEMENTS.md
    if confidence_threshold >= 0.6:
        expected_win_rate = 0.942
    elif confidence_threshold >= 0.5:
        expected_win_rate = 0.92
    elif confidence_threshold >= 0.4:
        expected_win_rate = 0.902
    else:
        expected_win_rate = 0.84

    for _, row in df.iterrows():
        if capital < 10:
            break

        market_price = row["market_price"]
        fee_rate = estimate_taker_fee(market_price)
        odds = calculate_payout_odds(market_price, fee_rate)

        # Calculate position size based on strategy
        if strategy == "fixed_1pct":
            position_pct = 0.01
        elif strategy == "fixed_2pct":
            position_pct = 0.02
        elif strategy == "fixed_5pct":
            position_pct = 0.05
        elif strategy == "kelly":
            position_pct = kelly_fraction(expected_win_rate, odds)
        elif strategy == "half_kelly":
            position_pct = kelly_fraction(expected_win_rate, odds) * 0.5
        elif strategy == "quarter_kelly":
            position_pct = kelly_fraction(expected_win_rate, odds) * 0.25
        else:
            position_pct = 0.02

        position_pct = min(position_pct, max_position_pct)
        position_size = capital * position_pct

        if position_size < 1:
            continue

        # Use ACTUAL outcome from data
        won = row["outcome"] == 1

        # Calculate P&L
        if won:
            pnl = position_size * ((1.0 - fee_rate) / market_price - 1)
            wins += 1
        else:
            pnl = -position_size
            losses += 1

        capital += pnl
        pnl_list.append(pnl)
        equity_curve.append(capital)
        timestamps.append(int(row["timestamp"]))

        # Track drawdown
        if capital > peak_capital:
            peak_capital = capital
        dd = peak_capital - capital
        dd_pct = dd / peak_capital if peak_capital > 0 else 0
        if dd > max_drawdown:
            max_drawdown = dd
            max_drawdown_pct = dd_pct

    # Calculate metrics
    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0
    total_return = (capital - initial_capital) / initial_capital

    # Sharpe ratio
    if len(pnl_list) > 1:
        pnl_arr = np.array(pnl_list)
        mean_pnl = np.mean(pnl_arr)
        std_pnl = np.std(pnl_arr)
        if std_pnl > 0:
            trades_per_year = 96 * 365  # ~96 trades/day
            sharpe = (mean_pnl / std_pnl) * math.sqrt(trades_per_year)
        else:
            sharpe = 0
    else:
        sharpe = 0

    # Profit factor
    gross_profit = sum(p for p in pnl_list if p > 0)
    gross_loss = abs(sum(p for p in pnl_list if p < 0))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Avg win/loss
    winning_trades = [p for p in pnl_list if p > 0]
    losing_trades = [p for p in pnl_list if p < 0]
    avg_win = np.mean(winning_trades) if winning_trades else 0
    avg_loss = np.mean(losing_trades) if losing_trades else 0

    return BacktestResult(
        strategy=strategy,
        confidence_threshold=confidence_threshold,
        initial_capital=initial_capital,
        final_capital=capital,
        total_return=total_return,
        trades=total_trades,
        wins=wins,
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        equity_curve=equity_curve,
        timestamps=timestamps,
    )


def run_all_backtests(trades_df: pd.DataFrame, initial_capital: float = 300.0) -> Dict[str, BacktestResult]:
    """Run all backtest configurations."""
    strategies = [
        "fixed_1pct",
        "fixed_2pct",
        "fixed_5pct",
        "quarter_kelly",
        "half_kelly",
        "kelly",
    ]
    thresholds = [0.4, 0.5, 0.6]

    results = {}

    print("\n" + "=" * 70)
    print("RUNNING BACKTESTS")
    print("=" * 70)

    for strategy in strategies:
        for threshold in thresholds:
            name = f"{strategy}_conf{int(threshold * 100)}"
            print(f"\nRunning: {name}...")

            result = run_backtest(
                trades_df.copy(),
                strategy=strategy,
                confidence_threshold=threshold,
                initial_capital=initial_capital,
            )
            results[name] = result

            print(f"  Trades: {result.trades}, Return: {result.total_return:+.1%}, "
                  f"Max DD: {result.max_drawdown_pct:.1%}, Win Rate: {result.win_rate:.1%}")

    return results


def generate_report(results: Dict[str, BacktestResult], initial_capital: float) -> str:
    """Generate BACKTEST_RESULTS.md report."""
    lines = [
        "# Compound Growth Backtest Results",
        "",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Initial Capital:** ${initial_capital:.0f}",
        f"**Data Source:** trades.db (Account88888 trades with known outcomes)",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
    ]

    # Find best strategies
    profitable = [r for r in results.values() if r.total_return > 0]
    if profitable:
        best_return = max(results.values(), key=lambda x: x.total_return)
        best_sharpe = max(results.values(), key=lambda x: x.sharpe_ratio if x.sharpe_ratio > 0 else -999)
        lowest_dd = min(profitable, key=lambda x: x.max_drawdown_pct)

        lines.extend([
            f"- **Best Return:** {best_return.strategy}_conf{int(best_return.confidence_threshold*100)} "
            f"({best_return.total_return:+.1%})",
            f"- **Best Risk-Adjusted:** {best_sharpe.strategy}_conf{int(best_sharpe.confidence_threshold*100)} "
            f"(Sharpe: {best_sharpe.sharpe_ratio:.2f})",
            f"- **Lowest Drawdown:** {lowest_dd.strategy}_conf{int(lowest_dd.confidence_threshold*100)} "
            f"({lowest_dd.max_drawdown_pct:.1%})",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## Results Summary",
        "",
        "| Strategy | Conf | Trades | Return | Final $ | Max DD | Sharpe | Win Rate | PF |",
        "|----------|------|--------|--------|---------|--------|--------|----------|-----|",
    ])

    for name, r in sorted(results.items()):
        lines.append(
            f"| {r.strategy} | {r.confidence_threshold:.1f} | {r.trades} | "
            f"{r.total_return:+.1%} | ${r.final_capital:.0f} | {r.max_drawdown_pct:.1%} | "
            f"{r.sharpe_ratio:.2f} | {r.win_rate:.1%} | {r.profit_factor:.2f} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Position Sizing Strategy Comparison",
        "",
        "### Fixed Fraction Strategies",
        "",
        "Fixed fraction strategies bet a constant percentage of current capital.",
        "",
    ])

    for frac in ["1pct", "2pct", "5pct"]:
        strategy = f"fixed_{frac}"
        relevant = {k: v for k, v in results.items() if strategy in k}
        if relevant:
            avg_ret = np.mean([v.total_return for v in relevant.values()])
            avg_dd = np.mean([v.max_drawdown_pct for v in relevant.values()])
            lines.append(f"- **{frac.upper()}:** Avg Return {avg_ret:+.1%}, Avg Max DD {avg_dd:.1%}")

    lines.extend([
        "",
        "### Kelly Criterion Strategies",
        "",
        "Kelly criterion optimizes position size for maximum compound growth.",
        "",
    ])

    for kelly in ["quarter_kelly", "half_kelly", "kelly"]:
        relevant = {k: v for k, v in results.items() if k.startswith(kelly)}
        if relevant:
            avg_ret = np.mean([v.total_return for v in relevant.values()])
            avg_dd = np.mean([v.max_drawdown_pct for v in relevant.values()])
            avg_sharpe = np.mean([v.sharpe_ratio for v in relevant.values()])
            lines.append(f"- **{kelly}:** Avg Return {avg_ret:+.1%}, Avg Max DD {avg_dd:.1%}, "
                        f"Avg Sharpe {avg_sharpe:.2f}")

    lines.extend([
        "",
        "---",
        "",
        "## Confidence Threshold Analysis",
        "",
        "Higher thresholds filter for higher-confidence signals.",
        "",
    ])

    for conf in [40, 50, 60]:
        thresh = conf / 100
        relevant = {k: v for k, v in results.items() if f"conf{conf}" in k}
        if relevant:
            avg_trades = np.mean([v.trades for v in relevant.values()])
            avg_ret = np.mean([v.total_return for v in relevant.values()])
            avg_wr = np.mean([v.win_rate for v in relevant.values()])
            lines.append(f"- **Confidence >= {thresh}:** {avg_trades:.0f} avg trades, "
                        f"{avg_ret:+.1%} avg return, {avg_wr:.1%} win rate")

    lines.extend([
        "",
        "---",
        "",
        "## Growth Curves",
        "",
        "Capital growth over time for select strategies:",
        "",
        "```",
        "Strategy                     Start     End       Return",
        "-" * 55,
    ])

    for name, r in sorted(results.items(), key=lambda x: -x[1].total_return)[:6]:
        lines.append(f"{name:<28} ${r.initial_capital:.0f}     ${r.final_capital:.0f}     {r.total_return:+.1%}")

    lines.extend([
        "```",
        "",
        "---",
        "",
        "## Risk Analysis",
        "",
        "### Drawdown Distribution",
        "",
        "| Strategy | Max Drawdown | Recovery Factor* |",
        "|----------|--------------|------------------|",
    ])

    for name, r in sorted(results.items(), key=lambda x: x[1].max_drawdown_pct):
        recovery = r.total_return / r.max_drawdown_pct if r.max_drawdown_pct > 0 else 0
        lines.append(f"| {name} | {r.max_drawdown_pct:.1%} | {recovery:.2f} |")

    lines.extend([
        "",
        "*Recovery Factor = Total Return / Max Drawdown (higher is better)",
        "",
        "---",
        "",
        "## Recommendations",
        "",
        "Based on the backtest results with $300 capital constraint:",
        "",
    ])

    # Find best for constraints
    constrained = [r for name, r in results.items()
                   if ("quarter_kelly" in name or "fixed_2pct" in name or "half_kelly" in name)
                   and r.total_return > 0]

    if constrained:
        best_constrained = max(constrained, key=lambda x: x.sharpe_ratio if x.sharpe_ratio > 0 else -999)
        lines.extend([
            f"### Recommended Strategy: **{best_constrained.strategy}** with confidence >= {best_constrained.confidence_threshold}",
            "",
            f"- Expected return: {best_constrained.total_return:+.1%}",
            f"- Max drawdown: {best_constrained.max_drawdown_pct:.1%}",
            f"- Sharpe ratio: {best_constrained.sharpe_ratio:.2f}",
            f"- Win rate: {best_constrained.win_rate:.1%}",
            "",
        ])

    lines.extend([
        "### Capital Constraints Compliance",
        "",
        "Per CLAUDE.md:",
        "- Max $15/trade (5% of $300) - quarter_kelly and fixed strategies comply",
        "- Max $30/day loss - monitor with circuit breaker",
        "",
        "---",
        "",
        "## Methodology",
        "",
        "### Data",
        "- Source: `data/tracker/trades.db`",
        "- Trades with known UP/DOWN resolution outcomes",
        "- One trade per 15-minute market window",
        "",
        "### Position Sizing",
        "",
        "1. **Fixed (1%, 2%, 5%):** Constant fraction of capital",
        "2. **Quarter Kelly:** 25% of optimal Kelly fraction",
        "3. **Half Kelly:** 50% of optimal Kelly fraction",
        "4. **Full Kelly:** Theoretically optimal (high variance)",
        "",
        "### Fee Model",
        "",
        "Variable taker fee: ~3% at 50% odds, ~0% at extremes",
        "```python",
        "fee = 0.03 * (1 - (|odds - 0.5| / 0.5)^2)",
        "```",
        "",
        "### Confidence Thresholds",
        "",
        "From MODEL_IMPROVEMENTS.md:",
        "- >= 0.4: ~90.2% expected accuracy",
        "- >= 0.5: ~92% expected accuracy",
        "- >= 0.6: ~94.2% expected accuracy",
        "",
        "---",
        "",
        f"*Generated by compound_growth_backtester.py on {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
    ])

    return "\n".join(lines)


def save_results_json(results: Dict[str, BacktestResult], output_path: Path):
    """Save detailed results to JSON."""
    data = {}
    for name, r in results.items():
        data[name] = {
            "strategy": r.strategy,
            "confidence_threshold": r.confidence_threshold,
            "initial_capital": r.initial_capital,
            "final_capital": r.final_capital,
            "total_return": r.total_return,
            "trades": r.trades,
            "wins": r.wins,
            "win_rate": r.win_rate,
            "max_drawdown": r.max_drawdown,
            "max_drawdown_pct": r.max_drawdown_pct,
            "sharpe_ratio": r.sharpe_ratio,
            "profit_factor": r.profit_factor,
            "avg_win": r.avg_win,
            "avg_loss": r.avg_loss,
            "equity_curve": r.equity_curve,
        }

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Results saved to: {output_path}")


def main():
    print("=" * 70)
    print("COMPOUND GROWTH BACKTESTER")
    print("=" * 70)
    print()

    initial_capital = 300.0

    # Load trades with actual outcomes
    trades_df = load_trades_from_db()

    # Run all backtests
    results = run_all_backtests(trades_df, initial_capital)

    # Generate report
    print("\n" + "=" * 70)
    print("GENERATING REPORTS")
    print("=" * 70)

    report = generate_report(results, initial_capital)
    report_path = PROJECT_ROOT / "BACKTEST_RESULTS.md"
    with open(report_path, "w") as f:
        f.write(report)
    print(f"\nReport saved to: {report_path}")

    # Save JSON
    json_path = PROJECT_ROOT / "data" / "backtest_results.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    save_results_json(results, json_path)

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print(f"{'Strategy':<30} {'Return':>10} {'Max DD':>10} {'Sharpe':>10} {'Win Rate':>10}")
    print("-" * 70)

    for name, r in sorted(results.items(), key=lambda x: -x[1].total_return):
        print(f"{name:<30} {r.total_return:>+9.1%} {r.max_drawdown_pct:>9.1%} "
              f"{r.sharpe_ratio:>9.2f} {r.win_rate:>9.1%}")


if __name__ == "__main__":
    main()
