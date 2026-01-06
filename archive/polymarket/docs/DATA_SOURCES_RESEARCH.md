# BTC Orderflow Trading Bot - Data Sources Research

**Date:** 2026-01-06
**Purpose:** Comprehensive analysis of available data sources for BTC perpetual futures orderflow/mean reversion trading

---

## Executive Summary

This research identifies optimal data sources for building a BTC orderflow trading bot with a $300 capital constraint. Key findings:

- **Best Low-Fee Exchange:** MEXC (0.01% maker / 0.04% taker) or Hyperliquid (maker rebates)
- **Best Free Data Source:** Binance Futures API (no API key required for market data WebSocket)
- **Best Historical Data:** Tardis.dev (free trial + first day of each month free)
- **Recommended Primary:** Binance or Hyperliquid for execution + data
- **Recommended Data Stack:** Binance WebSocket (real-time) + Tardis.dev (backtesting) + CoinGlass (market context)

---

## 1. Centralized Exchanges (CEX)

### 1.1 Binance Futures

#### Data Types Available
- **Orderbook (Depth)**: WebSocket streams with 100ms, 250ms, 500ms updates
- **Trade Data**: Individual trades + aggregated trades (aggTrades)
- **Open Interest**: Historical and real-time (`/futures/data/openInterestHist`)
- **Funding Rate**: Historical data via `/fapi/v1/fundingRate` (up to 1000 records per request)
- **Liquidation Data**: Available through market data endpoints
- **Klines/Candlestick**: Historical data available via API and downloadable from data.binance.vision

#### WebSocket Features
- **Base Endpoint**: `wss://fstream.binance.com/stream`
- **Orderbook Management**: Snapshot + differential updates system
  - Initial snapshot via REST: `/fapi/v1/depth`
  - Real-time updates: `btcusdt@depth@100ms` (fastest), `@depth@250ms`, `@depth@500ms`
  - Top 1000 levels depth snapshots available
- **Update Frequency**: Real-time (100ms minimum for depth updates)
- **Connection Limits**:
  - 10 messages per second per connection
  - Max 1024 streams per connection
  - Ping every 3 minutes, disconnect after 10 minutes without pong

#### Rate Limits
- **Default (Free Tier)**: 2,400 requests/min per IP
- **Order Limits**: 1,200 orders/min per account (default)
- **WebSocket Connections**: 300 connections per 5 minutes per IP
- **VIP Tiers**: Volume-based upgrades available (VIP 1+ can adjust limits)
- **Funding Rate Endpoint**: 500 requests per 5 minutes per IP (shared with fundingInfo)

#### Historical Data
- **Availability**: Data from 2019 onwards for most pairs
- **Access Methods**:
  - API endpoints (limited lookback)
  - Binance Data Vision (downloadable CSV/parquet files)
- **Depth Data**: Recorded at 100ms since 2020-01-07, earlier data at lower frequency

#### Trading Fees
- **Maker**: 0.02% (base tier)
- **Taker**: 0.04-0.05% (base tier, among lowest in industry)
- **BNB Discount**: Additional 10% off when paying fees with BNB (USDT-M futures only)
- **VIP 9 Rates**: 0% maker / 0.017% taker (requires 750,000+ BTC 30-day volume)

#### Pros
- Industry-leading liquidity and depth
- Lowest base taker fees among major CEX (0.04%)
- Free WebSocket market data (no API key required)
- Comprehensive historical data via Binance Data Vision
- Most exchanges/data providers support Binance data format

#### Cons
- Rate limits can be restrictive for high-frequency strategies without VIP status
- Requires significant volume for meaningful fee discounts
- Not the absolute lowest maker fees

#### API Documentation
- **Futures API Docs**: https://developers.binance.com/docs/derivatives/usds-margined-futures
- **WebSocket Streams**: https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams
- **Data Vision**: https://data.binance.vision

---

### 1.2 OKX

#### Data Types Available
- **Orderbook**: WebSocket books channel (L2 market depth)
- **Trade Data**: Real-time trades via WebSocket
- **Open Interest**: Available through market data endpoints
- **Funding Rate**: Updates every 8 hours
- **Perpetual Swaps**: BTC-USDT-SWAP and other instruments
- **Options**: Also supported alongside futures

#### WebSocket Features
- **Base Endpoint**: `wss://ws.okx.com:8443/ws/v5/public` (public), `/ws/v5/private` (private)
- **Channels**: `books`, `books5` (top 5 levels), `books-l2-tbt` (tick-by-tick)
- **Full Duplex**: Bidirectional data transmission
- **API v5**: Both REST and WebSocket support order operations
- **Connection Limit**: 3 requests per second per IP

#### Rate Limits
- **Connection Limit**: 3 requests/second based on IP
- **Authentication**: Required for private channels (account/order updates)
- **Headers**: OK-ACCESS-KEY, OK-ACCESS-SIGN, OK-ACCESS-TIMESTAMP

#### Historical Data
- Available through Tardis.dev (third-party provider)
- OKX provides historical data endpoints but with limitations on lookback period

#### Trading Fees
- **Maker**: 0.02% (base tier)
- **Taker**: 0.05% (base tier)
- **VIP Discounts**: Based on 30-day volume + OKB token holdings
- **Lowest Rates**: -0.005% maker (rebate) / 0.015% taker for elite traders
- **OKB Benefits**: Holding OKB tokens provides additional fee tier benefits
- **Funding Rate**: Updates every 8 hours, can be positive or negative

#### Pros
- Competitive fee structure with maker rebates for high-volume traders
- Both REST and WebSocket support trading operations (unique in v5)
- Strong support for derivatives (futures, swaps, options)
- VIP benefits accessible through OKB holdings (not just volume)

#### Cons
- Higher base taker fees than Binance (0.05% vs 0.04%)
- Smaller market share and liquidity compared to Binance
- Less comprehensive free historical data

#### API Documentation
- **Official API Docs**: https://www.okx.com/docs-v5/en/
- **WebSocket Guide**: https://www.okx.com/docs-v5/en/
- **Perpetual Futures**: https://www.okx.com/help/section/product-documentation-perpetual-contracts

---

### 1.3 Bybit

#### Data Types Available
- **Orderbook**: WebSocket orderbook stream with snapshots + delta updates
- **Trade Data**: Real-time trade execution data
- **Liquidation Data**:
  - **All Liquidation** (NEW - recommended): Full liquidation stream across all contracts
  - Deprecated liquidation stream (1 order/second/symbol limit)
- **Open Interest**: Available through market data endpoints
- **Contract Types**: USDT contract, USDC contract, Inverse contract

#### WebSocket Features
- **Orderbook Updates**:
  - Level 1 data: Snapshot every 3 seconds if no changes
  - Level 1000: Push frequency changed from 300ms to 200ms
  - Delta messages pushed on every orderbook change
  - Snapshots sent periodically to allow clients to reset local orderbooks
- **Liquidation Stream**: Real-time all liquidations (no throttling on new endpoint)
- **Best Practice**: Use WebSocket for market data (not counted against rate limits)
- **Server Location**: Singapore (AWS apse1-az3)

#### Rate Limits
- WebSocket requests NOT counted against rate limits
- Recommended for market data consumption over REST API

#### Historical Data
- Available through third-party providers:
  - **BybitMarketData** (GitHub): Logs trades, liquidations, ticker, orderbook every second
  - **Tardis.dev**: Professional historical data provider
- Granularity: 1-second logging available through community tools

#### Trading Fees
- **Maker**: ~0.02% (base tier)
- **Taker**: ~0.055% (base tier)
- **VIP Tiers**: Reduce to 0% maker / 0.018% taker at top levels
- **Special Campaigns**: Zero-fee BTC/USDT campaigns have attracted institutional traders

#### Pros
- New "All Liquidation" endpoint provides complete liquidation data (no throttling)
- Fast orderbook updates (200ms for level 1000)
- WebSocket market data doesn't count against rate limits
- Active community tools for data collection (GitHub repositories)

#### Cons
- Smaller market share than Binance
- Higher taker fees than Binance/MEXC
- Less comprehensive official historical data offerings

#### API Documentation
- **All Liquidation Stream**: https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation
- **Orderbook Stream**: https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook
- **Official V5 Docs**: https://bybit-exchange.github.io/docs/v5/
- **Community Data Tools**: https://github.com/sferez/BybitMarketData

