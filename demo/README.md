# Demo server — for recording a video, NOT part of the deliverable

`Task.md` §1 is explicit: **"No website, no hosted frontend."** The graded deliverable is
the CLI, the repo and the README.

This directory exists only to record a screen-capture of the pipeline working. It is a
local-only tool: it binds to `127.0.0.1`, is never deployed, and adds no capability the
CLI does not already have — every stage it shows is the same `facechain` code path,
called directly. Delete this directory and nothing about the submission changes.

```bash
.venv/bin/python demo/server.py          # then open http://127.0.0.1:8000
```

Add `--network local` and run `scripts/local_chain.py` alongside it if you want the
anchoring and verification stages to be real rather than skipped.
