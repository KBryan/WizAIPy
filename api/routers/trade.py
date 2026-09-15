"""
Trading endpoints for the NFT-Gated AI Trading Bot.
Handles prompt-to-trade conversion and trade execution.
"""
import json

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from enum import Enum
import logging
import re
import os
from datetime import datetime
import uuid
import redis

from config import get_settings
from api.deps import get_current_user, trade_rate_limiter, get_redis_client
from core.tokens import get_token, get_token_address, NATIVE_TOKEN_ADDRESS
from core.tasks import execute_trade_task

router = APIRouter()
settings = get_settings()
logger = logging.getLogger(__name__)


class TradeType(str, Enum):
    """Supported trade types."""
    BUY = "buy"
    SELL = "sell"
    SWAP = "swap"


class TradeStatus(str, Enum):
    """Trade execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PromptTradeRequest(BaseModel):
    """Request model for natural language trading."""
    prompt: str = Field(..., description="Natural language trading instruction")
    dry_run: bool = Field(default=True, description="Execute as simulation")
    max_slippage: Optional[float] = Field(None, description="Maximum slippage tolerance")
    gas_price: Optional[int] = Field(None, description="Gas price in gwei")
    network: str = Field(default="ethereum", description="Blockchain network")


class DirectTradeRequest(BaseModel):
    """Request model for direct trade execution."""
    trade_type: TradeType
    token_in: str = Field(..., description="Input token address or symbol")
    token_out: str = Field(..., description="Output token address or symbol")
    amount_in: Optional[float] = Field(None, description="Input amount")
    amount_out: Optional[float] = Field(None, description="Expected output amount")
    slippage: float = Field(default=0.5, description="Slippage tolerance percentage")
    network: str = Field(default="ethereum", description="Blockchain network")
    exchange: str = Field(default="uniswap_v3", description="Exchange to use")
    dry_run: bool = Field(default=True, description="Execute as simulation")


class TradeResponse(BaseModel):
    """Response model for trade operations."""
    trade_id: str
    status: TradeStatus
    trade_type: TradeType
    token_in: str
    token_out: str
    amount_in: Optional[float]
    amount_out: Optional[float]
    estimated_gas: Optional[int]
    gas_price: Optional[int]
    network: str
    exchange: str
    dry_run: bool
    created_at: datetime
    message: str
    transaction_hash: Optional[str] = None
    error: Optional[str] = None


class PortfolioResponse(BaseModel):
    """Response model for portfolio information."""
    wallet_address: str
    network: str
    total_value_usd: float
    tokens: List[Dict[str, Any]]
    last_updated: datetime


class StrategyResponse(BaseModel):
    """Response model for trading strategies."""
    strategy_id: str
    name: str
    description: str
    parameters: Dict[str, Any]
    active: bool
    performance: Optional[Dict[str, Any]] = None


@router.post("/prompt", response_model=TradeResponse)
async def prompt_to_trade(
        request: PromptTradeRequest,
        background_tasks: BackgroundTasks,
        current_user: Dict[str, Any] = Depends(get_current_user),
        _rate_limit: None = Depends(trade_rate_limiter)
):
    """
    Convert natural language prompt to trade execution.

    This endpoint uses improved parsing to extract amounts and tokens
    from natural language trading instructions.
    """
    try:
        logger.info(f"Prompt trade request from {current_user['wallet_address']}: {request.prompt}")

        # Generate unique trade ID
        trade_id = str(uuid.uuid4())

        # Parse the prompt using improved parser
        parsed_trade = await parse_trading_prompt(request.prompt)

        if not parsed_trade:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not parse trading instruction from prompt"
            )

        # Apply slippage override if provided
        if request.max_slippage is not None:
            parsed_trade["slippage"] = request.max_slippage

        # Determine if this should be a real trade
        # Debug logging for settings
        logger.info(f"🔍 Settings check: real_data_mode={settings.real_data_mode}, request.dry_run={request.dry_run}")

        # Force real trading if explicitly requested
        is_dry_run = request.dry_run
        if not request.dry_run and settings.real_data_mode:
            logger.info("🚀 REAL TRADING MODE ENABLED - Executing live trade!")
            is_dry_run = False
        elif not settings.real_data_mode:
            logger.warning("⚠️ REAL_DATA_MODE is False - Forcing dry run")
            is_dry_run = True

        # Create trade response
        trade_response = TradeResponse(
            trade_id=trade_id,
            status=TradeStatus.PENDING,
            trade_type=parsed_trade.get("trade_type", TradeType.SWAP),
            token_in=parsed_trade.get("token_in", "ETH"),
            token_out=parsed_trade.get("token_out", "USDC"),
            amount_in=parsed_trade.get("amount_in"),
            amount_out=parsed_trade.get("amount_out"),
            estimated_gas=parsed_trade.get("estimated_gas", 150000),
            gas_price=request.gas_price or settings.max_gas_price,
            network=request.network,
            exchange="uniswap_v3",  # Default exchange
            dry_run=is_dry_run,
            created_at=datetime.utcnow(),
            message="Trade parsed successfully, queued for execution"
        )

        # Queue trade for background execution
        if not is_dry_run:
            logger.info(f"🚀 Queueing REAL trade execution for {trade_id}")
            background_tasks.add_task(
                execute_trade_background,
                trade_id,
                parsed_trade,
                current_user["wallet_address"],
                request.network
            )
        else:
            logger.info(f"🧪 Dry run trade {trade_id} - no background execution")

        return trade_response

    except Exception as e:
        logger.error(f"Prompt trade error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trade processing failed: {str(e)}"
        )


@router.post("/execute", response_model=TradeResponse)
async def execute_direct_trade(
        request: DirectTradeRequest,
        background_tasks: BackgroundTasks,
        current_user: Dict[str, Any] = Depends(get_current_user),
        _rate_limit: None = Depends(trade_rate_limiter)
):
    """
    Execute a direct trade with specified parameters.

    This endpoint allows direct trade execution without natural language parsing.
    """
    try:
        logger.info(f"Direct trade request from {current_user['wallet_address']}")

        # Generate unique trade ID
        trade_id = str(uuid.uuid4())

        # Validate trade parameters
        if not request.amount_in and not request.amount_out:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Either amount_in or amount_out must be specified"
            )

        # Validate amount ranges for safety
        if request.amount_in and request.amount_in <= 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Amount must be greater than 0"
            )

        # Safety check for large amounts
        if request.amount_in and request.amount_in > 10.0:  # More than 10 ETH
            logger.warning(f"Large trade amount detected: {request.amount_in} ETH")

        # TODO: Implement trade validation and estimation
        estimated_gas = 150000  # Placeholder

        trade_response = TradeResponse(
            trade_id=trade_id,
            status=TradeStatus.PENDING,
            trade_type=request.trade_type,
            token_in=request.token_in,
            token_out=request.token_out,
            amount_in=request.amount_in,
            amount_out=request.amount_out,
            estimated_gas=estimated_gas,
            gas_price=settings.max_gas_price,
            network=request.network,
            exchange=request.exchange,
            dry_run=request.dry_run or not settings.real_data_mode,
            created_at=datetime.utcnow(),
            message="Trade queued for execution"
        )

        # Queue trade for background execution
        if not trade_response.dry_run:
            background_tasks.add_task(
                execute_trade_background,
                trade_id,
                request.dict(),
                current_user["wallet_address"],
                request.network
            )
        else:
            logger.info(f"Dry run trade {trade_id} - no background execution")

        return trade_response

    except Exception as e:
        logger.error(f"Direct trade error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trade execution failed: {str(e)}"
        )


@router.get("/status/{trade_id}")
async def get_trade_status(
        trade_id: str,
        current_user: Dict[str, Any] = Depends(get_current_user),
        redis_client: redis.Redis = Depends(get_redis_client)
):
    """
    Get the status of a specific trade.

    Returns current status, execution details, and transaction information.
    """
    try:
        # Check if this is a real Celery task or mock data
        cache_key = f"trade_status:{trade_id}"
        cached_status = redis_client.get(cache_key)

        if cached_status:
            import json
            logger.info(f"Found cached status for trade {trade_id}")
            return json.loads(cached_status)

        # Check for Celery task result
        celery_task_key = f"celery_task:{trade_id}"
        celery_task_id = redis_client.get(celery_task_key)

        if celery_task_id:
            # Get Celery task result
            from celery.result import AsyncResult
            result = AsyncResult(celery_task_id.decode(), app=execute_trade_task.app)

            if result.ready():
                if result.successful():
                    task_result = result.result
                    logger.info(f"Celery task completed for trade {trade_id}")
                    return {
                        "trade_id": trade_id,
                        "status": "completed",
                        "transaction_hash": task_result.get("transaction_hash"),
                        "block_number": task_result.get("block_number"),
                        "gas_used": task_result.get("gas_used"),
                        "execution_time": task_result.get("execution_time"),
                        "final_amount_out": task_result.get("final_amount_out"),
                        "message": task_result.get("message", "Trade executed successfully"),
                        "celery_task_id": celery_task_id.decode()
                    }
                else:
                    # Task failed
                    error_msg = str(result.result) if result.result else "Unknown error"
                    logger.error(f"Celery task failed for trade {trade_id}: {error_msg}")
                    return {
                        "trade_id": trade_id,
                        "status": "failed",
                        "error": error_msg,
                        "message": "Trade execution failed",
                        "celery_task_id": celery_task_id.decode()
                    }
            else:
                # Task still running
                return {
                    "trade_id": trade_id,
                    "status": "executing",
                    "message": "Trade execution in progress",
                    "celery_task_id": celery_task_id.decode()
                }

        # Fallback to mock response for testing
        logger.info(f"No Celery task found for trade {trade_id}, returning mock status")
        return {
            "trade_id": trade_id,
            "status": "completed",
            "transaction_hash": "0x1234567890abcdef...",
            "block_number": 18500000,
            "gas_used": 145000,
            "execution_time": 15.5,
            "final_amount_out": 1000.0,
            "message": "Trade executed successfully (MOCK DATA)"
        }

    except Exception as e:
        logger.error(f"Trade status lookup error: {e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trade not found: {trade_id}"
        )


@router.get("/portfolio", response_model=PortfolioResponse)
async def get_portfolio(
        network: str = "ethereum",
        current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get current portfolio for the authenticated user.

    Returns token balances, values, and portfolio summary.
    """
    try:
        # Check if blockchain is disabled
        if os.getenv("DISABLE_BLOCKCHAIN", "false").lower() == "true":
            logger.info("Using mock portfolio data - blockchain disabled")
            return PortfolioResponse(
                wallet_address="0x0000000000000000000000000000000000000000",
                network=network,
                total_value_usd=5000.0,
                tokens=[
                    {
                        "symbol": "ETH",
                        "address": NATIVE_TOKEN_ADDRESS,
                        "balance": 2.5,
                        "value_usd": 4000.0,
                        "price_usd": 1600.0
                    },
                    {
                        "symbol": "USDC",
                        "address": get_token_address("USDC"),
                        "balance": 1000.0,
                        "value_usd": 1000.0,
                        "price_usd": 1.0
                    }
                ],
                last_updated=datetime.utcnow()
            )

        from web3 import Web3
        import requests
        from config import get_settings

        settings = get_settings()

        # Check if we should use real data
        if not settings.real_data_mode or not hasattr(settings, 'private_key') or not settings.private_key:
            logger.info("Using mock portfolio data - real data mode disabled")
            return PortfolioResponse(
                wallet_address="0x0000000000000000000000000000000000000000",
                network=network,
                total_value_usd=5000.0,
                tokens=[
                    {
                        "symbol": "ETH",
                        "address": NATIVE_TOKEN_ADDRESS,
                        "balance": 2.5,
                        "value_usd": 4000.0,
                        "price_usd": 1600.0
                    },
                    {
                        "symbol": "USDC",
                        "address": get_token_address("USDC"),
                        "balance": 1000.0,
                        "value_usd": 1000.0,
                        "price_usd": 1.0
                    }
                ],
                last_updated=datetime.utcnow()
            )

        # === REAL BLOCKCHAIN DATA ===
        logger.info("Fetching real portfolio data from blockchain")

        # Connect to Ethereum
        w3 = Web3(Web3.HTTPProvider(settings.ethereum_rpc_url))

        if not w3.is_connected():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Failed to connect to Ethereum network"
            )

        # Get real wallet address from private key
        account = w3.eth.account.from_key(settings.private_key)
        wallet_address = account.address

        logger.info(f"Fetching portfolio for wallet: {wallet_address}")

        # ERC-20 tokens to report, resolved from the shared registry
        token_contracts = {
            symbol: {"address": get_token(symbol).address, "decimals": get_token(symbol).decimals}
            for symbol in ("USDC", "USDT", "WETH")
        }

        # ERC20 ABI for balance queries
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }
        ]

        def get_token_price(symbol: str) -> float:
            """Get token price from CoinGecko."""
            try:
                coingecko_ids = {
                    "ETH": "ethereum",
                    "USDC": "usd-coin",
                    "USDT": "tether",
                    "WETH": "weth"
                }

                if symbol not in coingecko_ids:
                    return 0.0

                url = f"https://api.coingecko.com/api/v3/simple/price"
                params = {
                    "ids": coingecko_ids[symbol],
                    "vs_currencies": "usd"
                }

                response = requests.get(url, params=params, timeout=10)
                data = response.json()
                return float(data[coingecko_ids[symbol]]["usd"])

            except Exception as e:
                logger.warning(f"Failed to get {symbol} price: {e}")
                # Fallback prices
                fallback_prices = {"ETH": 2000.0, "USDC": 1.0, "USDT": 1.0, "WETH": 2000.0}
                return fallback_prices.get(symbol, 0.0)

        tokens = []
        total_value_usd = 0.0

        # Get ETH balance
        try:
            balance_wei = w3.eth.get_balance(wallet_address)
            eth_balance = float(w3.from_wei(balance_wei, 'ether'))
            eth_price = get_token_price("ETH")
            eth_value = eth_balance * eth_price

            if eth_balance > 0:
                tokens.append({
                    "symbol": "ETH",
                    "address": NATIVE_TOKEN_ADDRESS,
                    "balance": eth_balance,
                    "value_usd": eth_value,
                    "price_usd": eth_price
                })
                total_value_usd += eth_value

            logger.info(f"ETH Balance: {eth_balance:.4f} ETH (${eth_value:.2f})")

        except Exception as e:
            logger.error(f"Failed to get ETH balance: {e}")

        # Get ERC20 token balances
        for token_symbol, token_info in token_contracts.items():
            try:
                contract = w3.eth.contract(
                    address=Web3.to_checksum_address(token_info["address"]),
                    abi=erc20_abi
                )

                balance_raw = contract.functions.balanceOf(wallet_address).call()
                balance = balance_raw / (10 ** token_info["decimals"])

                if balance > 0:
                    price = get_token_price(token_symbol)
                    value = balance * price

                    tokens.append({
                        "symbol": token_symbol,
                        "address": token_info["address"],
                        "balance": balance,
                        "value_usd": value,
                        "price_usd": price
                    })
                    total_value_usd += value

                    logger.info(f"{token_symbol} Balance: {balance:.2f} {token_symbol} (${value:.2f})")

            except Exception as e:
                logger.warning(f"Failed to get {token_symbol} balance: {e}")

        logger.info(f"Total Portfolio Value: ${total_value_usd:.2f}")

        return PortfolioResponse(
            wallet_address=wallet_address,  # Real wallet address!
            network=network,
            total_value_usd=total_value_usd,  # Real total value!
            tokens=tokens,  # Real token balances!
            last_updated=datetime.utcnow()
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Portfolio fetch error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Portfolio fetch failed: {str(e)}"
        )


