#!/usr/bin/env python3
"""
Feature Engineering Pipeline for Account88888 Signal Discovery

This script creates a comprehensive feature set for each trade to enable
ML-based signal discovery. Features cover:
1. Price momentum (1min, 5min, 10min lookback)
2. Volatility (realized vol, ATR)
3. Timing features (seconds into window, to resolution)
4. Cross-asset correlations (BTC vs ETH movements)
5. Trade clustering (same block/second)
6. Market microstructure signals

Usage:
    python scripts/reverse_engineer/feature_engineering.py

Output:
    data/features/account88888_features.parquet
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import sys

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def load_trades(trades_file: str) -> pd.DataFrame:
    """Load Account88888 trades into DataFrame."""
    print(f"Loading trades from {trades_file}...")

    with open(trades_file) as f:
        data = json.load(f)

    # Handle nested structure with metadata and trades
    if isinstance(data, dict) and "trades" in data:
        trades = data["trades"]
        metadata = data.get("metadata", {})
        print(f"  Metadata: {metadata.get('total_trades', 'N/A')} total, time range: {metadata.get('time_range_start', '')} to {metadata.get('time_range_end', '')}")
    else:
        trades = data

    df = pd.DataFrame(trades)
    print(f"  Loaded {len(df):,} trades")
    return df


def load_binance_klines(klines_file: str) -> pd.DataFrame:
    """Load Binance 1-minute klines."""
    print(f"Loading Binance klines from {klines_file}...")

    df = pd.read_csv(klines_file)

    # Convert timestamps to seconds
    df['timestamp'] = df['open_time'] // 1000
    df['close_timestamp'] = df['close_time'] // 1000

    # Ensure numeric columns
    for col in ['open', 'high', 'low', 'close', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    print(f"  Loaded {len(df):,} klines for {df['symbol'].nunique()} symbols")
    print(f"  Time range: {datetime.fromtimestamp(df['timestamp'].min(), tz=timezone.utc)} to {datetime.fromtimestamp(df['timestamp'].max(), tz=timezone.utc)}")

    return df


def load_token_mapping(mapping_file: str) -> Dict[str, dict]:
    """Load token ID to market mapping."""
    print(f"Loading token mapping from {mapping_file}...")

    with open(mapping_file) as f:
        data = json.load(f)

    # Handle nested structure
    if "token_to_market" in data:
        mapping = data["token_to_market"]
    else:
        mapping = data

    print(f"  Loaded {len(mapping):,} token mappings")
    return mapping


def extract_market_info(slug: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Extract asset, window start, and window end from market slug.

    Slug format: 'btc-updown-15m-1764933300'
    The timestamp is WINDOW START. Window END (resolution) is +900 seconds.
    """
    try:
        parts = slug.split("-")
        asset = parts[0].upper()  # BTC, ETH, SOL, XRP
        window_start = int(parts[-1])
        window_end = window_start + 900  # 15 minute window
        return asset, window_start, window_end
    except:
        return None, None, None


def determine_token_outcome(token_id: str, market_info: dict) -> Optional[str]:
    """
    Determine if a token represents UP or DOWN outcome.

    Returns: 'up', 'down', or None if unknown
    """
    outcomes = market_info.get('outcomes', [])
    clob_ids = market_info.get('clobTokenIds', [])

    # Parse if strings
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if isinstance(clob_ids, str):
        clob_ids = json.loads(clob_ids)

    # Find token in clob_ids
    for i, clob_id in enumerate(clob_ids):
        if str(clob_id) == str(token_id):
            if i < len(outcomes):
                return outcomes[i].lower()  # 'up' or 'down'

    return None


def get_binance_symbol(asset: str) -> str:
    """Convert asset to Binance symbol."""
    return f"{asset}USDT"


