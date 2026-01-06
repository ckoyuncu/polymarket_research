"""Gamma API client for market discovery."""
import json
from typing import List, Dict, Optional
from urllib.request import urlopen, Request
from urllib.parse import urlencode


class GammaClient:
    """
    Client for Polymarket Gamma API.
    
    Used for:
    - Market discovery
    - Market metadata (start/end times, token IDs)
    - Profile/wallet search
    """
    
    BASE_URL = "https://gamma-api.polymarket.com"
    
    def __init__(self):
        self.session_headers = {
            "Accept": "application/json",
            "User-Agent": "TradingLab/1.0",
        }
    
    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make GET request."""
        url = f"{self.BASE_URL}{endpoint}"
        
        if params:
            url = f"{url}?{urlencode(params)}"
        
        request = Request(url, headers=self.session_headers)
        
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    
    def search_markets(
        self,
        query: str,
        limit: int = 20,
        active: bool = True
    ) -> List[Dict]:
        """
        Search for markets by keyword.
        
        Args:
            query: Search term (e.g., "Bitcoin Up or Down")
            limit: Max results
            active: Only return active markets
        
        Returns:
            List of market objects
        """
        params = {
            "q": query,
            "limit": limit,
        }
        
        if active:
            params["active"] = "true"
        
        result = self._get("/markets", params)
        
        # Handle both list and dict responses
        if isinstance(result, list):
            return result
        return result.get("markets", [])
    
    def get_market(self, condition_id: str) -> Optional[Dict]:
        """Get market by condition ID."""
        try:
            return self._get(f"/markets/{condition_id}")
        except Exception as e:
            print(f"Error fetching market {condition_id}: {e}")
            return None
    
    def get_market_by_slug(self, slug: str) -> Optional[Dict]:
        """Get market by slug."""
        try:
            return self._get(f"/markets/slug/{slug}")
        except Exception:
            return None
    
    def search_profiles(self, query: str, limit: int = 10) -> List[Dict]:
        """
        Search for user profiles.
        
        Returns profile info including proxy wallet address.
        """
        params = {
            "q": query,
            "search_profiles": "true",
            "limit_per_type": limit,
        }
        
        result = self._get("/public-search", params)
        return result.get("profiles", [])
    
    def get_btc_eth_15m_markets(self, limit: int = 50) -> List[Dict]:
        """
        Get BTC and ETH 15-minute Up/Down markets.
        
        This is the specific market type for the reset-lag strategy.
        """
        markets = []
        
        # Search for BTC and ETH 15m markets
        for symbol in ["BTC", "ETH", "Bitcoin", "Ethereum"]:
            for term in ["Up or Down", "15m", "15 minute"]:
                try:
                    results = self.search_markets(f"{symbol} {term}", limit=20)
                    markets.extend(results)
                except Exception:
                    continue
        
        # Deduplicate by condition_id
        seen = set()
        unique = []
        for m in markets:
            cid = m.get("conditionId") or m.get("condition_id")
            if cid and cid not in seen:
                seen.add(cid)
                unique.append(m)
        
        return unique[:limit]
    
    def extract_market_info(self, market: Dict) -> Dict:
        """
        Extract key info from a market object.
        
        Returns normalized structure for storage.
        """
        return {
            "condition_id": market.get("conditionId") or market.get("condition_id"),
            "slug": market.get("slug"),
            "question": market.get("question"),
            "start_ts": self._parse_timestamp(market.get("startDateIso") or market.get("startDate")),
            "end_ts": self._parse_timestamp(market.get("endDateIso") or market.get("endDate")),
            "clob_token_ids": market.get("clobTokenIds", []),
            "outcomes": market.get("outcomes", []),
            "active": market.get("active", False),
        }
    
    def _parse_timestamp(self, date_str: Optional[str]) -> Optional[int]:
        """Parse ISO date string to Unix timestamp."""
        if not date_str:
            return None
        
        from datetime import datetime
        
        try:
            # Handle various ISO formats
            for fmt in [
                "%Y-%m-%dT%H:%M:%S.%fZ",
                "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S",
            ]:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return int(dt.timestamp())
                except ValueError:
                    continue
        except Exception:
            pass
        
        return None
