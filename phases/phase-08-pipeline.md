# Phase 8 — Pipeline wiring + report

**Depends on:** Phases 2, 3, 5, 7 · **Est:** 0.75d · **Unblocks:** Phases 9, 10

This is the join point for the two parallel tracks (chain and search).

Spec: `Task.md` §8

## Tasks

- [ ] `pipeline.py` — stages 1→2→3, consent gate first, anchoring on by default, `--no-anchor` honoured
- [ ] All five statuses reachable and tested: `MATCHED_AND_ANCHORED`, `MATCHED_NOT_ANCHORED`, `NO_MATCH`, `CONSENT_DENIED`, `SEARCH_FAILED`
- [ ] `report.py` — human-readable summary: candidate counts, best scores, status, tx link
- [ ] `facechain report --run out/<run_id>` regenerates from artifacts alone, with no re-run
- [ ] Every command exits non-zero on failure with a readable message
- [ ] `scripts/run_demo.sh`
- [ ] Each stage remains independently runnable from the CLI

## Notes

`report` reading only from the run directory is what proves the artifacts are complete —
if it needs to re-run anything, something the evidence record should have captured is missing.

## Gate

`scan --provider offline` produces a complete run directory and a report from a cold start.
