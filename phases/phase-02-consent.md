# Phase 2 — Consent gate

**Depends on:** Phases 0, 1 · **Est:** 0.5d · **Unblocks:** Phase 8

Goal: the pipeline is *incapable* of running against a non-enrolled subject.

Spec: `Task.md` §2.1, §8 · Acceptance: AC2, AC3

## Tasks

- [x] `consent.json` schema: `subject_id`, `display_name`, `date` (ISO), `scope`, `statement`
- [x] `enroll` command → writes consent record + enrolled encoding into gitignored `data/`
- [x] Gate is checked **before** any network call, upload, or inference on the query image
- [x] Query image must match the enrolled subject's encoding — not merely name a subject id
- [x] `CONSENT_DENIED` exits non-zero with a readable message
- [x] Test: scan with no consent record → `CONSENT_DENIED`, and no `out/` artifact leaks a hosted URL

## Notes

Ordering is the subtle part. §2.1 says refuse unless enrolled, but the gate must fire
*before* `hosting.py` uploads to imgbb — otherwise a denied run has already published
the subject's photo to a third party. Assert this in a test, not just by reading the code.

Name-matching alone is not a consent gate: anyone could pass `--subject tuhin` with a
stranger's photo. The query face has to match the enrolled encoding.

## Status

**Complete.** 24 consent tests, 56 total green. AC2 and AC3 pass.

Beyond the spec: consent revocation (D11), which deletes the enrolled encoding rather
than merely flagging it. Exit codes: 3 = consent denied, 2 = unimplemented, 1 = other.

CLI: `enroll`, `subjects`, `revoke`, `check-consent`.

## Gate

AC2 and AC3 pass. Confirmed by test that no upload occurs before the gate.
