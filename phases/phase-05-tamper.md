# Phase 5 — Tamper-evidence proof

**Depends on:** Phase 4 · **Est:** 0.25d · **Unblocks:** Phase 8

Spec: `Task.md` §10.8 · Acceptance: AC8

## Tasks

- [ ] `scripts/tamper_test.sh` — copies the evidence file, mutates one character of `match.page_url`, runs `verify`
- [ ] Prints `TAMPERED ✗` showing **both hashes side by side**; exits non-zero
- [ ] Second case worth adding: mutate only whitespace or key order → decide and document whether the record still verifies (it should, if canonicalization is correct) 
- [ ] Capture the terminal output — it goes verbatim into the README

## Notes

The whitespace/key-order case is the more interesting demo: it shows canonicalization is
doing real work, not just that a different file hashes differently. Worth 10 extra minutes.

## Gate

AC8 passes; transcript captured for Phase 11.
