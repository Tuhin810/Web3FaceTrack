# Phase 8 — Pipeline wiring + report

**Depends on:** Phases 2, 3, 5, 7 · **Est:** 0.75d · **Unblocks:** Phases 9, 10

This is the join point for the two parallel tracks (chain and search).

Spec: `Task.md` §8

## Tasks

- [x] `pipeline.py` — stages 1→2→3, consent gate first, anchoring on by default, `--no-anchor` honoured
- [x] All five statuses reachable and tested: `MATCHED_AND_ANCHORED`, `MATCHED_NOT_ANCHORED`, `NO_MATCH`, `CONSENT_DENIED`, `SEARCH_FAILED`
- [x] `report.py` — human-readable summary: candidate counts, best scores, status, tx link
- [x] `facechain report --run out/<run_id>` regenerates from artifacts alone, with no re-run
- [x] Every command exits non-zero on failure with a readable message
- [x] `scripts/run_demo.sh`
- [x] Each stage remains independently runnable from the CLI

## Notes

`report` reading only from the run directory is what proves the artifacts are complete —
if it needs to re-run anything, something the evidence record should have captured is missing.

## Status

**Complete.** 185 tests total (18 new pipeline/report + 4 consent), 170 green with no
network or model. All 15 CLI commands are implemented -- no `_todo` stubs remain.

Gate met: `facechain scan --subject tuhin --image test.png --provider offline --no-anchor`
from a cold start (`rm -rf out/`) writes a complete run directory --
`evidence.json`, `evidence.pretty.json`, `search_raw.json` (85KB verbatim),
`result.json` -- and renders a full report. `facechain report --run out/<run_id>` in a
fresh process reproduces it from disk alone (D37).

All five statuses are produced and tested, including the MATCHED path via a clearly
labelled synthetic fixture (D39), since the real captured response reaches NO_MATCH by
design (D27).

`scripts/run_demo.sh` runs the whole thing offline end to end and exits 0.

One real bug found by running the demo twice: it leaked `data/consent/demo_*/`
directories, because revoke deliberately keeps the consent record (D11). Fixed by adding
`revoke --purge` (D38) -- which turned out to be a genuine capability worth having for
erasure requests, not just demo cleanup.

## Gate

`scan --provider offline` produces a complete run directory and a report from a cold start.