---

### 1.4 MEXC

#### Data Types Available
- **Orderbook (Depth)**: Contract depth information via REST and WebSocket
- **Trade Data**: Real-time trade execution
- **Snapshot Updates**: Latest N depth updates for contracts
- **Open Interest**: Available through futures endpoints
- **Funding Rate**: Standard 8-hour funding rate updates

#### API Features
- **Request Types**: GET, POST, DELETE
- **Content-Type**: application/json for POST requests
- **Request Sources**: Supports APP, WEB, OPEN-API
- **Depth Limit**: Max 100 price levels per request (default)
- **Futures API**: Currently available to institutional users only (contact institution@mexc.com)

#### Rate Limits
- Not explicitly detailed in public documentation
- Institutional users should contact MEXC for dedicated limits

#### Historical Data
- **Order Book Data**: Available from 2022-10-19
- **Data Provider**: Amberdata offers MEXC order book snapshots
- **Snapshot Frequency**: Every minute via REST API
- **Depth**: Full order book depth in each snapshot

#### Trading Fees
- **Maker**: 0.01% (LOWEST among major exchanges)
- **Taker**: 0.04% (tied with Binance for lowest)
- **MX Token Discount**: 50% fee reduction when holding MX tokens
- **Leverage**: Up to 500x on BTC/USDT perpetual futures (highest in industry)

#### Pros
- **Lowest maker fees in the industry** (0.01%)
- Extremely high leverage available (500x)
- 50% fee discount with native token (MX)
- Historical data available since late 2022

#### Cons
- Futures API limited to institutional users only
- Less liquid than top-tier exchanges (Binance, OKX)
- Limited public documentation compared to competitors
- API maintenance issues reported (need workarounds)

#### API Documentation
- **Futures Market Endpoints**: https://www.mexc.com/api-docs/futures/market-endpoints
- **Integration Guide**: https://www.mexc.com/api-docs/futures/integration-guide
- **Python Library (unofficial)**: https://pypi.org/project/pymexc/
- **Institutional Contact**: institution@mexc.com

---

### 1.5 Deribit

#### Data Types Available
- **Orderbook**: Raw tick-by-tick or aggregated (100ms) order book data
- **Trade Data**: Individual trade execution data
- **Options Chains**: Comprehensive options data (unique strength)
- **BTC Futures**: Cash-settled futures (30-minute average settlement price)
- **Historical Data**: Available from 2021-05-21 (via Tardis.dev/Amberdata)

#### WebSocket Features
- **Base Endpoint**: `wss://test.deribit.com/ws/api/v2` (test), production endpoint also available
- **Channels**:
  - `book.BTC-PERPETUAL.raw` (tick-by-tick)
  - `book.BTC-PERPETUAL.100ms` (aggregated)
- **Subscription Limit**: Up to 500 channels in one subscription message
- **Event Ordering**: Guaranteed in-order delivery per instrument (verified via sequence numbers)
- **Change ID**: Orderbook updates include change_id for continuity verification

#### API Protocols
- **WebSocket**: Preferred for real-time data
- **FIX Protocol**: Also supported (equally fast as WebSocket in practice)
- **REST API**: Available but subscriptions and cancel-on-disconnect not supported
- **Latency**: Millisecond-level real-time updates

#### Best Practices
- Use raw feeds only if you need every tick
- Prefer 100ms or aggregated updates to reduce noise
- Subscribe to multiple channels in single API call
- Verify sequence numbers (change_id) for data integrity

#### Rate Limits
- Up to 500 channels per subscription message
- Connection and request limits apply (check official docs for current limits)

#### Historical Data
- **Tardis.dev**: Same format as real-time WebSocket API + local timestamps
- **Amberdata**: Futures data from 2021-05-21, Options data from 2021-05-21
- **Format**: JSON-RPC 2.0 for API requests

#### Trading Fees
- Fee structure not extensively detailed in search results
- Known for options trading focus rather than lowest perpetual fees
- Contact Deribit for current fee schedule

#### Pros
- **Best-in-class options data** (if needed for strategy expansion)
- Guaranteed in-order event delivery with sequence verification
- Both WebSocket and FIX protocol support
- High-quality tick data (raw or aggregated)
- Can subscribe to 500 channels simultaneously

#### Cons
- Not the lowest fee option for perpetual futures
- Smaller BTC futures market compared to pure futures exchanges
- Historical data requires third-party providers (Tardis.dev/Amberdata)

#### API Documentation
- **Official API Docs**: https://docs.deribit.com/
- **Market Data Best Practices**: https://support.deribit.com/hc/en-us/articles/29592500256669
- **Tardis.dev Integration**: https://docs.tardis.dev/historical-data-details/deribit

---

## 2. Decentralized Exchanges (DEX)

### 2.1 Hyperliquid

#### Platform Overview
- **Type**: Decentralized perpetual futures exchange
- **Blockchain**: Custom L1 blockchain (not Ethereum-based)
- **Leverage**: Up to 50x leverage across diverse asset classes
- **Performance**:
  - Order confirmation: <1 second
  - Transaction throughput: Up to 100,000 orders/second
  - API response time: 50-200ms (REST)
  - WebSocket latency: 10-100ms

#### Data Types Available
- **Orderbook**: WebSocket subscription for L2, L4 order book data
- **Trade Data**: Real-time trade execution
- **Liquidation Data**: Real-time liquidation events
- **Market Types**: Perpetual futures (SWAP contracts)
- **Ultra-Low Latency**: Dwellir provides high-performance WebSocket servers faster than public endpoints

#### WebSocket Features
- **Endpoint**: Custom WebSocket API (see official docs)
- **Subscription Format**: JSON subscription messages
- **Data Structures**:
  - `WsBook`: coin, levels, time
  - `WsLevel`: px (price), sz (size), n (number of orders)
- **Latency**: 10-100ms typical WebSocket delivery
- **Third-Party**: Dwellir offers ultra-low latency WebSocket server

#### Trading Fees
- **Perp Maker Rebates**: -0.001% to -0.003% (PAID to provide liquidity)
  - Base: -0.001% for 0.5%+ maker volume
  - Maximum: -0.003% for 3.0%+ maker volume provision
- **Perp Taker Fees**: 0.045% (base) → 0.030% (100M+ volume)
- **Spot Taker**: 0.070% (base)
- **Spot Maker**: 0.040% (base)
- **Fee Tier Calculation**: Perps and spot volume counted together (14-day weighted)
- **Recent Updates**:
  - 80% spot fee cut (September 2025)
  - HIP-3 Growth Mode: 90% fee reduction for new markets (November 2025)
- **Aligned Quote Assets**: 20% lower taker fees, 50% better maker rebates

#### Fee Structure Philosophy
- Fees directed entirely to community (HLP, assistance fund, deployers)
- No team/insider fee extraction (unlike most protocols)
- Deployers can keep up to 50% of trading fees for HIP-3 perps

#### Historical Data
- Integration with Tardis.dev and other providers likely (verify with official docs)
- Still a newer platform, historical data coverage may be limited compared to CEX

#### Pros
- **MAKER REBATES** (get paid to provide liquidity!)
- Ultra-low latency (10-100ms WebSocket)
- Extremely high throughput (100k orders/second)
- Community-centric fee model (no team extraction)
- Fast confirmations (<1 second)
- Lower gas costs than Ethereum-based DEXes

#### Cons
- Smaller liquidity than top CEX platforms
- Newer platform with less historical data
- Decentralized model may have different risk profile
- Limited fiat on/off ramps
- Need to manage own wallet/keys

#### API Documentation
- **Official Docs**: https://hyperliquid.gitbook.io/hyperliquid-docs
- **WebSocket Subscriptions**: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions
- **Fees**: https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees
- **Dwellir WebSocket**: https://www.dwellir.com/docs/hyperliquid/websocket-api
- **Hummingbot Integration**: https://hummingbot.org/exchanges/hyperliquid/

#### Authentication
- API key authentication now supported (in addition to Arbitrum wallet + private key mode)
- Easier integration than pure wallet-based auth

---

### 2.2 GMX

