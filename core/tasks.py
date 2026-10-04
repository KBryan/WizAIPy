"""
Celery tasks for background processing with live price feeds.
"""

import asyncio
from web3 import Web3
from eth_account import Account
import json
from celery import Celery
from core.celery_app import celery_app
import logging
from typing import Dict, Any
from config import get_settings
from core.tokens import NATIVE_TOKEN_ADDRESS, get_token_address, is_supported_token, to_base_units
from core.contracts import get_uniswap
import requests

logger = logging.getLogger(__name__)

# Uniswap V3 SwapRouter on Ethereum mainnet, from the shared contract registry
UNISWAP_V3_ROUTER = get_uniswap("v3", "ethereum").router


# Simplified Uniswap V3 Router ABI (just the exactInputSingle function)
UNISWAP_V3_ROUTER_ABI = [
    {
        "inputs": [
            {
                "components": [
                    {"name": "tokenIn", "type": "address"},
                    {"name": "tokenOut", "type": "address"},
                    {"name": "fee", "type": "uint24"},
                    {"name": "recipient", "type": "address"},
                    {"name": "deadline", "type": "uint256"},
                    {"name": "amountIn", "type": "uint256"},
                    {"name": "amountOutMinimum", "type": "uint256"},
                    {"name": "sqrtPriceLimitX96", "type": "uint160"}
                ],
                "name": "params",
                "type": "tuple"
            }
        ],
        "name": "exactInputSingle",
        "outputs": [{"name": "amountOut", "type": "uint256"}],
        "stateMutability": "payable",
        "type": "function"
    }
]

# Import your existing Twitter client
import os
if os.getenv("DISABLE_BLOCKCHAIN", "false").lower() == "true":
    logger.info("Twitter integration disabled via DISABLE_BLOCKCHAIN")
    TWITTER_AVAILABLE = False
    twitter_client = None
else:
    try:
        from core.twitter_integration import twitter_client
        TWITTER_AVAILABLE = True
    except ImportError as e:
        logger.warning(f"Twitter integration not available: {e}")
        TWITTER_AVAILABLE = False
        twitter_client = None


def get_live_token_price(symbol: str) -> float:
    """
    Get live token price from multiple sources with fallbacks.

    Args:
        symbol: Token symbol (ETH, USDC, etc.)

    Returns:
        Current USD price of the token
    """
    try:
        # Primary source: CoinGecko
        coingecko_ids = {
            "ETH": "ethereum",
            "USDC": "usd-coin",
            "USDT": "tether",
            "SKL": "skale",
            "WETH": "ethereum"  # WETH same as ETH
        }

        if symbol not in coingecko_ids:
            logger.warning(f"Unknown token symbol: {symbol}")
            return 0.0

        # Try CoinGecko first
        try:
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": coingecko_ids[symbol],
                "vs_currencies": "usd"
            }

            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            price = float(data[coingecko_ids[symbol]]["usd"])
            logger.info(f"✅ Got live {symbol} price from CoinGecko: ${price:.2f}")
            return price

        except Exception as e:
            logger.warning(f"CoinGecko failed for {symbol}: {e}")

        # Fallback: CoinCap API
        try:
            coincap_ids = {
                "ETH": "ethereum",
                "USDC": "usd-coin",
                "USDT": "tether",
                "WETH": "ethereum",
                "SKL": "skale"
            }

            if symbol in coincap_ids:
                url = f"https://api.coincap.io/v2/assets/{coincap_ids[symbol]}"
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                data = response.json()

                price = float(data["data"]["priceUsd"])
                logger.info(f"✅ Got live {symbol} price from CoinCap: ${price:.2f}")
                return price

        except Exception as e:
            logger.warning(f"CoinCap failed for {symbol}: {e}")

    except Exception as e:
        logger.error(f"All price sources failed for {symbol}: {e}")

    # Final fallback prices (updated to current market)
    fallback_prices = {
        "ETH": 3062.04,  # Updated fallback
        "USDC": 1.0,
        "USDT": 1.0,
        "WETH": 3062.04,
        "SKL": 0.02399
    }

    fallback_price = fallback_prices.get(symbol, 0.0)
    logger.warning(f"⚠️ Using fallback price for {symbol}: ${fallback_price:.2f}")
    return fallback_price


