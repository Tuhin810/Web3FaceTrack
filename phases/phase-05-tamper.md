# Phase 5 — Tamper-evidence proof

**Depends on:** Phase 4 · **Est:** 0.25d · **Unblocks:** Phase 8

Spec: `Task.md` §10.8 · Acceptance: AC8

## Tasks

- [x] `scripts/tamper_test.sh` — copies the evidence file, mutates one character of `match.page_url`, runs `verify`
- [x] Prints `TAMPERED ✗` showing **both hashes side by side**; exits non-zero
- [x] Second case worth adding: mutate only whitespace or key order → decide and document whether the record still verifies (it should, if canonicalization is correct) 
- [ ] Capture the terminal output — it goes verbatim into the README

## Notes

The whitespace/key-order case is the more interesting demo: it shows canonicalization is
doing real work, not just that a different file hashes differently. Worth 10 extra minutes.

## Status

**Built and unit-tested; not yet run as a live shell script.** `scripts/tamper_test.sh`
exists, is syntax-checked, and correctly aborts (exit 2) rather than silently no-op when
no PRIVATE_KEY is configured. Its logic -- 3 cases: page_url mutation, similarity
mutation, reformatting -- is proven by 5 new tests in `test_chain_roundtrip.py` against
`verify_report()`, the same function the script's `facechain verify` calls into (115
tests total green).

Real finding, not a workaround: §6's own record_id formula makes the spec's literal
tamper case (mutate `match.page_url`) shift the record's *identity*, not just its hash --
see D25. `verify_report()` resolves this by folding "no record found" and "hash mismatch"
into one TAMPERED verdict, with the reason preserved for detail.

Attempted an HTTP JSON-RPC shim (`scripts/local_chain.py`) to get a fully live CLI
transcript without installing Anvil; it works for reads but not contract deployment --
see D26. Left in the repo as a documented, non-load-bearing dev convenience.

**To close:** install Anvil, run `scripts/tamper_test.sh local` for real, capture the
transcript for Phase 11.

## Gate

AC8 passes; transcript captured for Phase 11.
