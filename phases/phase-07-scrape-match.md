# Phase 7 — Scrape + face re-verification (stage 2)

**Depends on:** Phases 1, 6 · **Est:** 1.5d · **Unblocks:** Phase 8

The engineering core of the task — turning a fuzzy reverse-image hit into a *confirmed*
match. Budget the most time here.

Spec: `Task.md` §5.2

## Tasks

- [x] `scrape.py` — honour `robots.txt` (skip + log on disallow); **validate the robots response is `text/*` before parsing** and cache per host — see DECISIONS D15, an image CDN was found serving `robots.txt` as a PNG with HTTP 200
- [x] Prefer the highest-resolution image variant a page offers — heavy JPEG recompression costs ~0.4 similarity (DECISIONS D13), 1 req/sec **per domain**, 10s timeout, 2 retries with backoff, descriptive User-Agent containing the repo URL
- [x] Extract `og:image`, `og:title`, `og:description`, `<title>`, first 2000 chars of visible text, all `<img>` srcs above 200×200; fetch max 5 images per page
- [x] `matcher.py` — social/profile domains prioritized (instagram, x, linkedin, facebook, github, medium, personal domains) but the remainder **not discarded**; cap at `MAX_CANDIDATES = 15`
- [x] Per fetched image: `primary_face()` + `similarity()` against the query encoding; candidate passes if any image scores ≥ `MATCH_THRESHOLD`
- [x] Record best score and which image URL produced it; return `VerifiedMatch[]` ranked by score
- [x] **Third-party faces held in memory only** — assert nothing touches disk; test this explicitly
- [x] Track counts: candidates returned / fetched / matched — these feed both the evidence record and the report

## Notes

The in-memory-only rule (§2.1) is an ethics requirement, not a performance one. A test
that asserts no image bytes are written during a matcher run is worth having and worth
mentioning in the README.

`NO_MATCH` is a valid, demonstrable outcome — it must still write full run artifacts and
exit cleanly. Do not let it become an error path.

## Status

**Complete, with real end-to-end proof.** 163 tests total (41 new: 21 matcher-logic +
scrape/matcher network tests). 148 green with no network or model.

`facechain match --image test.png --provider offline` runs the full stage-2 sweep against
the real 67-candidate fixture from Phase 6: 15 fetched (MAX_CANDIDATES), 0 matched --
correctly, since these are Harry Potter retail pages (D27). Real network run against
`github.com/Tuhin810` vs `github.com/torvalds` correctly separates a true match from an
unrelated profile (D33) -- the actual "fuzzy hit to confirmed match" claim the task is
about, proven, not just asserted from stubs.

Two real bugs found by running against live pages, not invented for demonstration: D31
(scoring only the "primary" face on a multi-face candidate image risks comparing the
wrong person, per D5's instability finding) and D32 (a 403 error page with an HTML body
was being silently parsed as real content -- content-type alone wasn't a sufficient
gate).

CLI: `facechain match --image <file> --provider offline|serpapi`.

## Gate

End-to-end run against the offline fixture; `NO_MATCH` path writes artifacts and exits
cleanly; no-disk-write test green.
