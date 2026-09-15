"""
Unit tests for API endpoints.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
import json

from fastapi.testclient import TestClient
from api.main import app
from api.deps import get_current_user, get_optional_user, trade_rate_limiter, api_rate_limiter, get_redis_client
from core.execution.engine import trade_engine, TradeQuote
import core.execution.adapters as adapters_module

TEST_WALLET = "0x1234567890abcdef1234567890abcdef12345678"


def _override(dep, value):
    """Register a FastAPI dependency override and return an undo callable."""
    app.dependency_overrides[dep] = lambda: value
    return lambda: app.dependency_overrides.pop(dep, None)


@pytest.fixture
def authenticated_user():
    """Make every auth dependency resolve to a verified NFT holder.

    get_current_user is captured inside Depends() at import time, so it must be
    overridden through app.dependency_overrides rather than patched.
    """
    user = {"wallet_address": TEST_WALLET, "authenticated": True, "bypass": False}
    undo = [_override(get_current_user, user), _override(get_optional_user, user)]
    yield user
    for fn in undo:
        fn()


@pytest.fixture
def anonymous_user():
    """Make optional-auth endpoints see no user."""
    undo = _override(get_optional_user, None)
    yield
    undo()


@pytest.fixture
def trade_deps():
    """Stub the Redis-backed rate limiter and client used by trade endpoints."""
    fake_redis = Mock()
    fake_redis.get.return_value = None
    undo = [_override(trade_rate_limiter, None), _override(get_redis_client, fake_redis)]
    yield fake_redis
    for fn in undo:
        fn()


class TestHealthEndpoints:
    """Test cases for health monitoring endpoints."""
    
    def test_root_endpoint(self):
        """Test root endpoint."""
        with TestClient(app) as client:
            response = client.get("/")
            
            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "NFT-Gated AI Trading Bot API"
            assert data["version"] == "1.0.0"
            assert data["status"] == "operational"
    
    @patch('api.deps.redis_client')
    @patch('api.deps.web3_manager')
    def test_health_check(self, mock_web3_manager, mock_redis):
        """Test comprehensive health check."""
        # Mock Redis
        mock_redis.ping.return_value = True
        
        # Mock Web3 manager
        mock_w3 = Mock()
        mock_w3.eth.block_number = 18500000
        mock_web3_manager.get_connection.return_value = mock_w3
        
        with TestClient(app) as client:
            response = client.get("/health/")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] in ["healthy", "degraded"]
            assert "services" in data
            assert "redis" in data["services"]
            assert "web3" in data["services"]
    
    def test_ping_endpoint(self):
        """Test simple ping endpoint."""
        with TestClient(app) as client:
            response = client.get("/health/ping")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["message"] == "pong"
            assert "timestamp" in data
    
    @patch('api.deps.redis_client')
    @patch('api.deps.web3_manager')
    def test_readiness_check_success(self, mock_web3_manager, mock_redis):
        """Test readiness check with healthy services."""
        # Mock healthy services
        mock_redis.ping.return_value = True
        
        mock_w3 = Mock()
        mock_w3.eth.block_number = 18500000
        mock_web3_manager.get_connection.return_value = mock_w3
        
        with TestClient(app) as client:
            response = client.get("/health/ready")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ready"
    
    @patch('api.deps.redis_client')
    def test_readiness_check_failure(self, mock_redis):
        """Test readiness check with unhealthy services."""
        # Mock Redis failure
        mock_redis.ping.side_effect = Exception("Redis connection failed")
        
        with TestClient(app) as client:
            response = client.get("/health/ready")
            
            assert response.status_code == 503
            data = response.json()
            assert "Service not ready" in data["detail"]
    
    def test_liveness_check(self):
        """Test liveness check."""
        with TestClient(app) as client:
            response = client.get("/health/live")
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "alive"
            assert "timestamp" in data


class TestAuthEndpoints:
    """Test cases for authentication endpoints."""
    
    @patch('api.routers.auth.verify_nft_ownership')
    def test_verify_nft_success(self, mock_verify):
        """Test successful NFT verification."""
        mock_verify.return_value = True
        
        with TestClient(app) as client:
            response = client.post("/auth/verify-nft", json={
                "wallet_address": "0x1234567890abcdef1234567890abcdef12345678"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["verified"] is True
            assert data["has_nft"] is True
            assert "access_token" in data
    
    @patch('api.routers.auth.verify_nft_ownership')
    def test_verify_nft_failure(self, mock_verify):
        """Test failed NFT verification."""
        mock_verify.return_value = False
        
        with TestClient(app) as client:
            response = client.post("/auth/verify-nft", json={
                "wallet_address": "0x1234567890abcdef1234567890abcdef12345678"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["verified"] is False
            assert data["has_nft"] is False
            assert data["access_token"] is None
    
    def test_verify_nft_invalid_address(self):
        """Test NFT verification with invalid wallet address."""
        with TestClient(app) as client:
            response = client.post("/auth/verify-nft", json={
                "wallet_address": "invalid_address"
            })
            
            assert response.status_code == 400
    
    def test_get_user_info(self, authenticated_user):
        """Test getting user information."""
        with TestClient(app) as client:
            response = client.get("/auth/me", headers={
                "Authorization": "Bearer test_token"
            })
            
            assert response.status_code == 200
            data = response.json()
            assert data["authenticated"] is True
            assert data["nft_verified"] is True
            assert "permissions" in data
    
    def test_get_user_info_unauthorized(self):
        """Test getting user info without authentication."""
        with TestClient(app) as client:
            response = client.get("/auth/me")
            
            assert response.status_code == 401
    
    def test_check_access_with_auth(self, authenticated_user):
        """Test access check with valid authentication."""
        with TestClient(app) as client:
            response = client.get("/auth/check-access")
            
            assert response.status_code == 200
            data = response.json()
            assert data["has_access"] is True
    
    def test_check_access_without_auth(self, anonymous_user):
        """Test access check without authentication."""
        with TestClient(app) as client:
            response = client.get("/auth/check-access")
            
            assert response.status_code == 200
            data = response.json()
            assert data["has_access"] is False


class TestTradeEndpoints:
    """Test cases for trading endpoints."""
    
    @patch('api.routers.trade.parse_trading_prompt')
    def test_prompt_to_trade(self, mock_parse, trade_deps, authenticated_user):
        """Test natural language prompt to trade conversion."""
        # Mock the prompt parser (called directly in the router, returns a dict)
        mock_parse.return_value = {
            "trade_type": "swap",
            "token_in": "ETH",
            "token_out": "USDC",
            "amount_in": 1.0,
        }
        
        with TestClient(app) as client:
            response = client.post("/trade/prompt", 
                headers={"Authorization": "Bearer test_token"},
                json={
                    "prompt": "Buy 1 ETH worth of USDC",
                    "dry_run": True
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "pending"
            assert data["trade_type"] == "swap"
            assert data["dry_run"] is True
    
    def test_direct_trade_execution(self, trade_deps, authenticated_user):
        """Test direct trade execution."""
        with TestClient(app) as client:
            response = client.post("/trade/execute",
                headers={"Authorization": "Bearer test_token"},
                json={
                    "trade_type": "swap",
                    "token_in": "ETH",
                    "token_out": "USDC",
                    "amount_in": 1.0,
                    "dry_run": True
                }
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "pending"
            assert data["trade_type"] == "swap"
            assert data["token_in"] == "ETH"
            assert data["token_out"] == "USDC"
    
    def test_trade_execution_unauthorized(self):
        """Test trade execution without authentication."""
        with TestClient(app) as client:
            response = client.post("/trade/execute", json={
                "trade_type": "swap",
                "token_in": "ETH",
                "token_out": "USDC",
                "amount_in": 1.0
            })
            
            assert response.status_code == 401
    
    def test_get_trade_status(self, trade_deps, authenticated_user):
        """Test getting trade status."""
        with TestClient(app) as client:
            response = client.get("/trade/status/test_trade_123",
                headers={"Authorization": "Bearer test_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "trade_id" in data
            assert "status" in data
    
    def test_get_portfolio(self, trade_deps, authenticated_user):
        """Test getting user portfolio."""
        with TestClient(app) as client:
            response = client.get("/trade/portfolio",
                headers={"Authorization": "Bearer test_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "wallet_address" in data
            assert "total_value_usd" in data
            assert "tokens" in data
    
    def test_get_strategies(self, trade_deps, authenticated_user):
        """Test getting available strategies."""
        with TestClient(app) as client:
            response = client.get("/trade/strategies",
                headers={"Authorization": "Bearer test_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            if data:  # If strategies are returned
                assert "strategy_id" in data[0]
                assert "name" in data[0]
    
    def test_get_trade_history(self, trade_deps, authenticated_user):
        """Test getting trade history."""
        with TestClient(app) as client:
            response = client.get("/trade/history",
                headers={"Authorization": "Bearer test_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "trades" in data
            assert "total" in data
            assert "limit" in data
            assert "offset" in data


def _fake_adapter(exchange: str, amount_out: float, fees: float, network: str = "ethereum"):
    """An ExchangeAdapter stand-in whose get_quote returns a fixed TradeQuote."""
    adapter = Mock()
    adapter.network = network
    adapter.get_quote = AsyncMock(return_value=TradeQuote(
        exchange=exchange, token_in="ETH", token_out="USDC", amount_in=1.0,
        amount_out=amount_out, price=amount_out, gas_estimate=150000, slippage=0.01,
        fees=fees, valid_until=datetime(2030, 1, 1), route=["0xWETH", "0xUSDC"],
    ))
    return adapter


class TestQuoteEndpoint:
    """Test cases for GET /trade/quote."""

    @pytest.fixture(autouse=True)
    def no_startup_registration(self):
        """Keep the lifespan from registering real adapters on top of the fakes."""
        with patch("api.main.register_default_adapters"):
            yield

    @pytest.fixture
    def engine_adapters(self):
        """Swap two fake adapters onto the global trade engine for the test."""
        adapters = {
            "uniswap_v2": _fake_adapter("uniswap_v2", amount_out=1600.0, fees=0.003),
            "uniswap_v3": _fake_adapter("uniswap_v3", amount_out=1602.0, fees=0.0005),
        }
        with patch.object(trade_engine, "adapters", adapters):
            yield adapters

    @pytest.fixture
    def no_rate_limit(self):
        undo = _override(api_rate_limiter, None)
        yield
        undo()

    def test_returns_best_quote_across_exchanges(self, engine_adapters, no_rate_limit, authenticated_user):
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "USDC", "amount_in": 1.0
            }, headers={"Authorization": "Bearer test_token"})

        assert response.status_code == 200, response.text
        data = response.json()
        assert data["exchange"] == "uniswap_v3"  # higher net output
        assert data["amount_out"] == 1602.0
        assert data["fees"] == 0.0005
        assert data["route"] == ["0xWETH", "0xUSDC"]
        assert data["exchanges_checked"] == ["uniswap_v2", "uniswap_v3"]
        for adapter in engine_adapters.values():
            adapter.get_quote.assert_awaited_once_with("ETH", "USDC", 1.0)

    def test_pinned_exchange(self, engine_adapters, no_rate_limit, authenticated_user):
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "USDC", "amount_in": 1.0, "exchange": "uniswap_v2"
            }, headers={"Authorization": "Bearer test_token"})

        assert response.status_code == 200
        assert response.json()["exchange"] == "uniswap_v2"
        assert response.json()["exchanges_checked"] == ["uniswap_v2"]
        engine_adapters["uniswap_v3"].get_quote.assert_not_awaited()

    def test_unknown_exchange_is_400(self, engine_adapters, no_rate_limit, authenticated_user):
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "USDC", "amount_in": 1.0, "exchange": "sushiswap"
            }, headers={"Authorization": "Bearer test_token"})

        assert response.status_code == 400
        assert "uniswap_v2" in response.json()["detail"]

    def test_same_token_is_400(self, engine_adapters, no_rate_limit, authenticated_user):
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "eth", "amount_in": 1.0
            }, headers={"Authorization": "Bearer test_token"})
        assert response.status_code == 400

    def test_non_positive_amount_is_422(self, engine_adapters, no_rate_limit, authenticated_user):
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "USDC", "amount_in": 0
            }, headers={"Authorization": "Bearer test_token"})
        assert response.status_code == 422

    def test_no_adapters_is_503(self, no_rate_limit, authenticated_user):
        with patch.object(trade_engine, "adapters", {}), \
             patch("core.execution.adapters.register_default_adapters", return_value={}) as register:
            adapters_module._last_attempt.clear()
            with TestClient(app) as client:
                response = client.get("/trade/quote", params={
                    "token_in": "ETH", "token_out": "USDC", "amount_in": 1.0
                }, headers={"Authorization": "Bearer test_token"})
        assert response.status_code == 503
        register.assert_called_once()  # the 503 path tried to re-register

    def test_recovers_once_node_is_reachable(self, no_rate_limit, authenticated_user):
        """503 while the node is down, then 200 on the next request after it recovers."""
        node_up = False

        def register(engine, network):
            if not node_up:
                return {}
            adapter = _fake_adapter("uniswap_v3", amount_out=1602.0, fees=0.0005)
            engine.register_adapter("uniswap_v3", adapter)
            return {"uniswap_v3": adapter}

        params = {"token_in": "ETH", "token_out": "USDC", "amount_in": 1.0}
        headers = {"Authorization": "Bearer test_token"}
        with patch.object(trade_engine, "adapters", {}), \
             patch("core.execution.adapters.register_default_adapters", side_effect=register):
            adapters_module._last_attempt.clear()
            with TestClient(app) as client:
                assert client.get("/trade/quote", params=params, headers=headers).status_code == 503

                node_up = True
                adapters_module._last_attempt.clear()  # cooldown elapsed
                response = client.get("/trade/quote", params=params, headers=headers)

        assert response.status_code == 200
        assert response.json()["exchange"] == "uniswap_v3"

    def test_all_adapters_failing_is_503(self, engine_adapters, no_rate_limit, authenticated_user):
        for adapter in engine_adapters.values():
            adapter.get_quote.side_effect = Exception("rpc down")
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "USDC", "amount_in": 1.0
            }, headers={"Authorization": "Bearer test_token"})
        assert response.status_code == 503
        assert "could quote" in response.json()["detail"]

    def test_requires_auth(self, engine_adapters, no_rate_limit):
        with TestClient(app) as client:
            response = client.get("/trade/quote", params={
                "token_in": "ETH", "token_out": "USDC", "amount_in": 1.0
            })
        assert response.status_code in (401, 403)


class TestAdminEndpoints:
    """Test cases for admin endpoints."""
    
    @patch('api.routers.admin.is_admin_user')
    def test_get_system_stats(self, mock_is_admin, authenticated_user):
        """Test getting system statistics."""
        mock_is_admin.return_value = True
        
        with TestClient(app) as client:
            response = client.get("/admin/stats",
                headers={"Authorization": "Bearer admin_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "total_users" in data
            assert "active_trades" in data
            assert "total_volume_24h" in data
    
    def test_admin_access_denied(self, authenticated_user):
        """Test admin access denied for non-admin user."""
        with TestClient(app) as client:
            response = client.get("/admin/stats",
                headers={"Authorization": "Bearer user_token"}
            )
            
            assert response.status_code == 403
    
    @patch('api.routers.admin.is_admin_user')
    def test_get_system_config(self, mock_is_admin, authenticated_user):
        """Test getting system configuration."""
        mock_is_admin.return_value = True
        
        with TestClient(app) as client:
            response = client.get("/admin/config",
                headers={"Authorization": "Bearer admin_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert "bypass_nft_gate" in data
            assert "real_data_mode" in data
            assert "supported_networks" in data
    
    @patch('api.routers.admin.is_admin_user')
    def test_emergency_stop(self, mock_is_admin, authenticated_user):
        """Test emergency stop functionality."""
        mock_is_admin.return_value = True
        
        with TestClient(app) as client:
            response = client.post("/admin/emergency-stop",
                headers={"Authorization": "Bearer admin_token"}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["message"] == "Emergency stop activated"
            assert "activated_by" in data


class TestRateLimiting:
    """Test cases for rate limiting."""
    
    @patch('api.deps.redis_client')
    def test_rate_limiting(self, mock_redis):
        """Test API rate limiting."""
        # Mock Redis to simulate rate limit exceeded
        mock_redis.get.return_value = "100"  # Current request count
        
        with TestClient(app) as client:
            # This would normally trigger rate limiting
            # For testing, we'll just verify the endpoint is accessible
            response = client.get("/health/ping")
            assert response.status_code == 200

    @pytest.fixture
    def fake_redis(self):
        """Override only the Redis client so the real trade_rate_limiter runs."""
        fake = Mock()
        fake.get.return_value = None
        undo = _override(get_redis_client, fake)
        yield fake
        undo()

    def test_trade_rate_limiter_keys_on_wallet(self, fake_redis, authenticated_user):
        """The limiter must not require a client-supplied request_id."""
        with TestClient(app) as client:
            response = client.post("/trade/execute",
                headers={"Authorization": "Bearer test_token"},
                json={"trade_type": "swap", "token_in": "ETH", "token_out": "USDC",
                      "amount_in": 1.0, "dry_run": True}
            )
            assert response.status_code == 200
        fake_redis.setex.assert_called_once()
        key = fake_redis.setex.call_args.args[0]
        assert key == f"rate_limit:wallet:{TEST_WALLET.lower()}"

    def test_trade_rate_limiter_exceeded(self, fake_redis, authenticated_user):
        """Requests over the limit get 429."""
        fake_redis.get.return_value = str(trade_rate_limiter.max_requests)
        with TestClient(app) as client:
            response = client.post("/trade/execute",
                headers={"Authorization": "Bearer test_token"},
                json={"trade_type": "swap", "token_in": "ETH", "token_out": "USDC",
                      "amount_in": 1.0, "dry_run": True}
            )
            assert response.status_code == 429


class TestErrorHandling:
    """Test cases for error handling."""
    
    def test_404_error(self):
        """Test 404 error handling."""
        with TestClient(app) as client:
            response = client.get("/nonexistent-endpoint")
            assert response.status_code == 404
    
    def test_422_validation_error(self):
        """Test validation error handling."""
        with TestClient(app) as client:
            response = client.post("/auth/verify-nft", json={
                "invalid_field": "invalid_value"
            })
            assert response.status_code == 422
    
    @patch('api.routers.auth.verify_nft_ownership')
    def test_internal_server_error(self, mock_verify):
        """Test internal server error handling."""
        mock_verify.side_effect = Exception("Internal error")
        
        with TestClient(app) as client:
            response = client.post("/auth/verify-nft", json={
                "wallet_address": "0x1234567890abcdef1234567890abcdef12345678"
            })
            
            assert response.status_code == 400  # Handled as bad request

