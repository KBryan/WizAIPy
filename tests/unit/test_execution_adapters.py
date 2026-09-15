"""
Tests for wiring exchange adapters into the trade execution engine.
"""

import pytest
from unittest.mock import Mock, patch
from web3 import Web3

from core.execution.engine import TradeExecutionEngine
import asyncio

import core.execution.adapters as adapters_module
from core.execution.adapters import register_default_adapters, ensure_adapters
from integrations.uniswap import (
    UniswapV2Adapter,
    UniswapV3Adapter,
    UniswapError,
    create_uniswap_adapter,
)


def _fake_web3(mock_web3, v2_out=1600_000_000, v3_out=1610_000_000):
    """Fake the Web3 constructor; one mock contract answers both V2 router and V3 quoter."""
    w3 = Mock()
    w3.is_connected.return_value = True
    contract = Mock()
    contract.functions.getAmountsOut.return_value.call.return_value = [10**18, v2_out]
    contract.functions.quoteExactInputSingle.return_value.call.return_value = v3_out
    w3.eth.contract.return_value = contract
    mock_web3.return_value = w3
    return contract


class TestRegisterDefaultAdapters:
    @pytest.mark.unit
    @patch("integrations.uniswap.Web3", wraps=Web3)
    def test_registers_every_implemented_exchange(self, mock_web3):
        _fake_web3(mock_web3)
        engine = TradeExecutionEngine()

        registered = register_default_adapters(engine, "ethereum")

        assert set(registered) == {"uniswap_v2", "uniswap_v3"}
        assert set(engine.adapters) == {"uniswap_v2", "uniswap_v3"}
        assert isinstance(engine.adapters["uniswap_v2"], UniswapV2Adapter)
        assert isinstance(engine.adapters["uniswap_v3"], UniswapV3Adapter)
        # sushiswap is in SUPPORTED_EXCHANGES but has no adapter implementation
        assert "sushiswap" not in engine.adapters

    @pytest.mark.unit
    @patch("integrations.uniswap.Web3", wraps=Web3)
    def test_unreachable_node_skips_only_that_adapter(self, mock_web3):
        _fake_web3(mock_web3)
        engine = TradeExecutionEngine()

        def flaky(version, network):
            if version == "v3":
                raise UniswapError("Failed to connect to ethereum network")
            return create_uniswap_adapter(version, network)

        with patch("integrations.uniswap.create_uniswap_adapter", side_effect=flaky):
            registered = register_default_adapters(engine, "ethereum")

        assert set(registered) == {"uniswap_v2"}
        assert set(engine.adapters) == {"uniswap_v2"}

    @pytest.mark.unit
    def test_network_without_exchanges_registers_nothing(self):
        engine = TradeExecutionEngine()
        assert register_default_adapters(engine, "beam") == {}
        assert engine.adapters == {}

    @pytest.mark.unit
    @patch("integrations.uniswap.Web3", wraps=Web3)
    async def test_engine_picks_best_quote_across_adapters(self, mock_web3):
        """End to end: engine -> both adapters -> mocked contracts -> best net output wins."""
        _fake_web3(mock_web3, v2_out=1600_000_000, v3_out=1610_000_000)
        engine = TradeExecutionEngine()
        register_default_adapters(engine, "ethereum")

        best = await engine.get_best_quote("ETH", "USDC", 1.0)

        assert best is not None
        assert best.exchange == "uniswap_v3"
        assert best.amount_out == 1610.0
        # V3 net of its 0.05% tier beats V2 net of 0.3%
        assert best.amount_out - best.fees > 1600.0 - 1.0 * 0.003


class TestAppStartup:
    @pytest.mark.unit
    def test_lifespan_registers_adapters_on_engine(self):
        from fastapi.testclient import TestClient
        from api.main import app, trade_engine

        with patch("api.main.register_default_adapters") as register:
            with TestClient(app):
                pass

        register.assert_called_once_with(trade_engine)


class TestEnsureAdapters:
    """Lazy re-registration when the engine has no adapters for a network."""

    @pytest.fixture(autouse=True)
    def reset_cooldown(self):
        adapters_module._last_attempt.clear()
        yield
        adapters_module._last_attempt.clear()

    @staticmethod
    def _engine_with(*exchanges):
        engine = TradeExecutionEngine()
        for name in exchanges:
            adapter = Mock()
            adapter.network = "ethereum"
            engine.adapters[name] = adapter
        return engine

    @pytest.mark.unit
    async def test_returns_registered_without_retrying(self):
        engine = self._engine_with("uniswap_v2", "uniswap_v3")
        with patch.object(adapters_module, "register_default_adapters") as register:
            assert await ensure_adapters(engine) == ["uniswap_v2", "uniswap_v3"]
        register.assert_not_called()

    @pytest.mark.unit
    async def test_retries_registration_when_empty(self):
        engine = TradeExecutionEngine()

        def register(eng, network):
            adapter = Mock()
            adapter.network = network
            eng.register_adapter("uniswap_v2", adapter)
            return {"uniswap_v2": adapter}

        with patch.object(adapters_module, "register_default_adapters", side_effect=register) as mock_register:
            assert await ensure_adapters(engine) == ["uniswap_v2"]
        mock_register.assert_called_once_with(engine, "ethereum")

    @pytest.mark.unit
    async def test_failed_retry_respects_cooldown(self):
        engine = TradeExecutionEngine()
        with patch.object(adapters_module, "register_default_adapters", return_value={}) as register:
            assert await ensure_adapters(engine, cooldown=60) == []
            assert await ensure_adapters(engine, cooldown=60) == []  # within cooldown: no second dial
            assert register.call_count == 1

            adapters_module._last_attempt["ethereum"] -= 61  # cooldown elapsed
            assert await ensure_adapters(engine, cooldown=60) == []
            assert register.call_count == 2

    @pytest.mark.unit
    async def test_startup_attempt_starts_the_cooldown(self):
        """register_default_adapters itself stamps the attempt, so a request right
        after a failed startup does not immediately re-dial the node."""
        engine = TradeExecutionEngine()
        with patch.object(adapters_module, "_adapter_factories", return_value={}):
            register_default_adapters(engine, "ethereum")  # startup: nothing registered
        with patch.object(adapters_module, "register_default_adapters") as register:
            assert await ensure_adapters(engine, cooldown=60) == []
        register.assert_not_called()

    @pytest.mark.unit
    async def test_concurrent_callers_share_one_attempt(self):
        engine = TradeExecutionEngine()
        calls = 0

        def slow_register(eng, network):
            nonlocal calls
            calls += 1
            import time
            time.sleep(0.05)  # runs in a worker thread via asyncio.to_thread
            adapter = Mock()
            adapter.network = network
            eng.register_adapter("uniswap_v3", adapter)
            return {"uniswap_v3": adapter}

        with patch.object(adapters_module, "register_default_adapters", side_effect=slow_register):
            results = await asyncio.gather(*(ensure_adapters(engine) for _ in range(5)))

        assert calls == 1
        assert all(r == ["uniswap_v3"] for r in results)
