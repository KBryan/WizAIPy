"""
CoinGecko API integration for market data and price feeds.
Provides real-time and historical cryptocurrency market data.
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
import json

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class CoinData:
    """Cryptocurrency data from CoinGecko."""
    id: str
    symbol: str
    name: str
    current_price: float
    market_cap: Optional[float]
    market_cap_rank: Optional[int]
    fully_diluted_valuation: Optional[float]
    total_volume: float
    high_24h: Optional[float]
    low_24h: Optional[float]
    price_change_24h: Optional[float]
    price_change_percentage_24h: Optional[float]
    market_cap_change_24h: Optional[float]
    market_cap_change_percentage_24h: Optional[float]
    circulating_supply: Optional[float]
    total_supply: Optional[float]
    max_supply: Optional[float]
    ath: Optional[float]
    ath_change_percentage: Optional[float]
    ath_date: Optional[datetime]
    atl: Optional[float]
    atl_change_percentage: Optional[float]
    atl_date: Optional[datetime]
    last_updated: datetime


@dataclass
class PriceHistory:
    """Historical price data."""
    timestamp: datetime
    price: float
    market_cap: Optional[float] = None
    volume: Optional[float] = None


class CoinGeckoError(Exception):
    """Custom exception for CoinGecko API errors."""
    pass


class CoinGeckoClient:
    """
    CoinGecko API client for cryptocurrency market data.
    
    Provides methods to fetch real-time prices, market data,
    historical data, and market statistics.
    """
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.coingecko_api_key
        self.session: Optional[aiohttp.ClientSession] = None
        self.rate_limit_delay = 1.0  # Delay between requests to respect rate limits
        self.max_retries = 3  # Max retries on HTTP 429 before giving up
        self.last_request_time = 0.0
        
        # Cache for coin IDs and symbols
        self._coin_list_cache: Optional[Dict[str, str]] = None
        self._cache_expiry: Optional[datetime] = None
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self._ensure_session()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def _ensure_session(self):
        """Ensure aiohttp session is created."""
        if not self.session:
            headers = {}
            if self.api_key:
                headers["x-cg-demo-api-key"] = self.api_key
            
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            )
    
    async def _rate_limit(self):
        """Implement rate limiting to respect API limits."""
        current_time = asyncio.get_event_loop().time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_delay:
            await asyncio.sleep(self.rate_limit_delay - time_since_last)
        
        self.last_request_time = asyncio.get_event_loop().time()
    
    async def _make_request(self, endpoint: str, params: Dict[str, Any] = None, _attempt: int = 0) -> Dict[str, Any]:
        """
        Make HTTP request to CoinGecko API.
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            
        Returns:
            JSON response data
        """
        await self._ensure_session()
        await self._rate_limit()
        
        url = f"{self.BASE_URL}/{endpoint}"
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    # Rate limit exceeded — retry a bounded number of times
                    if _attempt >= self.max_retries:
                        raise CoinGeckoError(f"Rate limit exceeded after {self.max_retries} retries")
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limit exceeded, waiting {retry_after} seconds")
                    await asyncio.sleep(retry_after)
                    return await self._make_request(endpoint, params, _attempt + 1)
                else:
                    error_text = await response.text()
                    raise CoinGeckoError(f"API request failed: {response.status} - {error_text}")
                    
        except aiohttp.ClientError as e:
            raise CoinGeckoError(f"Network error: {e}")
    
    async def get_coin_list(self, include_platform: bool = False) -> Dict[str, str]:
        """
        Get list of all supported coins with their IDs and symbols.
        
        Args:
            include_platform: Include platform data
            
        Returns:
            Dictionary mapping symbols to coin IDs
        """
        # Check cache
        if (self._coin_list_cache and 
            self._cache_expiry and 
            datetime.utcnow() < self._cache_expiry):
            return self._coin_list_cache
        
        params = {"include_platform": str(include_platform).lower()}
        data = await self._make_request("coins/list", params)
        
        # Create symbol to ID mapping
        coin_map = {}
        for coin in data:
            symbol = coin["symbol"].upper()
            coin_id = coin["id"]
            coin_map[symbol] = coin_id
        
        # Cache for 1 hour
        self._coin_list_cache = coin_map
        self._cache_expiry = datetime.utcnow() + timedelta(hours=1)
        
        return coin_map
    
    async def get_coin_id(self, symbol: str) -> Optional[str]:
        """
        Get CoinGecko coin ID for a symbol.
        
        Args:
            symbol: Coin symbol (e.g., "BTC", "ETH")
            
        Returns:
            Coin ID or None if not found
        """
        coin_list = await self.get_coin_list()
        return coin_list.get(symbol.upper())
    
    async def get_price(self, symbols: List[str], vs_currency: str = "usd") -> Dict[str, float]:
        """
        Get current prices for multiple cryptocurrencies.
        
        Args:
            symbols: List of coin symbols
            vs_currency: Currency to get prices in
            
        Returns:
            Dictionary mapping symbols to prices
        """
        # Convert symbols to coin IDs
        coin_list = await self.get_coin_list()
        coin_ids = []
        
        for symbol in symbols:
            coin_id = coin_list.get(symbol.upper())
            if coin_id:
                coin_ids.append(coin_id)
            else:
                logger.warning(f"Coin ID not found for symbol: {symbol}")
        
        if not coin_ids:
            return {}
        
        params = {
            "ids": ",".join(coin_ids),
            "vs_currencies": vs_currency
        }
        
        data = await self._make_request("simple/price", params)
        
        # Map back to symbols
        result = {}
        for symbol in symbols:
            coin_id = coin_list.get(symbol.upper())
            if coin_id and coin_id in data:
                result[symbol.upper()] = data[coin_id][vs_currency]
        
        return result
    
    async def get_coin_data(self, symbol: str, vs_currency: str = "usd") -> Optional[CoinData]:
        """
        Get detailed market data for a cryptocurrency.
        
        Args:
            symbol: Coin symbol
            vs_currency: Currency for price data
            
        Returns:
            CoinData object or None if not found
        """
        coin_id = await self.get_coin_id(symbol)
        if not coin_id:
            return None
        
        params = {
            "vs_currency": vs_currency,
            "ids": coin_id,
            "order": "market_cap_desc",
            "per_page": 1,
            "page": 1,
            "sparkline": False,
            "price_change_percentage": "24h"
        }
        
        data = await self._make_request("coins/markets", params)
        
        if not data:
            return None
        
        coin_data = data[0]
        
        return CoinData(
            id=coin_data["id"],
            symbol=coin_data["symbol"].upper(),
            name=coin_data["name"],
            current_price=coin_data["current_price"],
            market_cap=coin_data.get("market_cap"),
            market_cap_rank=coin_data.get("market_cap_rank"),
            fully_diluted_valuation=coin_data.get("fully_diluted_valuation"),
            total_volume=coin_data["total_volume"],
            high_24h=coin_data.get("high_24h"),
            low_24h=coin_data.get("low_24h"),
            price_change_24h=coin_data.get("price_change_24h"),
            price_change_percentage_24h=coin_data.get("price_change_percentage_24h"),
            market_cap_change_24h=coin_data.get("market_cap_change_24h"),
            market_cap_change_percentage_24h=coin_data.get("market_cap_change_percentage_24h"),
            circulating_supply=coin_data.get("circulating_supply"),
            total_supply=coin_data.get("total_supply"),
            max_supply=coin_data.get("max_supply"),
            ath=coin_data.get("ath"),
            ath_change_percentage=coin_data.get("ath_change_percentage"),
            ath_date=datetime.fromisoformat(coin_data["ath_date"].replace("Z", "+00:00")) if coin_data.get("ath_date") else None,
            atl=coin_data.get("atl"),
            atl_change_percentage=coin_data.get("atl_change_percentage"),
            atl_date=datetime.fromisoformat(coin_data["atl_date"].replace("Z", "+00:00")) if coin_data.get("atl_date") else None,
            last_updated=datetime.fromisoformat(coin_data["last_updated"].replace("Z", "+00:00"))
        )
    
    async def get_historical_prices(self, 
                                  symbol: str, 
                                  days: int = 30,
                                  vs_currency: str = "usd") -> List[PriceHistory]:
        """
        Get historical price data for a cryptocurrency.
        
        Args:
            symbol: Coin symbol
            days: Number of days of history
            vs_currency: Currency for price data
            
        Returns:
            List of PriceHistory objects
        """
        coin_id = await self.get_coin_id(symbol)
        if not coin_id:
            return []
        
        params = {
            "vs_currency": vs_currency,
            "days": str(days)
        }
        
        data = await self._make_request(f"coins/{coin_id}/market_chart", params)
        
        history = []
        prices = data.get("prices", [])
        market_caps = data.get("market_caps", [])
        volumes = data.get("total_volumes", [])
        
        for i, price_data in enumerate(prices):
            timestamp = datetime.fromtimestamp(price_data[0] / 1000)
            price = price_data[1]
            
            market_cap = market_caps[i][1] if i < len(market_caps) else None
            volume = volumes[i][1] if i < len(volumes) else None
            
            history.append(PriceHistory(
                timestamp=timestamp,
                price=price,
                market_cap=market_cap,
                volume=volume
            ))
        
        return history
    
    async def get_trending_coins(self) -> List[Dict[str, Any]]:
        """
        Get trending cryptocurrencies.
        
        Returns:
            List of trending coin data
        """
        data = await self._make_request("search/trending")
        return data.get("coins", [])
    
    async def get_global_data(self) -> Dict[str, Any]:
        """
        Get global cryptocurrency market data.
        
        Returns:
            Global market statistics
        """
        data = await self._make_request("global")
        return data.get("data", {})


# Global CoinGecko client instance
coingecko_client = CoinGeckoClient()

