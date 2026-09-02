# Phase 3 — Evidence record & canonical hashing

**Depends on:** Phase 0 · **Est:** 0.5d · **Unblocks:** Phase 4 (and everything downstream)

Do this **before** the chain work. Every anchored record hashes what this produces;
changing serialization later invalidates records already on chain.

Spec: `Task.md` §6 · Acceptance: AC10

## Tasks

- [x] `evidence.py` builds the exact §6 JSON shape — hashes and URLs only, never vectors, images, or scraped face data
- [x] Canonicalization: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` → UTF-8 → `Web3.keccak` (**not** sha3)
- [x] `record_id = keccak256(query.image_sha256 + "|" + match.page_url)`, UTF-8, same keccak
- [x] `evidence.json` written as the **exact canonical bytes**; optional `evidence.pretty.json` for humans, never hashed
- [x] `image_phash` computed for the query image
- [x] `tests/test_evidence_canonical.py` — fixture asserts a **fixed known hash literal**; add unicode and key-order-permutation cases

## Notes

`ensure_ascii=False` plus UTF-8 encoding is where cross-machine drift hides — the unicode
test case is not optional. The known-hash literal must be hardcoded in the test so any
serialization change fails loudly rather than silently producing a new hash.

## Status

**Complete.** 39 evidence tests, 95 total green. AC10 closed.

Known-good anchor, frozen in the test as a literal:
```
evidence_hash = 0xa075bde44c4015e476bb8a06ce3ff3bc9920f790288323afbb4a460db2f9732d
record_id     = 0xb14597effc1e43d15844b51096d2f8d35f2d9a3ca0a381376b1b8472385cb29c
```

Reproducibility confirmed across Python 3.9/3.12, randomised hash seeds, two locales, two
timezones, and an **independent stdlib reimplementation** touching no project code (D20).

Findings: D16 (a real ambiguity in the spec's `record_id` construction, caught by a test),
D17 (pHash pinned in-repo), D18 (float rounding), D19 (re-canonicalise, don't hash bytes).

CLI: `facechain evidence-hash --evidence <file>`.

## Gate

AC10. Known-hash test green, and re-run in a second environment (container or another
machine) to confirm byte-identity — that is the entire claim of `Task.md` §2.3.