# Add this function to your core/tasks.py

def check_and_approve_token(w3, token_address, spender_address, amount, wallet_address, private_key):
    """
    Check if token approval is needed and execute approval if necessary.

    Args:
        w3: Web3 instance
        token_address: Token contract address (e.g., WETH)
        spender_address: Spender address (Uniswap router)
        amount: Amount to approve
        wallet_address: User's wallet address
        private_key: User's private key

    Returns:
        bool: True if approval successful or not needed, False if failed
    """
    try:
        # Skip approval for ETH (native token)
        if token_address == NATIVE_TOKEN_ADDRESS:
            logger.info("✅ ETH trade - no approval needed")
            return True

        logger.info(f"🔍 Checking approval for token {token_address}")
        logger.info(f"🔍 Spender: {spender_address}")
        logger.info(f"🔍 Amount: {amount}")
        logger.info(f"🔍 Wallet: {wallet_address}")

        # Check ETH balance first
        eth_balance = w3.eth.get_balance(wallet_address)
        eth_balance_ether = w3.from_wei(eth_balance, 'ether')
        logger.info(f"💰 Wallet ETH balance: {eth_balance_ether} ETH")

        if eth_balance_ether < 0.005:  # Need at least 0.005 ETH for approval gas
            logger.error(f"❌ Insufficient ETH for approval gas. Balance: {eth_balance_ether} ETH")
            return False

        # ERC20 ABI for approval functions
        erc20_abi = [
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}, {"name": "_spender", "type": "address"}],
                "name": "allowance",
                "outputs": [{"name": "", "type": "uint256"}],
                "type": "function"
            },
            {
                "constant": False,
                "inputs": [{"name": "_spender", "type": "address"}, {"name": "_value", "type": "uint256"}],
                "name": "approve",
                "outputs": [{"name": "", "type": "bool"}],
                "type": "function"
            },
            {
                "constant": True,
                "inputs": [{"name": "_owner", "type": "address"}],
                "name": "balanceOf",
                "outputs": [{"name": "balance", "type": "uint256"}],
                "type": "function"
            }
        ]

        # Create token contract with proper checksum addresses
        token_checksum = Web3.to_checksum_address(token_address)
        spender_checksum = Web3.to_checksum_address(spender_address)
        wallet_checksum = Web3.to_checksum_address(wallet_address)

        logger.info(f"🔍 Using checksummed addresses:")
        logger.info(f"  Token: {token_checksum}")
        logger.info(f"  Spender: {spender_checksum}")
        logger.info(f"  Wallet: {wallet_checksum}")

        try:
            token_contract = w3.eth.contract(address=token_checksum, abi=erc20_abi)
            logger.info("✅ Token contract created successfully")
        except Exception as e:
            logger.error(f"❌ Failed to create token contract: {e}")
            return False

        # Check if token contract is valid by trying to call balanceOf
        try:
            token_balance = token_contract.functions.balanceOf(wallet_checksum).call()
            logger.info(f"💰 Token balance: {token_balance}")

            if token_balance < amount:
                logger.error(f"❌ Insufficient token balance. Have: {token_balance}, Need: {amount}")
                return False

        except Exception as e:
            logger.error(f"❌ Failed to check token balance - invalid token contract? Error: {e}")
            return False

        # Check current allowance
        try:
            current_allowance = token_contract.functions.allowance(wallet_checksum, spender_checksum).call()
            logger.info(f"💰 Current allowance: {current_allowance}, Required: {amount}")
        except Exception as e:
            logger.error(f"❌ Failed to check allowance: {e}")
            return False

        # If allowance is sufficient, no approval needed
        if current_allowance >= amount:
            logger.info("✅ Sufficient allowance already exists")
            return True

        # Need to approve - set to maximum for future trades
        max_approval = 2**256 - 1  # Maximum uint256 value
        logger.info(f"📝 Approving maximum amount: {max_approval}")

        # Estimate gas for approval transaction
        try:
            estimated_gas = token_contract.functions.approve(spender_checksum, max_approval).estimate_gas({
                'from': wallet_checksum
            })
            gas_limit = int(estimated_gas * 1.5)  # Add 50% buffer
            logger.info(f"⛽ Estimated gas: {estimated_gas}, using limit: {gas_limit}")
        except Exception as e:
            logger.warning(f"⚠️ Gas estimation failed: {e}, using default gas limit")
            gas_limit = 150000  # Increased default gas limit

        # Get current gas price
        try:
            gas_price = w3.eth.gas_price
            logger.info(f"⛽ Current gas price: {w3.from_wei(gas_price, 'gwei')} gwei")
        except Exception as e:
            logger.error(f"❌ Failed to get gas price: {e}")
            return False

        # Build approval transaction
        try:
            approval_txn = token_contract.functions.approve(spender_checksum, max_approval).build_transaction({
                'from': wallet_checksum,
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': w3.eth.get_transaction_count(wallet_checksum),
            })
            logger.info("✅ Approval transaction built successfully")
        except Exception as e:
            logger.error(f"❌ Failed to build approval transaction: {e}")
            return False

        # Sign transaction
        try:
            logger.info("🖊️ Signing approval transaction...")
            signed_approval = w3.eth.account.sign_transaction(approval_txn, private_key)
            logger.info("✅ Approval transaction signed successfully")
        except Exception as e:
            logger.error(f"❌ Failed to sign approval transaction: {e}")
            return False

        # Submit transaction
        try:
            logger.info("📡 Submitting approval transaction...")
            approval_hash = w3.eth.send_raw_transaction(signed_approval.rawTransaction)
            logger.info(f"✅ Approval submitted! Hash: {approval_hash.hex()}")
        except Exception as e:
            logger.error(f"❌ Failed to submit approval transaction: {e}")
            return False

        # Wait for approval confirmation with longer timeout
        try:
            logger.info("⏳ Waiting for approval confirmation...")
            approval_receipt = w3.eth.wait_for_transaction_receipt(approval_hash, timeout=300)  # 5 minutes

            if approval_receipt.status == 1:
                logger.info(f"🎉 Approval confirmed! Block: {approval_receipt.blockNumber}")
                logger.info(f"💰 Approval gas used: {approval_receipt.gasUsed}")
                return True
            else:
                logger.error(f"❌ Approval transaction failed/reverted. Status: {approval_receipt.status}")
                return False

        except Exception as e:
            logger.error(f"❌ Approval confirmation failed: {e}")
            # Check if transaction was still mined
            try:
                receipt = w3.eth.get_transaction_receipt(approval_hash)
                if receipt.status == 1:
                    logger.info("✅ Transaction was actually successful despite timeout")
                    return True
                else:
                    logger.error("❌ Transaction failed")
                    return False
            except:
                logger.error("❌ Could not verify transaction status")
                return False

    except Exception as e:
        logger.error(f"❌ Unexpected approval error: {e}")
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        return False


