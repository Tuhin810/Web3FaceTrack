# FaceChain Verify

Consent-scoped face identification with tamper-evident, on-chain evidence.

## What it does

A three-stage CLI pipeline: it detects and encodes a face, performs a **real** reverse-image
search of the web, re-verifies each candidate page by running face recognition on the images
actually found there, then hashes the confirmed match into a canonical evidence record and
anchors that hash on a blockchain. The interesting part is not calling a face API — it is
turning a fuzzy "visually similar" hit into a *confirmed* match, and producing an evidence
record whose hash is reproducible byte-for-byte on any machine, so the on-chain anchor means
something.

```
  face scan (image)
        |
        |  [stage 1]  detect + encode face           -> 512-d ArcFace embedding
        v
        |  [stage 2]  reverse-image search the web   -> candidate pages
        |             re-verify faces on those pages -> confirmed matches
        v
        |  [stage 3]  canonical evidence record      -> keccak256 hash
        |             anchor on-chain                -> tx hash
        v
  verifiable, tamper-evident record
```

**This pipeline refuses to run against anyone who has not been enrolled with an explicit
consent record.** See [Ethics and scope](#ethics-and-scope).

> **Reviewing this?** [**QUICKSTART.md**](QUICKSTART.md) gets you from clone to a working
> run in about five minutes, with no API keys, no blockchain and no internet.

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Setup](#setup)
- [Usage](#usage)
- [Which blockchain, and why](#which-blockchain-and-why)
- [How verification works](#how-verification-works)
- [Demo transcript](#demo-transcript)
- [Ethics and scope](#ethics-and-scope)
- [Known limitations](#known-limitations)
- [Testing](#testing)
- [License](#license)

---

## Architecture

Each stage is independently runnable from the CLI, so a broken stage 2 never blocks work on
stage 3.

### Stage 1 — face detection and encoding (`face.py`)

InsightFace `buffalo_l` on onnxruntime: SCRFD for detection, ArcFace `w600k_r50` for the
embedding. Produces a frozen `FaceEncoding` — an L2-normalised float32 vector of shape
`(512,)`, the bounding box, the detector's confidence, and the model identity string that
ends up in the evidence record.

Two behaviours worth knowing:

- **The largest face wins, not the highest-scoring one.** In a group photo the subject is
  the big face in front, while a sharp background face can easily out-score them.
- **Tight crops are recovered.** A pre-cropped avatar (a 112×112 aligned thumbnail) detects
  as *zero* faces, because SCRFD needs context around a face. When a first pass finds
  nothing, the image is padded and retried. Profile pictures and search thumbnails are
  routinely shaped exactly like that, so without this, stage 2 would silently discard real
  matches.

**Produces:** a `FaceEncoding` for the query image.

### Stage 2 — search and re-verification (`hosting.py`, `search/`, `scrape.py`, `matcher.py`)

1. The query image is uploaded to a public host (imgbb, with an expiry set; `0x0.st` as
   fallback), because reverse-image search needs a URL a crawler can fetch.
2. A `SearchProvider` runs the search. The **complete raw response is dumped verbatim** to
   `out/<run_id>/search_raw.json` — that file is the evidence the search was genuine.
3. Candidates are ranked with likely profile domains first, but **nothing is discarded** —
   only truncated at `MAX_CANDIDATES` (15).
4. Each candidate page is fetched, honouring `robots.txt`, at 1 request/second **per
   domain**, with a 10s timeout and 2 retries.
5. **Every face on every fetched image** is compared against the query encoding — not just
   the "primary" one. On a multi-face page image, which face a largest-bbox rule selects is
   unstable under resizing and recompression, so scoring only that face risks comparing the
   query against the wrong person while the right one sits unchecked in the same frame.
6. A candidate passes if any face on any of its images scores at or above the threshold.

**Produces:** `VerifiedMatch[]`, ranked by similarity, plus the counts that feed the
evidence record.

Third-party images fetched here are held **in memory only** and discarded after comparison.

### Stage 3 — evidence and anchoring (`evidence.py`, `chain/`)

The evidence record contains hashes and URLs — never face vectors, raw images, or any
scraped biometric data. It is canonicalised, hashed with keccak256, and anchored in a
`MatchRegistry` contract.

**Produces:** `evidence.json` (canonical bytes), `evidence.pretty.json` (human-readable,
never hashed), `result.json`, and an on-chain transaction.

---

## Setup

**Requires Python 3.11+.** The `X | Y` type syntax in the stage contracts will not parse on
3.10 or earlier.

```bash
git clone <this repo> && cd facechain-verify
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
```

### Model download

The `buffalo_l` models (~280MB) download automatically to `~/.insightface/` on first use.
No manual step, but the first run is slow.

### API keys

Copy `.env.example` to `.env` and fill in what you need. **Keys are validated per code
path, not at import** — `--provider offline` needs none of them, which is what makes a
clean-clone demo and CI possible with no credentials at all.

| Variable | Needed for | Where to get it |
|---|---|---|
| `SERPAPI_KEY` | `--provider serpapi` | <https://serpapi.com> (free tier available) |
| `IMGBB_KEY` | `--provider serpapi` (optional; falls back to `0x0.st`) | <https://api.imgbb.com> |
| `PRIVATE_KEY` | `deploy`, `anchor` | A **testnet-only** key. Never a real one. |
| `RPC_URL_AMOY` | `--network amoy` | Defaults to the public Amoy endpoint |

**Polygon Amoy faucet:** <https://faucet.polygon.technology/> (select Amoy). You need a
small amount of test POL to deploy and anchor.

### A local chain, with no toolchain install

Anvil (`brew install foundry`) is the recommended local chain. If you would rather not
install a toolchain, this repo ships a pure-Python stand-in:

```bash
.venv/bin/python scripts/local_chain.py --fund 0x<your-test-private-key>
```

It serves `eth-tester` over JSON-RPC on `127.0.0.1:8545`, and the CLI cannot tell the
difference. It is fine for exercising the full command path, but it is **not**
production-representative — gas accounting and EVM-version behaviour are py-evm's, not
revm's. Use Anvil before trusting anything about gas.

---

## Usage

Every command exits non-zero on failure with a readable message. Logs go to **stderr**, so
stdout stays clean for piping.

```
facechain enroll   --subject tuhin --image me.jpg --consent-statement "..."
facechain scan     --subject tuhin --image query.jpg [--provider serpapi|offline] [--no-anchor]
facechain deploy   --network amoy|local
facechain anchor   --evidence out/<run_id>/evidence.json
facechain verify   --evidence out/<run_id>/evidence.json
facechain report   --run out/<run_id>
```

Plus per-stage commands for inspection: `faces`, `compare`, `subjects`, `revoke`,
`check-consent`, `evidence-hash`, `search`, `match`.

### Statuses

| Status | Exit | Meaning |
|---|---|---|
| `MATCHED_AND_ANCHORED` | 0 | A match was confirmed and anchored on-chain |
| `MATCHED_NOT_ANCHORED` | 0 | Match confirmed; anchoring skipped or unavailable |
| `NO_MATCH` | 0 | No candidate passed re-verification — **a valid outcome**, not a failure |
| `CONSENT_DENIED` | 3 | The subject is not enrolled, or the query face does not match theirs |
| `SEARCH_FAILED` | 1 | The search provider failed |

---

## Which blockchain, and why

**Polygon Amoy testnet, chain ID 80002.**

- **Why a testnet, not mainnet:** anchoring a hash costs gas, and this is a demonstration.
  Paying real money to prove a hash existed adds nothing to the argument. Amoy's faucet is
  free and its explorer is public, so the anchor is independently checkable by anyone.
- **Why Polygon:** cheap, fast finality, and a well-maintained public explorer at
  <https://amoy.polygonscan.com>.
- **Why a local chain is also supported:** free RPC endpoints are unreliable, and a demo
  that depends on someone else's uptime is a demo that fails when it matters. The local
  path always works.

The ABI is written to `out/MatchRegistry.abi.<network>.json` on deploy, so verification
works from a clean clone. The private key never is.

**Contract address:** not yet deployed to Amoy — see [Demo transcript](#demo-transcript)
for exactly what was and was not demonstrated.

---

## How verification works

### What gets hashed

The evidence record ([`TASK.md` §6](TASK.md)) holds the query image's SHA-256 and
perceptual hash, the face model identity, the search provider and candidate counts, the raw
response's SHA-256, and the matched page's URL, title, text hash, image URL, image SHA-256
and similarity score.

It contains **no face vectors, no images, and no scraped biometric data**.

### Canonicalisation

Hash stability depends entirely on this being exact:

1. `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
2. Encode UTF-8
3. `evidence_hash = keccak256(bytes)` — via `Web3.keccak`, **not** SHA3-256
4. `record_id = keccak256(image_sha256 + "|" + page_url)`

Floats are rounded before serialisation, because two machines can compute
`0.6120000000000001` and `0.612` for the same cosine similarity, and those are different
bytes and therefore different hashes.

Verification **re-canonicalises the parsed record** rather than hashing the file's raw
bytes. This separates formatting from content: a pretty-printed copy still verifies, while
changing any *value* does not.

Reproducibility is verified across Python 3.9/3.12, randomised hash seeds, two locales, two
timezones, and — most importantly — an **independent reimplementation using only `json` and
`Web3.keccak`**, touching none of this codebase. Anyone can recompute an anchored hash from
a published record without trusting this code.

### What tamper-evidence does and does not prove

Anchoring proves: **this exact record existed at this block time and has not changed
since.**

It does **not** prove:

- that the match is correct;
- that the page was authentic, or that its content was what it claimed;
- that the page still says the same thing today — linked content is mutable, and only the
  snapshot's hash is fixed;
- that the subject is who the page says they are.

---

## Demo transcript

Everything below is real output, captured from an actual run — not illustrative.

**What was demonstrated:** the complete pipeline against a live JSON-RPC chain on
`127.0.0.1:8545`, including real deployment, anchoring, verification and tamper detection.

**What was not:** deployment to Polygon Amoy, and a live SerpAPI search that reaches a
genuine match. Both are explained honestly in [Known limitations](#known-limitations). The
live search itself *does* work — see the committed 67-candidate response in
`tests/fixtures/`.

### 1. Detecting the face

```console
$ facechain faces --image me.jpg
1 face(s) detected in test.png  [MIN_DET_SCORE=0.6]
  1. score=0.835  bbox=(130, 92, 183, 155)  area=   3339 px^2 <- primary
model: insightface/buffalo_l  embedding: 512-d, L2-normalized
```

### 2. Enrolling a subject

```console
$ facechain enroll --subject tuhin --image me.jpg \
    --display-name "Tuhin Thakur" \
    --consent-statement "I consent to my own public profile photo being used for this demo."
enrolled tuhin (Tuhin Thakur)
  consented : 2026-09-02T21:06:33Z
  scope     : reverse-image-search-and-onchain-anchor
  model     : insightface/buffalo_l
  stored    : consent record + face encoding only (no photograph kept)
```

### 3. Deploying the contract

```console
$ facechain deploy --network local
deployed to local (chain id 131277322940537)
  address : 0xB1bA21D4109cC91034Ba7964a9515b5F2e6956d2
  tx      : 0x9cc43d390317fa6814243ed17537e0ecf4af88e0bd5ef85674c8feb8196bffcf
  block   : 18
  written : /Users/tuhin/Coding/Projects/Web3FaceTrack/out/deployment.local.json
```

### 4. The consent gate refusing an unenrolled subject

```console
$ facechain scan --subject stranger --image me.jpg --provider offline
================================================================
  facechain run report -- 2026-09-02T21-09-32Z-8bf066
================================================================
status   : CONSENT_DENIED
detail   : no consent record for subject 'stranger'. Run: facechain enroll --subject stranger ...

no evidence.json written (the run ended before stage 2 completed)
================================================================
CONSENT_DENIED
run directory: /Users/tuhin/Coding/Projects/Web3FaceTrack/out/2026-09-02T21-09-32Z-8bf066
$ echo $?
1
```

A run directory is still written. A refusal is an event worth evidencing.

### 5. A clean NO_MATCH against the real captured search response

This runs against the genuine 67-candidate Google Lens response committed in
`tests/fixtures/`. None of those pages contain the subject's face, so re-verification
correctly rejects all of them.

```console
$ facechain scan --subject tuhin --image me.jpg --provider offline --no-anchor
================================================================
  facechain run report -- 2026-09-02T21-09-19Z-5e2c10
================================================================
status   : NO_MATCH
detail   : no candidate passed face re-verification (15 fetched of 67 returned)
raw search response: search_raw.json (85,274 bytes)

query
-----
  subject    : tuhin
  image sha  : 64fd37f7f62e1a2b...
  image phash: c6f6718c0073e0fd
  face model : insightface/buffalo_l  (det_score 0.8347)

search
------
  provider   : offline:replay
  hosted url : offline-replay
  candidates : 67 returned, 15 fetched, 0 matched

no verified match
-----------------
  No candidate page contained a face matching the subject above the
  threshold. This is a valid outcome, not a failure (TASK.md 2.2).

evidence
--------
  hash       : 0x6c6ccd77f97c8c87d7ef09c4f23194d2ab7847221fd5fad601867dfbd5655b5a
  record id  : n/a (nothing to anchor without a match)
================================================================
NO_MATCH
run directory: /Users/tuhin/Coding/Projects/Web3FaceTrack/out/2026-09-02T21-09-19Z-5e2c10
```

### 6. A confirmed match, anchored on-chain

```console
================================================================
  facechain run report -- 2026-09-02T21-08-51Z-1d73ff
================================================================
status   : MATCHED_AND_ANCHORED
detail   : matched https://github.com/Tuhin810 at similarity 1.000
raw search response: search_raw.json (1,054 bytes)

query
-----
  subject    : tuhin
  image sha  : 64fd37f7f62e1a2b...
  image phash: c6f6718c0073e0fd
  face model : insightface/buffalo_l  (det_score 0.8347)

search
------
  provider   : offline:replay
  hosted url : offline-replay
  candidates : 2 returned, 2 fetched, 1 matched

verified match
--------------
  page       : https://github.com/Tuhin810
  title      : Tuhin810 - Overview
  image      : https://avatars.githubusercontent.com/u/111550237?v=4?s=400
  similarity : 1.0  (threshold 0.45)
  fetched at : 2026-09-02T21:08:54Z

evidence
--------
  record id  : 0xbd651b3c11476eefe50ad1fc81de2064110d2b2bafd5639a5cb2ccf41a52fdae
  hash       : 0xa977828f6e219fd220d9096b88ad91f0cff9677dcbb6de07f1cd5d4a1ba430f2

on-chain anchor
---------------
  tx hash  : 0xff8f2dde70faef58d913b241471774bda1d5d2fc2ef7ac13a6b6293ad987adb3
  block    : 19
================================================================
MATCHED_AND_ANCHORED
RUNDIR=/Users/tuhin/Coding/Projects/Web3FaceTrack/out/2026-09-02T21-08-51Z-1d73ff
```

### 7. Verifying the anchored record

```console
$ facechain verify --evidence out/<run_id>/evidence.json --network local
VERIFIED ✓
  record id      : 0xbd651b3c11476eefe50ad1fc81de2064110d2b2bafd5639a5cb2ccf41a52fdae
  block          : 19
  anchored at    : 2026-09-02T21:08:50Z
  submitter      : 0x6b2f447AFF93656a0D3c4743f7a71325C4a51B77
  hash           : 0xa977828f6e219fd220d9096b88ad91f0cff9677dcbb6de07f1cd5d4a1ba430f2
```

### 8. Re-anchoring is rejected

```console
$ facechain anchor --evidence out/<run_id>/evidence.json --network local   # again
AlreadyAnchoredError: record 0xbd651b3c11476eefe50ad1fc81de2064110d2b2bafd5639a5cb2ccf41a52fdae is already anchored
$ echo $?
1
```

### 9. The tamper test

```console
$ scripts/tamper_test.sh local
=== tamper_test.sh -- network: local ===

--- deploying a throwaway MatchRegistry to local
deployed to local (chain id 131277322940537)
  address : 0xe555539eA1357665D38eEd0E7f46963c8D1000Db
  tx      : 0x03461f9713555631281a250bf17f42d2a2f371479528b3e66d742dd87e423103
  block   : 20
  written : /Users/tuhin/Coding/Projects/Web3FaceTrack/out/deployment.local.json

--- enrolling demo subject (throwaway consent record, deleted at the end)

--- building and anchoring a real evidence record
ANCHORED
  record id : 0xbd64780bb4f4b1c93a99b6670a7ac833eed053d9f391be42768adb65664be2c7
  tx hash   : 0xa63411ee14c16784fe748daee75dac724aaf5f6a7bbb44a9aede17a2bcebb0f1
  block     : 21
  submitter : 0x6b2f447AFF93656a0D3c4743f7a71325C4a51B77

--- baseline: verifying the untouched, freshly anchored record

--- baseline VERIFIED
VERIFIED ✓
  record id      : 0xbd64780bb4f4b1c93a99b6670a7ac833eed053d9f391be42768adb65664be2c7
  block          : 21
  anchored at    : 2026-09-02T21:09:33Z
  submitter      : 0x6b2f447AFF93656a0D3c4743f7a71325C4a51B77
  hash           : 0x446427129a169677b9c4d08325e058bf78a7aa12910763d2d748586f343f5adf
PASS (exit 0)

--- TASK.md 10.8 case: match.page_url changed by one character
TAMPERED ✗
  record id      : 0x712b10be5f5eff82f325fda861d493218a61eb6113f41fabda874accc7426920
  recomputed hash: 0xd867dbc351f3b01237fb195f2acb4f51e1a2d23d4d7b8138bcc12d50ba135ab4
  on-chain hash  : (no record found under this id)
  the evidence's own record_id no longer matches any anchored record --
  either it was never anchored, or match.page_url or query.image_sha256
  (the fields record_id is derived from) were altered after anchoring.
PASS (exit 1)

--- same record id, changed match.similarity (both hashes shown)
TAMPERED ✗
  record id      : 0xbd64780bb4f4b1c93a99b6670a7ac833eed053d9f391be42768adb65664be2c7
  block          : 21
  anchored at    : 2026-09-02T21:09:33Z
  submitter      : 0x6b2f447AFF93656a0D3c4743f7a71325C4a51B77
  recomputed hash: 0xc3e64129df28109229b6f7cf90d222098177934ac951d63ec76c246192a67f01
  on-chain hash  : 0x446427129a169677b9c4d08325e058bf78a7aa12910763d2d748586f343f5adf
PASS (exit 1)

--- reformatted (different bytes, same content) still verifies
VERIFIED ✓
  record id      : 0xbd64780bb4f4b1c93a99b6670a7ac833eed053d9f391be42768adb65664be2c7
  block          : 21
  anchored at    : 2026-09-02T21:09:33Z
  submitter      : 0x6b2f447AFF93656a0D3c4743f7a71325C4a51B77
  hash           : 0x446427129a169677b9c4d08325e058bf78a7aa12910763d2d748586f343f5adf
PASS (exit 0)

=== 4 passed, 0 failed ===
```

The last case is the important one: **reformatting the record does not break verification,
but changing any value does.** That is canonicalisation doing real work, rather than any
byte difference tripping a false alarm.

---

## Ethics and scope

This pipeline identifies real people from photographs. That is not a neutral capability,
and the design reflects it.

**It only runs against subjects who have consented.**

- The pipeline **refuses to run** unless the query image maps to an enrolled subject.
- Enrolment requires a consent record: subject id, display name, ISO date, scope, and a
  free-text statement in the subject's own words.
- **Consent authorises a face, not a string.** Passing `--subject tuhin` with a stranger's
  photo is refused — the query face must match the enrolled encoding. Otherwise anyone
  could point the pipeline at an arbitrary person by borrowing an enrolled id.
- **The gate runs before anything leaves the machine** — before the query image is uploaded
  to any image host. A run denied *after* the upload would already have published the
  subject's photograph to a third party, failing at the only moment that mattered.

**What is never stored:**

- No photograph is kept. Enrolment derives the encoding and discards the image.
- Third-party faces scraped during re-verification are held **in memory only**, never
  written to disk, never embedded in the evidence record. A test watches the filesystem
  during a real fetch-and-decode cycle to prove it.
- Consent records, face encodings, query images and run artifacts are all gitignored, and a
  test asserts none of them has ever entered git history — because `.gitignore` does not
  undo a past commit.

**Consent can be withdrawn.** `facechain revoke` deletes the enrolled encoding and marks the
record; `--purge` removes the record entirely. Consent that cannot be withdrawn is not
consent.

**Why you should not point this at strangers.** Reverse image search plus face matching is a
surveillance capability. Used against someone who has not agreed, it is a tool for stalking,
doxxing, or worse — and its errors fall unevenly, since face recognition accuracy varies
across demographic groups. The consent gate is not a formality; it is the thing that
distinguishes this from something that should not exist.

---

## Known limitations

Stated plainly, because a system like this is more dangerous when oversold.

**Reverse image search returns *visually similar pages*, not *identity matches*.** The face
re-verification step is what upgrades a hit to a match, and it is imperfect in both
directions.

**A real, measured example from this project:** a live Google Lens search on the subject's
own GitHub avatar returned **67 candidates and zero mentions of them**. The photo is a
mirror selfie in a Harry Potter merchandise store, so Lens matched the Gryffindor robe and
the shop — the face occupies about **2.7% of the frame**. This is exactly the failure mode
above, and it is why a live-search match is not demonstrated here: the fix is a face-forward
query photo, not a code change.

**Coverage depends entirely on the search provider's index.** Instagram and Facebook are
largely unindexed; LinkedIn, X, GitHub, news sites and personal domains work far better.
Expect no-match results on private individuals — that is correct behaviour, not a bug.

**The threshold is not a production decision boundary.** `MATCH_THRESHOLD = 0.45` is the
spec's suggested starting value. Measured on the samples available here, different people
score between −0.08 and +0.21, and degraded copies of the same photo score +0.58 to +1.00 —
a comfortable margin against false positives. But **the false-negative rate is unmeasured**,
because that requires genuinely different photographs of the same person, which is a much
harder case than any degraded copy. See `DECISIONS.md` D6.

**Anchoring proves only that a record existed and has not changed.** Not that it is correct.
See [How verification works](#how-verification-works).

**Linked content is mutable.** The matched page can change or vanish after anchoring. Only
our snapshot's hashes are fixed. Pinning the evidence JSON to IPFS and storing the CID in
the contract's `uri` field would mitigate this; it is not implemented.

**Redeploying invalidates verification of earlier evidence.** `facechain deploy` overwrites
the deployment file, so evidence anchored against a previous contract will report
`TAMPERED ✗` — the record is intact, but it is being checked against a contract that never
saw it. Confusing when it happens; worth knowing about.

**Testnet finality and free RPC endpoints are unreliable.** The local chain path exists so
the demo never depends on someone else's uptime.

**Face recognition accuracy varies across demographics.** This is a well-documented property
of the model class, not something mitigated here. Do not present this as an identification
system.

---

## Testing

```bash
.venv/bin/python -m pytest                                 # everything (needs model + network)
.venv/bin/python -m pytest -m "not model and not network"  # no credentials, no internet
```

**221 tests.** The second command — 206 of them — is what CI runs, deliberately with **no
secrets configured**: if any test outside the `network` marker starts requiring an API key or
the internet, CI fails. That makes "runs from a clean clone with no credentials" a property
enforced rather than claimed.

CI additionally checks a clean-venv install on Ubuntu and macOS across Python 3.11 and 3.12,
lint and format (`ruff`), the secret-hygiene audit against full git history, and that the
canonical evidence hash is byte-identical on every platform.

---

## License

MIT. See [LICENSE](LICENSE).
