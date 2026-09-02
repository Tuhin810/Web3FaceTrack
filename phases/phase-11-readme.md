# Phase 11 — README & docs

**Depends on:** Phases 9, 10 · **Est:** 0.5d

`Task.md` §11 grades the README explicitly. Treat every bullet as a required section.

## Tasks

- [x] **What it does** — one paragraph plus the pipeline diagram
- [x] **Architecture** — the three stages, what each produces
- [x] **Setup** — Python version, install, model download, API keys, Amoy faucet link
- [x] **Usage** — every CLI command with **real** example output
- [x] **Which blockchain and why** — Polygon Amoy, chain id 80002, contract address, explorer link, testnet rationale
- [x] **How verification works** — canonicalization rules, what is hashed, what tamper-evidence does **and does not** prove
- [x] **Demo transcript** — success run + tamper test, pasted verbatim from Phases 5 and 9
- [x] **Ethics and scope** — consent gate, what is never stored, why this should not be pointed at strangers
- [x] **Known limitations** — all of `Task.md` §12, honestly, including demographic accuracy variance
- [x] **License** — MIT, with the license file
- [x] `DECISIONS.md` complete — threshold tuning table, every deviation from the spec

## Notes

§12's limitations are graded on honesty. State plainly that anchoring proves only "this
exact record existed at this block time and hasn't changed since" — not that the match is
correct, the page authentic, or the page unchanged today.

## Status

**Complete.** 600-line README with every §11 section, and **all nine transcripts captured
from real runs**, not illustrative: face detection, enrolment, deploy, consent refusal,
a clean NO_MATCH against the genuine 67-candidate search response, a confirmed match
anchored on-chain, `VERIFIED ✓`, `AlreadyAnchored`, and the 4/4 tamper test.

The limitations section carries the measured findings rather than generic caveats --
including the 2.7%-of-frame result that explains why a live-search match is not shown, and
the redeploy footgun found while capturing transcripts (D48). MIT `LICENSE` added.

## Gate

A stranger can clone, install, run the offline demo, and verify the on-chain record using
the README alone.
