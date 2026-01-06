-- Markets
CREATE TABLE IF NOT EXISTS markets (
  condition_id TEXT PRIMARY KEY,
  slug TEXT,
  start_ts INTEGER,
  end_ts INTEGER,
  base_symbol TEXT
);

-- Order book snapshots
CREATE TABLE IF NOT EXISTS orderbook_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  condition_id TEXT,
  token_id TEXT,
  best_bid REAL,
  best_ask REAL,
  mid REAL,
  spread REAL
);

-- External price feeds
CREATE TABLE IF NOT EXISTS price_ticks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  symbol TEXT,
  source TEXT,
  price REAL
);

-- Wallet trades (for cloning)
CREATE TABLE IF NOT EXISTS wallet_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet TEXT,
  ts INTEGER,
  condition_id TEXT,
  token_id TEXT,
  side TEXT,
  price REAL,
  size REAL
);

-- Derived features (used by miner + cloner)
CREATE TABLE IF NOT EXISTS features (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  condition_id TEXT,
  t_since_start INTEGER,
  cl_delta REAL,
  cl_delta_bps REAL,
  mid_up REAL,
  mid_down REAL,
  spread_up REAL,
  spread_down REAL
);

-- Monitored wallets
CREATE TABLE IF NOT EXISTS monitored_wallets (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  address TEXT UNIQUE NOT NULL,
  display_name TEXT,
  added_at INTEGER,
  last_checked INTEGER,
  is_active INTEGER DEFAULT 1,
  min_trade_size REAL DEFAULT 0,
  notes TEXT
);

-- Paper trades
CREATE TABLE IF NOT EXISTS paper_trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id TEXT UNIQUE,
  portfolio TEXT DEFAULT 'default',
  ts INTEGER,
  market_id TEXT,
  market_name TEXT,
  token_id TEXT,
  side TEXT,
  outcome TEXT,
  size REAL,
  price REAL,
  fill_price REAL,
  status TEXT DEFAULT 'filled',
  source TEXT DEFAULT 'manual',
  signal_wallet TEXT,
  notes TEXT
);

-- Paper positions
CREATE TABLE IF NOT EXISTS paper_positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  portfolio TEXT DEFAULT 'default',
  market_id TEXT,
  market_name TEXT,
  token_id TEXT UNIQUE,
  side TEXT,
  size REAL,
  avg_cost REAL,
  opened_at INTEGER,
  last_update INTEGER
);

-- Alerts history
CREATE TABLE IF NOT EXISTS alert_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER,
  title TEXT,
  message TEXT,
  priority TEXT,
  category TEXT,
  source TEXT,
  sent_via TEXT,
  data TEXT
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_orderbook_ts ON orderbook_snapshots(ts);
CREATE INDEX IF NOT EXISTS idx_orderbook_condition ON orderbook_snapshots(condition_id);
CREATE INDEX IF NOT EXISTS idx_price_ts ON price_ticks(ts);
CREATE INDEX IF NOT EXISTS idx_price_symbol ON price_ticks(symbol);
CREATE INDEX IF NOT EXISTS idx_wallet_trades_wallet ON wallet_trades(wallet);
CREATE INDEX IF NOT EXISTS idx_wallet_trades_ts ON wallet_trades(ts);
CREATE INDEX IF NOT EXISTS idx_features_ts ON features(ts);
CREATE INDEX IF NOT EXISTS idx_features_condition ON features(condition_id);
CREATE INDEX IF NOT EXISTS idx_monitored_wallets_address ON monitored_wallets(address);
CREATE INDEX IF NOT EXISTS idx_paper_trades_portfolio ON paper_trades(portfolio);
CREATE INDEX IF NOT EXISTS idx_paper_trades_ts ON paper_trades(ts);
CREATE INDEX IF NOT EXISTS idx_paper_positions_portfolio ON paper_positions(portfolio);
CREATE INDEX IF NOT EXISTS idx_alert_history_ts ON alert_history(ts);
CREATE INDEX IF NOT EXISTS idx_alert_history_category ON alert_history(category);
