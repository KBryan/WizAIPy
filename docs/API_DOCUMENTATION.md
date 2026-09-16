# NFT-Gated AI Trading Bot API Documentation

## Overview

The NFT-Gated AI Trading Bot provides a comprehensive REST API for cryptocurrency trading operations, portfolio management, and system administration. The API is built using FastAPI and provides automatic OpenAPI documentation.

## Base URL

- **Development**: `http://localhost:8000`
- **Production**: `https://api.your-domain.com`

## Authentication

The API uses JWT-based authentication with NFT ownership verification. All protected endpoints require a valid JWT token in the Authorization header.

### Authentication Flow

1. **Verify NFT Ownership**: Submit wallet address for NFT verification
2. **Receive JWT Token**: Get access token upon successful verification
3. **Use Token**: Include token in Authorization header for subsequent requests

```http
Authorization: Bearer <jwt_token>
```

## Rate Limiting

The API implements rate limiting to ensure fair usage:

- **Development**: 100 requests/minute, 1000 requests/hour
- **Production**: 60 requests/minute, 500 requests/hour

Rate limit headers are included in responses:
- `X-RateLimit-Limit`: Request limit per window
- `X-RateLimit-Remaining`: Remaining requests in current window
- `X-RateLimit-Reset`: Time when rate limit resets

## Error Handling

The API uses standard HTTP status codes and returns detailed error information:

