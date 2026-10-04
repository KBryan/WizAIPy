## Summary

<!-- What changed and why. One or two sentences is fine; link the issue if there is one. -->

## Risk

<!-- Tick everything this PR touches. Each row is an escalation trigger in AGENTS.md
     and needs a maintainer's review before merge. -->

- [ ] `api/auth.py`, `api/deps.py`, `api/routers/auth.py` — NFT gate / JWT / rate limiting
- [ ] `core/execution/`, `integrations/uniswap.py`, `core/tasks.py` — on-chain execution with the wallet key
- [ ] `core/tokens.py`, `core/contracts.py` — contract addresses or decimals
- [ ] `core/strategies/` — signal logic that drives trades
- [ ] `alembic/` — schema migration
- [ ] Default of `BYPASS_NFT_GATE`, `REAL_DATA_MODE`, or `DEBUG`
- [ ] None of the above

## Behaviour changes

<!-- Anything a running deployment would notice: different trades taken, different
     responses, new required env vars, changed limits. "None" is a valid answer. -->

## Test plan

<!-- How you verified it. Paste the pytest summary line. -->

- [ ] `pytest -m "not external"` passes locally (CI runs the same on 3.11 and 3.12)
- [ ] New behaviour has a test that fails without this change
- [ ] Manually exercised against a real RPC / service, if the change touches one (say what you ran)

## Checklist

- [ ] No unrelated changes; no generated files, `.env`, keys, or `celerybeat-schedule` included
- [ ] Commits follow `type(scope): description`
- [ ] `docs/API_DOCUMENTATION.md` updated if an endpoint changed
- [ ] `AGENTS.md` updated if setup, commands, architecture, or known issues changed

### If this touches trading / execution

- [ ] Tested with `REAL_DATA_MODE=false` and a mocked `Web3` first
- [ ] Amounts go through `core.tokens.to_base_units` (no hard-coded `10**18`)
- [ ] Addresses come from `core.tokens` / `core.contracts` (no literals)
- [ ] Slippage, `MAX_GAS_PRICE`, `MIN_TRADE_AMOUNT` limits respected

### If this includes a migration

- [ ] `downgrade()` implemented and tested
- [ ] No data loss; indexes added for new query patterns
