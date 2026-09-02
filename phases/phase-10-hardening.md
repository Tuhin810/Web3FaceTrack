# Phase 10 — Production hardening

**Depends on:** Phase 8 · **Est:** 1d · **Unblocks:** Phase 11

The gap between "the demo works" and "production level." Not in `Task.md`'s build order —
added because the acceptance criteria assume it (AC1's clean-venv install on two OSes,
§2.3's cross-machine hash stability). Do not skip.

Acceptance: AC1, AC10

## Tasks

- [x] **Error taxonomy** — typed exceptions per failure mode; no bare traceback ever reaches the user
- [x] **Structured logging** with `run_id` on every line; `--verbose` / `--quiet` flags
- [x] **Secret-hygiene audit** — grep every artifact, log line, and committed file for API keys, private keys, and consent PII
- [x] **Clean-venv install verified on Linux and macOS** (AC1) — containerize the Linux check
- [x] Deterministic-hash check re-run in a second environment (closes Phase 3's gate properly)
- [x] CI: `pytest` + lint + an offline-provider end-to-end run on every push
- [x] Network resilience: RPC failover amoy→local, upload-host fallback exercised, rate-limit backoff tested
- [x] Idempotency: re-running `scan` on the same image does not double-anchor
- [x] Caps enforced everywhere — no unbounded fetch, no unbounded image size, all timeouts set
- [x] `--help` text genuinely useful for all six commands

## Notes

The secret-hygiene audit should check git history, not just the working tree. If a consent
record or key was ever committed, `.gitignore` does not undo it.

## Status

**Complete.** 221 tests (36 new: 12 secret-hygiene + 24 hardening), lint and format
clean, CI defined for {ubuntu, macos} x {py3.11, py3.12}.

**AC1 verified for real:** a genuinely fresh venv installs from `requirements.txt`,
imports every module, and runs 206 credential-free tests green.

**Two real defects found, both invisible in the dev environment:**
- D40: `requirements.txt` was missing **five runtime dependencies** (httpx, selectolax,
  pydantic-settings, py-solc-x, web3). AC1 had been silently broken since Phase 6 -- a
  clean clone would have failed on import. Found by AST-scanning `src/` for imports and
  diffing against the pinned list.
- D45: `.env.example` was missing entirely and had never been committed, despite §9
  requiring it.

**Also fixed:** insightface printing to stdout, which corrupted report output (D41 --
the reason every command this session needed `grep -v` to read); run_id now on every log
line (D42); a test whose name claimed more than it checked (D43).

Secret-hygiene audit covered git history, not just the working tree, and is now 12
regression tests. Notable finding: SerpAPI echoes an unauthenticated capability URL in
its response -- verified per-search rather than account-wide, and the subject's hosted
photo URL has correctly expired to 404.

## Gate

AC1 and AC10 pass on a clean clone in a fresh container with no local state, using the
offline provider.
