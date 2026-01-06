#!/usr/bin/env python3
"""
Outcome Predictor

Predicts actual market outcome (UP or DOWN resolution) using the same features
we used to predict Account88888's betting direction.

This allows comparison:
- signal_discovery_model.py: Predicts 88888's DIRECTION (what they bet)
- outcome_predictor.py: Predicts market OUTCOME (what actually happened)

If both have similar feature importance, 88888 is using public information.
If they differ, 88888 has private information we can't see.

Usage:
    python scripts/reverse_engineer/outcome_predictor.py

Requires: Features from feature_engineering.py and Binance data for outcomes
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_features(features_file: str) -> pd.DataFrame:
    """Load features from parquet file."""
    print(f"Loading features from {features_file}...")
    df = pd.read_parquet(features_file)
    print(f"  Loaded {len(df):,} feature vectors")
    return df


def load_binance_klines(klines_file: str) -> pd.DataFrame:
    """Load Binance klines for outcome determination."""
    print(f"Loading Binance klines from {klines_file}...")
    df = pd.read_csv(klines_file)
    print(f"  Loaded {len(df):,} klines")
    return df


def determine_market_outcome(row: pd.Series, klines_df: pd.DataFrame) -> Optional[int]:
    """
    Determine actual market outcome based on Binance price.

    A 15-minute UP/DOWN market resolves UP if:
    - Price at window_end > Price at window_start

    Returns: 1 for UP, 0 for DOWN, None if can't determine
    """
    asset = row.get('asset')
    window_start = row.get('window_start')
    window_end = row.get('window_end')

    if not asset or not window_start or not window_end:
        return None

    # Map asset to Binance symbol
    symbol_map = {
        'BTC': 'BTCUSDT',
        'ETH': 'ETHUSDT',
        'SOL': 'SOLUSDT',
        'XRP': 'XRPUSDT',
    }
    symbol = symbol_map.get(asset)
    if not symbol:
        return None

    # Get prices at window start and end
    symbol_klines = klines_df[klines_df['symbol'] == symbol]

    # Find closest kline to window start
    start_klines = symbol_klines[
        (symbol_klines['open_time'] >= (window_start - 60) * 1000) &
        (symbol_klines['open_time'] <= (window_start + 60) * 1000)
    ]

    # Find closest kline to window end
    end_klines = symbol_klines[
        (symbol_klines['open_time'] >= (window_end - 60) * 1000) &
        (symbol_klines['open_time'] <= (window_end + 60) * 1000)
    ]

    if len(start_klines) == 0 or len(end_klines) == 0:
        return None

    start_price = start_klines.iloc[0]['open']
    end_price = end_klines.iloc[-1]['close']

    # Determine outcome
    if end_price > start_price:
        return 1  # UP
    elif end_price < start_price:
        return 0  # DOWN
    else:
        return None  # Tie - rare


def add_outcomes(features_df: pd.DataFrame, klines_df: pd.DataFrame) -> pd.DataFrame:
    """Add actual market outcome to features."""
    print("\nDetermining market outcomes...")

    outcomes = []
    for idx, row in features_df.iterrows():
        outcome = determine_market_outcome(row, klines_df)
        outcomes.append(outcome)

    features_df['actual_outcome'] = outcomes

    valid_outcomes = features_df['actual_outcome'].notna().sum()
    print(f"  Determined outcomes for {valid_outcomes:,} / {len(features_df):,} trades")

    # Distribution
    if valid_outcomes > 0:
        up_pct = features_df['actual_outcome'].mean() * 100
        print(f"  Outcome distribution: {up_pct:.1f}% UP, {100-up_pct:.1f}% DOWN")

    return features_df


def train_outcome_model(features_df: pd.DataFrame) -> Tuple:
    """Train model to predict actual market outcome."""
    try:
        from xgboost import XGBClassifier
    except ImportError:
        print("Installing xgboost...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "xgboost", "-q"])
        from xgboost import XGBClassifier

    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import accuracy_score, classification_report

    print("\n" + "=" * 60)
    print("TRAINING OUTCOME PREDICTION MODEL")
    print("=" * 60)

    # Filter to trades with outcomes
    df = features_df.dropna(subset=['actual_outcome']).copy()
    print(f"\nUsing {len(df):,} trades with known outcomes")

    # Aggregate to market level (one prediction per market)
    market_features = df.groupby('slug').agg({
        'actual_outcome': 'first',  # Same for all trades in market
        'momentum_from_window_start': 'mean',
        'momentum_1min': 'mean',
        'momentum_5min': 'mean',
        'momentum_10min': 'mean',
        'volatility_5min': 'mean',
        'volatility_10min': 'mean',
        'rsi_14min': 'mean',
        'price': 'mean',
        'window_fraction': 'mean',
        'seconds_to_resolution': 'mean',
        'usdc_amount': 'sum',
        'btc_momentum_5min': 'mean',
    }).reset_index()

    print(f"Aggregated to {len(market_features):,} unique markets")

    # Feature columns
    feature_cols = [
        'momentum_from_window_start',
        'momentum_1min',
        'momentum_5min',
        'momentum_10min',
        'volatility_5min',
        'volatility_10min',
        'rsi_14min',
        'price',
        'window_fraction',
        'seconds_to_resolution',
        'btc_momentum_5min',
    ]

    # Filter to available columns
    available_cols = [c for c in feature_cols if c in market_features.columns]
    print(f"Using {len(available_cols)} features")

    # Prepare data
    X = market_features[available_cols].fillna(0)
    y = market_features['actual_outcome'].astype(int)

    # Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print(f"\nTrain set: {len(X_train):,} markets")
    print(f"Test set: {len(X_test):,} markets")

    # Train
    model = XGBClassifier(
        n_estimators=100,
        max_depth=4,
        learning_rate=0.1,
        random_state=42,
        eval_metric='logloss',
    )

    model.fit(X_train, y_train)

    # Evaluate
    train_pred = model.predict(X_train)
    test_pred = model.predict(X_test)

    train_acc = accuracy_score(y_train, train_pred)
    test_acc = accuracy_score(y_test, test_pred)

    print(f"\n--- Model Performance ---")
    print(f"Train accuracy: {train_acc:.1%}")
    print(f"Test accuracy: {test_acc:.1%}")

    # Cross-validation
    cv_scores = cross_val_score(model, X, y, cv=5)
    print(f"Cross-validation: {cv_scores.mean():.1%} (+/- {cv_scores.std()*2:.1%})")

    # Feature importance
    importance = pd.DataFrame({
        'feature': available_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    print(f"\n--- Feature Importance (Predicting OUTCOME) ---")
    for _, row in importance.head(10).iterrows():
        print(f"  {row['feature']}: {row['importance']*100:.1f}%")

    return model, importance, test_acc


def compare_with_direction_model(outcome_importance: pd.DataFrame):
    """Compare with direction prediction model."""
    print("\n" + "=" * 60)
    print("COMPARISON: OUTCOME vs DIRECTION PREDICTION")
    print("=" * 60)

    # Load direction model importance if available
    direction_file = PROJECT_ROOT / "data" / "models" / "feature_importance.csv"

    if not direction_file.exists():
        print("\nNo direction model importance found.")
        print("Run signal_discovery_model.py first.")
        return

    direction_importance = pd.read_csv(direction_file)

    print("\n| Feature | Outcome Pred | Direction Pred | Diff |")
    print("|---------|--------------|----------------|------|")

    # Merge
    merged = outcome_importance.merge(
        direction_importance,
        on='feature',
        suffixes=('_outcome', '_direction'),
        how='outer'
    ).fillna(0)

    for _, row in merged.head(10).iterrows():
        outcome_imp = row.get('importance_outcome', 0) * 100
        direction_imp = row.get('importance_direction', 0) * 100
        diff = abs(outcome_imp - direction_imp)
        print(f"| {row['feature'][:20]:20s} | {outcome_imp:11.1f}% | {direction_imp:14.1f}% | {diff:4.1f}% |")

    print("\n--- Interpretation ---")
    print("If features rank SIMILARLY for both models:")
    print("  → Account88888 uses publicly available signals")
    print("  → Their edge comes from EXECUTION, not INFORMATION")
    print()
    print("If features rank DIFFERENTLY:")
    print("  → Account88888 has private information")
    print("  → Features that predict 88888 but NOT outcome = their secret signal")


def main():
    """Run outcome predictor."""
    print("=" * 60)
    print("OUTCOME PREDICTOR")
    print("=" * 60)
    print()
    print("Predicting actual market outcome (UP/DOWN resolution)")
    print("to compare with Account88888's direction prediction.")
    print()

    # Load data
    features_file = PROJECT_ROOT / "data" / "features" / "account88888_features_sample50000.parquet"
    klines_file = PROJECT_ROOT / "data" / "binance_klines_full.csv"

    if not features_file.exists():
        print(f"Features file not found: {features_file}")
        print("Run feature_engineering.py first.")
        return

    if not klines_file.exists():
        print(f"Klines file not found: {klines_file}")
        return

    features_df = load_features(features_file)
    klines_df = load_binance_klines(klines_file)

    # Add outcomes
    features_df = add_outcomes(features_df, klines_df)

    # Train model
    model, importance, test_acc = train_outcome_model(features_df)

    # Compare with direction model
    compare_with_direction_model(importance)

    # Save importance
    output_dir = PROJECT_ROOT / "data" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    importance_file = output_dir / "outcome_feature_importance.csv"
    importance.to_csv(importance_file, index=False)
    print(f"\nSaved outcome feature importance to: {importance_file}")

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"\nOutcome prediction accuracy: {test_acc:.1%}")
    print(f"Direction prediction accuracy: ~74% (from signal_discovery_model)")
    print()

    if test_acc > 0.55:
        print("Outcome IS predictable from these features.")
        print("Account88888 may just be better at EXECUTING on public signals.")
    else:
        print("Outcome is near-random from these features.")
        print("Account88888 likely has PRIVATE information we can't see.")


if __name__ == "__main__":
    main()
