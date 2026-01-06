#!/usr/bin/env python3
"""
ML Signal Discovery Model for Account88888

This script trains a classifier to predict Account88888's betting direction
based on market conditions at trade time. The goal is to discover:

1. What features predict their bet direction?
2. Can we replicate their decision-making?
3. What's their secret sauce?

Model: XGBoost (interpretable, handles missing data)
Target: betting_up (1 = betting UP, 0 = betting DOWN)

Usage:
    python scripts/reverse_engineer/signal_discovery_model.py

Output:
    data/models/signal_discovery_model.json
    data/models/feature_importance.csv
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_features(features_file: Path) -> pd.DataFrame:
    """Load feature data."""
    print(f"Loading features from {features_file}...")
    df = pd.read_parquet(features_file)
    print(f"  Loaded {len(df):,} trades with {len(df.columns)} features")
    return df


def prepare_ml_data(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Prepare data for ML training.

    Returns X (features), y (target)
    """
    print("\nPreparing ML data...")

    # Target variable
    y = df['betting_up']

    # Filter to valid targets
    valid_mask = y.notna()
    print(f"  Valid targets: {valid_mask.sum():,} / {len(df):,}")

    # Only keep trades with side=BUY (selling complicates things)
    buy_mask = df['side'] == 'BUY'
    print(f"  BUY trades: {buy_mask.sum():,}")

    # Combine filters
    mask = valid_mask & buy_mask
    print(f"  Final dataset: {mask.sum():,} trades")

    y = y[mask].astype(int)
    df_filtered = df[mask].copy()

    # Feature columns (exclude identifiers and target-related)
    exclude_cols = [
        'tx_hash', 'slug', 'side', 'token_outcome', 'betting_up',
        'asset',  # categorical, handle separately
        'timestamp',  # not predictive
        'token_amount',  # correlated with price
        'betting_with_momentum',  # derived from target
    ]

    feature_cols = [col for col in df_filtered.columns if col not in exclude_cols]

    # Keep only numeric features
    numeric_cols = df_filtered[feature_cols].select_dtypes(include=[np.number]).columns.tolist()
    print(f"  Numeric features: {len(numeric_cols)}")

    X = df_filtered[numeric_cols].copy()

    # Add asset as one-hot encoding
    asset_dummies = pd.get_dummies(df_filtered['asset'], prefix='asset')
    X = pd.concat([X, asset_dummies], axis=1)

    print(f"  Final features: {len(X.columns)}")
    print(f"  Feature names: {list(X.columns)}")

    return X, y


