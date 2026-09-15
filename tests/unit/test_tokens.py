"""
Unit tests for the shared token registry.
"""

import pytest
from eth_utils import is_checksum_address

from core.tokens import (
    NATIVE_TOKEN_ADDRESS,
    TOKENS,
    UnknownTokenError,
    get_token,
    get_token_address,
    token_addresses,
    is_supported_token,
    to_base_units,
    from_base_units,
)


class TestTokenRegistry:
    """The registry is the single source of truth for token addresses."""

    @pytest.mark.unit
    def test_all_addresses_are_checksummed_or_native(self):
        for network, table in TOKENS.items():
            for symbol, info in table.items():
                assert info.symbol == symbol
                assert info.address == NATIVE_TOKEN_ADDRESS or is_checksum_address(
                    info.address
                ), f"{network}/{symbol}: {info.address}"

    @pytest.mark.unit
    def test_canonical_mainnet_contracts(self):
        assert get_token_address("WETH") == "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        assert get_token_address("USDC") == "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        assert get_token_address("USDT") == "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        assert get_token("USDC").decimals == 6
        assert get_token("USDT").decimals == 6
        assert get_token("WBTC").decimals == 8
        assert get_token("ETH").is_native

    @pytest.mark.unit
    def test_lookup_is_case_insensitive(self):
        assert get_token("usdc") is get_token("USDC")
        assert is_supported_token("weth")

    @pytest.mark.unit
    def test_unknown_token_and_network_raise(self):
        with pytest.raises(UnknownTokenError):
            get_token("NOPE")
        with pytest.raises(UnknownTokenError):
            get_token("USDC", network="beam")
        with pytest.raises(UnknownTokenError):
            token_addresses("skale")
        assert not is_supported_token("USDC", network="beam")

    @pytest.mark.unit
    def test_token_addresses_mapping(self):
        mapping = token_addresses("ethereum")
        assert mapping["ETH"] == NATIVE_TOKEN_ADDRESS
        assert set(mapping) == set(TOKENS["ethereum"])


class TestBaseUnits:
    """Amount conversions use each token's registered decimals, exactly."""

    @pytest.mark.unit
    def test_uses_token_decimals(self):
        assert to_base_units(1.5, "USDC") == 1_500_000
        assert to_base_units(1.5, "USDT") == 1_500_000
        assert to_base_units(1, "ETH") == 10**18
        assert to_base_units(0.5, "WBTC") == 50_000_000

    @pytest.mark.unit
    def test_no_float_noise(self):
        # int(1.1 * 10**18) == 1100000000000000128
        assert to_base_units(1.1, "ETH") == 1_100_000_000_000_000_000
        assert to_base_units("0.000001", "USDC") == 1

    @pytest.mark.unit
    def test_round_trip(self):
        assert from_base_units(1_500_000, "USDC") == 1.5
        assert from_base_units(to_base_units(2.25, "ETH"), "ETH") == 2.25
