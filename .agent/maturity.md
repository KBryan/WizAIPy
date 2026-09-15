# Repository Maturity Classification

**Date**: 2026-09-14
**Level**: 2 — Better (CI + pre-commit added 2026-09-15; PR/issue templates still missing for Level 3)
**Justification**: Before this run the repo was Level 0 (AGENTS.md was an unfilled template, manifest.yml had empty source/tests/validation fields, no working validation commands documented). `/prime` produced a complete AGENTS.md and manifest.yml, and the discovered test/lint/format/typecheck commands all execute (Level 2). They execute but are not green — 21/54 tests fail and lint/format/types are far from clean — and the repo has no CI, no templates, and no `.pre-commit-config.yaml`, so it does not yet meet Level 3.

## What Exists
- `AGENTS.md` — fully populated (project overview, navigation, architecture, commands, risk model, escalation, env vars, known issues)
- `manifest.yml` — populated with entry point, paths + risk, validation, run, setup
- `.claude/` — hooks (pre/post tool use, stop, notification), 37 command skills, `settings.json`
- `requirements/agent.txt` — adws 2.12.1 pin
- `pytest.ini`, `tests/` (unit + integration, 71 test functions, shared `conftest.py`)
- Linters pinned in `requirements.txt`: black 23.11, flake8 6.1, mypy 1.7
- `Dockerfile`, `docker-compose.yml` (9 services), `k8s/`, `Procfile`, `scripts/deploy.sh`
- `README.md`, `QUICK_START.md`, `docs/API_DOCUMENTATION.md`, `docs/DEPLOYMENT_GUIDE.md`, `env.example`
- Alembic migrations

## What is Missing
- Green test baseline (21 failures — mostly test-side patch targets; see `.agent/baseline.md`)
- Active pytest config (`pytest.ini` uses `[tool:pytest]`, which pytest ignores; `pytest-cov` not in requirements)
- Working fresh install: `requirements.txt` lacks `setuptools<81` and `eth-typing<5` pins needed by `web3==6.12.0`
- flake8 / black / mypy configuration files (`setup.cfg`, `pyproject.toml`, or `.flake8`)
- PR / issue templates

## Path to Next Level (3 — More)
1. Fix `pytest.ini` header to `[pytest]`; add `pytest-cov` and drop `--cov-fail-under=80` until coverage is real.
2. Pin `setuptools<81` and `eth-typing<5` in `requirements.txt` (or upgrade web3 to 7.x).
3. Fix `tests/unit/test_api.py` patch targets (`api.routers.<router>.get_current_user` instead of `api.deps.get_current_user`) or set `BYPASS_NFT_GATE=true` in a test fixture — recovers ~15 tests.
4. Mock `Web3` in `tests/integration/test_integrations.py` Uniswap tests (4 tests) and fix 3 momentum-strategy assertions.
6. Add a `pyproject.toml`/`setup.cfg` with tool config so flake8/black/mypy settings are not repeated across CI and pre-commit.
7. Add `.github/PULL_REQUEST_TEMPLATE.md` mirroring the Review Expectations checklist.
