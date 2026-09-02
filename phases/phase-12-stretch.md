# Phase 12 — Stretch goals

**Depends on:** Phase 11 complete and demoed

`Task.md` §14 is explicit: only start these once everything above is done. A half-finished
stretch goal scores worse than a clean core.

## Tasks

- [ ] Pin `evidence.json` to IPFS (web3.storage) and store the CID in the contract's `uri` field
- [ ] Second search provider (`bing_visual.py`) for cross-checking, with agreement noted in the evidence record
- [ ] EIP-712 signed evidence, so the submitter attests to the record rather than just the tx sender
- [ ] `facechain audit` — walk all `recordIds` and re-verify each against local evidence files
- [ ] Merkle-batch multiple runs into one anchor transaction to cut gas

## Notes

IPFS pinning is the highest-value one: it directly mitigates the "linked content is
mutable" limitation in §12, and the contract already has the `uri` field for it.