#### Platform Overview
- **Type**: Decentralized perpetual exchange (AMM-based)
- **Blockchain**: Arbitrum and Avalanche (multi-chain)
- **Model**: Liquidity pool (GLP) rather than order book
- **Leverage**: Up to 100x on select pairs
- **2025-2026 Expansion**: Solana, gasless transactions, cross-chain functionality

#### Architecture
- **Liquidity Model**: GLP (GMX Liquidity Pool) - multi-asset pool
- **Pricing**: Oracle-based (Chainlink) rather than orderbook
- **GMX v2**: Isolated pools per market (improved from single-pool v1)
- **Order Book Contract**: On-chain smart contract for limit orders (gmx-io/gmx-contracts on GitHub)

#### Trading Fees
- **Trading Fee**: 0.1% of position size (open/close)
- **Borrow Fee**: Variable based on asset utilization
- **Fee Distribution**:
  - 30% to GMX stakers
  - 70% to GLP holders (liquidity providers)
- **No Maker/Taker Split**: Flat 0.1% trading fee

#### Data Types Available
- **No Traditional Orderbook**: Uses oracle prices (Chainlink)
- **Smart Contract Events**: On-chain trade data, position updates
- **GLP Pool Metrics**: Pool composition, utilization, fees earned
- **Perpetual Markets**: Limited to 9+ main markets (BTC, ETH, SOL, etc.)

#### Pros
- Simple AMM model (easier for retail)
- Oracle pricing eliminates orderbook manipulation
- Earn yield as liquidity provider (70% of fees)
- Multi-chain support (Arbitrum, Avalanche, expanding)
- Gasless transactions coming (Q4 2025/Q1 2026)

#### Cons
- **NO ORDERBOOK DATA** (oracle-based pricing)
- Not suitable for orderflow/mean reversion strategies
- Higher trading fees (0.1% flat vs 0.01-0.05% on CEX)
- Limited market selection (9 perp markets)
- Liquidity depth less than major CEX

#### 2026 Roadmap
- Network Fee Subsidy Pool (Q1 2026)
- Multichain expansion (Solana + EVM chains)
- Gasless transactions (signature-only)

#### Verdict for Orderflow Trading
- **NOT RECOMMENDED** for orderflow/mean reversion strategies
- No access to orderbook depth, trade flow, or market microstructure
- Better suited for simple leveraged trading or LP yield farming

#### Resources
- **Official Site**: https://gmx.io/
- **Documentation**: https://gmx-docs.io/docs/trading/v2/
- **GitHub**: https://github.com/gmx-io/gmx-contracts

---

### 2.3 dYdX

#### Platform Overview
- **Type**: Decentralized perpetual futures exchange (order book based)
- **Blockchain**: Custom Cosmos SDK chain (migrated from Ethereum L2)
- **Launch**: 2019 (V1), evolved through multiple versions
- **Funding**: $85M from a16z, Polychain, Delphi Ventures, Hashkey Capital
- **TVL**: $2.18B (Q3 2025)

#### Architecture
- **Consensus**: CometBFT (formerly Tendermint)
- **Model**: Fully decentralized order book (not AMM)
- **Migration**: From StarkWare L2 to Cosmos SDK for sovereignty
- **Target Users**: Institutional and advanced traders

#### Data Types Available
- **Order Book**: Full order book depth via WebSocket
- **Trade Data**: Real-time trade execution
- **Account Updates**: Private WebSocket channels for positions/orders
- **Leverage**: Up to 20x maximum

#### Trading Features
- Perpetual futures (primary product)
- Margin trading
- Spot trading (also available)
- Broader product range than GMX

#### Pros
- True decentralized order book (suitable for orderflow strategies)
- Institutional-grade infrastructure
- Strong funding and backing
- Large TVL ($2.18B)
- Longer track record (since 2019)

#### Cons
- Lower leverage than competitors (20x vs 50x on GMX/Hyperliquid)
- Smaller market selection vs CEX
- Custom chain requires different tooling than EVM
- May have lower liquidity than top CEX

#### Market Position (2025-2026)
- Combined perp DEX market cap: $18.9B (up 654% YoY)
- dYdX is a top-tier perp DEX alongside Hyperliquid
- Institutional adoption increasing

#### Verdict for Orderflow Trading
- **SUITABLE** for orderflow strategies (has real order book)
- Precision execution for advanced traders
- Lower fees than GMX, competitive with some CEX
- Good option for decentralized orderflow trading

#### API Documentation
- Official documentation should provide WebSocket/REST API details
- Search results didn't capture specific API endpoints (check official docs)

#### Note
- Web search was unavailable for detailed dYdX API documentation
- Recommend visiting official dYdX docs for current 2026 API specifications

---

## 3. Data Aggregators & Analytics Providers

### 3.1 CoinGlass

#### Platform Overview
- **Type**: Crypto derivatives data aggregator and analytics platform
- **Coverage**: 100+ exchanges (CEX and DEX)
- **Data Types**: Open interest, funding rates, liquidations, long/short ratios, whale metrics

#### API v4 Features

##### Core Derivatives Data
- **Funding Rates**: Real-time and historical funding rate data
- **Open Interest**: Historical and real-time OI across exchanges
- **Liquidation Events**:
  - Liquidation history (long/short liquidations by trading pair)
  - Liquidation map (mapped visualization of liquidation events)
  - Liquidation heatmap (levels calculated from market data + leverage)
- **Long/Short Ratios**: Trader positioning metrics
- **Price OHLC**: Historical candlestick data

##### Advanced Market Data (NEW in v4)
- **Spot Order Books**: L2 and L3 order book depth
- **Order Flow Data**: Trade flow analysis
- **Whale Activity**: Large position tracking
- **ETF Net Flows**: Bitcoin and crypto ETF flow data
- **On-Chain Reserves**: Exchange reserve monitoring
- **Market Structure Indicators**: Macro crypto market metrics

#### Data Delivery
- **Methods**: API, CSV, real-time streaming, Snowflake integration
- **Update Frequency**: Real-time for liquidation endpoints (all plans)
- **Cache/Refresh**: Real-time across all API plans

#### Pricing
- **Free Tier**: NOT AVAILABLE for API access
- **API Access**: Requires purchase of API add-on (no free tier mentioned)
- **Recommendation**: Visit https://www.coinglass.com/pricing for current 2026 pricing

#### Use Cases
- Cross-exchange open interest aggregation
- Liquidation level analysis (heatmaps for support/resistance)
- Funding rate arbitrage opportunities
- Whale tracking and smart money following
- Market sentiment analysis (long/short ratios)

#### Pros
- Aggregates data from 100+ exchanges (comprehensive view)
- Real-time liquidation heatmaps (useful for orderflow context)
- Advanced v4 features (L2/L3 orderbook, whale tracking)
- Multiple delivery formats (API, CSV, Snowflake)

#### Cons
- **No free API tier** (paid subscription required)
- Not a direct trading/execution platform (analytics only)
- Pricing not publicly disclosed (must contact sales)

#### Resources
- **Official Site**: https://www.coinglass.com/
- **API Documentation**: https://docs.coinglass.com/
- **Pricing**: https://www.coinglass.com/pricing
- **Liquidation Heatmap**: https://www.coinglass.com/pro/futures/LiquidationHeatMap

---

### 3.2 Glassnode

#### Platform Overview
- **Type**: On-chain analytics and crypto market data provider
- **Specialty**: Bitcoin and altcoin on-chain metrics
- **Data Collection**: Longest-running on-chain data in the industry
- **Metrics**: 1000+ unique BTC metrics + extensive altcoin coverage

#### API Features
- **Protocol**: Single REST API for all metrics
- **Data Types**: Live and historical on-chain + crypto market data
- **Coverage**: Bitcoin (most comprehensive), major altcoins
- **Speed**: Built for speed, efficiency, and precision

#### On-Chain Metrics Categories
- Active addresses and transfer volumes
- Realized capital flows
- Network activity (transactions, fees)
- Holder behavior (long-term vs short-term)
- Mining metrics
- Exchange flows (inflows/outflows)
- UTXO age distribution
- Realized profit/loss metrics

#### Pricing
- **Free API Tier**: **NOT AVAILABLE**
- **API Access**: Requires Professional plan + API add-on purchase
- **Contact**: Must contact institutional team to upgrade
- **Web Dashboard**: May have limited free access for charting (not API)

