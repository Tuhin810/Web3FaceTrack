# Phase 7 — Scrape + face re-verification (stage 2)

**Depends on:** Phases 1, 6 · **Est:** 1.5d · **Unblocks:** Phase 8

The engineering core of the task — turning a fuzzy reverse-image hit into a *confirmed*
match. Budget the most time here.

Spec: `Task.md` §5.2

## Tasks

- [ ] `scrape.py` — honour `robots.txt` (skip + log on disallow), 1 req/sec **per domain**, 10s timeout, 2 retries with backoff, descriptive User-Agent containing the repo URL
- [ ] Extract `og:image`, `og:title`, `og:description`, `<title>`, first 2000 chars of visible text, all `<img>` srcs above 200×200; fetch max 5 images per page
- [ ] `matcher.py` — social/profile domains prioritized (instagram, x, linkedin, facebook, github, medium, personal domains) but the remainder **not discarded**; cap at `MAX_CANDIDATES = 15`
- [ ] Per fetched image: `primary_face()` + `similarity()` against the query encoding; candidate passes if any image scores ≥ `MATCH_THRESHOLD`
- [ ] Record best score and which image URL produced it; return `VerifiedMatch[]` ranked by score
- [ ] **Third-party faces held in memory only** — assert nothing touches disk; test this explicitly
- [ ] Track counts: candidates returned / fetched / matched — these feed both the evidence record and the report

## Notes

The in-memory-only rule (§2.1) is an ethics requirement, not a performance one. A test
that asserts no image bytes are written during a matcher run is worth having and worth
mentioning in the README.

`NO_MATCH` is a valid, demonstrable outcome — it must still write full run artifacts and
exit cleanly. Do not let it become an error path.

## Gate

End-to-end run against the offline fixture; `NO_MATCH` path writes artifacts and exits
cleanly; no-disk-write test green.
