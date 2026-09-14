# Validation Baseline

**Date**: 2026-09-14
**Maturity Level**: 2
**Environment**: uv-managed venv, CPython 3.12.14, `requirements.txt` + `setuptools<81` + `eth-typing<5` + `pytest-cov`
**Env vars for run**: `SECRET_KEY=test DATABASE_URL=sqlite:///./test.db REDIS_URL=redis://localhost:6379/0 ETHEREUM_RPC_URL=http://localhost:8545 PRIVATE_KEY=0x…01 CELERY_BROKER_URL=redis://localhost:6379/1 CELERY_RESULT_BACKEND=redis://localhost:6379/2` (no live Postgres/Redis/RPC)

## Test Results

Command: `.venv/bin/python -m pytest -p no:cacheprovider`

**21 failed, 33 passed, 17 skipped, 127 warnings in 8.52s**

Install-time blockers hit before the suite would collect (fixed for this run, not in repo):
- `ModuleNotFoundError: No module named 'pkg_resources'` — `web3/__init__.py` imports `pkg_resources`; uv venvs ship no setuptools and setuptools ≥81 removed it → pin `setuptools<81`.
- `ImportError: cannot import name 'ContractName' from 'eth_typing'` — `eth-typing` 6.x resolved; web3 6.12 needs <5.
- `pydantic ValidationError: 7 validation errors for Settings` — `get_settings()` runs at import in `core/execution/engine.py`; required env vars must be exported for collection.

### Failing tests

`tests/integration/test_integrations.py`
- `TestUniswapIntegration::test_create_uniswap_adapter` — `UniswapError: Failed to connect to ethereum network` (real Web3 provider, no RPC)
- `TestUniswapIntegration::test_token_address_resolution` — `assert <MagicMock Web3.to_checksum_address()> == '0x000…'` (Web3 mocked at wrong target)
- `TestUniswapIntegration::test_swap_path_building` — `UniswapError: Cannot swap token with itself`
- `TestTwitterIntegration::test_twitter_client_initialization_enabled` — `assert False` (line 335)

`tests/unit/test_api.py` — all 15 return **400** `{"detail":"NFT verification failed: NFT contract address not configured"}`. Root cause: tests `@patch('api.deps.get_current_user')` / `@patch('api.deps.verify_nft_ownership')`, but routers `from api.deps import …` at import time, so the patch is never seen and the real NFT gate runs.
- `TestAuthEndpoints::test_verify_nft_success` — assert 400 == 200
- `TestAuthEndpoints::test_verify_nft_failure` — assert 400 == 200
- `TestAuthEndpoints::test_get_user_info` — assert 400 == 200
- `TestAuthEndpoints::test_check_access_with_auth` — assert False is True
- `TestTradeEndpoints::test_prompt_to_trade` — assert 400 == 200
- `TestTradeEndpoints::test_direct_trade_execution` — assert 400 == 200
- `TestTradeEndpoints::test_get_trade_status` — assert 400 == 200
- `TestTradeEndpoints::test_get_portfolio` — assert 400 == 200
- `TestTradeEndpoints::test_get_strategies` — assert 400 == 200
- `TestTradeEndpoints::test_get_trade_history` — assert 400 == 200
- `TestAdminEndpoints::test_get_system_stats` — assert 400 == 200
- `TestAdminEndpoints::test_admin_access_denied` — assert 400 == 403
- `TestAdminEndpoints::test_get_system_config` — assert 400 == 200
- `TestAdminEndpoints::test_emergency_stop` — assert 400 == 200

`tests/unit/test_strategies.py`
- `TestMomentumStrategy::test_analyze_market_with_history` — `assert None is not None` (line 169; no signal generated)
- `TestMomentumStrategy::test_ma_crossover_calculation` — `assert 0 == 1` (line 201)
- `TestMomentumStrategy::test_volume_confirmation` — `assert True is True` failed (line 216 — reads as a `False is True` after evaluation)

### Passing (33)
Health endpoints, rate limiting, base strategy config/risk-limit checks, strategy registry, CoinGecko adapter, Twitter-disabled path, LLM client parsing, execution-engine unit tests.

### Skipped (17)
Tests marked `external`/requiring live services.

### Warnings
- `RuntimeWarning: coroutine 'BaseStrategy.stop' was never awaited` — `core/strategies/base.py:280`
- `DeprecationWarning: datetime.utcnow()` — `api/routers/health.py`, `tests/conftest.py`, `tests/unit/test_strategies.py`
- `pytest.ini` `[tool:pytest]` header is ignored → `asyncio_mode=auto`, markers, `--cov` flags inactive.

## Lint Results

Command: `.venv/bin/python -m flake8 --max-line-length=120 --exclude=.venv,alembic api core integrations config.py`
**756 findings** (dominated by W293 trailing whitespace on blank lines, W391, line length). No flake8 config file in repo.

## Format Results

Command: `.venv/bin/python -m black --check api core integrations config.py tests`
**25 files would be reformatted, 10 unchanged.**

## Typecheck Results

Command: `.venv/bin/python -m mypy api core integrations config.py --ignore-missing-imports`
**111 errors in 16 files** (checked 28 source files). Common: implicit Optional, missing annotations.

## Build Results

`docker build` not run (Docker daemon not exercised in this session). Dockerfile is straightforward (`python:3.11-slim`, pip install, uvicorn CMD) and will hit the same `pkg_resources`/`eth-typing` pins issue unless `requirements.txt` is updated.

## Action Items
- [ ] Pin `setuptools<81` and `eth-typing<5` in `requirements.txt`; add `pytest-cov`
- [ ] Rename `pytest.ini` header `[tool:pytest]` → `[pytest]`; reconsider `--cov-fail-under=80`
- [ ] Fix patch targets in `tests/unit/test_api.py` (patch where used, or use a `BYPASS_NFT_GATE` fixture) — recovers 15 tests
- [ ] Mock `Web3` correctly in Uniswap integration tests (4 tests)
- [ ] Investigate 3 momentum strategy failures (`core/strategies/momentum.py`)
- [ ] Await `strategy.stop()` in `core/strategies/base.py:280`
- [ ] Run `black` once over the codebase to reset the format baseline; add flake8 config
- [ ] Add CI workflow and `.pre-commit-config.yaml`
- [ ] Remove tracked `*.backup*` and `celerybeat-schedule`