#### 2026 Market Context (from Glassnode Insights)
- BTC consolidating between low $80Ks and mid $90Ks
- Network activity expanding (active addresses, transfer volumes)
- Fee pressure subdued (low congestion)
- Realized capital growth negative (net capital outflows)

#### Use Cases for Trading
- Macro trend analysis (not orderflow)
- On-chain support/resistance levels (realized price, MVRV)
- Smart money tracking (exchange flows, whale movements)
- Cycle timing (SOPR, NUPL, Puell Multiple)

#### Pros
- Industry-leading on-chain data (since 2010 for Bitcoin)
- Comprehensive metric catalog (1000+ for BTC)
- Professional-grade data quality
- Official documentation and metric guides

#### Cons
- **No free API access** (requires paid Professional plan)
- **Not suitable for orderflow trading** (macro/on-chain focus)
- Expensive for small capital traders ($300 budget)
- Data is slower-moving (on-chain vs tick-level orderbook)

#### Verdict for Orderflow Trading
- **NOT RECOMMENDED** for $300 budget orderflow bot
- Better suited for macro trend analysis and position sizing
- On-chain metrics are complementary, not primary signals for orderflow

#### Resources
- **Official Site**: https://glassnode.com/
- **API Documentation**: https://docs.glassnode.com/basic-api/api
- **Metric Coverage**: https://docs.glassnode.com/data/supported-assets/onchain-metrics-coverage
- **2026 Insights**: https://insights.glassnode.com/btc-market-pulse-week-2-2026/

---

### 3.3 Tardis.dev

#### Platform Overview
- **Type**: Historical cryptocurrency market data provider
- **Coverage**: Hundreds of terabytes of tick-level data
- **Exchanges**: All leading spot and derivatives crypto exchanges
- **Data Since**: 2019-03-30 for majority of exchanges

#### Data Types Available
- **Order Book**: Tick-level snapshots and incremental L2 updates
- **Trade Data**: Individual trade execution (tick data)
- **Quotes**: Bid/ask quotes
- **Funding Rates**: Historical funding rate data
- **Liquidations**: Historical liquidation events
- **Options Chains**: Options market data (select exchanges)
- **Format**: JSON + local timestamps, downloadable CSV files

#### Free Trial & Free Data
- **Free Trial**: Generous free trials available (contact Tardis team)
- **No API Key Required**: First day of each month's historical data is FREE
- **Test Data**: Test data quality, coverage, API performance before purchasing

#### Pricing Models

##### One-Off Purchases
- **Access Period**: Specific time ranges of historical data
- **API Key Validity**: 1 year from purchase
- **Data Types**: All available (trades, orderbooks, etc.)
- **Delivery**: API access + downloadable CSV files
- **Payment**: Accepts BTC, ETH, USDT

##### Subscriptions
- **Monthly**: 4 months of historical data + new data as collected
- **Quarterly**: 12 months of historical data + ongoing updates
- **Yearly**: ALL historical data (since 2019-03-30) + ongoing updates
- **Academic**: Heavily discounted for students/researchers (university email required)
- **Business**: Multi-user access, dedicated support, integration assistance

#### Supported Exchanges
- **Binance**: USDT futures, depth@100ms (later depth@0ms), depth snapshots (top 1000 levels)
- **Deribit**: Futures and options data (same format as real-time WebSocket)
- **OKX**: Swap/futures historical data
- **Bybit**: Historical tick data
- **Many others**: Check docs for full list

#### Client Libraries
- **Python**: Robust Python client library
- **Node.js**: Node.js client library
- **Access**: Programmatic API access or CSV download

#### Pros
- **First day of each month FREE** (no API key needed!)
- Generous free trials (test before buying)
- Comprehensive historical data (since 2019)
- Tick-level granularity (perfect for backtesting orderflow strategies)
- Multiple delivery formats (API, CSV)
- Academic discounts available

#### Cons
- Real-time data requires subscribing to exchanges directly
- Paid subscriptions required for extensive historical access
- One-off purchases expire after 1 year

#### Use Cases for Orderflow Bot
- **Backtesting orderflow strategies** (tick-level orderbook data)
- Strategy validation before live trading
- Training machine learning models on historical patterns
- Research and development

#### Recommended Approach
1. Use FREE first-day-of-month data for initial testing
2. Request free trial for deeper evaluation
3. Purchase monthly subscription ($cheaper) or one-off specific date range
4. Combine with live Binance WebSocket for real-time execution

#### Resources
- **Official Site**: https://tardis.dev/
- **Documentation**: https://docs.tardis.dev/
- **Free Trial**: Contact via website
- **Binance Data**: https://docs.tardis.dev/historical-data-details/binance-futures
- **Deribit Data**: https://docs.tardis.dev/historical-data-details/deribit

---

### 3.4 Kaiko

#### Platform Overview
- **Type**: Institutional-grade cryptocurrency market data provider
- **Established**: 2014 (10+ years of data collection)
- **Coverage**: 100+ exchanges (CEX and DEX), lending protocols
- **Market**: Projected $3.8B institutional digital asset data market by 2026

#### Data Types Available
- **Level 1 & Level 2 Data**: Trade and order book snapshots
- **L1/L2 Focus**: Primarily snapshots (not L3 per-order event streams)
- **Aggregation**: Standardized trade and orderbook data across markets
- **Precomputed Metrics**: Depth, slippage, fair value calculations
- **Derivatives**: Strong support for futures and perpetual markets
- **Spot Markets**: CEX and DEX coverage
- **Indices**: Kaiko provides crypto indices

#### Data Delivery
- **API**: REST API for programmatic access
- **CSV**: Downloadable historical data files
- **Real-time Streaming**: Live market data feeds
- **Snowflake**: Cloud-based data warehouse integration
- **LSEG Partnership**: Available through London Stock Exchange Group (LSEG)

#### Pricing
- **Free Tier**: **NOT AVAILABLE**
- **Published Pricing**: **NONE** (must contact Kaiko sales)
- **Estimated Cost** (Vendr transaction data):
  - Minimum: ~$9,500/year
  - Maximum: ~$55,000/year
  - Average: ~$28,500/year
- **Recent Trends**: Kaiko reducing discounts (correcting 20%+ discounts)
- **Example**: Customer price increase from $9.5K → $13.125K (was 46% discount)

#### Target Market
- Institutional traders
- Quantitative researchers
- Risk management teams
- Compliance departments
- Enterprise financial firms

#### Strengths
- Standardized, normalized data (high quality)
- Broad exchange coverage (100+)
- Historical datasets (since 2014)
- Regulatory-oriented datasets
- Strong analytics and indices
- Established enterprise positioning

#### Weaknesses
- **No L3/per-order event streams** (publicly disclosed)
- **No FIX Protocol support** (publicly disclosed)
- **No public SLAs on latency**
- Very expensive for retail/small traders ($300 budget)

#### Competitive Positioning
- Institutional competitor to CoinAPI, Tardis.dev
- Strong for compliance, risk management, backtesting
- Less suitable for real-time orderflow (no L3 data, no latency SLAs)

#### Verdict for Orderflow Trading
- **NOT RECOMMENDED** for $300 budget
- Pricing far exceeds available capital ($9.5K+ minimum)
- Better alternatives: Tardis.dev (cheaper), Binance (free real-time)

#### Resources
- **Official Site**: https://www.kaiko.com/
- **Pricing Contact**: https://www.kaiko.com/about-kaiko/pricing-and-contracts
- **Developer Hub**: https://docs.kaiko.com/
- **L1/L2 Data**: https://www.kaiko.com/products/data-feeds/l1-l2-data

---

### 3.5 CryptoCompare

#### Platform Overview
- **Type**: Cryptocurrency market data API provider
- **Coverage**: 316 exchanges, 7,287 assets, 338,335 trading pairs
- **Infrastructure**: 40,000 calls/second, 8,000 trades/second processing capacity
- **Specialty**: Normalized price indices (CCCAGG algorithm)

#### Data Types Available
- **Price Data**: Real-time and historical prices
- **OHLCV**: Daily, hourly, minute-level candlestick data
- **Order Book**: Market depth data
- **Trade Data**: Individual trade executions
- **News Feeds**: Latest crypto news articles
- **Social Sentiment**: Community sentiment analysis
- **Market Data**: Volume, market cap, supply