```json
{
  "detail": "Error description",
  "error_code": "SPECIFIC_ERROR_CODE",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Common Status Codes

- `200`: Success
- `201`: Created
- `400`: Bad Request
- `401`: Unauthorized
- `403`: Forbidden
- `404`: Not Found
- `422`: Validation Error
- `429`: Rate Limit Exceeded
- `500`: Internal Server Error

## Endpoints

### Health and Status

#### GET /

Get basic API information.

**Response:**
```json
{
  "message": "NFT-Gated AI Trading Bot API",
  "version": "1.0.0",
  "status": "operational",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### GET /health/

Comprehensive health check of all system components.

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00Z",
  "services": {
    "database": {
      "status": "healthy",
      "response_time_ms": 5
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 2
    },
    "web3": {
      "status": "healthy",
      "block_number": 18500000
    }
  },
  "version": "1.0.0"
}
```

#### GET /health/ping

Simple ping endpoint for basic connectivity testing.

**Response:**
```json
{
  "status": "ok",
  "message": "pong",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### GET /health/ready

Readiness check for deployment health monitoring.

**Response:**
```json
{
  "status": "ready",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### GET /health/live

Liveness check for container orchestration.

**Response:**
```json
{
  "status": "alive",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Authentication

#### POST /auth/verify-nft

Verify NFT ownership and obtain access token.

**Request Body:**
```json
{
  "wallet_address": "0x1234567890abcdef1234567890abcdef12345678"
}
```

**Response:**
```json
{
  "verified": true,
  "has_nft": true,
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "wallet_address": "0x1234567890abcdef1234567890abcdef12345678"
}
```

#### GET /auth/me

Get current user information.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "wallet_address": "0x1234567890abcdef1234567890abcdef12345678",
  "authenticated": true,
  "nft_verified": true,
  "permissions": ["trade", "view_portfolio"],
  "created_at": "2024-01-15T10:30:00Z",
  "last_login": "2024-01-15T10:30:00Z"
}
```

#### GET /auth/check-access

Check access permissions without authentication requirement.

**Response:**
```json
{
  "has_access": true,
  "access_level": "full",
  "restrictions": []
}
```

### Trading

#### POST /trade/prompt

Convert natural language prompt to trading instruction.

**Headers:**
```http
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "prompt": "Buy 1 ETH worth of USDC",
  "dry_run": false,
  "llm_provider": "anthropic"
}
```

**Response:**
```json
{
  "trade_id": "trade_123456",
  "status": "pending",
  "trade_type": "swap",
  "parsed_instruction": {
    "action": "buy",
    "token_in": "ETH",
    "token_out": "USDC",
    "amount": 1.0,
    "amount_type": "absolute",
    "confidence": 0.9,
    "reasoning": "User wants to swap 1 ETH for USDC"
  },
  "estimated_output": 1600.0,
  "gas_estimate": 150000,
  "dry_run": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### POST /trade/execute

Execute a direct trade without natural language processing.

**Headers:**
```http
Authorization: Bearer <jwt_token>
Content-Type: application/json
```

**Request Body:**
```json
{
  "trade_type": "swap",
  "token_in": "ETH",
  "token_out": "USDC",
  "amount_in": 1.0,
  "slippage": 0.5,
  "dry_run": false,
  "network": "ethereum"
}
```

**Response:**
```json
{
  "trade_id": "trade_123456",
  "status": "pending",
  "trade_type": "swap",
  "token_in": "ETH",
  "token_out": "USDC",
  "amount_in": 1.0,
  "estimated_amount_out": 1600.0,
  "slippage": 0.5,
  "gas_estimate": 150000,
  "network": "ethereum",
  "dry_run": false,
  "created_at": "2024-01-15T10:30:00Z"
}
```

#### GET /trade/quote

Get the best available swap quote from the execution engine. Read-only — nothing is executed. Compares every exchange adapter registered for the network, net of fees, unless `exchange` pins one.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Query Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `token_in` | string | Yes | Input token symbol or address |
| `token_out` | string | Yes | Output token symbol or address |
| `amount_in` | number | Yes | Input amount in `token_in` units (> 0) |
| `exchange` | string | No | Pin a single exchange, e.g. `uniswap_v3` |
| `network` | string | No | Blockchain network (default `ethereum`) |

**Example:**
```bash
curl "http://localhost:8000/trade/quote?token_in=ETH&token_out=USDC&amount_in=1.0" \
  -H "Authorization: Bearer <jwt_token>"
```

**Response:**
```json
{
  "exchange": "uniswap_v3",
  "network": "ethereum",
  "token_in": "ETH",
  "token_out": "USDC",
  "amount_in": 1.0,
  "amount_out": 1602.35,
  "price": 1602.35,
  "fees": 0.0005,
  "slippage": 0.01,
  "gas_estimate": 180000,
  "route": [
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
    "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
  ],
  "valid_until": "2024-01-15T10:35:00Z",
  "exchanges_checked": ["uniswap_v2", "uniswap_v3"]
}
```

**Errors:**

| Status | When |
|---|---|
| 400 | `token_in` equals `token_out`, or `exchange` is not registered on the network |
| 422 | `amount_in` is not > 0 or a required parameter is missing |
| 503 | No exchange adapters are registered for the network (RPC unreachable), or none could produce a quote. Registration is retried automatically, at most every 30s, so the endpoint recovers once the node is reachable |

#### GET /trade/status/{trade_id}

Get the status of a specific trade.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "trade_id": "trade_123456",
  "status": "completed",
  "trade_type": "swap",
  "token_in": "ETH",
  "token_out": "USDC",
  "amount_in": 1.0,
  "amount_out": 1595.50,
  "execution_price": 1595.50,
  "slippage": 0.28,
  "gas_used": 148500,
  "gas_price": 25,
  "transaction_hash": "0xabcdef1234567890...",
  "block_number": 18500123,
  "created_at": "2024-01-15T10:30:00Z",
  "executed_at": "2024-01-15T10:31:30Z"
}
```

#### GET /trade/portfolio

Get current portfolio information.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "wallet_address": "0x1234567890abcdef1234567890abcdef12345678",
  "total_value_usd": 5000.0,
  "tokens": [
    {
      "token": "ETH",
      "balance": 2.5,
      "value_usd": 4000.0,
      "price_usd": 1600.0,
      "percentage": 80.0
    },
    {
      "token": "USDC",
      "balance": 1000.0,
      "value_usd": 1000.0,
      "price_usd": 1.0,
      "percentage": 20.0
    }
  ],
  "last_updated": "2024-01-15T10:30:00Z"
}
```

#### GET /trade/history