@router.get("/strategies", response_model=List[StrategyResponse])
async def get_available_strategies(
        current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get list of available trading strategies.

    Returns all strategies that the user can activate or configure.
    """
    try:
        # TODO: Implement strategy registry lookup
        # For now, return mock strategies

        return [
            StrategyResponse(
                strategy_id="momentum_1",
                name="Momentum Trading",
                description="Follows price trends and momentum indicators",
                parameters={
                    "lookback_period": 14,
                    "threshold": 0.05,
                    "max_position_size": 0.1
                },
                active=False
            ),
            StrategyResponse(
                strategy_id="arbitrage_1",
                name="DEX Arbitrage",
                description="Exploits price differences between exchanges",
                parameters={
                    "min_profit_threshold": 0.01,
                    "max_gas_price": 100,
                    "exchanges": ["uniswap_v2", "uniswap_v3", "sushiswap"]
                },
                active=False
            ),
            StrategyResponse(
                strategy_id="dca_1",
                name="Dollar Cost Averaging",
                description="Automatically buy/sell fixed amounts at regular intervals",
                parameters={
                    "amount_usd": 100,
                    "interval_hours": 24,
                    "max_slippage": 1.0
                },
                active=False
            )
        ]

    except Exception as e:
        logger.error(f"Strategy fetch error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Strategy fetch failed: {str(e)}"
        )


@router.get("/history")
async def get_trade_history(
        limit: int = 50,
        offset: int = 0,
        current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get trade history for the authenticated user.

    Returns paginated list of past trades with execution details.
    """
    try:
        # TODO: Implement trade history lookup from database
        # For now, return mock history

        return {
            "trades": [
                {
                    "trade_id": "trade_123",
                    "timestamp": datetime.utcnow(),
                    "trade_type": "swap",
                    "token_in": "ETH",
                    "token_out": "USDC",
                    "amount_in": 1.0,
                    "amount_out": 1600.0,
                    "status": "completed",
                    "transaction_hash": "0xabcdef123456..."
                }
            ],
            "total": 1,
            "limit": limit,
            "offset": offset
        }

    except Exception as e:
        logger.error(f"Trade history error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Trade history fetch failed: {str(e)}"
        )


# Helper functions

async def parse_trading_prompt(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Parse natural language trading prompt with improved amount extraction.

    Extracts amounts, tokens, and trade types from natural language.
    This is a much improved version but still needs LLM integration for production.
    """
    prompt_lower = prompt.lower()

    # Extract dollar amounts: $5, $100, $1.50, etc.
    dollar_match = re.search(r"\$(\d+(?:\.\d+)?)", prompt)

    # Extract ETH amounts: 0.5 ETH, 1.2 eth, etc.
    eth_match = re.search(r"(\d+(?:\.\d+)?)\s*eth", prompt_lower)

    # Extract other token amounts: 1000 USDC, 500 usdt, etc.
    token_match = re.search(r"(\d+(?:\.\d+)?)\s*(usdc|usdt|weth|dai)", prompt_lower)

    # Extract token pairs: ETH/USDC, ETH for USDC, etc.
    pair_match = re.search(r"(eth|usdc|usdt|weth|dai)\s*(?:for|to|/)\s*(eth|usdc|usdt|weth|dai)", prompt_lower)

    # Determine trade type
    if "buy" in prompt_lower or "purchase" in prompt_lower:
        trade_type = TradeType.BUY
        default_token_in = "USDC"  # Buying ETH with USDC
        default_token_out = "ETH"
    elif "sell" in prompt_lower:
        trade_type = TradeType.SELL
        default_token_in = "ETH"   # Selling ETH for USDC
        default_token_out = "USDC"
    else:
        trade_type = TradeType.SWAP
        default_token_in = "ETH"   # Default swap ETH -> USDC
        default_token_out = "USDC"

    # Determine tokens from pair if specified
    if pair_match:
        token_in = pair_match.group(1).upper()
        token_out = pair_match.group(2).upper()
    else:
        token_in = default_token_in
        token_out = default_token_out

    # Calculate amount_in based on what was specified
    amount_in = 0.001  # Default small amount (safety)

    if dollar_match:
        usd_amount = float(dollar_match.group(1))

        # Safety check for large USD amounts
        if usd_amount > 1000:
            logger.warning(f"Large USD amount in prompt: ${usd_amount}")
            usd_amount = min(usd_amount, 1000)  # Cap at $1000 for safety

        if "worth of eth" in prompt_lower or ("eth" in prompt_lower and token_out != "ETH"):
            # $5 worth of ETH = 0.0025 ETH at $2000/ETH
            eth_price = 2000.0  # Fallback price, should use real price
            amount_in = usd_amount / eth_price
        else:
            # $1000 USDC to buy ETH
            amount_in = usd_amount

    elif eth_match:
        # Direct ETH amount specified
        amount_in = float(eth_match.group(1))

        # Safety check for large ETH amounts
        if amount_in > 5.0:
            logger.warning(f"Large ETH amount in prompt: {amount_in} ETH")
            amount_in = min(amount_in, 5.0)  # Cap at 5 ETH for safety

    elif token_match:
        # Other token amount specified
        amount_in = float(token_match.group(1))
        token_symbol = token_match.group(2).upper()

        # Safety check for large token amounts
        if token_symbol == "USDC" and amount_in > 10000:
            logger.warning(f"Large USDC amount in prompt: {amount_in} USDC")
            amount_in = min(amount_in, 10000)  # Cap at 10k USDC for safety

        if trade_type == TradeType.BUY:
            token_in = token_symbol
        else:
            token_in = token_symbol

    # Additional safety: Very small amounts
    if amount_in < 0.0001 and token_in == "ETH":
        amount_in = 0.0001  # Minimum viable ETH amount

    logger.info(f"Parsed prompt '{prompt}' -> {trade_type} {amount_in} {token_in} for {token_out}")

    return {
        "trade_type": trade_type,
        "token_in": token_in,
        "token_out": token_out,
        "amount_in": amount_in,
        "slippage": 0.5,  # Default slippage
        "estimated_gas": 150000
    }


async def execute_trade_background(
        trade_id: str,
        trade_params: Dict[str, Any],
        wallet_address: str,
        network: str
):
    """
    Execute trade in background using real Celery task.

    This function calls the actual Celery task for trade execution
    and stores the task ID for status tracking.
    """
    try:
        logger.info(f"Queueing Celery task for trade {trade_id} from {wallet_address}")

        # Prepare trade data for Celery task
        trade_data = {
            "trade_id": trade_id,
            "token_in": trade_params.get("token_in", "ETH"),
            "token_out": trade_params.get("token_out", "USDC"),
            "amount_in": trade_params.get("amount_in", 0.001),
            "slippage": trade_params.get("slippage", 0.5),
            "dry_run": False,  # This function is only called for real trades now
            "wallet_address": wallet_address,
            "network": network
        }

        # Call the real Celery task
        logger.info(f"Calling execute_trade_task with data: {trade_data}")
        result = execute_trade_task.delay(trade_data)

        logger.info(f"Celery task queued for trade {trade_id}, task_id: {result.id}")

        # Store task ID in Redis for status tracking
        redis_client = redis.from_url(settings.redis_url)
        celery_task_key = f"celery_task:{trade_id}"
        redis_client.setex(celery_task_key, 3600, result.id)  # Store for 1 hour

        logger.info(f"Stored Celery task ID {result.id} for trade {trade_id}")

        # TODO: Send Twitter notification if enabled

    except Exception as e:
        logger.error(f"Failed to queue Celery task for trade {trade_id}: {e}")

        # Store error status
        try:
            redis_client = redis.from_url(settings.redis_url)
            error_status = {
                "trade_id": trade_id,
                "status": "failed",
                "error": str(e),
                "message": "Failed to queue background task"
            }
            cache_key = f"trade_status:{trade_id}"
            redis_client.setex(cache_key, 3600, json.dumps(error_status))
        except Exception as cache_error:
            logger.error(f"Failed to cache error status: {cache_error}")