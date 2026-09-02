# Phase 0 — Scaffold & contracts-of-record

**Depends on:** nothing · **Est:** 0.5d · **Unblocks:** every other phase

Goal: every later phase has a place to put its code and a way to run it, and nothing
sensitive can ever be committed.

## Tasks

- [ ] `git init`; repo tree exactly as `Task.md` §4
- [ ] `.gitignore` covering `data/consent/`, `data/enrolled/`, `out/`, `.env`, `__pycache__/`, `*.onnx`
- [ ] `requirements.txt` with **pinned** versions: insightface, onnxruntime, pillow, numpy, opencv-python-headless, httpx, selectolax, web3, py-solc-x, typer, pydantic-settings, pytest
- [ ] `config.py` — `pydantic-settings` Settings; **required-key validation is per-path, not global** (the offline provider must not demand `SERPAPI_KEY`)
- [ ] `.env.example` verbatim from `Task.md` §9
- [ ] `cli.py` — all six typer commands registered (`enroll`, `scan`, `deploy`, `anchor`, `verify`, `report`), each raising `NotImplementedError`
- [ ] Typed status enum: `MATCHED_AND_ANCHORED`, `MATCHED_NOT_ANCHORED`, `NO_MATCH`, `CONSENT_DENIED`, `SEARCH_FAILED`
- [ ] `DECISIONS.md` seeded with the "ambiguity → simpler option" log format
- [ ] Run-directory helper: `out/<run_id>/` where `run_id = <ISO8601-Z>-<6 hex>`

## Notes

The per-path key validation matters more than it looks. If `config.py` validates all
keys at import time, `--provider offline` breaks on a machine with no `.env` — and that
path is what makes CI and the judges' clean-clone run possible (Phase 6).

## Gate

`facechain --help` lists all six commands; `pytest` collects with zero failures on an
empty suite; `git status` shows no ignored path staged.
