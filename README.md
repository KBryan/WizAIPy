# WizAIPy

[![CI](https://github.com/KBryan/WizAIPy/actions/workflows/ci.yml/badge.svg)](https://github.com/KBryan/WizAIPy/actions/workflows/ci.yml)

<img width="754" height="763" alt="wizaipi" src="https://github.com/user-attachments/assets/0ab049e8-6370-4048-8c7a-897c3e381871" />


A sophisticated, AI-powered cryptocurrency trading bot that leverages natural language processing and NFT-based access control to provide automated trading strategies across multiple blockchain networks.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Architecture](#architecture)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Deployment](#deployment)
- [Testing](#testing)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)

## Overview

The NFT-Gated AI Trading Bot is an advanced cryptocurrency trading system that combines artificial intelligence, natural language processing, and blockchain technology to provide automated trading capabilities. The system uses NFT ownership as a gating mechanism, ensuring that only verified NFT holders can access the trading functionality.

### Key Capabilities

- **Natural Language Trading**: Convert plain English instructions into executable trades using advanced LLM integration
- **Multi-Chain Support**: Trade across Ethereum, Skale, and Beam networks
- **NFT-Based Access Control**: Secure access through NFT ownership verification
- **Automated Strategies**: Pluggable trading strategies including momentum, mean reversion, and custom algorithms
- **Real-Time Market Data**: Integration with CoinGecko and other market data providers
- **Social Media Integration**: Automated notifications and updates via Twitter
- **Comprehensive Monitoring**: Health checks, metrics, and performance tracking

## Features

### Core Trading Features

- **Multi-Exchange Support**: Integrated with Uniswap V2/V3 for decentralized trading
- **Strategy Framework**: Extensible strategy system supporting custom trading algorithms
- **Risk Management**: Built-in position sizing, stop-loss, and risk limit controls
- **Portfolio Management**: Real-time portfolio tracking and rebalancing
- **Gas Optimization**: Intelligent gas price management and transaction optimization

### AI and NLP Features

- **Multi-LLM Support**: Compatible with Anthropic Claude, OpenAI GPT, Google Gemini, and Venice AI
- **Prompt Engineering**: Advanced prompt parsing for complex trading instructions
- **Confidence Scoring**: AI-driven confidence assessment for trade recommendations
- **Natural Language Queries**: Support for conversational trading commands

### Security and Access Control

- **NFT Gating**: Ethereum-based NFT ownership verification
- **Wallet Integration**: Secure wallet connection and transaction signing
- **Rate Limiting**: API rate limiting and abuse prevention
- **Audit Logging**: Comprehensive logging of all trading activities

### Infrastructure Features

- **Microservices Architecture**: Scalable, containerized deployment
- **Background Processing**: Celery-based task queue for async operations
- **Caching Layer**: Redis-based caching for performance optimization
- **Database Management**: PostgreSQL with migration support
- **Monitoring and Alerting**: Prometheus metrics and Grafana dashboards

## Architecture

The system follows a microservices architecture with clear separation of concerns:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Frontend UI   │    │   API Gateway   │    │  Load Balancer  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  Auth Service   │    │ Trading Service │    │ Strategy Engine │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   NFT Gateway   │    │  LLM Processor  │    │ Market Data API │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   PostgreSQL    │    │      Redis      │    │  Message Queue  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Component Overview

- **API Layer**: FastAPI-based REST API with automatic documentation
- **Core Engine**: Trading logic, strategy execution, and risk management
- **Integration Layer**: External service integrations (exchanges, data providers, social media)
- **Data Layer**: PostgreSQL for persistent storage, Redis for caching and sessions
- **Background Processing**: Celery workers for async task execution

## Installation

### Prerequisites

- Python 3.11+
- Docker and Docker Compose
- PostgreSQL 15+
- Redis 7+
- Node.js 18+ (for frontend development)

### Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/your-org/nft-trading-bot.git
   cd nft-trading-bot
   ```

2. **Set up Python environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Start services with Docker Compose**:
   ```bash
   docker-compose up -d
   ```

5. **Run database migrations**:
   ```bash
   python -m alembic upgrade head
   ```

6. **Start the development server**:
   ```bash
   uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Docker Installation

1. **Build and run with Docker Compose**:
   ```bash
   docker-compose up --build
   ```

2. **Access the application**:
   - API: http://localhost:8000
   - API Documentation: http://localhost:8000/docs
   - Flower (Celery monitoring): http://localhost:5555

## Configuration

### Environment Variables

The application uses environment variables for configuration. Key variables include:

#### Application Settings
- `DEBUG`: Enable debug mode (default: false)
- `BYPASS_NFT_GATE`: Bypass NFT verification for testing (default: false)
- `REAL_DATA_MODE`: Use real market data vs. mock data (default: true)
- `SECRET_KEY`: Application secret key for JWT tokens

#### Database Configuration
- `DATABASE_URL`: PostgreSQL connection string
- `REDIS_URL`: Redis connection string

#### Blockchain Configuration
- `ETHEREUM_RPC_URL`: Ethereum RPC endpoint
- `SKALE_RPC_URL`: Skale network RPC endpoint
- `BEAM_RPC_URL`: Beam network RPC endpoint
- `PRIVATE_KEY`: Trading wallet private key

#### API Keys
- `ANTHROPIC_API_KEY`: Anthropic Claude API key
- `OPENAI_API_KEY`: OpenAI GPT API key
- `GEMINI_API_KEY`: Google Gemini API key
- `COINGECKO_API_KEY`: CoinGecko API key for market data

#### Trading Configuration
- `MAX_GAS_PRICE`: Maximum gas price in gwei
- `DEFAULT_SLIPPAGE`: Default slippage tolerance (%)
- `MIN_TRADE_AMOUNT`: Minimum trade amount
- `MAX_TRADE_AMOUNT`: Maximum trade amount

### Configuration Files

- `.env.development`: Development environment settings
- `.env.production.template`: Production environment template
- `config.py`: Application configuration management

## Usage

### Basic Trading Commands

The bot supports natural language trading commands through the API:

```bash
# Buy ETH with USDC
curl -X POST "http://localhost:8000/trade/prompt" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Buy 1 ETH with USDC", "dry_run": false}'

# Sell half of WBTC position
curl -X POST "http://localhost:8000/trade/prompt" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Sell 50% of my #BTC position", "dry_run": false}'
```

### Strategy Management

```bash
# List available strategies
curl -X GET "http://localhost:8000/trade/strategies" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get strategy performance
curl -X GET "http://localhost:8000/trade/strategies/momentum_1/performance" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Portfolio Management

```bash
# Get current portfolio
curl -X GET "http://localhost:8000/trade/portfolio" \
  -H "Authorization: Bearer YOUR_TOKEN"

# Get trade history
curl -X GET "http://localhost:8000/trade/history?limit=50" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

## API Documentation

The API is fully documented using OpenAPI/Swagger. Access the interactive documentation at:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

### Authentication

The API uses JWT-based authentication with NFT ownership verification:

1. **Verify NFT ownership**:
   ```bash
   curl -X POST "http://localhost:8000/auth/verify-nft" \
     -H "Content-Type: application/json" \
     -d '{"wallet_address": "0x..."}'
   ```

2. **Use the returned token** in subsequent requests:
   ```bash
   curl -H "Authorization: Bearer YOUR_JWT_TOKEN" \
     "http://localhost:8000/trade/portfolio"
   ```

### Rate Limiting

The API implements rate limiting to prevent abuse:
- **Development**: 100 requests/minute, 1000 requests/hour
- **Production**: 60 requests/minute, 500 requests/hour

## Deployment

### Production Deployment

#### Using Docker

1. **Build production image**:
   ```bash
   docker build -t nft-trading-bot:latest .
   ```

2. **Deploy with Docker Compose**:
   ```bash
   docker-compose -f docker-compose.prod.yml up -d
   ```

#### Using Kubernetes

1. **Apply Kubernetes manifests**:
   ```bash
   kubectl apply -f k8s/
   ```

2. **Configure secrets**:
   ```bash
   kubectl create secret generic nft-trading-bot-secrets \
     --from-env-file=.env.production
   ```

#### Using Heroku

1. **Deploy to Heroku**:
   ```bash
   git push heroku main
   ```

2. **Configure environment variables**:
   ```bash
   heroku config:set DATABASE_URL=postgresql://...
   heroku config:set REDIS_URL=redis://...
   ```

### Deployment Script

Use the provided deployment script for automated deployments:

```bash
# Development deployment
./scripts/deploy.sh development

# Production deployment with image build
./scripts/deploy.sh production --build --tag v1.0.0 --run-tests
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run integration tests
pytest tests/integration/

# Run with coverage
pytest --cov=api --cov=core --cov=integrations --cov-report=html
```

### Test Categories

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **External Tests**: Test external service integrations (requires API keys)
- **End-to-End Tests**: Test complete user workflows

### Test Configuration

Tests use pytest with the following markers:
- `@pytest.mark.unit`: Unit tests
- `@pytest.mark.integration`: Integration tests
- `@pytest.mark.external`: Tests requiring external services
- `@pytest.mark.slow`: Long-running tests

## Contributing

### Development Workflow

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/your-feature`
3. **Make changes and add tests**
4. **Run the test suite**: `pytest`
5. **Submit a pull request**

### Code Standards

- **Python**: Follow PEP 8 style guidelines
- **Type Hints**: Use type hints for all function signatures
- **Documentation**: Document all public APIs and complex logic
- **Testing**: Maintain >80% test coverage

### Pre-commit Hooks

Install pre-commit hooks to ensure code quality:

```bash
pip install pre-commit
pre-commit install
```

## Security

### Security Considerations

- **Private Key Management**: Never commit private keys to version control
- **API Key Security**: Use environment variables for all API keys
- **Rate Limiting**: Implement rate limiting to prevent abuse
- **Input Validation**: Validate all user inputs and API parameters
- **Audit Logging**: Log all trading activities for audit purposes

### Security Best Practices

- Use strong, unique passwords for all accounts
- Enable two-factor authentication where available
- Regularly rotate API keys and access tokens
- Monitor for unusual trading activity
- Keep dependencies updated to patch security vulnerabilities

### Vulnerability Reporting

Report security vulnerabilities to: kwame.bryan@gmail.com

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Support

For support and questions:
- **Documentation**: Check this README and API docs
- **Issues**: Create a GitHub issue
- **Discord**: Join our Discord community
- **Email**: kwame.bryan@gmail.com

---

**Disclaimer**: This software is for educational and research purposes. Cryptocurrency trading involves significant risk. Use at your own risk and never trade with funds you cannot afford to lose.

