"""
Protocol contract registry for the NFT-Gated AI Trading Bot.

Single source of truth for non-token contract addresses (Uniswap routers and
factories), keyed by network and protocol version. Companion to core.tokens,
which holds the token registry; both validate every address with EIP-55 at
import time so a typo or placeholder fails on startup, not at swap time.
"""

from dataclasses import dataclass
from typing import Dict

from eth_utils import is_checksum_address


class UnknownContractError(KeyError):
    """Raised when no deployment is registered for the requested protocol/network."""


def checksummed(label: str, address: str) -> str:
    """Return the address unchanged if it is EIP-55 checksummed, else raise."""
    if not is_checksum_address(address):
        raise ValueError(f"{label}: {address!r} is not a checksummed address")
    return address


@dataclass(frozen=True)
class UniswapDeployment:
    version: str
    router: str
    factory: str


def _uniswap(version: str, router: str, factory: str) -> UniswapDeployment:
    return UniswapDeployment(
        version,
        checksummed(f"uniswap {version} router", router),
        checksummed(f"uniswap {version} factory", factory),
    )


# network -> version -> deployment
UNISWAP: Dict[str, Dict[str, UniswapDeployment]] = {
    "ethereum": {
        "v2": _uniswap(
            "v2",
            router="0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
            factory="0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f",
        ),
        "v3": _uniswap(
            "v3",
            router="0xE592427A0AEce92De3Edee1F18E0157C05861564",
            factory="0x1F98431c8aD98523631AE4a59f267346ea31F984",
        ),
    },
    # skale / beam: no Uniswap deployments registered; see core.tokens for the
    # same caveat about those networks.
}


def get_uniswap(version: str, network: str = "ethereum") -> UniswapDeployment:
    """Look up the Uniswap deployment for a version ("v2"/"v3") on a network."""
    try:
        return UNISWAP[network][version.lower()]
    except KeyError:
        raise UnknownContractError(
            f"No Uniswap {version!r} deployment registered on {network!r}"
        ) from None
