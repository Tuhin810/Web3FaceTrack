# Phase 10 — Production hardening

**Depends on:** Phase 8 · **Est:** 1d · **Unblocks:** Phase 11

The gap between "the demo works" and "production level." Not in `Task.md`'s build order —
added because the acceptance criteria assume it (AC1's clean-venv install on two OSes,
§2.3's cross-machine hash stability). Do not skip.

Acceptance: AC1, AC10

## Tasks

- [ ] **Error taxonomy** — typed exceptions per failure mode; no bare traceback ever reaches the user
- [ ] **Structured logging** with `run_id` on every line; `--verbose` / `--quiet` flags
- [ ] **Secret-hygiene audit** — grep every artifact, log line, and committed file for API keys, private keys, and consent PII
- [ ] **Clean-venv install verified on Linux and macOS** (AC1) — containerize the Linux check
- [ ] Deterministic-hash check re-run in a second environment (closes Phase 3's gate properly)
- [ ] CI: `pytest` + lint + an offline-provider end-to-end run on every push
- [ ] Network resilience: RPC failover amoy→local, upload-host fallback exercised, rate-limit backoff tested
- [ ] Idempotency: re-running `scan` on the same image does not double-anchor
- [ ] Caps enforced everywhere — no unbounded fetch, no unbounded image size, all timeouts set
- [ ] `--help` text genuinely useful for all six commands

## Notes

The secret-hygiene audit should check git history, not just the working tree. If a consent
record or key was ever committed, `.gitignore` does not undo it.

## Gate

AC1 and AC10 pass on a clean clone in a fresh container with no local state, using the
offline provider.