#### Free Tier
- **API Key Required**: Yes (free registration for non-commercial use)
- **Free Tier Limits**:
  - A few thousand calls per day (community reports)
  - Exact limits not publicly specified
  - IP-based limiting for older endpoints
- **Attribution Required**: Must reference CryptoCompare in your app
- **Use Case**: Personal/non-commercial projects

#### Paid Plans
- **Basic**: ~$80/month
- **Advanced**: ~$200/month
- **Call Limits**: 100K - few hundred thousand calls/month (varies by plan)
- **Features**:
  - Access to ~60+ endpoints
  - Full historical data download (daily/hourly)
  - Minute data beyond 7 days (enterprise-only)

#### Data Quality
- **Normalization**: Proprietary CCCAGG algorithm
- **Filtering**: Removes outlier prices and exchange anomalies
- **Clean Indices**: Delivers consistent price indices across markets

#### Historical Data
- **Daily/Hourly**: Substantial historical depth on free tier
- **Minute Data**: Last 7 days on paid plans, beyond 7 days enterprise-only
- **Throttling**: Heavy use may be throttled on free tier

#### Pros
- Free tier available for small projects
- Broad exchange and asset coverage
- Historical price data on free tier
- News and sentiment feeds included
- Normalized price indices (CCCAGG)

#### Cons
- Limited calls per day on free tier (not suitable for high-frequency)
- Minute data beyond 7 days requires expensive enterprise plan
- **Not tick-level orderbook data** (aggregated/snapshot focus)
- Attribution required for free tier

#### Verdict for Orderflow Trading
- **LIMITED USE** for orderflow bot
- Good for price context and historical backtesting (daily/hourly)
- NOT suitable for tick-level orderflow strategies
- Free tier insufficient for real-time orderflow monitoring

#### Recommended Use Case
- Supplement to primary data source (price context, news)
- Historical price data for macro analysis
- Free tier for prototyping before paying for real data

#### Resources
- **Official Site**: https://www.cryptocompare.com/
- **API Guide**: https://www.cryptocompare.com/coins/guides/how-to-use-our-api/
- **API Documentation**: https://min-api.cryptocompare.com/
- **Pricing**: https://min-api.cryptocompare.com/pricing

---

## 4. Comparison Tables

### 4.1 Exchange Fee Comparison (BTC Perpetual Futures)

| Exchange | Maker Fee | Taker Fee | Notes |
|----------|-----------|-----------|-------|
| **MEXC** | **0.01%** | **0.04%** | Lowest maker; 50% discount with MX token; 500x leverage |
| **Binance** | 0.02% | 0.04% | 10% BNB discount; best liquidity |
| **Bybit** | 0.02% | 0.055% | Zero-fee campaigns; VIP → 0%/0.018% |
| **OKX** | 0.02% | 0.05% | OKB discounts; VIP → -0.005%/0.015% |
| **Hyperliquid** | **-0.001% to -0.003%** | 0.045%→0.030% | **MAKER REBATES!**; DEX; <1s confirms |
| **GMX** | 0.1% | 0.1% | No maker/taker split; AMM model; **NO ORDERBOOK** |
| **dYdX** | ~0.02% | ~0.05% | DEX; order book based; institutional |
| **Paradex** | **0%** | **0%** | Zero-fee DEX; Starknet-based |

**Lowest Fees**: MEXC (maker), Hyperliquid (maker rebates), Binance (taker)

---

### 4.2 Data Availability Comparison

| Source | Real-Time Orderbook | Historical Data | Free Tier | Best For |
|--------|---------------------|-----------------|-----------|----------|
| **Binance API** | ✅ 100ms WebSocket | ✅ Data Vision | ✅ Yes (no key for WS) | Real-time execution + free data |
| **Tardis.dev** | ❌ Historical only | ✅ Since 2019 | ✅ Free trial + 1st day/month | Backtesting, research |
| **OKX API** | ✅ WebSocket | ✅ Limited | ✅ Yes (public WS) | Alternative to Binance |
| **Bybit API** | ✅ WebSocket | ✅ Limited | ✅ Yes (WS not rate-limited) | Liquidation data |
| **Hyperliquid** | ✅ 10-100ms WS | ⚠️ Limited (newer) | ✅ Yes | DEX trading + rebates |
| **CoinGlass** | ❌ Analytics only | ✅ Aggregated | ❌ No (paid API) | Market context, liquidations |
| **Glassnode** | ❌ On-chain only | ✅ Since 2010 | ❌ No (paid API) | Macro analysis |
| **CryptoCompare** | ⚠️ Aggregated | ✅ Daily/hourly | ✅ Limited free | Price context |
| **Kaiko** | ⚠️ L1/L2 snapshots | ✅ Since 2014 | ❌ No ($9.5K+/year) | Institutional only |

**Best Free Real-Time**: Binance WebSocket
**Best Free Historical**: Tardis.dev (first day of month + free trial)
**Best Combined**: Binance + Tardis.dev

---

### 4.3 Exchange Liquidity & Features

| Exchange | Type | Liquidity | Max Leverage | Unique Features |
|----------|------|-----------|--------------|-----------------|
| **Binance** | CEX | ⭐⭐⭐⭐⭐ Highest | 125x | Industry standard; best liquidity; Data Vision |
| **MEXC** | CEX | ⭐⭐⭐ Medium | 500x | Lowest maker fee; highest leverage |
| **OKX** | CEX | ⭐⭐⭐⭐ High | 125x | WebSocket trading via v5; OKB benefits |
| **Bybit** | CEX | ⭐⭐⭐⭐ High | 100x | Best liquidation data; zero-fee campaigns |
| **Hyperliquid** | DEX | ⭐⭐⭐ Medium | 50x | Maker rebates; <1s confirms; 100K orders/s |
| **dYdX** | DEX | ⭐⭐⭐ Medium | 20x | True DEX orderbook; $2.18B TVL; institutional |
| **GMX** | DEX | ⭐⭐ Low | 100x | AMM model; **NO ORDERBOOK**; LP yield |

**Highest Liquidity**: Binance > OKX > Bybit
**Best DEX Liquidity**: Hyperliquid, dYdX

---

## 5. Recommended Data Stack

### For $300 Budget Orderflow Trading Bot

#### Primary Data Source (Real-Time)
**Binance Futures WebSocket** ✅
- **Why**: Free, highest liquidity, 100ms orderbook updates, no API key required for market data
- **Data**: Orderbook depth, trades, funding rate, open interest
- **Endpoint**: `wss://fstream.binance.com/stream?streams=btcusdt@depth@100ms|btcusdt@aggTrade`
- **Cost**: FREE

#### Historical Data (Backtesting)
**Tardis.dev** ✅
- **Why**: Free trial + first day of each month free, tick-level orderbook data
- **Use**: Backtest orderflow strategies, validate signals
- **Cost**: FREE for initial testing, then ~$50-100/month if needed

#### Market Context (Optional)
**CoinGlass Web Dashboard** (Free charts, no API)
- **Why**: Visualize liquidation heatmaps, open interest, funding rates
- **Use**: Understand market structure, identify liquidation clusters
- **Cost**: FREE (web dashboard)

#### Execution Platform
**Option A: Binance Futures** (if staying CEX)
- Fees: 0.02% maker / 0.04% taker
- Liquidity: Best in industry
- Integration: Same as data source (simpler)

**Option B: Hyperliquid** (if willing to use DEX)
- Fees: **-0.001% to -0.003% maker rebates** (PAID to trade!)
- Liquidity: Good (but less than Binance)
- Integration: Requires wallet management, different tooling

#### Alternative Low-Fee Option
**MEXC** (if futures API access granted)
- Fees: 0.01% maker / 0.04% taker (lowest maker)
- Requires: Institutional account (contact institution@mexc.com)

---

## 6. Implementation Recommendations

### Phase 1: Development & Backtesting (FREE)
1. **Real-Time Data**: Binance Futures WebSocket
   - Subscribe to: `btcusdt@depth@100ms`, `btcusdt@aggTrade`, `btcusdt@markPrice@1s`
   - Monitor: Orderbook imbalance, trade flow, funding rate
   - No API key required for market data

2. **Historical Data**: Tardis.dev
   - Request free trial account
   - Download first day of each month (free)
   - Backtest orderflow signals on tick data
   - Validate strategy before live trading

