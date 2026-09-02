# Phase 4 — Chain: compile, deploy, anchor, verify (local first)

**Depends on:** Phase 3 · **Est:** 1d · **Unblocks:** Phases 5, 9

Spec: `Task.md` §7 · Acceptance: AC4, AC7, AC9

## Tasks

- [ ] `contracts/MatchRegistry.sol` exactly as specced, Solidity `^0.8.20`
- [ ] `chain/compile.py` — py-solc-x pinned to solc 0.8.24
- [ ] `chain/deploy.py` — writes `out/deployment.<network>.json` with address, ABI, chain id, deployer, tx hash, block number; **ABI committed**, key never
- [ ] `chain/anchor.py` — `AlreadyAnchored` custom error decoded and handled gracefully (AC9), not surfaced as a raw revert blob
- [ ] `chain/verify.py` — reads evidence, **recomputes** `evidence_hash` and `record_id` from its contents, calls `get(record_id)`, compares, prints `VERIFIED ✓` with block number, timestamp, submitter, explorer link
- [ ] `tests/test_chain_roundtrip.py` against local Anvil/Ganache

## Notes

Verify must recompute from the evidence file, never trust a hash stored alongside it —
otherwise the tamper test in Phase 5 proves nothing.

Custom-error decoding in web3.py needs the ABI to resolve the selector; without it
`AlreadyAnchored` shows up as an opaque revert. Wire that before AC9.

This command's output is the money shot of the whole task. Make it clean and
screenshot-friendly now, not in Phase 11.

## Gate

AC4, AC7, AC9 all pass on the local chain.
