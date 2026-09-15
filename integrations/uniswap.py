"""
Uniswap V2/V3 integration for decentralized exchange trading.
Provides swap functionality and liquidity pool interactions.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from datetime import datetime, timedelta
from dataclasses import dataclass
from web3 import Web3
from web3.contract import Contract
from eth_account import Account

from config import get_settings, SUPPORTED_NETWORKS
from core.execution.engine import ExchangeAdapter, TradeQuote, ExecutionError
from core.tokens import token_addresses, UnknownTokenError

logger = logging.getLogger(__name__)
settings = get_settings()


@dataclass
class PoolInfo:
    """Uniswap pool information."""
    address: str
    token0: str
    token1: str
    fee: int
    liquidity: int
    sqrt_price_x96: int
    tick: int
    version: str  # "v2" or "v3"


@dataclass
class SwapRoute:
    """Swap routing information."""
    path: List[str]
    pools: List[PoolInfo]
    expected_output: float
    price_impact: float
    gas_estimate: int


class UniswapError(Exception):
    """Custom exception for Uniswap-related errors."""
    pass


class UniswapV2Adapter(ExchangeAdapter):
    """
    Uniswap V2 adapter for token swaps.
    """
    
    # Uniswap V2 contract addresses (Ethereum mainnet)
    ROUTER_ADDRESS = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
    FACTORY_ADDRESS = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
    
    # Uniswap V2 Router ABI (simplified)
    ROUTER_ABI = [
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"}
            ],
            "name": "getAmountsOut",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "view",
            "type": "function"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactETHForTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "payable",
            "type": "function"
        },
        {
            "inputs": [
                {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
                {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
                {"internalType": "address[]", "name": "path", "type": "address[]"},
                {"internalType": "address", "name": "to", "type": "address"},
                {"internalType": "uint256", "name": "deadline", "type": "uint256"}
            ],
            "name": "swapExactTokensForTokens",
            "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
            "stateMutability": "nonpayable",
            "type": "function"
        }
    ]
    
    def __init__(self, network: str = "ethereum"):
        super().__init__(network)
        self.w3 = self._get_web3_connection()
        self.router_contract = self._get_router_contract()
        
        # Symbol -> address for this network, from the shared registry
        try:
            self.token_addresses = token_addresses(network)
        except UnknownTokenError as e:
            raise UniswapError(str(e))
    
    def _get_web3_connection(self) -> Web3:
        """Get Web3 connection for the network."""
        network_config = SUPPORTED_NETWORKS.get(self.network)
        if not network_config:
            raise UniswapError(f"Unsupported network: {self.network}")
        
        rpc_key = network_config["rpc_key"]
        rpc_url = getattr(settings, rpc_key)
        
        if not rpc_url:
            raise UniswapError(f"RPC URL not configured for {self.network}")
        
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        
        if not w3.is_connected():
            raise UniswapError(f"Failed to connect to {self.network} network")
        
        return w3
    
    def _get_router_contract(self) -> Contract:
        """Get Uniswap V2 router contract."""
        return self.w3.eth.contract(
            address=Web3.to_checksum_address(self.ROUTER_ADDRESS),
            abi=self.ROUTER_ABI
        )
    
    def _get_token_address(self, token: str) -> str:
        """
        Get token contract address.
        
        Args:
            token: Token symbol or address
            
        Returns:
            Token contract address
        """
        if Web3.is_address(token):
            return Web3.to_checksum_address(token)
        
        address = self.token_addresses.get(token.upper())
        if not address:
            raise UniswapError(f"Unknown token: {token}")
        
        return Web3.to_checksum_address(address)
    
    def _build_swap_path(self, token_in: str, token_out: str) -> List[str]:
        """
        Build swap path between two tokens.
        
        Args:
            token_in: Input token
            token_out: Output token
            
        Returns:
            List of token addresses in swap path
        """
        token_in_addr = self._get_token_address(token_in)
        token_out_addr = self._get_token_address(token_out)
        
        # For simplicity, use direct path or route through WETH
        if token_in.upper() == "ETH":
            token_in_addr = self._get_token_address("WETH")
        
        if token_out.upper() == "ETH":
            token_out_addr = self._get_token_address("WETH")
        
        # Direct path if possible, otherwise route through WETH
        if token_in_addr == token_out_addr:
            raise UniswapError("Cannot swap token with itself")
        
        weth_addr = self._get_token_address("WETH")
        
        # Try direct path first
        if self._pair_exists(token_in_addr, token_out_addr):
            return [token_in_addr, token_out_addr]
        
        # Route through WETH
        if token_in_addr != weth_addr and token_out_addr != weth_addr:
            return [token_in_addr, weth_addr, token_out_addr]
        
        raise UniswapError(f"No swap path found between {token_in} and {token_out}")
    
    def _pair_exists(self, token_a: str, token_b: str) -> bool:
        """
        Check if a trading pair exists.
        
        Args:
            token_a: First token address
            token_b: Second token address
            
        Returns:
            True if pair exists, False otherwise
        """
        # TODO: Implement actual pair existence check
        # For now, assume common pairs exist
        return True
    
    async def get_quote(self, token_in: str, token_out: str, amount_in: float) -> TradeQuote:
        """
        Get a quote for a token swap.
        
        Args:
            token_in: Input token symbol or address
            token_out: Output token symbol or address
            amount_in: Amount of input token
            
        Returns:
            TradeQuote with swap details
        """
        try:
            # Build swap path
            path = self._build_swap_path(token_in, token_out)
            
            # Convert amount to wei (assuming 18 decimals for simplicity)
            amount_in_wei = int(amount_in * 10**18)
            
            # Get amounts out from Uniswap
            amounts_out = await asyncio.to_thread(
                self.router_contract.functions.getAmountsOut(amount_in_wei, path).call
            )
            
            amount_out_wei = amounts_out[-1]
            amount_out = amount_out_wei / 10**18
            
            # Calculate price and slippage
            price = amount_out / amount_in if amount_in > 0 else 0
            
            # Estimate gas
            gas_estimate = await self.estimate_gas(token_in, token_out, amount_in)
            
            # Calculate fees (0.3% for Uniswap V2)
            fees = amount_in * 0.003
            
            # Calculate slippage (simplified)
            slippage = 0.01  # 1% default slippage estimate
            
            return TradeQuote(
                exchange="uniswap_v2",
                token_in=token_in,
                token_out=token_out,
                amount_in=amount_in,
                amount_out=amount_out,
                price=price,
                gas_estimate=gas_estimate,
                slippage=slippage,
                fees=fees,
                valid_until=datetime.utcnow() + timedelta(minutes=5),
                route=path
            )
            
        except Exception as e:
            self.logger.error(f"Error getting Uniswap quote: {e}")
            raise UniswapError(f"Failed to get quote: {e}")
    
    async def execute_trade(self, quote: TradeQuote, wallet_address: str, slippage: float) -> str:
        """
        Execute a token swap.
        
        Args:
            quote: Trade quote to execute
            wallet_address: Wallet address for execution
            slippage: Maximum slippage tolerance
            
        Returns:
            Transaction hash
        """
        try:
            # Get private key for the network
            private_key = getattr(settings, SUPPORTED_NETWORKS[self.network]["private_key"])
            if not private_key:
                raise UniswapError("Private key not configured")
            
            account = Account.from_key(private_key)
            
            # Build swap path
            path = quote.route or self._build_swap_path(quote.token_in, quote.token_out)
            
            # Calculate minimum amount out with slippage
            min_amount_out = quote.amount_out * (1 - slippage / 100)
            min_amount_out_wei = int(min_amount_out * 10**18)
            
            # Set deadline (10 minutes from now)
            deadline = int((datetime.utcnow() + timedelta(minutes=10)).timestamp())
            
            # Build transaction
            if quote.token_in.upper() == "ETH":
                # ETH to token swap
                amount_in_wei = int(quote.amount_in * 10**18)
                
                transaction = self.router_contract.functions.swapExactETHForTokens(
                    min_amount_out_wei,
                    path,
                    wallet_address,
                    deadline
                ).build_transaction({
                    "from": wallet_address,
                    "value": amount_in_wei,
                    "gas": quote.gas_estimate,
                    "gasPrice": self.w3.to_wei(settings.max_gas_price, "gwei"),
                    "nonce": self.w3.eth.get_transaction_count(wallet_address)
                })
            else:
                # Token to token swap
                amount_in_wei = int(quote.amount_in * 10**18)
                
                transaction = self.router_contract.functions.swapExactTokensForTokens(
                    amount_in_wei,
                    min_amount_out_wei,
                    path,
                    wallet_address,
                    deadline
                ).build_transaction({
                    "from": wallet_address,
                    "gas": quote.gas_estimate,
                    "gasPrice": self.w3.to_wei(settings.max_gas_price, "gwei"),
                    "nonce": self.w3.eth.get_transaction_count(wallet_address)
                })
            
            # Sign and send transaction
            signed_txn = account.sign_transaction(transaction)
            tx_hash = await asyncio.to_thread(
                self.w3.eth.send_raw_transaction,
                signed_txn.rawTransaction
            )
            
            return tx_hash.hex()
            
        except Exception as e:
            self.logger.error(f"Error executing Uniswap trade: {e}")
            raise UniswapError(f"Failed to execute trade: {e}")
    
    async def get_transaction_status(self, tx_hash: str) -> Dict[str, Any]:
        """
        Get transaction status and details.
        
        Args:
            tx_hash: Transaction hash
            
        Returns:
            Transaction status and details
        """
        try:
            tx_receipt = await asyncio.to_thread(
                self.w3.eth.get_transaction_receipt,
                tx_hash
            )
            
            if tx_receipt:
                return {
                    "status": "success" if tx_receipt.status == 1 else "failed",
                    "block_number": tx_receipt.blockNumber,
                    "gas_used": tx_receipt.gasUsed,
                    "transaction_hash": tx_hash
                }
            else:
                return {"status": "pending"}
                
        except Exception as e:
            self.logger.error(f"Error getting transaction status: {e}")
            return {"status": "unknown", "error": str(e)}
    
    async def estimate_gas(self, token_in: str, token_out: str, amount_in: float) -> int:
        """
        Estimate gas cost for a swap.
        
        Args:
            token_in: Input token
            token_out: Output token
            amount_in: Input amount
            
        Returns:
            Estimated gas units
        """
        # Default gas estimates for Uniswap V2
        if token_in.upper() == "ETH" or token_out.upper() == "ETH":
            return 150000  # ETH swaps
        else:
            return 200000  # Token swaps


class UniswapV3Adapter(UniswapV2Adapter):
    """
    Uniswap V3 adapter for token swaps.
    Extends V2 adapter with V3-specific functionality.
    """
    
    # Uniswap V3 contract addresses (Ethereum mainnet)
    ROUTER_ADDRESS = "0xE592427A0AEce92De3Edee1F18E0157C05861564"
    FACTORY_ADDRESS = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
    
    def __init__(self, network: str = "ethereum"):
        super().__init__(network)
        # Override with V3 router
        # TODO: Implement V3-specific contract interactions
    
    async def get_quote(self, token_in: str, token_out: str, amount_in: float) -> TradeQuote:
        """Get quote using Uniswap V3 pricing."""
        # TODO: Implement V3-specific quote logic with concentrated liquidity
        quote = await super().get_quote(token_in, token_out, amount_in)
        quote.exchange = "uniswap_v3"
        return quote
    
    async def estimate_gas(self, token_in: str, token_out: str, amount_in: float) -> int:
        """Estimate gas for V3 swaps."""
        # V3 typically uses more gas due to complexity
        base_gas = await super().estimate_gas(token_in, token_out, amount_in)
        return int(base_gas * 1.2)  # 20% more gas for V3


# Factory function to create appropriate adapter
def create_uniswap_adapter(version: str = "v3", network: str = "ethereum") -> ExchangeAdapter:
    """
    Create Uniswap adapter for specified version.
    
    Args:
        version: Uniswap version ("v2" or "v3")
        network: Blockchain network
        
    Returns:
        Uniswap adapter instance
    """
    if version.lower() == "v2":
        return UniswapV2Adapter(network)
    elif version.lower() == "v3":
        return UniswapV3Adapter(network)
    else:
        raise ValueError(f"Unsupported Uniswap version: {version}")

