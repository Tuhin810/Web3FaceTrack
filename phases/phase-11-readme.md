# Phase 11 — README & docs

**Depends on:** Phases 9, 10 · **Est:** 0.5d

`Task.md` §11 grades the README explicitly. Treat every bullet as a required section.

## Tasks

- [ ] **What it does** — one paragraph plus the pipeline diagram
- [ ] **Architecture** — the three stages, what each produces
- [ ] **Setup** — Python version, install, model download, API keys, Amoy faucet link
- [ ] **Usage** — every CLI command with **real** example output
- [ ] **Which blockchain and why** — Polygon Amoy, chain id 80002, contract address, explorer link, testnet rationale
- [ ] **How verification works** — canonicalization rules, what is hashed, what tamper-evidence does **and does not** prove
- [ ] **Demo transcript** — success run + tamper test, pasted verbatim from Phases 5 and 9
- [ ] **Ethics and scope** — consent gate, what is never stored, why this should not be pointed at strangers
- [ ] **Known limitations** — all of `Task.md` §12, honestly, including demographic accuracy variance
- [ ] **License** — MIT, with the license file
- [ ] `DECISIONS.md` complete — threshold tuning table, every deviation from the spec

## Notes

§12's limitations are graded on honesty. State plainly that anchoring proves only "this
exact record existed at this block time and hasn't changed since" — not that the match is
correct, the page authentic, or the page unchanged today.

## Gate

A stranger can clone, install, run the offline demo, and verify the on-chain record using
the README alone.