3. **Market Context**: CoinGlass web charts
   - View liquidation heatmaps (free web access)
   - Check open interest trends
   - Monitor funding rates across exchanges

**Cost: $0**

---

### Phase 2: Paper Trading (FREE)
1. Continue using Binance WebSocket for real-time data
2. Simulate order execution with zero cost
3. Track hypothetical P&L
4. Validate strategy performance over 3-7 days (per CLAUDE.md P0 requirements)

**Cost: $0**

---

### Phase 3: Live Trading (LOW COST)
1. **Choose Execution Platform**:
   - **Binance**: Safest, most liquid (0.02%/0.04% fees)
   - **Hyperliquid**: Maker rebates (-0.003%) but DEX complexity
   - **MEXC**: Lowest maker (0.01%) if institutional access granted

2. **Start Small**:
   - $15/trade max (5% of $300 capital per CLAUDE.md)
   - $30/day max loss (per CLAUDE.md kill switch)

3. **Monitor Performance**:
   - Use same Binance WebSocket data (free)
   - Track actual vs expected execution
   - Adjust strategy as needed

**Cost: Trading fees only** (0.01-0.04% per trade)

---

### Optional: Advanced Data (If Strategy Proves Profitable)
1. **Tardis.dev Subscription**: ~$50-100/month
   - Access more historical data
   - Improve backtesting depth
   - Train ML models

2. **CoinGlass API**: Contact for pricing
   - Programmatic access to liquidation data
   - Cross-exchange open interest
   - Automate market context analysis

**Cost: $50-100+/month** (only if strategy is profitable)

---

## 7. Data Source JSON Summary