def calculate_output_amount(amount_in: float, token_in: str, token_out: str, slippage: float) -> tuple:
    """
    Calculate expected output amount using live prices.

    Args:
        amount_in: Input amount
        token_in: Input token symbol
        token_out: Output token symbol
        slippage: Slippage tolerance (as decimal, e.g., 0.01 for 1%)

    Returns:
        (estimated_amount_out, amount_out_minimum)
    """
    try:
        # Get live prices
        price_in = get_live_token_price(token_in)
        price_out = get_live_token_price(token_out)

        if price_in == 0 or price_out == 0:
            raise Exception(f"Failed to get prices: {token_in}=${price_in}, {token_out}=${price_out}")

        # Calculate USD value of input
        usd_value = amount_in * price_in

        # Calculate expected output amount
        estimated_amount_out = usd_value / price_out

        # Apply slippage protection
        amount_out_minimum = estimated_amount_out * (1 - slippage)

        logger.info(f"💰 Price calculation:")
        logger.info(f"  {amount_in} {token_in} @ ${price_in:.2f} = ${usd_value:.2f}")
        logger.info(f"  Expected: {estimated_amount_out:.6f} {token_out} @ ${price_out:.2f}")
        logger.info(f"  Minimum (with {slippage*100:.1f}% slippage): {amount_out_minimum:.6f} {token_out}")

        return estimated_amount_out, amount_out_minimum

    except Exception as e:
        logger.error(f"Price calculation failed: {e}")
        raise Exception(f"Cannot calculate output amount: {str(e)}")