Get trading history with pagination.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Query Parameters:**
- `limit` (optional): Number of trades to return (default: 50, max: 100)
- `offset` (optional): Number of trades to skip (default: 0)
- `status` (optional): Filter by trade status
- `token` (optional): Filter by token symbol

**Response:**
```json
{
  "trades": [
    {
      "trade_id": "trade_123456",
      "status": "completed",
      "trade_type": "swap",
      "token_in": "ETH",
      "token_out": "USDC",
      "amount_in": 1.0,
      "amount_out": 1595.50,
      "execution_price": 1595.50,
      "created_at": "2024-01-15T10:30:00Z",
      "executed_at": "2024-01-15T10:31:30Z"
    }
  ],
  "total": 25,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

#### GET /trade/strategies

Get available trading strategies.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Response:**
```json
[
  {
    "strategy_id": "momentum_1",
    "name": "Momentum Strategy",
    "description": "Trades based on price momentum indicators",
    "status": "active",
    "performance": {
      "total_trades": 150,
      "win_rate": 0.68,
      "total_pnl": 2500.0,
      "sharpe_ratio": 1.45
    },
    "parameters": {
      "lookback_period": 14,
      "momentum_threshold": 0.05
    }
  }
]
```

#### GET /trade/strategies/{strategy_id}/performance

Get detailed performance metrics for a specific strategy.

**Headers:**
```http
Authorization: Bearer <jwt_token>
```

**Response:**
```json
{
  "strategy_id": "momentum_1",
  "performance_period": "30d",
  "metrics": {
    "total_trades": 150,
    "winning_trades": 102,
    "losing_trades": 48,
    "win_rate": 0.68,
    "total_pnl": 2500.0,
    "average_win": 45.2,
    "average_loss": -18.7,
    "max_drawdown": -125.0,
    "sharpe_ratio": 1.45,
    "sortino_ratio": 1.82
  },
  "daily_returns": [
    {
      "date": "2024-01-15",
      "pnl": 125.50,
      "trades": 3
    }
  ]
}
```

### Administrative

#### GET /admin/stats

Get system statistics (admin only).

**Headers:**
```http
Authorization: Bearer <admin_jwt_token>
```

**Response:**
```json
{
  "total_users": 1250,
  "active_users_24h": 89,
  "total_trades": 15420,
  "active_trades": 12,
  "total_volume_24h": 2500000.0,
  "system_uptime": "15d 8h 32m",
  "active_strategies": 8,
  "system_health": "healthy"
}
```

#### GET /admin/config

Get system configuration (admin only).

**Headers:**
```http
Authorization: Bearer <admin_jwt_token>
```

**Response:**
```json
{
  "bypass_nft_gate": false,
  "real_data_mode": true,
  "supported_networks": ["ethereum", "skale", "beam"],
  "max_gas_price": 50,
  "default_slippage": 0.3,
  "rate_limits": {
    "per_minute": 60,
    "per_hour": 500
  },
  "feature_flags": {
    "twitter_notifications": true,
    "advanced_strategies": true
  }
}
```

#### POST /admin/emergency-stop

Activate emergency stop to halt all trading (admin only).

**Headers:**
```http
Authorization: Bearer <admin_jwt_token>
```

**Response:**
```json
{
  "message": "Emergency stop activated",
  "activated_at": "2024-01-15T10:30:00Z",
  "activated_by": "0xadmin_wallet_address",
  "affected_trades": 12,
  "status": "all_trading_halted"
}
```

## WebSocket API

The API also provides WebSocket endpoints for real-time updates:

### /ws/trades

Real-time trade updates for authenticated users.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/trades?token=jwt_token');
```

**Message Format:**
```json
{
  "type": "trade_update",
  "data": {
    "trade_id": "trade_123456",
    "status": "completed",
    "amount_out": 1595.50
  }
}
```

### /ws/market

Real-time market data updates.

**Connection:**
```javascript
const ws = new WebSocket('ws://localhost:8000/ws/market');
```

