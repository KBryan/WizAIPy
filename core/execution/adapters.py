"""
Wires exchange adapters into the trade execution engine.

Kept separate from engine.py because integrations.uniswap imports
ExchangeAdapter from the engine; importing the adapters back into engine.py
would be circular.
"""

import asyncio
import logging
import time
from typing import Callable, Dict, List

from config import SUPPORTED_EXCHANGES
from core.execution.engine import ExchangeAdapter, TradeExecutionEngine

logger = logging.getLogger(__name__)

# Minimum interval between registration attempts for a network that has no
# adapters, so a dead RPC node is not re-dialled on every request.
RETRY_COOLDOWN_SECONDS = 30.0

_retry_lock = asyncio.Lock()
_last_attempt: Dict[str, float] = {}  # network -> time.monotonic() of last attempt


def _adapter_factories() -> Dict[str, Callable[[str], ExchangeAdapter]]:
    """Exchange name (as in config.SUPPORTED_EXCHANGES) -> adapter constructor."""
    # Imported here rather than at module level to avoid an import cycle.
    from integrations.uniswap import create_uniswap_adapter

    return {
        "uniswap_v2": lambda network: create_uniswap_adapter("v2", network),
        "uniswap_v3": lambda network: create_uniswap_adapter("v3", network),
        # "sushiswap": no adapter implemented yet
    }


def register_default_adapters(
    engine: TradeExecutionEngine, network: str = "ethereum"
) -> Dict[str, ExchangeAdapter]:
    """
    Register an adapter on the engine for every supported exchange on a network.

    Adapter construction opens an RPC connection, so a node that is down or
    unconfigured makes that one adapter fail; it is logged and skipped rather
    than failing startup. Exchanges with no adapter implementation are skipped
    silently.

    Returns the adapters that were registered, keyed by exchange name.
    """
    factories = _adapter_factories()
    registered: Dict[str, ExchangeAdapter] = {}

    for exchange, meta in SUPPORTED_EXCHANGES.items():
        if network not in meta.get("networks", []):
            continue
        factory = factories.get(exchange)
        if factory is None:
            logger.debug(f"No adapter implemented for {exchange}; skipping")
            continue
        try:
            adapter = factory(network)
        except Exception as e:
            logger.warning(f"Could not initialise {exchange} adapter on {network}: {e}")
            continue
        engine.register_adapter(exchange, adapter)
        registered[exchange] = adapter

    _last_attempt[network] = time.monotonic()
    logger.info(
        f"Registered {len(registered)} exchange adapter(s) on {network}: {sorted(registered) or 'none'}"
    )
    return registered


def registered_exchanges(
    engine: TradeExecutionEngine, network: str = "ethereum"
) -> List[str]:
    """Names of the adapters registered on the engine for a network, sorted."""
    return sorted(
        name for name, adapter in engine.adapters.items() if adapter.network == network
    )


async def ensure_adapters(
    engine: TradeExecutionEngine,
    network: str = "ethereum",
    cooldown: float = RETRY_COOLDOWN_SECONDS,
) -> List[str]:
    """
    Return the exchanges registered for a network, retrying registration if none are.

    Startup registration fails silently when the RPC node is unreachable; this
    lets the first request after the node comes back recover without a restart.
    Attempts are serialised so concurrent callers do not each dial the node,
    and rate-limited to one per `cooldown` seconds per network.
    """
    available = registered_exchanges(engine, network)
    if available:
        return available

    async with _retry_lock:
        # Another request may have registered while we waited for the lock.
        available = registered_exchanges(engine, network)
        if available:
            return available

        last = _last_attempt.get(network)
        if last is not None and time.monotonic() - last < cooldown:
            return []

        # Stamp before dialling so a failure part-way still starts the cooldown.
        _last_attempt[network] = time.monotonic()
        logger.info(f"No exchange adapters on {network}; retrying registration")
        await asyncio.to_thread(register_default_adapters, engine, network)
        return registered_exchanges(engine, network)
