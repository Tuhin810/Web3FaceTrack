# Phase 6 — Hosting + search providers

**Depends on:** Phase 0 · **Est:** 1d · **Unblocks:** Phase 7

Spec: `Task.md` §5.2, §2.2 · Acceptance: AC11

## Tasks

- [x] `hosting.py` — imgbb primary with expiry set, `0x0.st` fallback; returns a public URL, logged
- [x] `search/base.py` — `SearchCandidate` dataclass + `SearchProvider` protocol
- [x] `search/serpapi_lens.py` — `google_lens` engine; **complete raw response dumped verbatim** to `out/<run_id>/search_raw.json`
- [x] `search/offline.py` — replays a saved `search_raw.json`; no keys, no network (AC11)
- [x] Capture one real SerpAPI response into `tests/fixtures/` for offline replay and CI
- [x] `SEARCH_FAILED` status on provider error, with run artifacts still written

## Notes

Capture the real response the *first* time you call SerpAPI, before building anything on
top of it. Every subsequent dev iteration runs against the fixture, which protects your
quota through Phase 7 — the phase that would otherwise burn it.

§2.2 is a hard rule: no hardcoded URLs, no subject-conditioned shortcuts. The verbatim
raw dump is the evidence that the search is real, so dump the whole response, unfiltered.

## Status

**Complete, with a real live capture.** 139 tests total (16 search + 8 hosting new), 127
green with no network or model. AC11 confirmed: `facechain search --image test.png
--provider offline` returns 67 candidates with zero keys and zero network calls.

**Real finding (D27), not just plumbing:** a live SerpAPI call against the subject's own
photo returned zero name/GitHub hits -- Google Lens matched the Harry Potter merchandise
scene, not the small (~2.7% of frame) face. This directly informs the Phase 9 photo
choice: a face-forward headshot will out-perform this scene photo for a genuine identity
match. Kept the messy real response as the permanent fixture anyway -- it's exactly the
kind of noisy input Phase 7's re-verification has to filter correctly.

Two real bugs found by the tests: D29 (a missing imgbb key crashed past the 0x0.st
fallback instead of triggering it), and the offline/live extraction-sharing design (D28)
that makes replay tests actual evidence for the live path rather than a parallel
reimplementation.

CLI: `facechain search --image <file> --provider offline|serpapi [--out <dir>]`.

## Gate

AC11 — the full pipeline runs with `--provider offline` on a machine with no API keys
and no network. This is what makes CI and a clean-clone judge run possible.