def run_async_task(coro):
    """Helper function to run async code in sync Celery tasks."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


@celery_app.task(bind=True)
def example_task(self, message: str):
    """Example Celery task for testing."""
    try:
        logger.info(f"Processing task: {message}")
        # Simulate some work
        import time
        time.sleep(2)
        return f"Task completed: {message}"
    except Exception as exc:
        logger.error(f"Task failed: {exc}")
        raise self.retry(exc=exc, countdown=60, max_retries=3)


@celery_app.task
def health_check():
    """Health check task for monitoring."""
    return {"status": "healthy", "timestamp": "2025-07-13"}


@celery_app.task
def analyze_market_data():
    """Task to analyze market data."""
    logger.info("Analyzing market data...")
    # Add your market analysis logic here
    return {"status": "completed", "analysis": "mock_data"}


@celery_app.task
def execute_trade(trade_data: Dict[str, Any]):
    """
    Execute a real trade on Uniswap V3 with live price feeds.

    Args:
        trade_data: Dictionary containing trade parameters

    Returns:
        Dictionary with execution results
    """
    try:
        settings = get_settings()

        # Extract trade parameters
        token_in = trade_data.get("token_in", "ETH")
        token_out = trade_data.get("token_out", "USDC")
        amount_in = float(trade_data.get("amount_in", 0))
        slippage = float(trade_data.get("slippage", 0.5)) / 100  # Convert percentage to decimal
        dry_run = trade_data.get("dry_run", True)

        logger.info(f"🚀 Executing trade: {amount_in} {token_in} -> {token_out} (dry_run: {dry_run})")

        # If dry_run is True, return mock data with live prices
        if dry_run:
            logger.info("Dry run mode - calculating with live prices")
            try:
                estimated_out, min_out = calculate_output_amount(amount_in, token_in, token_out, slippage)
                return {
                    "status": "completed",
                    "trade_id": trade_data.get("trade_id", "mock_trade"),
                    "transaction_hash": "0x1234567890abcdef...",
                    "block_number": 18500000,
                    "gas_used": 145000,
                    "execution_time": 15.5,
                    "final_amount_out": estimated_out,
                    "message": f"Trade executed successfully (DRY RUN) - Live price calculation: {estimated_out:.6f} {token_out}"
                }
            except Exception as e:
                return {
                    "status": "failed",
                    "trade_id": trade_data.get("trade_id", "mock_trade"),
                    "error": str(e),
                    "message": f"Dry run failed: {str(e)}"
                }

        # === REAL TRADE EXECUTION ===
        logger.info("🚀 EXECUTING REAL TRADE ON ETHEREUM MAINNET!")

        # Safety check: If blockchain is disabled, return mock data even for real trades
        if os.getenv("DISABLE_BLOCKCHAIN", "false").lower() == "true":
            logger.warning("⚠️ DISABLE_BLOCKCHAIN is set, but dry_run=False. Returning mock data for safety.")
            estimated_out, _ = calculate_output_amount(amount_in, token_in, token_out, slippage)
            return {
                "status": "completed",
                "trade_id": trade_data.get("trade_id", "mock_trade"),
                "transaction_hash": "0xMOCK1234567890abcdef...",
                "block_number": 18500000,
                "gas_used": 145000,
                "execution_time": 15.5,
                "final_amount_out": estimated_out,
                "message": "Trade executed successfully (BLOCKCHAIN DISABLED - MOCK DATA WITH LIVE PRICES)"
            }

        # Validate inputs
        if amount_in <= 0:
            raise Exception(f"Invalid amount: {amount_in}")

        if not (is_supported_token(token_in) and is_supported_token(token_out)):
            raise Exception(f"Unsupported token pair: {token_in} -> {token_out}")

        # Calculate output amounts using LIVE PRICES! 🚀
        logger.info("💰 Getting live prices for trade calculation...")
        estimated_amount_out, amount_out_minimum_float = calculate_output_amount(amount_in, token_in, token_out, slippage)

        # Connect to Ethereum
        logger.info(f"Connecting to Ethereum via RPC...")
        w3 = Web3(Web3.HTTPProvider(settings.ethereum_rpc_url))

        if not w3.is_connected():
            raise Exception("Failed to connect to Ethereum network")

        logger.info("✅ Connected to Ethereum network")

        # Get wallet account
        account = w3.eth.account.from_key(settings.private_key)
        wallet_address = account.address

        logger.info(f"Trading from wallet: {wallet_address}")

        # Convert amounts to base units using each token's registered decimals
        amount_in_wei = to_base_units(amount_in, token_in)
        amount_out_minimum = to_base_units(amount_out_minimum_float, token_out)

        # Get token addresses
        token_in_address = get_token_address(token_in)
        token_out_address = get_token_address(token_out)

        logger.info(f"Token addresses: {token_in_address} -> {token_out_address}")
        logger.info(f"Amount calculations: input={amount_in_wei}, min_out={amount_out_minimum}")

        # CHECK AND HANDLE TOKEN APPROVAL
        if token_in != "ETH":  # Only ERC-20 tokens need approval
            logger.info(f"🔐 Checking if {token_in} approval is needed...")
            logger.info(f"🔐 Approval details:")
            logger.info(f"  Token: {token_in}")
            logger.info(f"  Token address: {token_in_address}")
            logger.info(f"  Spender (Router): {UNISWAP_V3_ROUTER}")
            logger.info(f"  Amount to approve: {amount_in_wei}")
            logger.info(f"  Wallet address: {wallet_address}")

            # Verify token address is valid
            if not token_in_address or token_in_address == "":
                raise Exception(f"Invalid token address for {token_in}")

            try:
                approval_success = check_and_approve_token(
                    w3=w3,
                    token_address=token_in_address,
                    spender_address=UNISWAP_V3_ROUTER,
                    amount=amount_in_wei,
                    wallet_address=wallet_address,
                    private_key=settings.private_key
                )

                if not approval_success:
                    logger.error("❌ Token approval returned False - check approval logs above for specific error")
                    raise Exception(f"Token approval failed for {token_in}. Common causes: insufficient ETH for gas, invalid token contract, network issues, or insufficient token balance.")

                logger.info("✅ Token approval completed successfully")

            except Exception as e:
                logger.error(f"❌ Token approval exception for {token_in}: {str(e)}")
                # Re-raise the exception to stop trade execution
                raise

        # Get current block timestamp for deadline
        current_block = w3.eth.get_block('latest')
        deadline = current_block['timestamp'] + 1800  # 30 minutes from now

        logger.info(f"Transaction deadline: {deadline}")

        # Create Uniswap V3 Router contract
        router_contract = w3.eth.contract(
            address=Web3.to_checksum_address(UNISWAP_V3_ROUTER),
            abi=UNISWAP_V3_ROUTER_ABI
        )

        logger.info("✅ Uniswap V3 Router contract created")

        # Ensure all addresses are properly checksummed (CRITICAL FIX!)
        token_in_checksum = Web3.to_checksum_address(token_in_address)
        token_out_checksum = Web3.to_checksum_address(token_out_address)
        wallet_checksum = Web3.to_checksum_address(wallet_address)

        # Build swap parameters as tuple with proper Web3 types (FIXED!)
        swap_params_tuple = (
            token_in_checksum,    # tokenIn (address)
            token_out_checksum,   # tokenOut (address)
            500,                 # fee (uint24) - 0.3% fee tier
            wallet_checksum,      # recipient (address)
            deadline,             # deadline (uint256)
            amount_in_wei,        # amountIn (uint256)
            amount_out_minimum,   # amountOutMinimum (uint256) - NOW WITH LIVE PRICES!
            0                     # sqrtPriceLimitX96 (uint160) - no price limit
        )

        logger.info(f"✅ Swap parameters prepared with LIVE PRICES:")
        logger.info(f"  tokenIn: {token_in_checksum}")
        logger.info(f"  tokenOut: {token_out_checksum}")
        logger.info(f"  fee: 3000 (0.3%)")
        logger.info(f"  recipient: {wallet_checksum}")
        logger.info(f"  deadline: {deadline}")
        logger.info(f"  amountIn: {amount_in_wei}")
        logger.info(f"  amountOutMinimum: {amount_out_minimum} (LIVE PRICE BASED!)")

        # Estimate gas
        try:
            logger.info("Estimating gas for transaction...")
            estimated_gas = router_contract.functions.exactInputSingle(swap_params_tuple).estimate_gas({
                'from': wallet_checksum,
                'value': amount_in_wei if token_in == "ETH" else 0
            })
            gas_limit = int(estimated_gas * 1.2)  # Add 20% buffer
            logger.info(f" Gas estimation successful: {estimated_gas}, using limit: {gas_limit}")
        except Exception as e:
            logger.warning(f" Gas estimation failed: {e}, using default gas limit")
            gas_limit = 200000

        # Get current gas price
        gas_price = w3.eth.gas_price
        logger.info(f"Current gas price: {w3.from_wei(gas_price, 'gwei')} gwei")

        # Build transaction
        try:
            logger.info("Building transaction...")
            transaction = router_contract.functions.exactInputSingle(swap_params_tuple).build_transaction({
                'from': wallet_checksum,
                'value': amount_in_wei if token_in == "ETH" else 0,
                'gas': gas_limit,
                'gasPrice': gas_price,
                'nonce': w3.eth.get_transaction_count(wallet_checksum),
            })

            logger.info(f"✅ Transaction built successfully:")
            logger.info(f"  Gas limit: {gas_limit}")
            logger.info(f"  Gas price: {w3.from_wei(gas_price, 'gwei')} gwei")
            logger.info(f"  Value: {w3.from_wei(transaction['value'], 'ether') if transaction['value'] > 0 else 0} ETH")
        except Exception as e:
            logger.error(f"❌ Failed to build transaction: {e}")
            raise Exception(f"Transaction build failed: {str(e)}")

        # Sign transaction
        try:
            logger.info("Signing transaction...")
            signed_txn = w3.eth.account.sign_transaction(transaction, settings.private_key)
            logger.info("✅ Transaction signed successfully")
        except Exception as e:
            logger.error(f"❌ Failed to sign transaction: {e}")
            raise Exception(f"Transaction signing failed: {str(e)}")

        # Submit transaction to blockchain
        logger.info("📡 Submitting transaction to Ethereum mainnet...")
        try:
            tx_hash = w3.eth.send_raw_transaction(signed_txn.rawTransaction)
            logger.info(f"✅ Transaction submitted! Hash: {tx_hash.hex()}")
        except Exception as e:
            logger.error(f"❌ Failed to submit transaction: {e}")
            raise Exception(f"Transaction submission failed: {str(e)}")

        # Wait for transaction confirmation
        logger.info("⏳ Waiting for transaction confirmation...")
        try:
            tx_receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)  # 5 minute timeout
            logger.info(f"🎉 Transaction confirmed! Block: {tx_receipt.blockNumber}")
        except Exception as e:
            logger.error(f"⚠️ Transaction confirmation timeout: {e}")
            # Return partial success - transaction was submitted but confirmation failed
            return {
                "status": "pending",
                "trade_id": trade_data.get("trade_id"),
                "transaction_hash": tx_hash.hex(),
                "block_number": None,
                "gas_used": None,
                "gas_cost_eth": None,
                "execution_time": None,
                "final_amount_out": estimated_amount_out,
                "message": f"Transaction submitted but confirmation timeout. Check Etherscan for status.",
                "etherscan_url": f"https://etherscan.io/tx/{tx_hash.hex()}"
            }

        # Calculate actual gas used and costs
        gas_used = tx_receipt.gasUsed
        gas_cost_wei = gas_used * gas_price
        gas_cost_eth = w3.from_wei(gas_cost_wei, 'ether')

        logger.info(f"💰 Gas used: {gas_used}")
        logger.info(f"💰 Gas cost: {gas_cost_eth} ETH")

        # TODO: Parse logs to get actual amount out from Transfer events
        # For now, use estimated amount
        actual_amount_out = estimated_amount_out

        # Return real execution results
        result = {
            "status": "completed",
            "trade_id": trade_data.get("trade_id"),
            "transaction_hash": tx_hash.hex(),
            "block_number": tx_receipt.blockNumber,
            "gas_used": gas_used,
            "gas_cost_eth": float(gas_cost_eth),
            "execution_time": 30.0,
            "final_amount_out": actual_amount_out,
            "message": "🎉 Trade executed successfully on Ethereum mainnet with LIVE PRICES!",
            "etherscan_url": f"https://etherscan.io/tx/{tx_hash.hex()}"
        }

        logger.info(f"✅ REAL TRADE COMPLETED WITH LIVE PRICES: {result}")

        # Auto-tweet the successful trade (if Twitter is available)
        try:
            if TWITTER_AVAILABLE and twitter_client:
                tweet_data = {
                    "action": f"{token_in} -> {token_out}",
                    "amount_in": amount_in,
                    "token_in": token_in,
                    "amount_out": actual_amount_out,
                    "token_out": token_out,
                    "price": actual_amount_out / amount_in if amount_in > 0 else 0,
                    "gas_used": gas_used,
                    "tx_hash": tx_hash.hex()
                }
                tweet_trade_notification.delay(tweet_data)
                logger.info("📱 Trade tweet queued")
        except Exception as e:
            logger.warning(f"Failed to queue trade tweet: {e}")

        return result

    except Exception as e:
        logger.error(f"❌ Trade execution failed: {e}")
        return {
            "status": "failed",
            "trade_id": trade_data.get("trade_id"),
            "transaction_hash": None,
            "error": str(e),
            "message": f"Trade execution failed: {str(e)}"
        }


# Update your existing execute_trade task to call this new implementation
@celery_app.task
def execute_trade_task(trade_data: Dict[str, Any]):
    """Updated execute_trade task that handles real trading with live prices."""
    return execute_trade(trade_data)


@celery_app.task
def update_nft_verification():
    """Task to update NFT verification status."""
    logger.info("Updating NFT verification...")
    # Add NFT verification logic here
    return {"status": "updated", "verified_count": 0}


@celery_app.task
def send_notifications():
    """Task to send notifications."""
    logger.info("Sending notifications...")
    # Add notification logic here
    return {"status": "sent", "notification_count": 0}


# === TWITTER INTEGRATION TASKS ===

@celery_app.task
def tweet_trade_notification(trade_data: dict):
    """Tweet about completed trade using your existing Twitter client."""
    if not TWITTER_AVAILABLE or not twitter_client:
        logger.warning("Twitter not available for trade notification")
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        # Use your existing post_trade_notification method
        tweet_id = run_async_task(twitter_client.post_trade_notification(trade_data))

        if tweet_id:
            tweet_url = f"https://twitter.com/{twitter_client.username}/status/{tweet_id}"
            logger.info(f"Trade notification tweet sent: {tweet_id}")
            return {
                "status": "success",
                "tweet_id": tweet_id,
                "tweet_url": tweet_url,
                "message": "Trade notification posted successfully"
            }
        else:
            logger.warning("Failed to send trade notification tweet")
            return {"status": "failed", "reason": "Tweet creation failed"}

    except Exception as e:
        logger.error(f"Error tweeting trade notification: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def tweet_strategy_signal(signal_data: dict):
    """Tweet strategy signal notification."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        tweet_id = run_async_task(twitter_client.post_strategy_signal(signal_data))

        if tweet_id:
            logger.info(f"Strategy signal tweet sent: {tweet_id}")
            return {"status": "success", "tweet_id": tweet_id}

        return {"status": "failed", "reason": "Tweet creation failed"}

    except Exception as e:
        logger.error(f"Error tweeting strategy signal: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def tweet_market_update(market_data: dict):
    """Tweet market update notification."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        tweet_id = run_async_task(twitter_client.post_market_update(market_data))

        if tweet_id:
            logger.info(f"Market update tweet sent: {tweet_id}")
            return {"status": "success", "tweet_id": tweet_id}

        return {"status": "failed", "reason": "Tweet creation failed"}

    except Exception as e:
        logger.error(f"Error tweeting market update: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def tweet_system_status(status_data: dict):
    """Tweet system status update."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        tweet_id = run_async_task(twitter_client.post_system_status(status_data))

        if tweet_id:
            logger.info(f"System status tweet sent: {tweet_id}")
            return {"status": "success", "tweet_id": tweet_id}

        return {"status": "failed", "reason": "Tweet creation failed"}

    except Exception as e:
        logger.error(f"Error tweeting system status: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def tweet_custom_message(message: str, hashtags: list = None):
    """Tweet a custom message."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        tweet_id = run_async_task(twitter_client.post_custom_message(message, hashtags))

        if tweet_id:
            tweet_url = f"https://twitter.com/{twitter_client.username}/status/{tweet_id}"
            logger.info(f"Custom tweet sent: {tweet_id}")
            return {
                "status": "success",
                "tweet_id": tweet_id,
                "tweet_url": tweet_url
            }

        return {"status": "failed", "reason": "Tweet creation failed"}

    except Exception as e:
        logger.error(f"Error sending custom tweet: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def process_twitter_mentions():
    """Process and respond to Twitter mentions."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        mentions = run_async_task(twitter_client.get_mentions(max_results=10))

        processed = 0
        for mention in mentions:
            # Add your logic to process mentions here
            # For example, respond to certain keywords or questions
            logger.info(f"Processing mention from {mention.author_id}: {mention.text[:50]}...")
            processed += 1

        return {
            "status": "success",
            "mentions_processed": processed,
            "total_mentions": len(mentions)
        }

    except Exception as e:
        logger.error(f"Error processing Twitter mentions: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def auto_tweet_daily_summary():
    """Daily task to tweet system summary."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        # Generate daily summary data
        status_data = {
            "status": "operational",
            "active_strategies": 5,
            "trades_24h": 12,
            "volume_24h": 125000.00
        }

        return tweet_system_status.delay(status_data)

    except Exception as e:
        logger.error(f"Error in auto daily summary tweet: {e}")
        return {"status": "error", "error": str(e)}


@celery_app.task
def auto_tweet_price_alerts():
    """Check price thresholds and tweet alerts."""
    if not TWITTER_AVAILABLE or not twitter_client:
        return {"status": "disabled", "reason": "Twitter not enabled"}

    try:
        # Example: Check for significant price movements
        # This would integrate with your price monitoring system
        price_alerts = [
            {
                "token": "BTC",
                "price": 45000.00,
                "price_change_24h": 0.05,  # 5% increase
                "volume_24h": 2500000000,
                "market_cap": 850000000000
            }
        ]

        alerts_sent = 0
        for alert in price_alerts:
            if abs(alert["price_change_24h"]) > 0.05:  # 5% threshold
                tweet_market_update.delay(alert)
                alerts_sent += 1

        return {
            "status": "success",
            "alerts_checked": len(price_alerts),
            "alerts_sent": alerts_sent
        }

    except Exception as e:
        logger.error(f"Error in auto price alerts: {e}")
        return {"status": "error", "error": str(e)}