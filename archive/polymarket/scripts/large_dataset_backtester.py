#!/usr/bin/env python3
"""
Large Dataset Compound Growth Backtester

Uses the full account88888 dataset (2.9M trades) for statistically significant results.
Maps trades to BTC/ETH 15-min markets and calculates actual outcomes.

Usage:
    python scripts/large_dataset_backtester.py
"""

import json
import math
import numpy as np
import pandas as pd
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timezone
import re

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class BacktestResult:
    """Result of a backtest run."""
    strategy: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    avg_trade_return: float
    trades_per_day: float
    confidence_interval_95: Tuple[float, float]


def load_token_mapping() -> Dict[str, dict]:
    """Load token_id to market mapping."""
    mapping_path = PROJECT_ROOT / "data" / "token_to_market.json"
    with open(mapping_path, 'r') as f:
        data = json.load(f)
    return data.get('token_to_market', {})


def parse_market_info(market_data: dict) -> Optional[dict]:
    """Extract asset, direction, and outcome from market data."""
    slug = market_data.get('slug', '')
    question = market_data.get('question', '')
    outcomes = market_data.get('outcomes', '[]')
    outcome_prices = market_data.get('outcomePrices', '[]')

    # Parse outcomes and prices
    try:
        outcomes_list = json.loads(outcomes) if isinstance(outcomes, str) else outcomes
        prices_list = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
    except:
        return None

    # Determine asset from slug
    asset = None
    if 'btc' in slug.lower() or 'bitcoin' in slug.lower():
        asset = 'BTC'
    elif 'eth' in slug.lower() or 'ethereum' in slug.lower():
        asset = 'ETH'
    else:
        return None  # Skip non-BTC/ETH markets

    # Check if it's a 15-min market
    if '15m' not in slug and '15-min' not in question.lower():
        return None

    # Determine resolved outcome
    resolved_outcome = None
    if prices_list:
        try:
            if str(prices_list[0]) == '1':
                resolved_outcome = 'UP'
            elif str(prices_list[1]) == '1':
                resolved_outcome = 'DOWN'
        except:
            pass

    # Get token IDs for UP and DOWN
    clob_tokens = market_data.get('clobTokenIds', '[]')
    try:
        token_ids = json.loads(clob_tokens) if isinstance(clob_tokens, str) else clob_tokens
    except:
        token_ids = []

    return {
        'asset': asset,
        'slug': slug,
        'resolved_outcome': resolved_outcome,
        'token_ids': token_ids,
        'end_date': market_data.get('endDate'),
    }


def load_trades_with_outcomes() -> pd.DataFrame:
    """Load account88888 trades and map to market outcomes."""
    print("Loading account88888 trades...")

    # Load trades
    trades_path = PROJECT_ROOT / "data" / "account88888_trades_joined.json"
    with open(trades_path, 'r') as f:
        data = json.load(f)

    trades = data.get('trades', [])
    print(f"  Total trades: {len(trades):,}")

    # Load token mapping
    token_mapping = load_token_mapping()
    print(f"  Token mappings: {len(token_mapping):,}")

    # Build reverse mapping: token_id -> market info
    token_to_market = {}
    markets_processed = 0
    btc_markets = 0
    eth_markets = 0

    for token_id, market_data in token_mapping.items():
        info = parse_market_info(market_data)
        if info and info['resolved_outcome']:
            # Map both UP and DOWN token IDs to this market
            for tid in info['token_ids']:
                # Determine if this token_id is UP or DOWN based on position
                is_up_token = (tid == info['token_ids'][0])  # First token is usually UP
                token_to_market[tid] = {
                    **info,
                    'is_up_token': is_up_token,
                }
            markets_processed += 1
            if info['asset'] == 'BTC':
                btc_markets += 1
            else:
                eth_markets += 1

    print(f"  Markets with outcomes: {markets_processed:,} (BTC: {btc_markets}, ETH: {eth_markets})")

    # Process trades
    processed_trades = []
    matched = 0
    unmatched = 0

    for trade in trades:
        token_id = trade.get('token_id')
        if token_id in token_to_market:
            market_info = token_to_market[token_id]

            # Determine if this trade won
            is_up_token = market_info['is_up_token']
            resolved_up = (market_info['resolved_outcome'] == 'UP')

            # Trade wins if: bought UP and resolved UP, or bought DOWN and resolved DOWN
            side = trade.get('side', 'BUY')
            if side == 'BUY':
                trade_won = (is_up_token == resolved_up)
            else:
                # SELL is exiting a position, not a bet
                continue

            processed_trades.append({
                'timestamp': trade['timestamp'],
                'asset': market_info['asset'],
                'price': trade['price'],
                'usdc_amount': trade['usdc_amount'],
                'token_amount': trade['token_amount'],
                'is_up_bet': is_up_token,
                'resolved_up': resolved_up,
                'won': trade_won,
                'slug': market_info['slug'],
            })
            matched += 1
        else:
            unmatched += 1

    print(f"  Matched trades: {matched:,}")
    print(f"  Unmatched trades: {unmatched:,}")

    df = pd.DataFrame(processed_trades)

    if len(df) > 0:
        # Calculate actual win rate
        actual_win_rate = df['won'].mean()
        print(f"  Actual win rate: {actual_win_rate:.1%}")

        # Group by market window (slug) and take first trade per window
        df_by_window = df.groupby('slug').first().reset_index()
        print(f"  Unique market windows: {len(df_by_window):,}")

        return df_by_window

    return df


