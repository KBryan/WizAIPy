"""
Token registry for the NFT-Gated AI Trading Bot.

Single source of truth for token contract addresses and decimals, keyed by
network. Every other module (Uniswap adapters, Celery trade tasks, portfolio
endpoints) must resolve tokens through this registry rather than carrying its
own table — three divergent copies is how placeholder addresses ended up in
production code.

Addresses are validated with EIP-55 at import time, so a typo or placeholder
fails fast on startup instead of at swap time.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Union

from core.contracts import checksummed

# Sentinel address used for the chain's native asset (ETH on Ethereum).
NATIVE_TOKEN_ADDRESS = "0x0000000000000000000000000000000000000000"


class UnknownTokenError(KeyError):
    """Raised when a symbol is not registered for the requested network."""


@dataclass(frozen=True)
class TokenInfo:
    symbol: str
    address: str
    decimals: int

    @property
    def is_native(self) -> bool:
        return self.address == NATIVE_TOKEN_ADDRESS


def _token(symbol: str, address: str, decimals: int) -> TokenInfo:
    if address != NATIVE_TOKEN_ADDRESS:
        checksummed(symbol, address)
    return TokenInfo(symbol, address, decimals)


# network -> symbol -> TokenInfo. Symbols are upper-case.
TOKENS: Dict[str, Dict[str, TokenInfo]] = {
    "ethereum": {
        "ETH": _token("ETH", NATIVE_TOKEN_ADDRESS, 18),
        "WETH": _token("WETH", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", 18),
        "USDC": _token("USDC", "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", 6),
        "USDT": _token("USDT", "0xdAC17F958D2ee523a2206206994597C13D831ec7", 6),
        "DAI": _token("DAI", "0x6B175474E89094C44Da98b954EedeAC495271d0F", 18),
        "WBTC": _token("WBTC", "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", 8),
        "SKL": _token("SKL", "0x00c83aeCC790e8a4453e5dD3B0B4b3680501a7A7", 18),
    },
    # "skale" and "beam" are listed in config.SUPPORTED_NETWORKS but have no
    # token registry yet; resolving a token on them raises UnknownTokenError
    # rather than silently using Ethereum mainnet addresses.
}


def get_token(symbol: str, network: str = "ethereum") -> TokenInfo:
    """Look up a token by symbol (case-insensitive) on a network."""
    try:
        return TOKENS[network][symbol.upper()]
    except KeyError:
        raise UnknownTokenError(f"Unknown token {symbol!r} on network {network!r}") from None


def get_token_address(symbol: str, network: str = "ethereum") -> str:
    """Checksummed contract address for a token symbol."""
    return get_token(symbol, network).address


def get_token_decimals(symbol: str, network: str = "ethereum") -> int:
    return get_token(symbol, network).decimals


def token_addresses(network: str = "ethereum") -> Dict[str, str]:
    """Plain symbol -> address mapping for a network."""
    if network not in TOKENS:
        raise UnknownTokenError(f"No token registry for network {network!r}")
    return {symbol: info.address for symbol, info in TOKENS[network].items()}


def is_supported_token(symbol: str, network: str = "ethereum") -> bool:
    return symbol.upper() in TOKENS.get(network, {})


def to_base_units(amount: Union[float, str, Decimal], symbol: str, network: str = "ethereum") -> int:
    """
    Convert a human amount (e.g. 1.5 USDC) to integer base units (wei-equivalent).

    Goes through Decimal(str(amount)) so that float noise does not leak into the
    integer: int(1.1 * 10**18) is 1100000000000000128, this returns exactly
    1100000000000000000 (matching Web3.to_wei).
    """
    scaled = Decimal(str(amount)) * (10 ** get_token_decimals(symbol, network))
    return int(scaled)


def from_base_units(amount: int, symbol: str, network: str = "ethereum") -> float:
    """Convert integer base units back to a human amount."""
    return float(Decimal(amount) / (10 ** get_token_decimals(symbol, network)))
