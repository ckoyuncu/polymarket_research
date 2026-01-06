"""
Orderbook collector for 15-minute crypto markets.
Collects snapshots every 10 seconds and saves to JSONL.

Uses the predictable slug pattern: {asset}-updown-15m-{end_timestamp}
where end_timestamp is the resolution time (every 15 min on :00, :15, :30, :45).
"""
import json
import time
import requests
from datetime import datetime
from pathlib import Path

DATA_DIR = Path("/Users/shem/Desktop/polymarket_research/data/orderbook_live")
DATA_DIR.mkdir(parents=True, exist_ok=True)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# Assets to track
ASSETS = ["btc", "eth"]


def get_next_15m_timestamp() -> int:
    """Get the Unix timestamp for the next 15-minute boundary."""
    now = int(time.time())
    return ((now // 900) + 1) * 900


def build_market_slug(asset: str, timestamp: int) -> str:
    """Build the market slug for a given asset and timestamp."""
    return f"{asset.lower()}-updown-15m-{timestamp}"


def fetch_market_by_slug(slug: str) -> dict:
    """Fetch a single market by its exact slug."""
    try:
        url = f"{GAMMA_API}/markets"
        params = {"slug": slug}
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            return data[0]
        return None
    except Exception as e:
        return None


def get_orderbook(token_id: str) -> dict:
    """Get orderbook for a token."""
    try:
        resp = requests.get(
            f"{CLOB_API}/book",
            params={"token_id": token_id},
            timeout=10
        )
        return resp.json()
    except Exception as e:
        print(f"Error fetching orderbook: {e}")
        return None


def find_active_15m_markets():
    """Find currently active 15-minute markets using predictable slug pattern."""
    markets = []

    # Calculate timestamps to check
    base_ts = get_next_15m_timestamp()
    timestamps = [
        base_ts - 900,   # Previous window
        base_ts,         # Current window
        base_ts + 900,   # Next window
    ]

    for asset in ASSETS:
        found = False
        for ts in timestamps:
            if found:
                break

            slug = build_market_slug(asset, ts)
            market = fetch_market_by_slug(slug)

            if market:
                # Check if market is still tradeable (>60s to resolution)
                seconds_left = ts - int(time.time())
                if seconds_left > 60:
                    markets.append(market)
                    found = True

    return markets


def collect_snapshot():
    """Collect one snapshot of all active 15m markets."""
    markets = find_active_15m_markets()
    timestamp = int(time.time())

    snapshots = []
    for market in markets:
        slug = market.get("slug", "")

        # Parse token IDs
        token_ids_raw = market.get("clobTokenIds", "[]")
        token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else token_ids_raw

        if not token_ids or len(token_ids) < 2:
            continue

        # Parse outcomes to find Up/Down indices
        outcomes_raw = market.get("outcomes", "[]")
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

        up_idx, down_idx = 0, 1
        for i, outcome in enumerate(outcomes):
            if outcome.upper() in ("UP", "YES"):
                up_idx = i
            elif outcome.upper() in ("DOWN", "NO"):
                down_idx = i

        # Parse prices
        prices_raw = market.get("outcomePrices", "[]")
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        up_price = float(prices[up_idx]) if len(prices) > up_idx else None
        down_price = float(prices[down_idx]) if len(prices) > down_idx else None

        # Get orderbook for UP token
        orderbook = get_orderbook(token_ids[up_idx])
        if not orderbook:
            continue

        # Extract end time from slug
        parts = slug.split("-")
        end_time = int(parts[-1]) if parts[-1].isdigit() else None

        snapshot = {
            "timestamp": timestamp,
            "slug": slug,
            "question": market.get("question", ""),
            "up_token_id": token_ids[up_idx],
            "down_token_id": token_ids[down_idx],
            "up_price": up_price,
            "down_price": down_price,
            "spread": market.get("spread"),
            "volume": market.get("volumeNum") or market.get("volume24hr"),
            "liquidity": market.get("liquidityNum") or market.get("liquidity"),
            "end_time": end_time,
            "seconds_to_resolution": end_time - timestamp if end_time else None,
            "orderbook": orderbook,
        }
        snapshots.append(snapshot)

    return snapshots


def main():
    print("Starting orderbook collector...")
    print(f"Saving to: {DATA_DIR}")
    print(f"Tracking assets: {ASSETS}")

    # Output file with date
    date_str = datetime.now().strftime("%Y%m%d")
    output_file = DATA_DIR / f"orderbook_{date_str}.jsonl"

    snapshot_count = 0
    start_time = time.time()

    while True:
        try:
            snapshots = collect_snapshot()

            # Append to file
            with open(output_file, "a") as f:
                for snap in snapshots:
                    f.write(json.dumps(snap) + "\n")

            snapshot_count += 1
            elapsed = time.time() - start_time

            if snapshot_count % 6 == 0:  # Every minute
                market_names = [s["slug"] for s in snapshots]
                print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                      f"Collected {snapshot_count} snapshots, "
                      f"{len(snapshots)} markets: {market_names}, "
                      f"running {elapsed/60:.1f}min")

            # Wait 10 seconds
            time.sleep(10)

        except KeyboardInterrupt:
            print(f"\nStopping. Collected {snapshot_count} snapshots.")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()
