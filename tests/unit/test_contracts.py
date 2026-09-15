"""
Unit tests for the shared protocol contract registry.
"""

import pytest
from eth_utils import is_checksum_address

from core.contracts import UNISWAP, UnknownContractError, checksummed, get_uniswap


class TestContractRegistry:
    @pytest.mark.unit
    def test_all_addresses_are_checksummed(self):
        for network, versions in UNISWAP.items():
            for version, deployment in versions.items():
                assert deployment.version == version
                assert is_checksum_address(
                    deployment.router
                ), f"{network}/{version} router"
                assert is_checksum_address(
                    deployment.factory
                ), f"{network}/{version} factory"

    @pytest.mark.unit
    def test_canonical_mainnet_deployments(self):
        v2 = get_uniswap("v2")
        v3 = get_uniswap("V3")  # case-insensitive
        assert v2.router == "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
        assert v2.factory == "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
        assert v3.router == "0xE592427A0AEce92De3Edee1F18E0157C05861564"
        assert v3.factory == "0x1F98431c8aD98523631AE4a59f267346ea31F984"

    @pytest.mark.unit
    def test_unknown_version_and_network_raise(self):
        with pytest.raises(UnknownContractError):
            get_uniswap("v4")
        with pytest.raises(UnknownContractError):
            get_uniswap("v3", network="beam")

    @pytest.mark.unit
    def test_checksummed_rejects_placeholders(self):
        assert checksummed("ok", "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2")
        with pytest.raises(ValueError):
            checksummed("bad", "0xC02aaA39b223FE8C0625C6E8C11028C0C5B9B2dB")
        with pytest.raises(ValueError):
            checksummed("lowercase", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2")
