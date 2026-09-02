# Phase 3 — Evidence record & canonical hashing

**Depends on:** Phase 0 · **Est:** 0.5d · **Unblocks:** Phase 4 (and everything downstream)

Do this **before** the chain work. Every anchored record hashes what this produces;
changing serialization later invalidates records already on chain.

Spec: `Task.md` §6 · Acceptance: AC10

## Tasks

- [ ] `evidence.py` builds the exact §6 JSON shape — hashes and URLs only, never vectors, images, or scraped face data
- [ ] Canonicalization: `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)` → UTF-8 → `Web3.keccak` (**not** sha3)
- [ ] `record_id = keccak256(query.image_sha256 + "|" + match.page_url)`, UTF-8, same keccak
- [ ] `evidence.json` written as the **exact canonical bytes**; optional `evidence.pretty.json` for humans, never hashed
- [ ] `image_phash` computed for the query image
- [ ] `tests/test_evidence_canonical.py` — fixture asserts a **fixed known hash literal**; add unicode and key-order-permutation cases

## Notes

`ensure_ascii=False` plus UTF-8 encoding is where cross-machine drift hides — the unicode
test case is not optional. The known-hash literal must be hardcoded in the test so any
serialization change fails loudly rather than silently producing a new hash.

## Gate

AC10. Known-hash test green, and re-run in a second environment (container or another
machine) to confirm byte-identity — that is the entire claim of `Task.md` §2.3.
