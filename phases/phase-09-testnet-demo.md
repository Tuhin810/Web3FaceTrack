# Phase 9 — Testnet deploy + live demo

**Depends on:** Phases 4, 8 · **Est:** 0.5d · **Unblocks:** Phase 11

Acceptance: AC5, AC6, AC7

## Tasks

- [ ] Fund a **throwaway** testnet key from the Polygon Amoy faucet
- [ ] `deploy --network amoy`; confirm the address on the Amoy explorer (AC5)
- [ ] Live `scan` with your own photo: real search, real `search_raw.json`, ≥1 verified match, evidence anchored, tx hash + explorer link printed (AC6)
- [ ] `verify` on that evidence → `VERIFIED ✓` (AC7)
- [ ] Capture: full successful transcript, tamper-test transcript, explorer screenshots
- [ ] If the live search genuinely returns no match: capture that transcript too, and demo the matched path offline — say so honestly rather than faking a hit

## Notes

**Target confirmed (DECISIONS D14):** the subject's GitHub avatar is public, and
`github.com/Tuhin810` is crawlable with the right `og:` tags. Capture a *second, different*
photo of the subject to use as the query — if the query is the same file as the page's
image, stage 2 proves nothing.

**Known tension:** AC6 requires ≥1 verified match from a live search, but §12 says private
individuals will legitimately return nothing. Pick a query photo that is actually indexed —
a GitHub or LinkedIn profile photo is the best bet; Instagram is largely unindexed. Decide
this before Phase 9 starts, and check by running a manual Google Lens search on the photo.

Amoy RPC and faucet flakiness is a real risk. The local Anvil path from Phase 4 is the
guaranteed demo; keep both transcripts.

## Gate

AC5, AC6, AC7 with real, pasteable terminal output.