```json
{
  "exchanges": {
    "binance": {
      "type": "CEX",
      "data_types": [
        "Orderbook (100ms, 250ms, 500ms WebSocket)",
        "Trade data (individual + aggTrades)",
        "Open interest (historical + real-time)",
        "Funding rate (historical API)",
        "Liquidations",
        "Klines/OHLCV (historical download)"
      ],
      "historical_depth": "Since 2019 (most pairs), Data Vision archive available",
      "rate_limits": {
        "rest_api": "2,400 req/min (default), volume-based VIP tiers available",
        "websocket": "10 msg/sec per connection, max 1024 streams",
        "websocket_connections": "300 per 5 min per IP"
      },
      "fees": {
        "maker": "0.02%",
        "taker": "0.04-0.05%",
        "bnb_discount": "10% (USDT-M futures)",
        "vip9": "0% maker / 0.017% taker"
      },
      "api_docs_url": "https://developers.binance.com/docs/derivatives/usds-margined-futures",
      "websocket_endpoint": "wss://fstream.binance.com/stream",
      "free_tier": true,
      "notes": "Best liquidity, free WebSocket market data, industry standard"
    },
    "okx": {
      "type": "CEX",
      "data_types": [
        "Orderbook (WebSocket books channel)",
        "Trade data",
        "Open interest",
        "Funding rate (8h intervals)",
        "Perpetual swaps, futures, options"
      ],
      "historical_depth": "Available but limited (use Tardis.dev for extensive history)",
      "rate_limits": {
        "websocket": "3 req/sec per IP",
        "authentication": "OK-ACCESS-KEY, OK-ACCESS-SIGN, OK-ACCESS-TIMESTAMP"
      },
      "fees": {
        "maker": "0.02%",
        "taker": "0.05%",
        "vip_max": "-0.005% maker (rebate) / 0.015% taker",
        "okb_discount": "Additional tier benefits with OKB holdings"
      },
      "api_docs_url": "https://www.okx.com/docs-v5/en/",
      "websocket_endpoint": "wss://ws.okx.com:8443/ws/v5/public",
      "free_tier": true,
      "notes": "API v5 supports trading via WebSocket (unique), competitive VIP rebates"
    },
    "bybit": {
      "type": "CEX",
      "data_types": [
        "Orderbook (snapshots + delta, 200ms for L1000)",
        "Trade data",
        "All Liquidation stream (full, no throttling)",
        "Open interest",
        "USDT, USDC, Inverse contracts"
      ],
      "historical_depth": "Limited official, use Tardis.dev or community tools (BybitMarketData GitHub)",
      "rate_limits": {
        "websocket": "WebSocket market data NOT counted against rate limits",
        "server_location": "Singapore AWS apse1-az3"
      },
      "fees": {
        "maker": "0.02%",
        "taker": "0.055%",
        "vip_max": "0% maker / 0.018% taker",
        "promotions": "Zero-fee BTC/USDT campaigns"
      },
      "api_docs_url": "https://bybit-exchange.github.io/docs/v5/",
      "websocket_endpoint": "wss://stream.bybit.com/v5/public",
      "free_tier": true,
      "notes": "Best liquidation data (All Liquidation endpoint), WS not rate-limited"
    },
    "mexc": {
      "type": "CEX",
      "data_types": [
        "Orderbook depth (max 100 levels)",
        "Trade data",
        "Snapshot updates",
        "Open interest",
        "Funding rate"
      ],
      "historical_depth": "Since 2022-10-19 (via Amberdata)",
      "rate_limits": {
        "futures_api": "Institutional users only (contact institution@mexc.com)"
      },
      "fees": {
        "maker": "0.01% (LOWEST)",
        "taker": "0.04%",
        "mx_discount": "50% reduction with MX tokens",
        "leverage": "500x (highest in industry)"
      },
      "api_docs_url": "https://www.mexc.com/api-docs/futures/market-endpoints",
      "free_tier": "Limited (institutional access for futures)",
      "notes": "Lowest maker fee, highest leverage, but futures API restricted to institutions"
    },
    "deribit": {
      "type": "CEX",
      "data_types": [
        "Orderbook (raw tick-by-tick or 100ms aggregated)",
        "Trade data",
        "Options chains (unique strength)",
        "BTC futures (cash-settled)"
      ],
      "historical_depth": "From 2021-05-21 (via Tardis.dev/Amberdata)",
      "rate_limits": {
        "subscription_limit": "500 channels per subscription",
        "protocols": "WebSocket, FIX, REST (WS preferred)"
      },
      "fees": {
        "maker": "Not detailed in research",
        "taker": "Not detailed in research",
        "notes": "Focus on options, not lowest perp fees"
      },
      "api_docs_url": "https://docs.deribit.com/",
      "websocket_endpoint": "wss://www.deribit.com/ws/api/v2",
      "free_tier": true,
      "notes": "Best for options data, guaranteed in-order delivery, 500 channels/subscription"
    },
    "hyperliquid": {
      "type": "DEX",
      "data_types": [
        "Orderbook (L2, L4 via WebSocket)",
        "Trade data",
        "Liquidations",
        "Perpetual futures"
      ],
      "historical_depth": "Limited (newer platform, verify with Tardis.dev integration)",
      "rate_limits": {
        "latency": "10-100ms WebSocket, 50-200ms REST",
        "throughput": "100,000 orders/second",
        "confirmation": "<1 second"
      },
      "fees": {
        "maker": "-0.001% to -0.003% (REBATES!)",
        "taker": "0.045% → 0.030% (high volume)",
        "maker_tiers": "-0.001% (0.5%+ maker vol) → -0.003% (3.0%+ maker vol)",
        "aligned_assets": "20% lower taker, 50% better maker rebates",
        "hip3_growth_mode": "90% fee reduction for new markets"
      },
      "api_docs_url": "https://hyperliquid.gitbook.io/hyperliquid-docs",
      "websocket_endpoint": "See official docs",
      "free_tier": true,
      "notes": "MAKER REBATES (paid to provide liquidity!), ultra-low latency, DEX model"
    },
    "gmx": {
      "type": "DEX (AMM)",
      "data_types": [
        "NO ORDERBOOK (oracle-based pricing)",
        "GLP pool metrics",
        "On-chain trade events",
        "Position updates"
      ],
      "historical_depth": "On-chain data via blockchain explorers",
      "rate_limits": {
        "model": "Liquidity pool (AMM), not order book"
      },
      "fees": {
        "trading": "0.1% flat (open/close)",
        "borrow": "Variable by asset utilization",
        "distribution": "30% GMX stakers, 70% GLP holders"
      },
      "api_docs_url": "https://gmx-docs.io/docs/trading/v2/",
      "free_tier": true,
      "notes": "NOT SUITABLE for orderflow trading (no orderbook), AMM model, LP yield focus"
    },
    "dydx": {
      "type": "DEX (Order Book)",
      "data_types": [
        "Order book (full depth via WebSocket)",
        "Trade data",
        "Account updates (private WS)",
        "Perpetual futures, margin, spot"
      ],
      "historical_depth": "Since 2019 (V1 launch), Cosmos SDK chain since migration",
      "rate_limits": {
        "blockchain": "Cosmos SDK + CometBFT consensus",
        "leverage": "20x maximum"
      },
      "fees": {
        "maker": "~0.02%",
        "taker": "~0.05%",
        "notes": "Competitive with CEX, lower than GMX"
      },
      "api_docs_url": "Check official dYdX docs (search unavailable for details)",
      "free_tier": true,
      "notes": "True DEX order book (suitable for orderflow), institutional-grade, $2.18B TVL"
    }
  },
  "aggregators": {
    "coinglass": {
      "type": "Derivatives data aggregator",
      "data_types": [
        "Open interest (100+ exchanges)",
        "Funding rates",
        "Liquidation history/map/heatmap",
        "Long/short ratios",
        "Whale tracking",
        "L2/L3 orderbook (API v4)",
        "Order flow data",
        "ETF flows",
        "On-chain reserves"
      ],
      "historical_depth": "Extensive cross-exchange historical data",
      "rate_limits": {
        "update_frequency": "Real-time (all plans)",
        "delivery": "API, CSV, real-time streaming, Snowflake"
      },
      "fees": {
        "free_tier": "NOT AVAILABLE",
        "paid_api": "Must purchase API add-on, pricing not disclosed"
      },
      "api_docs_url": "https://docs.coinglass.com/",
      "free_tier": false,
      "notes": "Aggregates 100+ exchanges, real-time liquidation heatmaps, no free API"
    },
    "glassnode": {
      "type": "On-chain analytics",
      "data_types": [
        "On-chain metrics (1000+ for BTC)",
        "Active addresses, transfers",
        "Realized capital flows",
        "Network activity, fees",
        "Exchange flows",
        "UTXO age, holder behavior"
      ],
      "historical_depth": "Since 2010 (Bitcoin), longest-running on-chain data",
      "rate_limits": {
        "access": "Professional plan + API add-on required"
      },
      "fees": {
        "free_tier": "NOT AVAILABLE for API",
        "paid_api": "Professional plan required, contact sales"
      },
      "api_docs_url": "https://docs.glassnode.com/basic-api/api",
      "free_tier": false,
      "notes": "NOT for orderflow (macro/on-chain focus), expensive, institutional-grade"
    },
    "tardis_dev": {
      "type": "Historical market data provider",
      "data_types": [
        "Tick-level orderbook (snapshots + L2 incremental)",
        "Trade data (tick)",
        "Quotes (bid/ask)",
        "Funding rates",
        "Liquidations",
        "Options chains"
      ],
      "historical_depth": "Since 2019-03-30 (most exchanges), hundreds of TB",
      "rate_limits": {
        "free_trial": "Generous free trials (contact Tardis)",
        "free_data": "First day of each month FREE (no API key)"
      },
      "fees": {
        "free_tier": "FREE trial + first day/month",
        "monthly": "~$50-100/mo (4 months history)",
        "quarterly": "12 months history",
        "yearly": "All data since 2019",
        "academic": "Discounted (university email)",
        "one_off": "Specific date ranges, 1-year validity, accepts BTC/ETH/USDT"
      },
      "api_docs_url": "https://docs.tardis.dev/",
      "free_tier": true,
      "notes": "BEST for backtesting, free trial + first day/month, tick-level orderbook, Python/Node.js libraries"
    },
    "kaiko": {
      "type": "Institutional market data",
      "data_types": [
        "L1/L2 market data (snapshots)",
        "Precomputed metrics (depth, slippage, fair value)",
        "Derivatives support",
        "Spot (CEX + DEX)",
        "Indices"
      ],
      "historical_depth": "Since 2014 (10+ years)",
      "rate_limits": {
        "delivery": "API, CSV, real-time streaming, Snowflake"
      },
      "fees": {
        "free_tier": "NOT AVAILABLE",
        "minimum": "$9,500/year",
        "maximum": "$55,000/year",
        "average": "$28,500/year"
      },
      "api_docs_url": "https://docs.kaiko.com/",
      "free_tier": false,
      "notes": "NOT for $300 budget, institutional only, expensive ($9.5K+ min), no L3 data"
    },
    "cryptocompare": {
      "type": "Market data API",
      "data_types": [
        "Price data (real-time + historical)",
        "OHLCV (daily, hourly, minute)",
        "Order book (aggregated)",
        "Trade data",
        "News feeds",
        "Social sentiment"
      ],
      "historical_depth": "Substantial (daily/hourly on free tier, minute limited)",
      "rate_limits": {
        "free_tier": "Few thousand calls/day (community reports)",
        "api_key": "Required (free registration for non-commercial)"
      },
      "fees": {
        "free_tier": "FREE (non-commercial, attribution required)",
        "basic": "$80/month (100K+ calls)",
        "advanced": "$200/month",
        "minute_data": "7 days on paid, >7 days enterprise-only"
      },
      "api_docs_url": "https://min-api.cryptocompare.com/",
      "free_tier": true,
      "notes": "Limited use for orderflow (aggregated, not tick-level), good for price context"
    }
  },
  "dex_options": {
    "hyperliquid": {
      "advantage": "Maker rebates (-0.003%), ultra-low latency, high throughput",
      "disadvantage": "Lower liquidity than CEX, DEX complexity, wallet management",
      "fee_structure": "Paid to provide liquidity (rebates)",
      "suitable_for_orderflow": true
    },
    "dydx": {
      "advantage": "True order book DEX, institutional-grade, $2.18B TVL",
      "disadvantage": "Lower leverage (20x), smaller market selection, custom Cosmos chain",
      "fee_structure": "Competitive with CEX (~0.02%/0.05%)",
      "suitable_for_orderflow": true
    },
    "gmx": {
      "advantage": "Simple AMM, LP yield (70% of fees), multi-chain, gasless txns coming",
      "disadvantage": "NO ORDERBOOK (oracle pricing), higher fees (0.1%), not for orderflow",
      "fee_structure": "0.1% flat trading fee",
      "suitable_for_orderflow": false
    },
    "paradex": {
      "advantage": "Zero-fee perpetual and options DEX",
      "disadvantage": "Newer platform, limited information in research",
      "fee_structure": "0% maker / 0% taker",
      "suitable_for_orderflow": "Unknown (requires further research)"
    }
  },
  "recommended_primary": "Binance Futures",
  "recommended_data_stack": [
    "Binance Futures WebSocket (real-time orderbook, trades, funding - FREE)",
    "Tardis.dev (historical tick data for backtesting - FREE trial + first day/month)",
    "CoinGlass web dashboard (liquidation heatmaps, market context - FREE web access)",
    "Optional: Hyperliquid for execution (if willing to use DEX for maker rebates)"
  ],
  "recommended_execution": {
    "option_a": {
      "platform": "Binance Futures",
      "fees": "0.02% maker / 0.04% taker",
      "pros": "Highest liquidity, same as data source, simple integration",
      "cons": "No maker rebates"
    },
    "option_b": {
      "platform": "Hyperliquid",
      "fees": "-0.001% to -0.003% maker (REBATE) / 0.045% taker",
      "pros": "Paid to provide liquidity, ultra-low latency",
      "cons": "DEX complexity, wallet management, lower liquidity than Binance"
    },
    "option_c": {
      "platform": "MEXC",
      "fees": "0.01% maker / 0.04% taker (lowest maker)",
      "pros": "Lowest maker fee among CEX, 500x leverage",
      "cons": "Requires institutional access (contact institution@mexc.com)"
    }
  },
  "total_cost_estimate": {
    "phase_1_development": "$0 (free data sources)",
    "phase_2_paper_trading": "$0 (simulated execution)",
    "phase_3_live_trading": "0.01-0.04% per trade (execution fees only)",
    "optional_advanced_data": "$50-100/month (Tardis.dev subscription if strategy proves profitable)"
  },
  "notes": [
    "For $300 budget, prioritize FREE data sources (Binance WS, Tardis free trial)",
    "Binance provides best free real-time data + liquidity",
    "Tardis.dev best for free historical backtesting (first day of month + trial)",
    "Hyperliquid offers maker rebates but requires DEX familiarity",
    "Avoid expensive institutional providers (Kaiko, Glassnode paid API) until profitable",
    "GMX not suitable for orderflow trading (no orderbook, AMM model)",
    "CoinGlass useful for market context but no free API (use web dashboard)"
  ]
}
```

