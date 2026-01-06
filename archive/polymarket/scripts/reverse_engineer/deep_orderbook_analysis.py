#!/usr/bin/env python3
"""
Deep Orderbook Signal Analysis

Analyzes the 77.8% accurate orderbook imbalance signal to:
1. Time-weighted analysis - does signal improve closer to resolution?
2. Threshold analysis - does higher |imbalance| = better accuracy?
3. Combined signals - orderbook + momentum together
4. Spread analysis - does spread correlate with reliability?
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import statistics
from collections import defaultdict

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


def get_actual_outcome(data: Dict) -> str:
    """Determine the actual outcome from price data."""
    return "UP" if data['end_price'] > data['start_price'] else "DOWN"


def calculate_imbalance(orderbook_snapshots: List[Dict], outcome_filter: str = "up") -> List[Tuple[float, float]]:
    """
    Calculate imbalance values with timestamps for a specific outcome token.
    Returns list of (seconds_before_end, imbalance) tuples.
    """
    imbalances = []
    for ob in orderbook_snapshots:
        if ob.get('outcome') != outcome_filter:
            continue
        bid_depth = ob.get('bid_depth', 0) or 0
        ask_depth = ob.get('ask_depth', 0) or 0
        if bid_depth + ask_depth > 0:
            imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
            imbalances.append((ob['timestamp'], imbalance, bid_depth, ask_depth))
    return imbalances


def analyze_time_weighted(data: Dict, window_end: int) -> Dict:
    """
    Analyze imbalance at different time windows before resolution.
    """
    orderbook = data.get('orderbook_snapshots', [])
    if not orderbook:
        return None

    imbalances = calculate_imbalance(orderbook, "up")
    if not imbalances:
        return None

    result = {
        'actual_outcome': get_actual_outcome(data),
        'time_windows': {}
    }

    # Analyze at different time windows: 60s, 30s, 15s, 10s, 5s before end
    for window_name, seconds_before in [('60s', 60), ('30s', 30), ('15s', 15), ('10s', 10), ('5s', 5)]:
        cutoff_time = window_end - seconds_before
        window_imbalances = [imb for ts, imb, _, _ in imbalances if ts >= cutoff_time]

        if window_imbalances:
            avg_imbalance = statistics.mean(window_imbalances)
            result['time_windows'][window_name] = {
                'avg_imbalance': avg_imbalance,
                'num_snapshots': len(window_imbalances),
                'predicted_outcome': 'UP' if avg_imbalance > 0 else 'DOWN'
            }

    return result


def analyze_threshold(data: Dict) -> Dict:
    """
    Analyze if higher absolute imbalance thresholds improve accuracy.
    """
    orderbook = data.get('orderbook_snapshots', [])
    if not orderbook:
        return None

    imbalances = calculate_imbalance(orderbook, "up")
    if not imbalances:
        return None

    avg_imbalance = statistics.mean([imb for _, imb, _, _ in imbalances])
    actual_outcome = get_actual_outcome(data)

    result = {
        'actual_outcome': actual_outcome,
        'avg_imbalance': avg_imbalance,
        'abs_imbalance': abs(avg_imbalance),
        'predicted_outcome': 'UP' if avg_imbalance > 0 else 'DOWN',
        'thresholds': {}
    }

    # Test different thresholds
    for threshold in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
        if abs(avg_imbalance) >= threshold:
            result['thresholds'][f't{threshold}'] = {
                'qualifies': True,
                'predicted': 'UP' if avg_imbalance > 0 else 'DOWN',
                'correct': (avg_imbalance > 0 and actual_outcome == 'UP') or
                          (avg_imbalance < 0 and actual_outcome == 'DOWN')
            }
        else:
            result['thresholds'][f't{threshold}'] = {'qualifies': False}

    return result


def analyze_combined_signals(data: Dict) -> Dict:
    """
    Analyze combined orderbook + momentum signals.
    """
    orderbook = data.get('orderbook_snapshots', [])
    binance_prices = data.get('binance_prices', [])

    if not orderbook or not binance_prices:
        return None

    imbalances = calculate_imbalance(orderbook, "up")
    if not imbalances:
        return None

    # Calculate orderbook signal
    avg_imbalance = statistics.mean([imb for _, imb, _, _ in imbalances])
    ob_signal = 'UP' if avg_imbalance > 0 else 'DOWN'

    # Calculate momentum signals
    prices = sorted([(p['timestamp'], p['price']) for p in binance_prices], key=lambda x: x[0])
    if len(prices) < 10:
        return None

    start_price = prices[0][1]
    end_price = prices[-1][1]
    mid_idx = len(prices) // 2
    mid_price = prices[mid_idx][1]

    # Early momentum (first half)
    early_change = mid_price - start_price
    early_signal = 'UP' if early_change > 0 else 'DOWN'

    # Late momentum (last 30%)
    late_idx = int(len(prices) * 0.7)
    late_price = prices[late_idx][1]
    late_change = end_price - late_price
    late_signal = 'UP' if late_change > 0 else 'DOWN'

    actual_outcome = get_actual_outcome(data)

    return {
        'actual_outcome': actual_outcome,
        'ob_signal': ob_signal,
        'ob_imbalance': avg_imbalance,
        'early_momentum_signal': early_signal,
        'early_change_pct': (mid_price - start_price) / start_price * 100,
        'late_momentum_signal': late_signal,
        'late_change_pct': (end_price - late_price) / late_price * 100,
        'ob_correct': ob_signal == actual_outcome,
        'early_correct': early_signal == actual_outcome,
        'late_correct': late_signal == actual_outcome,
        'ob_and_early_agree': ob_signal == early_signal,
        'ob_and_late_agree': ob_signal == late_signal,
        'all_agree': ob_signal == early_signal == late_signal
    }


def analyze_spread(data: Dict) -> Dict:
    """
    Analyze if spread correlates with signal reliability.
    """
    orderbook = data.get('orderbook_snapshots', [])
    if not orderbook:
        return None

    # Get UP token orderbook with spread data
    spreads = []
    imbalances = []

    for ob in orderbook:
        if ob.get('outcome') != 'up':
            continue

        best_bid = ob.get('best_bid')
        best_ask = ob.get('best_ask')

        if best_bid is not None and best_ask is not None:
            spread = best_ask - best_bid
            spreads.append(spread)

        bid_depth = ob.get('bid_depth', 0) or 0
        ask_depth = ob.get('ask_depth', 0) or 0
        if bid_depth + ask_depth > 0:
            imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
            imbalances.append(imbalance)

    if not imbalances:
        return None

    avg_imbalance = statistics.mean(imbalances)
    actual_outcome = get_actual_outcome(data)
    ob_correct = (avg_imbalance > 0 and actual_outcome == 'UP') or \
                 (avg_imbalance < 0 and actual_outcome == 'DOWN')

    result = {
        'actual_outcome': actual_outcome,
        'avg_imbalance': avg_imbalance,
        'ob_correct': ob_correct
    }

    if spreads:
        result['avg_spread'] = statistics.mean(spreads)
        result['min_spread'] = min(spreads)
        result['max_spread'] = max(spreads)
        result['spread_std'] = statistics.stdev(spreads) if len(spreads) > 1 else 0

    return result


def main(data_dir: str):
    print(f"\n{'='*70}")
    print("DEEP ORDERBOOK SIGNAL ANALYSIS")
    print(f"{'='*70}\n")

    # Load data
    files = load_final_minute_files(data_dir)
    print(f"Loaded {len(files)} final minute captures\n")

    if not files:
        print("No data files found!")
        return

    # Separate by asset
    btc_files = [f for f in files if f.get('asset') == 'BTC']
    eth_files = [f for f in files if f.get('asset') == 'ETH']

    for asset, asset_files in [('BTC', btc_files), ('ETH', eth_files)]:
        if not asset_files:
            continue

        print(f"\n{'='*70}")
        print(f"{asset} ANALYSIS ({len(asset_files)} windows)")
        print(f"{'='*70}\n")

        # ========================================
        # 1. TIME-WEIGHTED ANALYSIS
        # ========================================
        print(f"--- 1. TIME-WEIGHTED ANALYSIS ---")
        print("Does the signal improve closer to resolution?\n")

        time_results = []
        for data in asset_files:
            result = analyze_time_weighted(data, data['window_end'])
            if result:
                time_results.append(result)

        if time_results:
            for window in ['60s', '30s', '15s', '10s', '5s']:
                window_data = [(r['time_windows'].get(window), r['actual_outcome'])
                              for r in time_results if window in r.get('time_windows', {})]
                if window_data:
                    correct = sum(1 for tw, actual in window_data
                                 if tw['predicted_outcome'] == actual)
                    total = len(window_data)
                    print(f"  {window} before resolution: {correct}/{total} = {correct/total*100:.1f}% accuracy")

        # ========================================
        # 2. THRESHOLD ANALYSIS
        # ========================================
        print(f"\n--- 2. THRESHOLD ANALYSIS ---")
        print("Does higher |imbalance| threshold improve accuracy?\n")

        threshold_results = []
        for data in asset_files:
            result = analyze_threshold(data)
            if result:
                threshold_results.append(result)

        if threshold_results:
            for threshold in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
                key = f't{threshold}'
                qualifying = [r for r in threshold_results
                             if r['thresholds'][key].get('qualifies', False)]
                if qualifying:
                    correct = sum(1 for r in qualifying if r['thresholds'][key]['correct'])
                    total = len(qualifying)
                    pct = correct/total*100
                    print(f"  |imbalance| >= {threshold}: {correct}/{total} = {pct:.1f}% accuracy ({total} trades)")

        # ========================================
        # 3. COMBINED SIGNALS ANALYSIS
        # ========================================
        print(f"\n--- 3. COMBINED SIGNALS ANALYSIS ---")
        print("Does combining orderbook + momentum improve accuracy?\n")

        combined_results = []
        for data in asset_files:
            result = analyze_combined_signals(data)
            if result:
                combined_results.append(result)

        if combined_results:
            # Individual signal accuracy
            ob_correct = sum(1 for r in combined_results if r['ob_correct'])
            early_correct = sum(1 for r in combined_results if r['early_correct'])
            late_correct = sum(1 for r in combined_results if r['late_correct'])
            total = len(combined_results)

            print(f"  Individual Signal Accuracy:")
            print(f"    Orderbook alone:      {ob_correct}/{total} = {ob_correct/total*100:.1f}%")
            print(f"    Early momentum alone: {early_correct}/{total} = {early_correct/total*100:.1f}%")
            print(f"    Late momentum alone:  {late_correct}/{total} = {late_correct/total*100:.1f}%")

            # Combined signals - when they agree
            ob_early_agree = [r for r in combined_results if r['ob_and_early_agree']]
            if ob_early_agree:
                correct = sum(1 for r in ob_early_agree if r['ob_correct'])
                print(f"\n  When OB + Early Momentum agree ({len(ob_early_agree)} cases):")
                print(f"    Accuracy: {correct}/{len(ob_early_agree)} = {correct/len(ob_early_agree)*100:.1f}%")

            ob_late_agree = [r for r in combined_results if r['ob_and_late_agree']]
            if ob_late_agree:
                correct = sum(1 for r in ob_late_agree if r['ob_correct'])
                print(f"\n  When OB + Late Momentum agree ({len(ob_late_agree)} cases):")
                print(f"    Accuracy: {correct}/{len(ob_late_agree)} = {correct/len(ob_late_agree)*100:.1f}%")

            all_agree = [r for r in combined_results if r['all_agree']]
            if all_agree:
                correct = sum(1 for r in all_agree if r['ob_correct'])
                print(f"\n  When ALL signals agree ({len(all_agree)} cases):")
                print(f"    Accuracy: {correct}/{len(all_agree)} = {correct/len(all_agree)*100:.1f}%")

            # When signals disagree - who wins?
            ob_early_disagree = [r for r in combined_results if not r['ob_and_early_agree']]
            if ob_early_disagree:
                ob_wins = sum(1 for r in ob_early_disagree if r['ob_correct'])
                early_wins = sum(1 for r in ob_early_disagree if r['early_correct'])
                print(f"\n  When OB vs Early Momentum DISAGREE ({len(ob_early_disagree)} cases):")
                print(f"    Orderbook correct:      {ob_wins}/{len(ob_early_disagree)} = {ob_wins/len(ob_early_disagree)*100:.1f}%")
                print(f"    Early momentum correct: {early_wins}/{len(ob_early_disagree)} = {early_wins/len(ob_early_disagree)*100:.1f}%")

        # ========================================
        # 4. SPREAD ANALYSIS
        # ========================================
        print(f"\n--- 4. SPREAD ANALYSIS ---")
        print("Does spread correlate with signal reliability?\n")

        spread_results = []
        for data in asset_files:
            result = analyze_spread(data)
            if result and 'avg_spread' in result:
                spread_results.append(result)

        if spread_results:
            # Categorize by spread
            tight_spread = [r for r in spread_results if r['avg_spread'] < 0.03]
            medium_spread = [r for r in spread_results if 0.03 <= r['avg_spread'] < 0.06]
            wide_spread = [r for r in spread_results if r['avg_spread'] >= 0.06]

            for name, group in [('Tight (<3%)', tight_spread),
                               ('Medium (3-6%)', medium_spread),
                               ('Wide (>6%)', wide_spread)]:
                if group:
                    correct = sum(1 for r in group if r['ob_correct'])
                    print(f"  {name}: {correct}/{len(group)} = {correct/len(group)*100:.1f}% accuracy")

            # Correlation between spread and correctness
            correct_spreads = [r['avg_spread'] for r in spread_results if r['ob_correct']]
            incorrect_spreads = [r['avg_spread'] for r in spread_results if not r['ob_correct']]

            if correct_spreads and incorrect_spreads:
                print(f"\n  Avg spread when CORRECT:   {statistics.mean(correct_spreads):.4f}")
                print(f"  Avg spread when INCORRECT: {statistics.mean(incorrect_spreads):.4f}")
        else:
            print("  No spread data available (ask_price often null)")

    # ========================================
    # TRADING RULES SUMMARY
    # ========================================
    print(f"\n{'='*70}")
    print("TRADING RULES SUMMARY")
    print(f"{'='*70}\n")

    # Best performing configurations for BTC
    if btc_files:
        print("RECOMMENDED BTC TRADING RULES:")
        print("-" * 40)

        # Find best threshold
        threshold_results = []
        for data in btc_files:
            result = analyze_threshold(data)
            if result:
                threshold_results.append(result)

        best_threshold = None
        best_accuracy = 0
        best_trades = 0

        for threshold in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]:
            key = f't{threshold}'
            qualifying = [r for r in threshold_results
                         if r['thresholds'][key].get('qualifies', False)]
            if qualifying and len(qualifying) >= 5:  # Minimum sample
                correct = sum(1 for r in qualifying if r['thresholds'][key]['correct'])
                accuracy = correct / len(qualifying)
                if accuracy > best_accuracy or (accuracy == best_accuracy and len(qualifying) > best_trades):
                    best_accuracy = accuracy
                    best_threshold = threshold
                    best_trades = len(qualifying)

        if best_threshold is not None:
            print(f"\n1. THRESHOLD RULE:")
            print(f"   Trade when |orderbook imbalance| >= {best_threshold}")
            print(f"   Expected accuracy: {best_accuracy*100:.1f}%")
            print(f"   Trade frequency: {best_trades}/{len(threshold_results)} windows")

        # Best time window
        time_results = []
        for data in btc_files:
            result = analyze_time_weighted(data, data['window_end'])
            if result:
                time_results.append(result)

        if time_results:
            best_window = None
            best_window_accuracy = 0

            for window in ['60s', '30s', '15s', '10s', '5s']:
                window_data = [(r['time_windows'].get(window), r['actual_outcome'])
                              for r in time_results if window in r.get('time_windows', {})]
                if window_data:
                    correct = sum(1 for tw, actual in window_data
                                 if tw['predicted_outcome'] == actual)
                    accuracy = correct / len(window_data)
                    if accuracy > best_window_accuracy:
                        best_window_accuracy = accuracy
                        best_window = window

            if best_window:
                print(f"\n2. TIMING RULE:")
                print(f"   Use orderbook signal from {best_window} before resolution")
                print(f"   Expected accuracy: {best_window_accuracy*100:.1f}%")

        # Combined signal rule
        combined_results = []
        for data in btc_files:
            result = analyze_combined_signals(data)
            if result:
                combined_results.append(result)

        if combined_results:
            all_agree = [r for r in combined_results if r['all_agree']]
            if all_agree:
                correct = sum(1 for r in all_agree if r['ob_correct'])
                accuracy = correct / len(all_agree)
                print(f"\n3. CONFIRMATION RULE:")
                print(f"   Only trade when OB + early + late momentum ALL agree")
                print(f"   Expected accuracy: {accuracy*100:.1f}%")
                print(f"   Trade frequency: {len(all_agree)}/{len(combined_results)} windows")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]
    else:
        data_dir = "data/research_ec2_jan6/final_minute"

    main(data_dir)
