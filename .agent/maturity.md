# Repository Maturity Classification

**Date**: 2026-09-14
**Level**: 3 — More (CI, pre-commit, PR and issue templates added 2026-09-15; shared tool config in pyproject.toml/.flake8) — Level 3 criteria met; see Path to Next Level for Level 4
**Justification**: Started at Level 0 on 2026-09-14 (template AGENTS.md, empty manifest.yml, no working commands). Now: complete AGENTS.md and manifest.yml (Level 1); documented test/lint/format/typecheck commands that run, with a green suite of 105 tests (Level 2); CI on two Python versions, pre-commit hooks, PR and issue templates, a risk model with escalation triggers in AGENTS.md, and 37 agent skills under `.claude/commands` (Level 3). Lint/format/type debt remains but is measured, not blocking.

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

## Path to Next Level (4 — Custom)
1. Pay down the informational CI debt and flip each step to blocking: `black .` once over the tree (~30 files), then flake8 (~750, mostly whitespace), then mypy (110 errors in 15 files — start with the modules listed in the commented `[[tool.mypy.overrides]]` block in `pyproject.toml`).
2. Set `fail_under` in `[tool.coverage.report]` once coverage (46%) is meaningful; add tests for `core/tasks.py` and `api/routers/trade.py` real-data paths.
3. Team escalation paths: replace the single-maintainer contact in AGENTS.md with a CODEOWNERS file mapping the High-risk paths (auth, execution, registries, migrations) to required reviewers, and enable branch protection requiring CI + a CODEOWNERS review on `main`.
4. Enable private vulnerability reporting (Settings → Code security) so the security contact link in `.github/ISSUE_TEMPLATE/config.yml` works.
5. Register `skale` / `beam` tokens and Uniswap deployments in `core/tokens.py` / `core/contracts.py` before enabling those networks; add a per-network risk override to the risk model.
6. Route `/trade/execute` through the execution engine (or retire the engine) so there is one trade path to review, not two.
