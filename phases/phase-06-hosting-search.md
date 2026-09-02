# Phase 6 — Hosting + search providers

**Depends on:** Phase 0 · **Est:** 1d · **Unblocks:** Phase 7

Spec: `Task.md` §5.2, §2.2 · Acceptance: AC11

## Tasks

- [ ] `hosting.py` — imgbb primary with expiry set, `0x0.st` fallback; returns a public URL, logged
- [ ] `search/base.py` — `SearchCandidate` dataclass + `SearchProvider` protocol
- [ ] `search/serpapi_lens.py` — `google_lens` engine; **complete raw response dumped verbatim** to `out/<run_id>/search_raw.json`
- [ ] `search/offline.py` — replays a saved `search_raw.json`; no keys, no network (AC11)
- [ ] Capture one real SerpAPI response into `tests/fixtures/` for offline replay and CI
- [ ] `SEARCH_FAILED` status on provider error, with run artifacts still written

## Notes

Capture the real response the *first* time you call SerpAPI, before building anything on
top of it. Every subsequent dev iteration runs against the fixture, which protects your
quota through Phase 7 — the phase that would otherwise burn it.

§2.2 is a hard rule: no hardcoded URLs, no subject-conditioned shortcuts. The verbatim
raw dump is the evidence that the search is real, so dump the whole response, unfiltered.

## Gate

AC11 — the full pipeline runs with `--provider offline` on a machine with no API keys
and no network. This is what makes CI and a clean-clone judge run possible.
