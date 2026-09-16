"""
Shared dependencies for FastAPI application.
Handles NFT gating, authentication, and other common dependencies.
"""

from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, Request, status, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging
from web3 import Web3
import redis
import json
import os

from config import get_settings, SUPPORTED_NETWORKS

logger = logging.getLogger(__name__)
settings = get_settings()

# Security scheme
security = HTTPBearer(auto_error=False)

# Redis client for caching
redis_client = redis.from_url(settings.redis_url)


class NFTGateError(Exception):
    """Custom exception for NFT gating errors."""
    pass


class Web3Manager:
    """Manages Web3 connections for different networks."""
    
    def __init__(self):
        self._connections: Dict[str, Web3] = {}
        self._initialize_connections()
    
    def _initialize_connections(self):
        """Initialize Web3 connections for supported networks."""
        # Check if blockchain is disabled
        if os.getenv("DISABLE_BLOCKCHAIN", "false").lower() == "true":
            print("DEBUG: DISABLE_BLOCKCHAIN detected, skipping Web3 init"); logger.info("Blockchain connections disabled via DISABLE_BLOCKCHAIN")
            return
            
        for network_name, network_config in SUPPORTED_NETWORKS.items():
            rpc_key = network_config["rpc_key"]
            rpc_url = getattr(settings, rpc_key, None)
            
            if rpc_url:
                try:
                    w3 = Web3(Web3.HTTPProvider(rpc_url))
                    if w3.is_connected():
                        self._connections[network_name] = w3
                        logger.info(f"Connected to {network_name} network")
                    else:
                        logger.warning(f"Failed to connect to {network_name} network")
                except Exception as e:
                    logger.error(f"Error connecting to {network_name}: {e}")
    
    def get_connection(self, network: str) -> Optional[Web3]:
        """Get Web3 connection for a specific network."""
        return self._connections.get(network)
    
    def get_default_connection(self) -> Web3:
        """Get default Web3 connection (Ethereum)."""
        if "ethereum" in self._connections:
            return self._connections["ethereum"]
        raise NFTGateError("No Ethereum connection available")


# Global Web3 manager instance
web3_manager = Web3Manager()


async def verify_nft_ownership(
    wallet_address: str,
    contract_address: Optional[str] = None,
    chain_id: Optional[int] = None
) -> bool:
    """
    Verify NFT ownership for a given wallet address.
    
    Args:
        wallet_address: The wallet address to check
        contract_address: NFT contract address (optional, uses config default)
        chain_id: Chain ID to check on (optional, uses config default)
    
    Returns:
        bool: True if wallet owns the required NFT
    """
    if settings.bypass_nft_gate:
        logger.info("NFT gate bypassed via configuration")
        return True
    
    try:
        # Use default values from config if not provided
        contract_address = contract_address or settings.nft_contract_address
        chain_id = chain_id or settings.nft_chain_id
        
        if not contract_address:
            raise NFTGateError("NFT contract address not configured")
        
        # Check cache first
        cache_key = f"nft_ownership:{wallet_address}:{contract_address}:{chain_id}"
        cached_result = redis_client.get(cache_key)
        
        if cached_result:
            logger.info(f"NFT ownership cache hit for {wallet_address}")
            return json.loads(cached_result)
        
        # Get appropriate Web3 connection
        network = "ethereum"  # Default to Ethereum for now
        for net_name, net_config in SUPPORTED_NETWORKS.items():
            if net_config["chain_id"] == chain_id:
                network = net_name
                break
        
        w3 = web3_manager.get_connection(network)
        if not w3:
            raise NFTGateError(f"No connection available for chain {chain_id}")
        
        # Check if address is valid
        if not Web3.is_address(wallet_address):
            raise NFTGateError("Invalid wallet address")
        
        if not Web3.is_address(contract_address):
            raise NFTGateError("Invalid contract address")
        
        # Simple ERC-721 balance check
        # In production, you'd want to use the actual contract ABI
        contract_abi = [
            {
                "constant": True,
                "inputs": [{"name": "owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            }
        ]
        
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(contract_address),
            abi=contract_abi
        )
        
        balance = contract.functions.balanceOf(
            Web3.to_checksum_address(wallet_address)
        ).call()
        
        has_nft = balance > 0
        
        # Cache result for 5 minutes
        redis_client.setex(cache_key, 300, json.dumps(has_nft))
        
        logger.info(f"NFT ownership check for {wallet_address}: {has_nft}")
        return has_nft
        
    except Exception as e:
        logger.error(f"NFT ownership verification failed: {e}")
        raise NFTGateError(f"NFT verification failed: {str(e)}")


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_wallet_address: Optional[str] = Header(None)
) -> Dict[str, Any]:
    """
    Get current authenticated user based on NFT ownership.
    
    Args:
        credentials: Bearer token credentials (optional)
        x_wallet_address: Wallet address from header
    
    Returns:
        Dict containing user information
    """
    if settings.bypass_nft_gate:
        return {
            "wallet_address": "0x0000000000000000000000000000000000000000",
            "authenticated": True,
            "bypass": True
        }
    
    # Extract wallet address from token or header
    wallet_address = None
    
    if credentials and credentials.credentials:
        # In a real implementation, you'd decode and validate the JWT token
        # For now, we'll assume the token contains the wallet address
        wallet_address = credentials.credentials
    elif x_wallet_address:
        wallet_address = x_wallet_address
    
    if not wallet_address:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Wallet address required for authentication",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    try:
        has_nft = await verify_nft_ownership(wallet_address)
        
        if not has_nft:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="NFT ownership required for access"
            )
        
        return {
            "wallet_address": wallet_address,
            "authenticated": True,
            "bypass": False
        }
        
    except NFTGateError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_wallet_address: Optional[str] = Header(None)
) -> Optional[Dict[str, Any]]:
    """
    Get current user if authenticated, otherwise return None.
    Used for endpoints that work with or without authentication.
    """
    try:
        return await get_current_user(credentials, x_wallet_address)
    except HTTPException:
        return None


def get_redis_client() -> redis.Redis:
    """Get Redis client dependency."""
    return redis_client


def get_web3_manager() -> Web3Manager:
    """Get Web3 manager dependency."""
    return web3_manager


# Rate limiting decorator
class RateLimiter:
    """Simple rate limiter using Redis."""
    
    def __init__(self, max_requests: int = 100, window_seconds: int = 3600):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    async def __call__(self,
                      request: Request,
                      user: Optional[Dict[str, Any]] = Depends(get_optional_user),
                      redis_client: redis.Redis = Depends(get_redis_client)):
        """
        Check rate limit for a request.

        Buckets are keyed by the verified wallet address when the caller is
        authenticated, otherwise by client IP. The key must never come from
        the client itself, or callers could reset their own bucket at will.
        """
        if user and user.get("wallet_address"):
            identity = f"wallet:{user['wallet_address'].lower()}"
        else:
            identity = f"ip:{request.client.host if request.client else 'unknown'}"
        key = f"rate_limit:{identity}"
        current = redis_client.get(key)
        
        if current is None:
            redis_client.setex(key, self.window_seconds, 1)
            return
        
        if int(current) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded"
            )
        
        redis_client.incr(key)


# Common rate limiters
api_rate_limiter = RateLimiter(max_requests=1000, window_seconds=3600)
trade_rate_limiter = RateLimiter(max_requests=100, window_seconds=3600)