def train_model(X: pd.DataFrame, y: pd.Series) -> Tuple[object, pd.DataFrame]:
    """
    Train XGBoost model to predict betting direction.

    Returns: model, feature_importance_df
    """
    try:
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
        import xgboost as xgb
    except ImportError:
        print("Installing required packages...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "scikit-learn", "xgboost", "-q"])
        from sklearn.model_selection import train_test_split, cross_val_score
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
        import xgboost as xgb

    print("\n" + "=" * 60)
    print("TRAINING ML MODEL")
    print("=" * 60)

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    print(f"\nTrain set: {len(X_train):,} samples")
    print(f"Test set: {len(X_test):,} samples")
    print(f"Class balance (train): UP={y_train.sum():,} ({y_train.mean():.1%}), DOWN={(~y_train.astype(bool)).sum():,}")

    # Train XGBoost
    print("\nTraining XGBoost classifier...")
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        n_jobs=-1,
        eval_metric='logloss'
    )

    model.fit(X_train, y_train)

    # Evaluate
    print("\n--- MODEL EVALUATION ---")

    y_pred_train = model.predict(X_train)
    y_pred_test = model.predict(X_test)

    train_acc = accuracy_score(y_train, y_pred_train)
    test_acc = accuracy_score(y_test, y_pred_test)

    print(f"\nAccuracy:")
    print(f"  Train: {train_acc:.4f}")
    print(f"  Test:  {test_acc:.4f}")

    # Cross-validation
    print("\nCross-validation (5-fold)...")
    cv_scores = cross_val_score(model, X, y, cv=5, scoring='accuracy')
    print(f"  Mean CV accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std()*2:.4f})")

    # Classification report
    print("\nClassification Report (Test):")
    print(classification_report(y_test, y_pred_test, target_names=['DOWN', 'UP']))

    # Confusion matrix
    cm = confusion_matrix(y_test, y_pred_test)
    print("Confusion Matrix:")
    print(f"             Pred DOWN  Pred UP")
    print(f"  Actual DOWN    {cm[0,0]:5d}    {cm[0,1]:5d}")
    print(f"  Actual UP      {cm[1,0]:5d}    {cm[1,1]:5d}")

    # Feature importance
    print("\n" + "=" * 60)
    print("FEATURE IMPORTANCE")
    print("=" * 60)

    importance = pd.DataFrame({
        'feature': X.columns,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    print("\nTop 15 Most Important Features:")
    for i, row in importance.head(15).iterrows():
        print(f"  {row['feature']:30s}: {row['importance']:.4f}")

    return model, importance


def analyze_predictions(X: pd.DataFrame, y: pd.Series, model, df: pd.DataFrame):
    """Analyze where model succeeds and fails."""
    print("\n" + "=" * 60)
    print("PREDICTION ANALYSIS")
    print("=" * 60)

    # Get predictions
    y_pred = model.predict(X)
    y_pred_proba = model.predict_proba(X)[:, 1]

    # Add to dataframe for analysis
    analysis = df[['asset', 'price', 'usdc_amount', 'seconds_into_window',
                   'momentum_from_window_start', 'betting_up']].copy()
    analysis = analysis.iloc[:len(y)]
    analysis['predicted'] = y_pred
    analysis['confidence'] = np.abs(y_pred_proba - 0.5) * 2  # 0-1 scale
    analysis['correct'] = (analysis['predicted'] == analysis['betting_up']).astype(int)

    # Accuracy by confidence
    print("\nAccuracy by Prediction Confidence:")
    for thresh in [0.0, 0.2, 0.4, 0.6]:
        subset = analysis[analysis['confidence'] >= thresh]
        if len(subset) > 0:
            acc = subset['correct'].mean()
            print(f"  Confidence >= {thresh:.1f}: {acc:.3f} (n={len(subset):,})")

    # Accuracy by timing
    print("\nAccuracy by Timing (seconds into window):")
    timing_bins = [(0, 180), (180, 360), (360, 540), (540, 720), (720, 900)]
    for start, end in timing_bins:
        subset = analysis[(analysis['seconds_into_window'] >= start) &
                         (analysis['seconds_into_window'] < end)]
        if len(subset) > 0:
            acc = subset['correct'].mean()
            print(f"  {start:3d}-{end:3d}s: {acc:.3f} (n={len(subset):,})")

    # Accuracy by asset
    print("\nAccuracy by Asset:")
    for asset in analysis['asset'].unique():
        subset = analysis[analysis['asset'] == asset]
        if len(subset) > 0:
            acc = subset['correct'].mean()
            print(f"  {asset}: {acc:.3f} (n={len(subset):,})")


def interpret_findings(importance: pd.DataFrame):
    """Interpret what the model learned."""
    print("\n" + "=" * 60)
    print("INTERPRETATION")
    print("=" * 60)

    top_features = importance.head(10)['feature'].tolist()

    print("\nKey Findings:")

    # Check for momentum features
    momentum_features = [f for f in top_features if 'momentum' in f.lower()]
    if momentum_features:
        print(f"\n1. MOMENTUM MATTERS:")
        print(f"   Top momentum features: {momentum_features}")
        print("   This suggests price direction leading up to trade affects betting decision")

    # Check for timing features
    timing_features = [f for f in top_features if 'second' in f.lower() or 'window' in f.lower()]
    if timing_features:
        print(f"\n2. TIMING MATTERS:")
        print(f"   Top timing features: {timing_features}")
        print("   Trade timing within window is predictive of direction")

    # Check for price features
    price_features = [f for f in top_features if 'price' in f.lower()]
    if price_features:
        print(f"\n3. PRICE LEVEL MATTERS:")
        print(f"   Top price features: {price_features}")
        print("   Token price level influences decision")

    # Check for volatility
    vol_features = [f for f in top_features if 'volatil' in f.lower() or 'atr' in f.lower()]
    if vol_features:
        print(f"\n4. VOLATILITY MATTERS:")
        print(f"   Top volatility features: {vol_features}")
        print("   Market volatility affects betting direction")

    print("\n" + "=" * 60)
    print("CONCLUSION")
    print("=" * 60)
    print("""
If the model achieves ~50% accuracy, their decision is essentially random
(or based on information not in our features).

If the model achieves ~60-70% accuracy, we've captured part of their signal.

If the model achieves >70% accuracy, we've found significant predictive features.

The ~30% edge they have over base rate likely comes from:
1. Information not in our features (orderbook, faster feeds)
2. Complex non-linear combinations of features
3. External signals (other exchanges, mempool)
""")


def main():
    """Run signal discovery."""
    import argparse

    parser = argparse.ArgumentParser(description="ML Signal Discovery")
    parser.add_argument("--features", type=str, default="data/features/account88888_features_sample50000.parquet",
                       help="Path to features parquet file")
    args = parser.parse_args()

    print("=" * 60)
    print("ML SIGNAL DISCOVERY MODEL")
    print("=" * 60)
    print()
    print("Goal: Predict Account88888's betting direction (UP vs DOWN)")
    print("      based on market conditions at trade time")
    print()

    # Load data
    features_file = PROJECT_ROOT / args.features
    df = load_features(features_file)

    # Prepare ML data
    X, y = prepare_ml_data(df)

    # Train model
    model, importance = train_model(X, y)

    # Analyze predictions
    analyze_predictions(X, y, model, df)

    # Interpret findings
    interpret_findings(importance)

    # Save outputs
    output_dir = PROJECT_ROOT / "data" / "models"
    output_dir.mkdir(parents=True, exist_ok=True)

    importance_file = output_dir / "feature_importance.csv"
    importance.to_csv(importance_file, index=False)
    print(f"\nSaved feature importance to: {importance_file}")

    # Save model (use native format for scikit-learn compatibility)
    model_file = output_dir / "signal_discovery_model.ubj"
    try:
        model.save_model(str(model_file))
        print(f"Saved model to: {model_file}")
    except Exception as e:
        print(f"Note: Could not save model ({e})")


if __name__ == "__main__":
    main()
