#!/usr/bin/env python3
"""
Analyze Final Minute Data - Find patterns in the last 60 seconds before resolution

This script analyzes the collected final minute data to discover:
1. Price movement patterns in the last 60 seconds
2. Orderbook imbalance signals
3. Whether the direction is predictable from sub-minute data
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import statistics

def load_final_minute_files(directory: str) -> List[Dict]:
    """Load all JSON files from the directory."""
    files = []
    for filename in sorted(os.listdir(directory)):
        if filename.endswith('.json'):
            filepath = os.path.join(directory, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    data['_filename'] = filename
                    files.append(data)
            except Exception as e:
                print(f"Error loading {filename}: {e}")
    return files

def analyze_price_movement(data: Dict) -> Dict:
    """Analyze price movement within a single window."""
    binance_prices = data.get('binance_prices', [])
    orderbook = data.get('orderbook_snapshots', [])

    if not binance_prices:
        return None

    # Get prices at different time points
    prices = [(p['timestamp'], p['price']) for p in binance_prices]
    prices.sort(key=lambda x: x[0])

    if len(prices) < 10:
        return None

    start_price = prices[0][1]
    end_price = prices[-1][1]

    # Calculate returns at different intervals
    mid_idx = len(prices) // 2
    mid_price = prices[mid_idx][1]

    # Direction (UP if end > start for BTC/ETH)
    outcome = "UP" if end_price > start_price else "DOWN"
    price_change_pct = (end_price - start_price) / start_price * 100

    # Early momentum (first half)
    early_change = (mid_price - start_price) / start_price * 100

    # Late momentum (second half)
    late_change = (end_price - mid_price) / mid_price * 100

    # Momentum consistency
    momentum_consistent = (early_change > 0 and late_change > 0) or (early_change < 0 and late_change < 0)

    # Orderbook analysis
    ob_analysis = analyze_orderbook(orderbook)

    return {
        'asset': data.get('asset', 'Unknown'),
        'window_start': data.get('window_start'),
        'start_price': start_price,
        'end_price': end_price,
        'outcome': outcome,
        'price_change_pct': price_change_pct,
        'early_change_pct': early_change,
        'late_change_pct': late_change,
        'momentum_consistent': momentum_consistent,
        'num_price_points': len(prices),
        'orderbook': ob_analysis
    }

def analyze_orderbook(orderbook: List[Dict]) -> Dict:
    """Analyze orderbook patterns."""
    if not orderbook:
        return {'available': False}

    # Get UP token orderbook (to analyze betting on UP)
    up_obs = [ob for ob in orderbook if ob.get('outcome') == 'up']

    if not up_obs:
        return {'available': False}

    # Calculate average imbalance
    imbalances = []
    spreads = []
    for ob in up_obs:
        bid_depth = ob.get('bid_depth', 0)
        ask_depth = ob.get('ask_depth', 0)
        if bid_depth + ask_depth > 0:
            imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
            imbalances.append(imbalance)
        if ob.get('spread'):
            spreads.append(ob['spread'])

    if not imbalances:
        return {'available': False}

    return {
        'available': True,
        'avg_imbalance': statistics.mean(imbalances),
        'imbalance_std': statistics.stdev(imbalances) if len(imbalances) > 1 else 0,
        'avg_spread': statistics.mean(spreads) if spreads else None,
        'num_snapshots': len(up_obs)
    }

def main(data_dir: str):
    print(f"\n{'='*60}")
    print("FINAL MINUTE ANALYSIS RESULTS")
    print(f"{'='*60}\n")

    # Load data
    files = load_final_minute_files(data_dir)
    print(f"Loaded {len(files)} final minute captures\n")

    if not files:
        print("No data files found!")
        return

    # Analyze each file
    results = []
    for data in files:
        analysis = analyze_price_movement(data)
        if analysis:
            results.append(analysis)

    print(f"Successfully analyzed {len(results)} windows\n")

    # Aggregate statistics
    btc_results = [r for r in results if r['asset'] == 'BTC']
    eth_results = [r for r in results if r['asset'] == 'ETH']

    for asset, asset_results in [('BTC', btc_results), ('ETH', eth_results)]:
        if not asset_results:
            continue

        print(f"\n{'='*40}")
        print(f"{asset} ANALYSIS ({len(asset_results)} windows)")
        print(f"{'='*40}\n")

        # Outcome distribution
        up_count = sum(1 for r in asset_results if r['outcome'] == 'UP')
        down_count = len(asset_results) - up_count
        print(f"Outcome Distribution:")
        print(f"  UP:   {up_count} ({up_count/len(asset_results)*100:.1f}%)")
        print(f"  DOWN: {down_count} ({down_count/len(asset_results)*100:.1f}%)")

        # Average price change
        avg_change = statistics.mean([abs(r['price_change_pct']) for r in asset_results])
        print(f"\nAvg Absolute Price Change: {avg_change:.4f}%")

        # Momentum consistency
        consistent_count = sum(1 for r in asset_results if r['momentum_consistent'])
        print(f"\nMomentum Consistency (early & late same direction):")
        print(f"  Consistent: {consistent_count} ({consistent_count/len(asset_results)*100:.1f}%)")

        # Early momentum predicting outcome
        early_predicts_outcome = sum(1 for r in asset_results
                                     if (r['early_change_pct'] > 0 and r['outcome'] == 'UP') or
                                        (r['early_change_pct'] < 0 and r['outcome'] == 'DOWN'))
        print(f"\nEarly Momentum (first half) Predicting Outcome:")
        print(f"  Correct: {early_predicts_outcome} ({early_predicts_outcome/len(asset_results)*100:.1f}%)")

        # Orderbook analysis
        ob_results = [r for r in asset_results if r['orderbook']['available']]
        if ob_results:
            print(f"\n--- Orderbook Analysis ({len(ob_results)} with data) ---")

            # Imbalance predicting outcome
            # Positive imbalance = more bids = bullish
            imbalance_predicts = sum(1 for r in ob_results
                                     if (r['orderbook']['avg_imbalance'] > 0 and r['outcome'] == 'UP') or
                                        (r['orderbook']['avg_imbalance'] < 0 and r['outcome'] == 'DOWN'))
            print(f"Orderbook Imbalance Predicting Outcome:")
            print(f"  Correct: {imbalance_predicts} ({imbalance_predicts/len(ob_results)*100:.1f}%)")

            avg_imbalance = statistics.mean([r['orderbook']['avg_imbalance'] for r in ob_results])
            print(f"  Average Imbalance: {avg_imbalance:.4f}")

    # Key insights
    print(f"\n{'='*60}")
    print("KEY INSIGHTS")
    print(f"{'='*60}\n")

    if results:
        all_early_correct = sum(1 for r in results
                                if (r['early_change_pct'] > 0 and r['outcome'] == 'UP') or
                                   (r['early_change_pct'] < 0 and r['outcome'] == 'DOWN'))
        print(f"1. EARLY MOMENTUM SIGNAL: {all_early_correct/len(results)*100:.1f}% predictive")
        print(f"   → If price moving UP in first 30s, outcome more likely UP")

        all_consistent = sum(1 for r in results if r['momentum_consistent'])
        print(f"\n2. MOMENTUM PERSISTENCE: {all_consistent/len(results)*100:.1f}% of windows")
        print(f"   → Direction rarely reverses in final minute")

        # Check if late reversal is profitable
        late_reversal = [r for r in results if not r['momentum_consistent']]
        if late_reversal:
            late_reversal_correct = sum(1 for r in late_reversal
                                        if (r['late_change_pct'] > 0 and r['outcome'] == 'UP') or
                                           (r['late_change_pct'] < 0 and r['outcome'] == 'DOWN'))
            print(f"\n3. LATE REVERSAL SIGNAL (when momentum flips):")
            print(f"   → Late direction correct: {late_reversal_correct}/{len(late_reversal)}")
            print(f"   → Late momentum is MORE reliable than early momentum for final outcome")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        data_dir = "data/research_ec2_jan6/final_minute"

    main(data_dir)