def estimate_fee(price: float) -> float:
    """Estimate taker fee based on market price."""
    distance = abs(price - 0.50)
    max_fee = 0.03
    fee = max_fee * (1 - (distance / 0.50) ** 2)
    return max(0.0, fee)


def kelly_fraction(win_prob: float, odds: float) -> float:
    """Calculate Kelly optimal fraction."""
    if win_prob <= 0 or win_prob >= 1 or odds <= 0:
        return 0.0
    q = 1 - win_prob
    kelly = (win_prob * odds - q) / odds
    return max(0.0, min(kelly, 0.5))


def run_backtest(
    trades_df: pd.DataFrame,
    strategy: str,
    initial_capital: float = 300.0,
    expected_win_rate: float = 0.84,
) -> BacktestResult:
    """Run compound growth backtest."""
    capital = initial_capital
    peak_capital = initial_capital
    max_drawdown = 0.0

    equity_curve = [capital]
    returns = []
    wins = 0
    losses = 0
    total_profit = 0.0
    total_loss = 0.0

    for _, trade in trades_df.iterrows():
        if capital < 10:
            break

        price = trade['price']
        fee_rate = estimate_fee(price)

        # Calculate position size based on strategy
        if strategy == 'fixed_1pct':
            position_pct = 0.01
        elif strategy == 'fixed_2pct':
            position_pct = 0.02
        elif strategy == 'fixed_5pct':
            position_pct = 0.05
        elif strategy == 'quarter_kelly':
            odds = (1.0 - fee_rate - price) / price if price > 0 else 0
            position_pct = kelly_fraction(expected_win_rate, odds) * 0.25
        elif strategy == 'half_kelly':
            odds = (1.0 - fee_rate - price) / price if price > 0 else 0
            position_pct = kelly_fraction(expected_win_rate, odds) * 0.5
        elif strategy == 'kelly':
            odds = (1.0 - fee_rate - price) / price if price > 0 else 0
            position_pct = kelly_fraction(expected_win_rate, odds)
        else:
            position_pct = 0.05

        # Cap position size
        position_pct = min(position_pct, 0.20)
        position_size = capital * position_pct

        if position_size < 1:
            continue

        # Calculate P&L
        if trade['won']:
            # Win: receive payout minus fees
            payout = position_size / price * (1.0 - fee_rate)
            profit = payout - position_size
            capital += profit
            wins += 1
            total_profit += profit
            returns.append(profit / (capital - profit))
        else:
            # Lose: lose entire position
            capital -= position_size
            losses += 1
            total_loss += position_size
            returns.append(-position_size / (capital + position_size))

        # Track drawdown
        peak_capital = max(peak_capital, capital)
        drawdown = (peak_capital - capital) / peak_capital
        max_drawdown = max(max_drawdown, drawdown)

        equity_curve.append(capital)

    # Calculate metrics
    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0
    total_return = (capital - initial_capital) / initial_capital * 100
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

    # Sharpe ratio (annualized, assuming ~100 trades/day)
    if len(returns) > 1:
        returns_array = np.array(returns)
        sharpe = (returns_array.mean() / returns_array.std()) * np.sqrt(252 * 100) if returns_array.std() > 0 else 0
    else:
        sharpe = 0

    # Confidence interval for win rate
    if total_trades > 0:
        se = np.sqrt(win_rate * (1 - win_rate) / total_trades)
        ci_low = win_rate - 1.96 * se
        ci_high = win_rate + 1.96 * se
    else:
        ci_low, ci_high = 0, 0

    # Days span
    if len(trades_df) > 0:
        time_span = trades_df['timestamp'].max() - trades_df['timestamp'].min()
        days = time_span / 86400
        trades_per_day = total_trades / days if days > 0 else 0
    else:
        trades_per_day = 0

    return BacktestResult(
        strategy=strategy,
        initial_capital=initial_capital,
        final_capital=capital,
        total_return_pct=total_return,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        max_drawdown_pct=max_drawdown * 100,
        sharpe_ratio=sharpe,
        profit_factor=profit_factor,
        avg_trade_return=total_return / total_trades if total_trades > 0 else 0,
        trades_per_day=trades_per_day,
        confidence_interval_95=(ci_low, ci_high),
    )


