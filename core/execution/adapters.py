"""
Wires exchange adapters into the trade execution engine.

Kept separate from engine.py because integrations.uniswap imports
ExchangeAdapter from the engine; importing the adapters back into engine.py
would be circular.
"""

import logging
from typing import Callable, Dict

from config import SUPPORTED_EXCHANGES
from core.execution.engine import ExchangeAdapter, TradeExecutionEngine

logger = logging.getLogger(__name__)


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

    logger.info(
        f"Registered {len(registered)} exchange adapter(s) on {network}: {sorted(registered) or 'none'}"
    )
    return registered
