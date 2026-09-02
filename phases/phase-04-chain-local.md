# Phase 4 — Chain: compile, deploy, anchor, verify (local first)

**Depends on:** Phase 3 · **Est:** 1d · **Unblocks:** Phases 5, 9

Spec: `Task.md` §7 · Acceptance: AC4, AC7, AC9

## Tasks

- [x] `contracts/MatchRegistry.sol` exactly as specced, Solidity `^0.8.20`
- [x] `chain/compile.py` — py-solc-x pinned to solc 0.8.24
- [x] `chain/deploy.py` — writes `out/deployment.<network>.json` with address, ABI, chain id, deployer, tx hash, block number; **ABI committed**, key never
- [x] `chain/anchor.py` — `AlreadyAnchored` custom error decoded and handled gracefully (AC9), not surfaced as a raw revert blob
- [x] `chain/verify.py` — reads evidence, **recomputes** `evidence_hash` and `record_id` from its contents, calls `get(record_id)`, compares, prints `VERIFIED ✓` with block number, timestamp, submitter, explorer link
- [x] `tests/test_chain_roundtrip.py` against local Anvil/Ganache

## Notes

Verify must recompute from the evidence file, never trust a hash stored alongside it —
otherwise the tamper test in Phase 5 proves nothing.

Custom-error decoding in web3.py needs the ABI to resolve the selector; without it
`AlreadyAnchored` shows up as an opaque revert. Wire that before AC9.

This command's output is the money shot of the whole task. Make it clean and
screenshot-friendly now, not in Phase 11.

## Status

**Functionally complete, gated on tooling.** 15 chain tests, 110 total green. All three
acceptance behaviours (AC4 deploy, AC7 verify, AC9 graceful AlreadyAnchored) proven
against `eth-tester` through the identical deploy/anchor/verify code path a real network
uses -- see D21 for exactly what is and isn't covered by that substitution.

**Not yet run:** the CLI commands (`facechain deploy/anchor/verify`) end-to-end against a
real listening chain, since no local chain binary (Anvil/Ganache) is installed in this
environment and it has no general internet access either. Confirmed instead: CLI error
handling is correct when no chain is reachable.

Two real bugs found and fixed by the test suite itself: D22 (a structurally broken
existence probe that let a duplicate anchor reach the chain), D23 (verify reported the
current chain tip instead of the anchoring block), D24 (missing `0x` prefix on tx hashes).

**To close:** install Anvil, run `facechain deploy --network local` -> `anchor` -> `verify`
for real, then Phase 5's tamper_test.sh against the same deployment.

## Gate

AC4, AC7, AC9 all pass on the local chain.