def main():
    print("=" * 60)
    print("LARGE DATASET COMPOUND GROWTH BACKTESTER")
    print("=" * 60)
    print()

    # Load data
    trades_df = load_trades_with_outcomes()

    if len(trades_df) == 0:
        print("ERROR: No trades with outcomes found!")
        return

    print()
    print("=" * 60)
    print("RUNNING BACKTESTS")
    print("=" * 60)

    strategies = ['fixed_1pct', 'fixed_2pct', 'fixed_5pct', 'quarter_kelly', 'half_kelly', 'kelly']
    results = []

    # Use actual win rate from data
    actual_win_rate = trades_df['won'].mean()

    for strategy in strategies:
        result = run_backtest(trades_df, strategy, expected_win_rate=actual_win_rate)
        results.append(result)
        print(f"\n{strategy}:")
        print(f"  Final: ${result.final_capital:.2f} ({result.total_return_pct:+.1f}%)")
        print(f"  Trades: {result.total_trades}, Win Rate: {result.win_rate:.1%}")
        print(f"  Max DD: {result.max_drawdown_pct:.1f}%, Sharpe: {result.sharpe_ratio:.2f}")

    # Generate report
    print()
    print("=" * 60)
    print("GENERATING REPORT")
    print("=" * 60)

    report = f"""# Large Dataset Backtest Results

**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
**Dataset:** account88888 trades (2.9M total, {len(trades_df):,} unique windows with outcomes)
**Initial Capital:** $300

---

## Data Summary

| Metric | Value |
|--------|-------|
| Total Trades in Dataset | {len(trades_df):,} |
| Actual Win Rate | {actual_win_rate:.1%} |
| 95% Confidence Interval | {actual_win_rate - 1.96*np.sqrt(actual_win_rate*(1-actual_win_rate)/len(trades_df)):.1%} - {actual_win_rate + 1.96*np.sqrt(actual_win_rate*(1-actual_win_rate)/len(trades_df)):.1%} |
| Time Span | {(trades_df['timestamp'].max() - trades_df['timestamp'].min()) / 86400:.1f} days |
| BTC Trades | {len(trades_df[trades_df['asset']=='BTC']):,} |
| ETH Trades | {len(trades_df[trades_df['asset']=='ETH']):,} |

---

## Backtest Results

| Strategy | Final $ | Return | Win Rate | Max DD | Sharpe | Profit Factor |
|----------|---------|--------|----------|--------|--------|---------------|
"""

    for r in results:
        report += f"| {r.strategy} | ${r.final_capital:.0f} | {r.total_return_pct:+.1f}% | {r.win_rate:.1%} | {r.max_drawdown_pct:.1f}% | {r.sharpe_ratio:.2f} | {r.profit_factor:.2f} |\n"

    report += f"""
---

## Key Findings

### 1. Actual Win Rate: {actual_win_rate:.1%}

This is the **real** win rate from Account88888's trades on BTC/ETH 15-minute markets.
- Sample size: {len(trades_df):,} unique market windows
- Statistically significant (95% CI: {actual_win_rate - 1.96*np.sqrt(actual_win_rate*(1-actual_win_rate)/len(trades_df)):.1%} - {actual_win_rate + 1.96*np.sqrt(actual_win_rate*(1-actual_win_rate)/len(trades_df)):.1%})

### 2. Best Strategy by Return

"""

    best_return = max(results, key=lambda x: x.total_return_pct)
    best_sharpe = max(results, key=lambda x: x.sharpe_ratio)
    lowest_dd = min(results, key=lambda x: x.max_drawdown_pct)

    report += f"""- **Highest Return:** {best_return.strategy} ({best_return.total_return_pct:+.1f}%)
- **Best Risk-Adjusted:** {best_sharpe.strategy} (Sharpe: {best_sharpe.sharpe_ratio:.2f})
- **Lowest Drawdown:** {lowest_dd.strategy} ({lowest_dd.max_drawdown_pct:.1f}%)

### 3. Recommendation

Based on this large-sample backtest:

| Metric | Recommended |
|--------|-------------|
| Strategy | **{best_sharpe.strategy}** |
| Expected Win Rate | {actual_win_rate:.1%} |
| Expected Return | {best_sharpe.total_return_pct:+.1f}% |
| Max Drawdown | {best_sharpe.max_drawdown_pct:.1f}% |

---

## Statistical Notes

- This backtest uses **actual resolved outcomes** from Polymarket
- Takes one trade per 15-minute market window (avoids over-counting)
- Fee model: Variable 0-3% based on market odds
- Kelly calculations use actual observed win rate

---

*Generated by large_dataset_backtester.py*
"""

    # Write report
    report_path = PROJECT_ROOT / "BACKTEST_RESULTS_LARGE.md"
    with open(report_path, 'w') as f:
        f.write(report)

    print(f"\nReport written to: {report_path}")


if __name__ == "__main__":
    main()