---

## 8. Final Recommendations

### For Immediate Implementation ($300 Budget)

**✅ DO:**
1. **Use Binance Futures WebSocket** for real-time data (FREE)
   - Orderbook depth at 100ms updates
   - Trade flow (aggTrades)
   - Funding rate and open interest
   - No API key required for market data

2. **Use Tardis.dev** for backtesting (FREE trial + first day/month)
   - Request free trial account immediately
   - Download first day of each month (free forever)
   - Validate orderflow signals on historical tick data
   - Only subscribe (~$50-100/mo) if strategy proves profitable

3. **Use CoinGlass web dashboard** for market context (FREE)
   - View liquidation heatmaps (no API needed)
   - Monitor open interest trends across exchanges
   - Identify liquidation clusters for support/resistance

4. **Execute on Binance Futures** (safest) OR **Hyperliquid** (maker rebates)
   - **Binance**: 0.02%/0.04% fees, highest liquidity, simple integration
   - **Hyperliquid**: -0.003% maker rebates (PAID to trade!), but DEX complexity

**❌ DON'T:**
1. **Don't pay for Kaiko** ($9,500+/year - far exceeds budget)
2. **Don't pay for Glassnode API** (on-chain data not needed for orderflow)
3. **Don't use GMX** (no orderbook, oracle-based pricing, not suitable)
4. **Don't pay for CoinGlass API** (use free web dashboard instead)
5. **Don't subscribe to Tardis.dev** until strategy is profitable

### Development Workflow

**Week 1-2: Backtesting (FREE)**
- Request Tardis.dev free trial
- Download first day of month data (BTC perpetual futures)
- Develop orderflow signals (imbalance, momentum, volume)
- Backtest on historical tick data
- Iterate until 60%+ win rate (as per existing Polymarket model)

**Week 3: Paper Trading (FREE)**
- Connect to Binance Futures WebSocket
- Run strategy in paper trading mode (no execution)
- Log signals, hypothetical trades, P&L
- Validate real-time performance matches backtest
- Monitor for 3-7 days (per CLAUDE.md P0 requirement)

**Week 4: Live Trading (LOW COST)**
- Start with $15/trade (5% of $300 capital)
- Implement kill switch ($30 daily loss limit)
- Execute on Binance Futures OR Hyperliquid
- Monitor actual vs expected performance
- Scale up only if profitable

**Month 2+: Optimize & Scale**
- If profitable: Subscribe to Tardis.dev (~$50-100/mo)
- Access more historical data for deeper backtesting
- Train ML models on larger datasets
- Consider MEXC institutional access (0.01% maker fee)
- Explore Hyperliquid maker rebates if comfortable with DEX

---

## 9. Research Sources

### Binance
- [Order Book | Binance Open Platform](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/websocket-api/Order-Book)
- [How To Manage A Local Order Book Correctly](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/How-to-manage-a-local-order-book-correctly)
- [Diff Book Depth Streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Diff-Book-Depth-Streams)
- [Rate Limits on Binance Futures](https://www.binance.com/en/support/faq/rate-limits-on-binance-futures-281596e222414cdd9051664ea621cdc3)
- [Binance Fees Breakdown: A Detailed Guide for 2026](https://www.bitdegree.org/crypto/tutorials/binance-fees)
- [Binance USDT Futures | Tardis.dev](https://docs.tardis.dev/historical-data-details/binance-futures)

### OKX
- [OKX API guide](https://www.okx.com/docs-v5/en/)
- [A complete guide to OKX's API v5](https://www.okx.com/en-us/learn/complete-guide-to-okex-api-v5-upgrade)
- [Trading Fee | Fee Rate | OKX](https://www.okx.com/en-us/fees)
- [OKX vs Binance 2025: Features, Fees, Security & Futures](https://www.datawallet.com/crypto/okx-vs-binance)

### Bybit
- [All Liquidation | Bybit API Documentation](https://bybit-exchange.github.io/docs/v5/websocket/public/all-liquidation)
- [Orderbook | Bybit API Documentation](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- [BybitMarketData GitHub](https://github.com/sferez/BybitMarketData)

### MEXC
- [MEXC Futures Market Endpoints](https://www.mexc.com/api-docs/futures/market-endpoints)
- [MEXC Integration Guide](https://www.mexc.com/api-docs/futures/integration-guide)
- [Lowest Crypto Futures Trading Fees 2026](https://www.bitget.site/academy/lowest-futures-trading-fees-exchange-comparison-2026)

### Deribit
- [Deribit API](https://docs.deribit.com/)
- [Market Data Best Practices](https://support.deribit.com/hc/en-us/articles/29592500256669)
- [Deribit | Tardis.dev](https://docs.tardis.dev/historical-data-details/deribit)

### Hyperliquid
- [Fees | Hyperliquid Docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees)
- [WebSocket Subscriptions](https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions)
- [Order Book WebSocket API - Dwellir](https://www.dwellir.com/docs/hyperliquid/websocket-api)
- [Hyperliquid Slashes Trading Fees by 80%](https://finance.yahoo.com/news/hyperliquid-slashes-trading-fees-80-164528783.html)

### GMX
- [GMX | Decentralized Perpetual Exchange](https://gmx.io/)
- [GMX Docs](https://gmx-docs.io/docs/trading/v2/)
- [A Guide to Perpetual Contracts and GMX V2](https://medium.com/@compasslabs/a-guide-to-perpetual-contracts-and-gmx-v2-a4770cbc25e3)

### dYdX
- [GMX vs. dYdX: A Comparison](https://beincrypto.com/learn/gmx-vs-dydx/)
- [The Rise of Perpetual DEXs: A 2025 Revolution](https://www.ainvest.com/news/rise-perpetual-dexs-2025-chain-futures-revolution-2512/)
- [Top Perp DEXs to Know in 2025](https://bingx.com/en/learn/article/top-perp-dex-perpetual-decentralized-exchange-to-know)

### CoinGlass
- [CoinGlass API](https://docs.coinglass.com/)
- [CoinGlass Pricing](https://www.coinglass.com/pricing)
- [Liquidation Heatmap](https://www.coinglass.com/pro/futures/LiquidationHeatMap)

### Glassnode
- [Glassnode API Documentation](https://docs.glassnode.com/basic-api/api)
- [BTC Market Pulse: Week 2 2026](https://insights.glassnode.com/btc-market-pulse-week-2-2026/)
- [On-chain Metrics Coverage](https://docs.glassnode.com/data/supported-assets/onchain-metrics-coverage)

### Tardis.dev
- [Tardis.dev Homepage](https://tardis.dev/)
- [Celebrating Tardis.dev partnership - Deribit](https://insights.deribit.com/exchange-updates/celebrating-our-tardis-dev-partnership-get-free-historical-data/)
- [Billing and Subscriptions](https://docs.tardis.dev/faq/billing-and-subscriptions)

### Kaiko
- [Kaiko Homepage](https://www.kaiko.com/)
- [Level 1 and Level 2 Market Data](https://www.kaiko.com/products/data-feeds/l1-l2-data)
- [Kaiko Pricing](https://www.kaiko.com/about-kaiko/pricing-and-contracts)
- [Kaiko Software Pricing & Plans 2025](https://www.vendr.com/buyer-guides/kaiko)

### CryptoCompare
- [Best Cryptocurrency APIs of 2026](https://www.coingecko.com/learn/best-cryptocurrency-apis)
- [How to use the CryptoCompare API](https://www.cryptocompare.com/coins/guides/how-to-use-our-api/)
- [CryptoCompare Pricing](https://min-api.cryptocompare.com/pricing)

---

**End of Report**

This comprehensive research provides all necessary information to build a BTC orderflow trading bot within the $300 budget constraint. The recommended stack (Binance + Tardis.dev + CoinGlass dashboard) provides professional-grade data at zero cost during development and minimal cost during live trading.