**Message Format:**
```json
{
  "type": "price_update",
  "data": {
    "symbol": "ETH",
    "price": 1600.0,
    "change_24h": 5.2,
    "timestamp": "2024-01-15T10:30:00Z"
  }
}
```

## SDK and Client Libraries

### Python SDK

```python
from nft_trading_bot import TradingBotClient

client = TradingBotClient(
    base_url="http://localhost:8000",
    wallet_address="0x...",
    private_key="0x..."
)

# Authenticate
await client.authenticate()

# Execute trade
trade = await client.execute_trade(
    prompt="Buy 1 ETH with USDC",
    dry_run=False
)

# Get portfolio
portfolio = await client.get_portfolio()
```

### JavaScript SDK

```javascript
import { TradingBotClient } from '@nft-trading-bot/sdk';

const client = new TradingBotClient({
  baseUrl: 'http://localhost:8000',
  walletAddress: '0x...'
});

// Authenticate
await client.authenticate();

// Execute trade
const trade = await client.executeTrade({
  prompt: 'Buy 1 ETH with USDC',
  dryRun: false
});

// Get portfolio
const portfolio = await client.getPortfolio();
```

## Examples

### Complete Trading Workflow

```bash
# 1. Verify NFT ownership
curl -X POST "http://localhost:8000/auth/verify-nft" \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0x1234567890abcdef1234567890abcdef12345678"}'

# 2. Extract token from response
TOKEN="eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."

# 3. Check portfolio
curl -X GET "http://localhost:8000/trade/portfolio" \
  -H "Authorization: Bearer $TOKEN"

# 4. Execute trade
curl -X POST "http://localhost:8000/trade/prompt" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Buy 0.5 ETH with USDC", "dry_run": false}'

# 5. Check trade status
curl -X GET "http://localhost:8000/trade/status/trade_123456" \
  -H "Authorization: Bearer $TOKEN"
```

### Batch Operations

```bash
# Get multiple trade statuses
for trade_id in trade_123456 trade_123457 trade_123458; do
  curl -X GET "http://localhost:8000/trade/status/$trade_id" \
    -H "Authorization: Bearer $TOKEN"
done

# Get strategy performance for all strategies
curl -X GET "http://localhost:8000/trade/strategies" \
  -H "Authorization: Bearer $TOKEN" | \
  jq -r '.[].strategy_id' | \
  xargs -I {} curl -X GET "http://localhost:8000/trade/strategies/{}/performance" \
    -H "Authorization: Bearer $TOKEN"
```

## Testing the API

### Using curl

```bash
# Health check
curl -X GET "http://localhost:8000/health/"

# Authentication test
curl -X POST "http://localhost:8000/auth/verify-nft" \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0x1234567890abcdef1234567890abcdef12345678"}'
```

### Using Python requests

```python
import requests

# Health check
response = requests.get("http://localhost:8000/health/")
print(response.json())

# Authentication
auth_response = requests.post(
    "http://localhost:8000/auth/verify-nft",
    json={"wallet_address": "0x1234567890abcdef1234567890abcdef12345678"}
)
token = auth_response.json()["access_token"]

# Get portfolio
portfolio_response = requests.get(
    "http://localhost:8000/trade/portfolio",
    headers={"Authorization": f"Bearer {token}"}
)
print(portfolio_response.json())
```

## Troubleshooting

### Common Issues

1. **401 Unauthorized**: Check that JWT token is valid and included in Authorization header
2. **403 Forbidden**: Verify NFT ownership and user permissions
3. **422 Validation Error**: Check request body format and required fields
4. **429 Rate Limit Exceeded**: Reduce request frequency or upgrade rate limits
5. **500 Internal Server Error**: Check server logs and system health

### Debug Mode

Enable debug mode for detailed error information:

```bash
export DEBUG=true
uvicorn api.main:app --reload
```

### Logging

Check application logs for detailed error information:

```bash
# Docker logs
docker-compose logs api

# Kubernetes logs
kubectl logs deployment/nft-trading-bot-api
```

---

For additional support, please refer to the main README or contact the development team.