class FeatureEngineer:
    """Feature engineering for Account88888 trades."""

    def __init__(self, trades_df: pd.DataFrame, klines_df: pd.DataFrame, token_mapping: Dict[str, dict]):
        self.trades = trades_df.copy()
        self.klines = klines_df
        self.token_mapping = token_mapping

        # Pre-index klines for fast lookup
        self._index_klines()

    def _index_klines(self):
        """Create efficient klines lookup structure."""
        print("Indexing klines for fast lookup...")

        self.klines_by_symbol = {}
        for symbol in self.klines['symbol'].unique():
            symbol_klines = self.klines[self.klines['symbol'] == symbol].copy()
            symbol_klines = symbol_klines.sort_values('timestamp')
            symbol_klines = symbol_klines.set_index('timestamp')
            self.klines_by_symbol[symbol] = symbol_klines

        print(f"  Indexed {len(self.klines_by_symbol)} symbols")

    def get_price_at_time(self, symbol: str, timestamp: int) -> Optional[float]:
        """Get Binance close price at given timestamp (or nearest prior)."""
        if symbol not in self.klines_by_symbol:
            return None

        klines = self.klines_by_symbol[symbol]

        # Find the candle containing this timestamp
        minute_ts = timestamp - (timestamp % 60)

        if minute_ts in klines.index:
            return klines.loc[minute_ts, 'close']

        # Find nearest prior
        prior = klines[klines.index <= minute_ts]
        if len(prior) > 0:
            return prior.iloc[-1]['close']

        return None

    def get_price_series(self, symbol: str, end_ts: int, lookback_minutes: int) -> Optional[pd.Series]:
        """Get price series for lookback period."""
        if symbol not in self.klines_by_symbol:
            return None

        klines = self.klines_by_symbol[symbol]
        start_ts = end_ts - (lookback_minutes * 60)

        mask = (klines.index >= start_ts) & (klines.index <= end_ts)
        if mask.sum() == 0:
            return None

        return klines.loc[mask, 'close']

    def calculate_momentum(self, symbol: str, timestamp: int, lookback_minutes: int) -> Optional[float]:
        """Calculate price momentum over lookback period."""
        prices = self.get_price_series(symbol, timestamp, lookback_minutes)
        if prices is None or len(prices) < 2:
            return None

        return (prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0]

    def calculate_volatility(self, symbol: str, timestamp: int, lookback_minutes: int) -> Optional[float]:
        """Calculate realized volatility over lookback period."""
        prices = self.get_price_series(symbol, timestamp, lookback_minutes)
        if prices is None or len(prices) < 3:
            return None

        returns = prices.pct_change().dropna()
        if len(returns) == 0:
            return None

        return returns.std()

    def calculate_atr(self, symbol: str, timestamp: int, lookback_minutes: int) -> Optional[float]:
        """Calculate Average True Range over lookback period."""
        if symbol not in self.klines_by_symbol:
            return None

        klines = self.klines_by_symbol[symbol]
        start_ts = timestamp - (lookback_minutes * 60)

        mask = (klines.index >= start_ts) & (klines.index <= timestamp)
        subset = klines.loc[mask]

        if len(subset) < 2:
            return None

        # True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        high = subset['high'].values
        low = subset['low'].values
        close = subset['close'].values

        tr1 = high - low
        tr2 = np.abs(high[1:] - close[:-1])
        tr3 = np.abs(low[1:] - close[:-1])

        tr = np.maximum(np.maximum(tr1[1:], tr2), tr3)

        return np.mean(tr) if len(tr) > 0 else None

    def calculate_rsi(self, symbol: str, timestamp: int, lookback_minutes: int = 14) -> Optional[float]:
        """Calculate RSI over lookback period."""
        prices = self.get_price_series(symbol, timestamp, lookback_minutes + 1)
        if prices is None or len(prices) < lookback_minutes:
            return None

        delta = prices.diff().dropna()
        gains = delta.where(delta > 0, 0)
        losses = -delta.where(delta < 0, 0)

        avg_gain = gains.rolling(window=lookback_minutes).mean().iloc[-1]
        avg_loss = losses.rolling(window=lookback_minutes).mean().iloc[-1]

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def engineer_features(self) -> pd.DataFrame:
        """Generate all features for trades."""
        print("\nEngineering features...")

        # Enrich trades with market info
        print("  Extracting market info from token IDs...")

        market_info = []
        for token_id in self.trades['token_id']:
            info = self.token_mapping.get(token_id, {})
            slug = info.get('slug', '')
            asset, window_start, window_end = extract_market_info(slug)
            outcome = determine_token_outcome(token_id, info)  # 'up' or 'down'
            market_info.append({
                'slug': slug,
                'asset': asset,
                'window_start': window_start,
                'window_end': window_end,
                'token_outcome': outcome,  # Which side of the bet this token is
            })

        market_df = pd.DataFrame(market_info)
        self.trades = pd.concat([self.trades.reset_index(drop=True), market_df], axis=1)

        # Filter to valid trades with market info
        valid_mask = self.trades['asset'].notna()
        print(f"  Valid trades with market info: {valid_mask.sum():,} / {len(self.trades):,}")

        trades = self.trades[valid_mask].copy()

        # Feature lists
        features = []

        total = len(trades)
        processed = 0
        last_pct = 0

        print("  Calculating features for each trade...")

        for idx, row in trades.iterrows():
            timestamp = row['timestamp']
            asset = row['asset']
            symbol = get_binance_symbol(asset)
            window_start = row['window_start']
            window_end = row['window_end']

            feat = {
                # Core identifiers
                'tx_hash': row['tx_hash'],
                'timestamp': timestamp,
                'asset': asset,
                'side': row['side'],
                'price': row['price'],
                'usdc_amount': row['usdc_amount'],
                'token_amount': row['token_amount'],
                'slug': row['slug'],

                # Token direction (critical for understanding their bet)
                'token_outcome': row.get('token_outcome'),  # 'up' or 'down'
                'betting_up': 1 if row.get('token_outcome') == 'up' else (0 if row.get('token_outcome') == 'down' else None),

                # Timing features
                'seconds_into_window': timestamp - window_start if window_start else None,
                'seconds_to_resolution': window_end - timestamp if window_end else None,
                'window_fraction': (timestamp - window_start) / 900 if window_start else None,

                # Binance price at trade time
                'binance_price': self.get_price_at_time(symbol, timestamp),

                # Momentum features
                'momentum_1min': self.calculate_momentum(symbol, timestamp, 1),
                'momentum_5min': self.calculate_momentum(symbol, timestamp, 5),
                'momentum_10min': self.calculate_momentum(symbol, timestamp, 10),
                'momentum_15min': self.calculate_momentum(symbol, timestamp, 15),

                # Momentum from window start
                'momentum_from_window_start': None,  # Calculated below

                # Volatility features
                'volatility_5min': self.calculate_volatility(symbol, timestamp, 5),
                'volatility_10min': self.calculate_volatility(symbol, timestamp, 10),
                'volatility_15min': self.calculate_volatility(symbol, timestamp, 15),

                # ATR
                'atr_10min': self.calculate_atr(symbol, timestamp, 10),

                # RSI
                'rsi_14min': self.calculate_rsi(symbol, timestamp, 14),
            }

            # Momentum from window start
            if window_start:
                price_at_start = self.get_price_at_time(symbol, window_start)
                price_now = feat['binance_price']
                if price_at_start and price_now:
                    feat['momentum_from_window_start'] = (price_now - price_at_start) / price_at_start

                    # Key signal: are they betting WITH or AGAINST momentum?
                    # betting_up=1 and positive momentum = betting with momentum
                    if feat['betting_up'] is not None and feat['momentum_from_window_start'] is not None:
                        price_is_up = feat['momentum_from_window_start'] > 0
                        betting_up = feat['betting_up'] == 1
                        feat['betting_with_momentum'] = 1 if price_is_up == betting_up else 0

            features.append(feat)

            # Progress tracking
            processed += 1
            pct = int(100 * processed / total)
            if pct >= last_pct + 5:
                print(f"    {pct}% complete ({processed:,}/{total:,})...")
                last_pct = pct

        features_df = pd.DataFrame(features)

        # Add cross-asset features
        print("  Adding cross-asset features...")
        features_df = self._add_cross_asset_features(features_df)

        # Add clustering features
        print("  Adding clustering features...")
        features_df = self._add_clustering_features(features_df)

        # Add target variable (trade direction)
        print("  Adding target variables...")
        features_df = self._add_target_variables(features_df)

        return features_df

    def _add_cross_asset_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add features based on cross-asset correlations."""
        # BTC momentum for non-BTC trades
        df['btc_momentum_5min'] = None

        for idx, row in df.iterrows():
            if row['asset'] != 'BTC':
                btc_mom = self.calculate_momentum('BTCUSDT', row['timestamp'], 5)
                df.at[idx, 'btc_momentum_5min'] = btc_mom

        return df

    def _add_clustering_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add features based on trade clustering."""
        # Sort by timestamp
        df = df.sort_values('timestamp')

        # Trades in same second
        df['trades_same_second'] = df.groupby(df['timestamp'])['tx_hash'].transform('count')

        # Time since last trade (same asset)
        df['time_since_last_trade'] = df.groupby('asset')['timestamp'].diff()

        # Rolling trade count (last 60 seconds)
        # Using a simple approximation
        df['recent_trade_intensity'] = df['trades_same_second'].rolling(window=60, min_periods=1).sum()

        return df

    def _add_target_variables(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Add target variables for ML:
        1. trade_direction: Did they bet UP (1) or DOWN (0)?
        2. window_outcome: Did market resolve UP (1) or DOWN (0)?
        """
        # Infer trade direction from token type (requires parsing slug/question)
        # For now, use price heuristic:
        # - If price > 0.5, they're betting on the more likely outcome
        # - We need to know if token is UP or DOWN

        # This requires additional data - mark as unknown for now
        # The ML model can still learn patterns even without explicit labels

        df['price_above_half'] = (df['price'] > 0.5).astype(int)

        return df


def main():
    """Run feature engineering pipeline."""
    import argparse

    parser = argparse.ArgumentParser(description="Feature Engineering Pipeline")
    parser.add_argument("--sample", type=int, default=None, help="Sample N trades (for testing)")
    parser.add_argument("--random-sample", action="store_true", help="Use random sampling instead of first N")
    args = parser.parse_args()

    print("=" * 60)
    print("FEATURE ENGINEERING PIPELINE")
    print("=" * 60)
    print()

    # Paths
    trades_file = PROJECT_ROOT / "data" / "account88888_trades_joined.json"
    klines_file = PROJECT_ROOT / "data" / "binance_klines_full.csv"
    mapping_file = PROJECT_ROOT / "data" / "token_to_market.json"
    output_dir = PROJECT_ROOT / "data" / "features"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    trades_df = load_trades(trades_file)
    klines_df = load_binance_klines(klines_file)
    token_mapping = load_token_mapping(mapping_file)

    # Sample if requested
    if args.sample:
        print(f"\nSampling {args.sample:,} trades...")
        if args.random_sample:
            trades_df = trades_df.sample(n=min(args.sample, len(trades_df)), random_state=42)
        else:
            trades_df = trades_df.head(args.sample)
        print(f"  Working with {len(trades_df):,} trades")

    # Engineer features
    engineer = FeatureEngineer(trades_df, klines_df, token_mapping)
    features_df = engineer.engineer_features()

    print(f"\nGenerated {len(features_df):,} feature vectors")
    print(f"Features per trade: {len(features_df.columns)}")

    # Feature summary
    print("\nFeature columns:")
    for col in features_df.columns:
        non_null = features_df[col].notna().sum()
        pct = 100 * non_null / len(features_df)
        print(f"  {col}: {pct:.1f}% non-null")

    # Save
    suffix = f"_sample{args.sample}" if args.sample else ""
    output_file = output_dir / f"account88888_features{suffix}.parquet"
    features_df.to_parquet(output_file, index=False)
    print(f"\nSaved features to: {output_file}")

    # Also save a small sample as CSV for inspection
    sample_file = output_dir / f"account88888_features{suffix}_sample.csv"
    features_df.head(1000).to_csv(sample_file, index=False)
    print(f"Saved sample CSV to: {sample_file}")

    # Summary stats
    print("\n" + "=" * 60)
    print("FEATURE SUMMARY")
    print("=" * 60)

    numeric_cols = features_df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols[:15]:  # First 15 numeric features
        if col in ['timestamp', 'window_start', 'window_end']:
            continue
        valid = features_df[col].dropna()
        if len(valid) > 0:
            print(f"\n{col}:")
            print(f"  Mean: {valid.mean():.6f}")
            print(f"  Std:  {valid.std():.6f}")
            print(f"  Min:  {valid.min():.6f}")
            print(f"  Max:  {valid.max():.6f}")


if __name__ == "__main__":
    main()
