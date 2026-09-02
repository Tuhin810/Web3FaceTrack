# PHASES.md — FaceChain Verify

Execution plan derived from `Task.md`. One file per phase in [`phases/`](phases/).

Phases are ordered by **dependency**, not apparent difficulty. Each has a hard **exit
gate** — do not start a dependent phase until the gate passes. Commit at every checkpoint.
Acceptance references (`AC1`–`AC11`) point at `Task.md` §10.

## Index

| # | Phase | Depends on | Deliverable | Est. |
|---|-------|-----------|-------------|------|
| 0 | [Scaffold & contracts-of-record](phases/phase-00-scaffold.md) | — | Repo skeleton, config, CLI stubs, `DECISIONS.md` | 0.5d |
| 1 | [Face engine](phases/phase-01-face-engine.md) | 0 | `face.py` + tuned threshold + tests | 1d |
| 2 | [Consent gate](phases/phase-02-consent.md) | 0, 1 | `consent.py`, `enroll`, refusal path | 0.5d |
| 3 | [Evidence & canonical hashing](phases/phase-03-evidence.md) | 0 | `evidence.py` + fixed-hash test | 0.5d |
| 4 | [Chain, local first](phases/phase-04-chain-local.md) | 3 | Contract on Anvil, `VERIFIED ✓` | 1d |
| 5 | [Tamper-evidence proof](phases/phase-05-tamper.md) | 4 | `tamper_test.sh`, `TAMPERED ✗` | 0.25d |
| 6 | [Hosting + search providers](phases/phase-06-hosting-search.md) | 0 | `hosting.py`, serpapi, offline | 1d |
| 7 | [Scrape + re-verification](phases/phase-07-scrape-match.md) | 1, 6 | `scrape.py`, `matcher.py` | 1.5d |
| 8 | [Pipeline wiring + report](phases/phase-08-pipeline.md) | 2,3,5,7 | `scan` end-to-end, all 5 statuses | 0.75d |
| 9 | [Testnet deploy + live demo](phases/phase-09-testnet-demo.md) | 4, 8 | Amoy address, real tx, transcripts | 0.5d |
| 10 | [Production hardening](phases/phase-10-hardening.md) | 8 | Errors, logging, CI, clean-venv install | 1d |
| 11 | [README & docs](phases/phase-11-readme.md) | 9, 10 | Graded README with real transcripts | 0.5d |
| 12 | [Stretch](phases/phase-12-stretch.md) | 11 | IPFS `uri`, 2nd provider, EIP-712, `audit` | — |

## Parallel tracks

After Phase 1, the chain track (**3 → 4 → 5**) and the search track (**6 → 7**) share no
dependencies and can run concurrently. **Phase 8 is the join point.** If two people are
working, that is the split.

```
0 ──┬── 1 ──┬────────────── 2 ──────────┐
    │       └── 6 ── 7 ─────────────────┤
    └── 3 ── 4 ── 5 ────────────────────┴── 8 ──┬── 9 ──┬── 11 ── 12
                                                └── 10 ─┘
```

## Risk register

| Risk | Phase | Mitigation |
|---|---|---|
| insightface / onnxruntime install pain on macOS ARM | 1 | Pin versions early; `face_recognition` fallback behind the same interface |
| SerpAPI quota burned during dev | 6, 7 | Capture one real response immediately, develop against `offline` |
| Live search returns no match for the subject | 9 | Valid outcome — demo it honestly; offline provider covers the matched path |
| Amoy RPC / faucet flakiness | 9 | Local Anvil path is the guaranteed demo |
| Hash instability across machines | 3 | Fixed-hash test + second-environment check in Phase 10 |
| Scraping rate-limited or blocked | 7 | Per-domain 1 req/s, backoff, honest UA, skip-and-log on robots disallow |

## Definition of done

All 11 acceptance criteria in `Task.md` §10 pass on a clean clone, the README carries real
transcripts, `DECISIONS.md` explains every deviation, and no consent record, face encoding,
query image, or key exists anywhere in git history.
