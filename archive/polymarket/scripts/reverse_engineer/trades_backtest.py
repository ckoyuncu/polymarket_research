#!/usr/bin/env python3
"""
Backtest Trading Signals using trades.db

Uses historical trade data to validate signals on a larger sample size.
We use trade prices as a proxy for market sentiment (similar to orderbook imbalance).

Key insight: If traders are paying high prices for UP tokens, that signals bullish sentiment.
"""

import sqlite3
import os
from collections import defaultdict
from typing import Dict, List, Tuple
import statistics

DB_PATH = "data/tracker/trades.db"


def get_market_data(conn) -> Dict[str, Dict]:
    """
    Get all markets with enough trade data to analyze.
    Returns dict of slug -> market data
    """
    cursor = conn.cursor()

    # Get markets with their actual outcomes based on Binance prices
    query = """
    WITH market_summary AS (
        SELECT
            slug,
            asset,
            COUNT(*) as trade_count,
            MIN(timestamp) as first_ts,
            MAX(timestamp) as last_ts,
            MIN(seconds_until_close) as min_secs_to_close
        FROM trades
        WHERE asset IN ('BTC', 'ETH')
          AND slug LIKE '%-updown-15m-%'  -- Only 15-min markets
        GROUP BY slug
        HAVING COUNT(*) >= 10  -- Need enough trades
    )
    SELECT
        ms.slug,
        ms.asset,
        ms.trade_count,
        ms.first_ts,
        ms.last_ts,
        ms.min_secs_to_close,
        -- Get start price (from earliest trade)
        (SELECT binance_btc FROM trades t2
         WHERE t2.slug = ms.slug ORDER BY timestamp ASC LIMIT 1) as start_btc,
        (SELECT binance_eth FROM trades t2
         WHERE t2.slug = ms.slug ORDER BY timestamp ASC LIMIT 1) as start_eth,
        -- Get end price (from latest trade)
        (SELECT binance_btc FROM trades t2
         WHERE t2.slug = ms.slug ORDER BY timestamp DESC LIMIT 1) as end_btc,
        (SELECT binance_eth FROM trades t2
         WHERE t2.slug = ms.slug ORDER BY timestamp DESC LIMIT 1) as end_eth
    FROM market_summary ms
    ORDER BY ms.first_ts
    """

    cursor.execute(query)
    markets = {}

    for row in cursor.fetchall():
        slug, asset, trade_count, first_ts, last_ts, min_secs, start_btc, start_eth, end_btc, end_eth = row

        # Determine actual outcome
        if asset == 'BTC':
            if start_btc and end_btc:
                actual = 'UP' if end_btc > start_btc else 'DOWN'
            else:
                continue
        else:  # ETH
            if start_eth and end_eth:
                actual = 'UP' if end_eth > start_eth else 'DOWN'
            else:
                continue

        markets[slug] = {
            'asset': asset,
            'trade_count': trade_count,
            'actual_outcome': actual,
            'duration': last_ts - first_ts,
            'min_secs_to_close': min_secs
        }

    return markets


def get_trades_for_market(conn, slug: str) -> List[Dict]:
    """Get all trades for a specific market."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT timestamp, outcome, side, price, size, seconds_until_close
        FROM trades
        WHERE slug = ?
        ORDER BY timestamp
    """, (slug,))

    trades = []
    for row in cursor.fetchall():
        ts, outcome, side, price, size, secs = row
        trades.append({
            'timestamp': ts,
            'outcome': outcome,  # UP or DOWN token
            'side': side,
            'price': price,
            'size': size,
            'seconds_until_close': secs
        })
    return trades


def calculate_sentiment_score(trades: List[Dict], time_window: int = None) -> float:
    """
    Calculate a sentiment score from trades.

    Score > 0 = bullish (more/higher priced UP buying)
    Score < 0 = bearish (more/higher priced DOWN buying)

    Uses volume-weighted average prices as sentiment indicator.
    """
    if not trades:
        return 0

    # Filter by time window if specified (seconds until close)
    if time_window:
        trades = [t for t in trades if t['seconds_until_close'] and t['seconds_until_close'] <= time_window]

    if not trades:
        return 0

    up_value = 0  # Total $ value bet on UP
    down_value = 0  # Total $ value bet on DOWN

    for t in trades:
        if t['outcome'] == 'UP':
            if t['side'] == 'BUY':
                # Buying UP at price p means paying p per share
                up_value += t['price'] * t['size']
            else:  # SELL
                # Selling UP means giving up UP exposure
                up_value -= t['price'] * t['size']
        else:  # DOWN
            if t['side'] == 'BUY':
                down_value += t['price'] * t['size']
            else:
                down_value -= t['price'] * t['size']

    total = abs(up_value) + abs(down_value)
    if total == 0:
        return 0

    # Imbalance: positive = more UP buying, negative = more DOWN buying
    return (up_value - down_value) / total


