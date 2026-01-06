"""Data API client for wallet and trade data."""
import json
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode


# Gamma API base URL for profile searches
GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


class DataAPIClient:
    """
    Client for Polymarket Data API.
    
    Used for:
    - Wallet trade history
    - Positions
    - Portfolio value
    - Leaderboard
    """
    
    BASE_URL = "https://data-api.polymarket.com"
    
    def __init__(self):
        self.session_headers = {
            "Accept": "application/json",
            "User-Agent": "TradingLab/1.0",
        }
    
    def _get(self, endpoint: str, params: Optional[Dict] = None, base_url: str = None) -> any:
        """Make GET request."""
        url = f"{base_url or self.BASE_URL}{endpoint}"
        
        if params:
            # Filter out None values
            params = {k: v for k, v in params.items() if v is not None}
            url = f"{url}?{urlencode(params)}"
        
        request = Request(url, headers=self.session_headers)
        
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    
    def search_profile(self, username: str) -> Optional[Dict]:
        """
        Search for a user profile by username.
        
        Uses Gamma API for profile lookup.
        Returns profile dict with proxyWallet address.
        """
        try:
            result = self._get(
                "/public-search",
                params={"q": username, "search_profiles": "true", "limit_per_type": 10},
                base_url=GAMMA_BASE_URL
            )
            
            profiles = result.get("profiles", [])
            
            # Find exact match
            for p in profiles:
                if p.get("name", "").lower() == username.lower():
                    return p
            
            # Return first result if no exact match
            return profiles[0] if profiles else None
            
        except Exception as e:
            print(f"   Error searching profile: {e}")
            return None
    
    def get_trades(
        self,
        user: Optional[str] = None,
        market: Optional[str] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get trades.
        
        Args:
            user: Wallet address (proxy wallet)
            market: Condition ID
            limit: Max results per page
            offset: Pagination offset
        """
        params = {
            "limit": limit,
            "offset": offset,
        }
        
        if user:
            params["user"] = user
        if market:
            params["market"] = market
        
        result = self._get("/trades", params)
        
        if isinstance(result, list):
            return result
        return result.get("trades", result.get("data", []))
    
    def get_all_trades(
        self,
        user: str,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        max_pages: int = 100
    ) -> List[Dict]:
        """
        Paginate through all trades for a user.
        
        Warning: Can be slow for active wallets.
        """
        all_trades = []
        offset = 0
        page_size = 100
        
        for _ in range(max_pages):
            trades = self.get_trades(user=user, limit=page_size, offset=offset)
            
            if not trades:
                break
            
            # Filter by timestamp if specified
            for trade in trades:
                ts = trade.get("timestamp") or trade.get("ts")
                if isinstance(ts, str):
                    ts = int(ts)
                
                if start_ts and ts < start_ts:
                    continue
                if end_ts and ts > end_ts:
                    continue
                
                all_trades.append(trade)
            
            if len(trades) < page_size:
                break
            
            offset += page_size
        
        return all_trades
    
    def get_activity(
        self,
        user: str,
        activity_type: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 50
    ) -> List[Dict]:
        """
        Get wallet activity.
        
        Args:
            user: Wallet address
            activity_type: TRADE, SPLIT, MERGE, REDEEM, REWARD, CONVERSION
            start: Start timestamp (ms)
            end: End timestamp (ms)
            limit: Max results
        """
        params = {
            "user": user,
            "limit": limit,
        }
        
        if activity_type:
            params["type"] = activity_type
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        
        result = self._get("/activity", params)
        
        if isinstance(result, list):
            return result
        return result.get("activity", result.get("data", []))
    
    def get_positions(
        self,
        user: str,
        market: Optional[str] = None
    ) -> List[Dict]:
        """Get user's current positions."""
        params = {"user": user}
        
        if market:
            params["market"] = market
        
        result = self._get("/positions", params)
        
        if isinstance(result, list):
            return result
        return result.get("positions", result.get("data", []))
    
    def get_leaderboard(
        self,
        category: str = "CRYPTO",
        time_period: str = "WEEK",
        order_by: str = "PNL",
        limit: int = 50
    ) -> List[Dict]:
        """
        Get leaderboard.
        
        Args:
            category: CRYPTO, POLITICS, SPORTS, etc.
            time_period: DAY, WEEK, MONTH, ALL
            order_by: PNL, VOLUME, NUM_TRADES
            limit: Max results
        """
        params = {
            "category": category,
            "timePeriod": time_period,
            "orderBy": order_by,
            "limit": limit,
        }
        
        result = self._get("/v1/leaderboard", params)
        
        if isinstance(result, list):
            return result
        return result.get("leaderboard", result.get("data", []))
    
    def get_top_crypto_traders(self, limit: int = 20) -> List[Dict]:
        """Get top crypto traders by PnL."""
        return self.get_leaderboard(
            category="CRYPTO",
            time_period="WEEK",
            order_by="PNL",
            limit=limit
        )
    
    def normalize_trade(self, trade: Dict) -> Dict:
        """
        Normalize trade data for storage.
        
        Different endpoints return slightly different formats.
        """
        # Handle timestamp
        ts = trade.get("timestamp") or trade.get("ts") or trade.get("createdAt")
        if isinstance(ts, str):
            if "T" in ts:
                from datetime import datetime
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = int(dt.timestamp() * 1000)
                except Exception:
                    ts = 0
            else:
                ts = int(ts)
        
        return {
            "wallet": trade.get("user") or trade.get("maker") or trade.get("taker"),
            "ts": ts,
            "condition_id": trade.get("market") or trade.get("conditionId"),
            "token_id": trade.get("assetId") or trade.get("tokenId"),
            "side": trade.get("side", "").lower(),
            "price": float(trade.get("price", 0)),
            "size": float(trade.get("size") or trade.get("amount", 0)),
            "transaction_hash": trade.get("transactionHash"),
        }