def calculate_price_sentiment(trades: List[Dict], time_window: int = None) -> float:
    """
    Alternative sentiment: Use average price paid for UP vs DOWN.

    If UP price > 0.5, people think UP is more likely.
    If DOWN price > 0.5, people think DOWN is more likely.
    """
    if not trades:
        return 0

    if time_window:
        trades = [t for t in trades if t['seconds_until_close'] and t['seconds_until_close'] <= time_window]

    if not trades:
        return 0

    up_prices = [t['price'] for t in trades if t['outcome'] == 'UP' and t['side'] == 'BUY']
    down_prices = [t['price'] for t in trades if t['outcome'] == 'DOWN' and t['side'] == 'BUY']

    if not up_prices and not down_prices:
        return 0

    avg_up = statistics.mean(up_prices) if up_prices else 0.5
    avg_down = statistics.mean(down_prices) if down_prices else 0.5

    # If UP is priced higher than DOWN, that's bullish
    return avg_up - avg_down


def backtest_signal(markets: Dict, conn, signal_func, signal_name: str, time_window: int = None):
    """
    Backtest a signal function across all markets.
    """
    results = {'BTC': [], 'ETH': []}

    for slug, market in markets.items():
        trades = get_trades_for_market(conn, slug)
        if not trades:
            continue

        # Calculate signal
        signal = signal_func(trades, time_window)
        predicted = 'UP' if signal > 0 else 'DOWN'
        correct = predicted == market['actual_outcome']

        results[market['asset']].append({
            'slug': slug,
            'signal': signal,
            'predicted': predicted,
            'actual': market['actual_outcome'],
            'correct': correct,
            'abs_signal': abs(signal)
        })

    return results


def analyze_results(results: Dict, signal_name: str):
    """Analyze and print backtest results."""

    print(f"\n{'='*60}")
    print(f"BACKTEST RESULTS: {signal_name}")
    print(f"{'='*60}")

    for asset in ['BTC', 'ETH']:
        asset_results = results[asset]
        if not asset_results:
            continue

        print(f"\n--- {asset} ({len(asset_results)} markets) ---")

        # Overall accuracy
        correct = sum(1 for r in asset_results if r['correct'])
        total = len(asset_results)
        print(f"Overall accuracy: {correct}/{total} = {correct/total*100:.1f}%")

        # Accuracy by signal strength (threshold analysis)
        print(f"\nBy signal strength:")
        for threshold in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
            qualifying = [r for r in asset_results if r['abs_signal'] >= threshold]
            if qualifying:
                correct = sum(1 for r in qualifying if r['correct'])
                pct = correct/len(qualifying)*100
                print(f"  |signal| >= {threshold}: {correct}/{len(qualifying)} = {pct:.1f}% ({len(qualifying)} trades)")


def main():
    print(f"\n{'='*70}")
    print("TRADES DATABASE BACKTEST")
    print(f"{'='*70}")

    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)

    # Get all markets
    markets = get_market_data(conn)
    print(f"\nLoaded {len(markets)} markets with trade data")

    btc_count = sum(1 for m in markets.values() if m['asset'] == 'BTC')
    eth_count = sum(1 for m in markets.values() if m['asset'] == 'ETH')
    print(f"  BTC: {btc_count} markets")
    print(f"  ETH: {eth_count} markets")

    # Test 1: Volume-weighted sentiment (all trades)
    print("\n" + "="*60)
    print("TEST 1: Volume-Weighted Trade Sentiment (all trades)")
    print("="*60)
    results = backtest_signal(markets, conn, calculate_sentiment_score, "Volume Sentiment")
    analyze_results(results, "Volume-Weighted Sentiment")

    # Test 2: Volume-weighted sentiment (final 60 seconds)
    print("\n" + "="*60)
    print("TEST 2: Volume-Weighted Sentiment (final 60 seconds)")
    print("="*60)
    results = backtest_signal(markets, conn, calculate_sentiment_score, "Volume Sentiment 60s", time_window=60)
    analyze_results(results, "Volume Sentiment (60s window)")

    # Test 3: Price-based sentiment (all trades)
    print("\n" + "="*60)
    print("TEST 3: Price-Based Sentiment (UP price vs DOWN price)")
    print("="*60)
    results = backtest_signal(markets, conn, calculate_price_sentiment, "Price Sentiment")
    analyze_results(results, "Price-Based Sentiment")

    # Test 4: Price-based sentiment (final 60 seconds)
    print("\n" + "="*60)
    print("TEST 4: Price-Based Sentiment (final 60 seconds)")
    print("="*60)
    results = backtest_signal(markets, conn, calculate_price_sentiment, "Price Sentiment 60s", time_window=60)
    analyze_results(results, "Price Sentiment (60s window)")

    conn.close()

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print("""
This backtest uses TRADE PRICES as a proxy for market sentiment.
Compare these results to the orderbook-based analysis to validate.

Key questions:
1. Do the trade-based signals show similar accuracy to orderbook signals?
2. Does the signal improve in the final 60 seconds?
3. Does higher signal strength = better accuracy?
""")


if __name__ == "__main__":
    main()
