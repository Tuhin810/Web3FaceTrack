# TASK.md — FaceChain Verify

Build spec for **HH Goa 2026 Shortlisting Task 3: Face Identification & Blockchain Verification**.

This file is the source of truth. Build exactly what's described here. If something is ambiguous, pick the simpler option and note the decision in `DECISIONS.md`.

---

## 1. What we're building

A CLI pipeline with three stages:

```
face scan (image)
   ↓  [stage 1] detect + encode face
   ↓  [stage 2] reverse-image search the web → candidate pages → re-verify faces on those pages
   ↓  [stage 3] hash the verified match into a canonical evidence record → anchor on-chain
verifiable, tamper-evident record
```

The deliverable is a GitHub repo with working code, a README, and a reproducible demo. **No website, no hosted frontend.**

The interesting engineering here is not "call a face API." It's:
- turning a fuzzy reverse-image hit into a **confirmed** face match (stage 2 re-verification),
- building a **canonical, reproducible** evidence hash so the on-chain record actually means something,
- proving tamper-evidence with a failing verification run.

---

## 2. Non-negotiable rules

Read these before writing code. They shape the design.

### 2.1 Consent-scoped operation
This pipeline identifies real people from photographs. It only ever runs against subjects who have consented.

- The pipeline **refuses to run** unless the query image maps to an enrolled subject in `data/consent/`.
- Enrollment requires a `consent.json` per subject: subject id, display name, ISO date, scope string, and a free-text `statement` field.
- For the demo, the subject is **you** (or a teammate who has explicitly agreed). Use your own public profile photo as the query image.
- Never commit face encodings, consent records, or query images of real people to git. `.gitignore` must cover `data/consent/`, `data/enrolled/`, `out/`.
- Scraped third-party faces used during re-verification are held **in memory only** and discarded after comparison. Never written to disk, never embedded in the evidence record.
- The README must carry a short, honest "Ethics and scope" section. Judges notice this; more importantly it's the correct thing to ship.

### 2.2 The search must be real
No hardcoded URLs, no pre-picked results, no "if subject == 'tuhin': return known_url".

- Every raw search API response is dumped verbatim to `out/<run_id>/search_raw.json`.
- The run report lists how many candidates came back, how many were fetched, how many passed face re-verification.
- If zero candidates match, the pipeline exits with a clear `NO_MATCH` status and still writes the run artifacts. A clean no-match is a valid, demonstrable outcome.

### 2.3 Reproducibility
Given the same query image and the same evidence JSON, the evidence hash must be byte-identical on any machine. This is what makes the on-chain anchor meaningful. Canonicalization rules are in §6.

---

## 3. Tech stack

Pick these unless you hit a hard blocker. Python-only for the pipeline avoids a Node/Python split.

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| Face detection + embedding | `insightface` (`buffalo_l`) on `onnxruntime` | Better than dlib and far easier to install. Fallback: `face_recognition` behind the same interface. |
| Image handling | `Pillow`, `numpy`, `opencv-python-headless` | |
| Reverse image search | SerpAPI (`google_lens` engine) as primary provider | Pluggable — see §5.2 |
| Image hosting (search needs a public URL) | `imgbb` API, with `0x0.st` fallback | Deleted/expiring uploads preferred |
| Page fetching | `httpx` + `selectolax` | Respect `robots.txt`, 1 req/sec, real UA string |
| Chain client | `web3.py` | |
| Contract compile | `py-solc-x` (solc 0.8.24) | Keeps everything in Python. Hardhat is acceptable if you prefer, but then document the extra setup. |
| Network | Polygon Amoy testnet (primary), Anvil/Ganache local (fallback) | Amoy faucet is free; local chain means the demo never fails on RPC |
| CLI | `typer` | |
| Config | `pydantic-settings` + `.env` | |
| Tests | `pytest` | |

---

## 4. Repo structure

```
facechain-verify/
├── README.md
├── TASK.md                      # this file
├── DECISIONS.md                 # log deviations from this spec
├── requirements.txt
├── .env.example
├── .gitignore
├── contracts/
│   └── MatchRegistry.sol
├── src/facechain/
│   ├── __init__.py
│   ├── cli.py                   # typer app, all commands
│   ├── config.py                # settings, env loading
│   ├── consent.py               # enrollment + consent gate
│   ├── face.py                  # detect, embed, compare
│   ├── hosting.py               # upload query image, return public URL
│   ├── search/
│   │   ├── base.py              # SearchProvider protocol
│   │   ├── serpapi_lens.py
│   │   ├── bing_visual.py       # optional second provider
│   │   └── offline.py           # replays a saved search_raw.json, for dev/CI
│   ├── scrape.py                # fetch candidate page, extract images + text + meta
│   ├── matcher.py               # orchestrates stage 2, returns ranked MatchCandidates
│   ├── evidence.py              # canonical JSON, hashing, record ids
│   ├── chain/
│   │   ├── compile.py
│   │   ├── deploy.py
│   │   ├── anchor.py
│   │   └── verify.py
│   ├── pipeline.py              # wires stages 1→2→3
│   └── report.py                # human-readable run summary
├── scripts/
│   ├── run_demo.sh
│   └── tamper_test.sh
├── tests/
│   ├── test_evidence_canonical.py
│   ├── test_face.py
│   ├── test_chain_roundtrip.py
│   └── fixtures/
├── data/                        # gitignored
│   ├── consent/
│   └── enrolled/
└── out/                         # gitignored
```

---

## 5. Stage contracts

Each stage is a pure-ish function with a typed input and output. Build them in order and make each one independently runnable from the CLI, so a broken stage 2 doesn't block work on stage 3.

### 5.1 Stage 1 — Face detection and encoding

`src/facechain/face.py`

```python
@dataclass(frozen=True)
class FaceEncoding:
    vector: np.ndarray        # float32, L2-normalized, shape (512,)
    bbox: tuple[int,int,int,int]
    det_score: float
    model: str                # "insightface/buffalo_l"

def detect_faces(image: bytes | Path) -> list[FaceEncoding]: ...
def primary_face(image: bytes | Path) -> FaceEncoding: ...   # highest det_score; raises if 0 or if best < MIN_DET_SCORE
def similarity(a: FaceEncoding, b: FaceEncoding) -> float:   # cosine, range [-1, 1]
```

- `MIN_DET_SCORE = 0.60`
- `MATCH_THRESHOLD = 0.45` cosine similarity for "same person" (tune on your own photos; record the tuned value and how you picked it in `DECISIONS.md`)
- Multi-face query images: use the largest face by bbox area among those above `MIN_DET_SCORE`, and warn.

### 5.2 Stage 2 — Search and re-verification

This is the stage that satisfies "genuine search step."

**Provider interface** (`search/base.py`):

```python
@dataclass(frozen=True)
class SearchCandidate:
    page_url: str
    thumbnail_url: str | None
    title: str | None
    source: str            # "serpapi:google_lens"
    raw: dict              # verbatim provider entry

class SearchProvider(Protocol):
    name: str
    def search_by_image(self, image_url: str) -> list[SearchCandidate]: ...
```

**Flow:**

1. Upload the query image via `hosting.py`, get a public URL. Log the URL.
2. Call the provider. Dump the complete raw response to `out/<run_id>/search_raw.json`.
3. Filter candidates to likely social/profile domains first (instagram, x/twitter, linkedin, facebook, github, medium, personal domains), but **do not discard the rest** — process them after, up to `MAX_CANDIDATES = 15`.
4. For each candidate, `scrape.py`:
   - honour `robots.txt`; skip and log if disallowed
   - fetch HTML, extract: `og:image`, `og:title`, `og:description`, `<title>`, visible text (first 2000 chars), all `<img>` srcs above 200×200
   - fetch up to 5 images per page
5. For each fetched image, run `primary_face()` and `similarity()` against the query encoding.
6. A candidate **passes** if any image on it scores ≥ `MATCH_THRESHOLD`. Record best score and which image URL produced it.
7. Return candidates ranked by best score.

```python
@dataclass(frozen=True)
class VerifiedMatch:
    page_url: str
    matched_image_url: str
    similarity: float
    page_title: str | None
    page_text_excerpt: str
    matched_image_sha256: str
    fetched_at: str          # ISO 8601 UTC
```

Rate limit: 1 request/sec per domain, 10s timeout, 2 retries with backoff. Set a descriptive User-Agent that includes the repo URL.

### 5.3 Stage 3 — Blockchain anchoring

See §6 and §7.

---

## 6. Evidence record and canonical hashing

`src/facechain/evidence.py`

**Evidence JSON** (this is the artifact written to `out/<run_id>/evidence.json`):

```json
{
  "schema": "facechain-verify/evidence/1",
  "run_id": "2026-09-02T11-04-33Z-8f3a1c",
  "created_at": "2026-09-02T11:04:33Z",
  "subject_id": "tuhin",
  "query": {
    "image_sha256": "…",
    "image_phash": "…",
    "face_model": "insightface/buffalo_l",
    "det_score": 0.94
  },
  "search": {
    "provider": "serpapi:google_lens",
    "hosted_query_url": "https://i.ibb.co/…",
    "candidates_returned": 42,
    "candidates_fetched": 15,
    "candidates_matched": 1,
    "search_raw_sha256": "…"
  },
  "match": {
    "page_url": "https://…",
    "page_title": "…",
    "page_text_sha256": "…",
    "matched_image_url": "https://…",
    "matched_image_sha256": "…",
    "similarity": 0.612,
    "match_threshold": 0.45,
    "fetched_at": "2026-09-02T11:04:29Z"
  },
  "pipeline_version": "0.1.0"
}
```

Note what is **not** in there: no face vectors, no raw images, no scraped third-party face data. Hashes and URLs only.

**Canonicalization** — hash stability depends entirely on this being exact:

1. Serialize with `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
2. Encode UTF-8
3. `evidence_hash = keccak256(bytes)` — use `Web3.keccak`, not sha3
4. `record_id = keccak256(query.image_sha256 + "|" + match.page_url)` (UTF-8, same keccak)

Write `evidence.json` with the **exact canonical bytes**, not a pretty-printed variant. Provide a `--pretty` copy alongside as `evidence.pretty.json` for humans if you want, but never hash that one.

Write a unit test that round-trips the canonical form and asserts a known-good hash on a fixture.

---

## 7. Smart contract

`contracts/MatchRegistry.sol`, Solidity `^0.8.20`.

```solidity
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MatchRegistry {
    struct Record {
        bytes32 evidenceHash;
        address submitter;
        uint64  timestamp;
        string  uri;          // optional off-chain pointer (IPFS CID), may be ""
    }

    mapping(bytes32 => Record) private _records;
    bytes32[] public recordIds;

    event MatchAnchored(
        bytes32 indexed recordId,
        bytes32 indexed evidenceHash,
        address indexed submitter,
        uint64  timestamp,
        string  uri
    );

    error AlreadyAnchored(bytes32 recordId);
    error NotFound(bytes32 recordId);

    function anchor(bytes32 recordId, bytes32 evidenceHash, string calldata uri) external {
        if (_records[recordId].timestamp != 0) revert AlreadyAnchored(recordId);
        _records[recordId] = Record(evidenceHash, msg.sender, uint64(block.timestamp), uri);
        recordIds.push(recordId);
        emit MatchAnchored(recordId, evidenceHash, msg.sender, uint64(block.timestamp), uri);
    }

    function get(bytes32 recordId) external view returns (Record memory r) {
        r = _records[recordId];
        if (r.timestamp == 0) revert NotFound(recordId);
    }

    function verify(bytes32 recordId, bytes32 evidenceHash) external view returns (bool) {
        Record storage r = _records[recordId];
        return r.timestamp != 0 && r.evidenceHash == evidenceHash;
    }

    function count() external view returns (uint256) {
        return recordIds.length;
    }
}
```

Deployment writes `out/deployment.<network>.json` with address, ABI, chain id, deployer, tx hash, block number. Commit the ABI (not the key) so verification works from a clean clone.

**Verification command must:**
1. Read `evidence.json`
2. Recompute `evidence_hash` and `record_id` from its contents
3. Call `get(record_id)` on-chain
4. Compare recomputed hash vs on-chain hash
5. Print `VERIFIED ✓` with block number, timestamp, submitter, explorer link — or `TAMPERED ✗` showing both hashes side by side

This step is the whole point of the task. Make its output clean and screenshot-friendly.

---

## 8. CLI

```
facechain enroll   --subject tuhin --image ./me.jpg --consent-statement "..."
facechain scan     --subject tuhin --image ./query.jpg [--provider serpapi|offline] [--no-anchor]
facechain deploy   --network amoy|local
facechain anchor   --evidence out/<run_id>/evidence.json
facechain verify   --evidence out/<run_id>/evidence.json
facechain report   --run out/<run_id>
```

`scan` runs the full pipeline end to end and anchors by default. Every command exits non-zero on failure with a readable message.

Statuses: `MATCHED_AND_ANCHORED`, `MATCHED_NOT_ANCHORED`, `NO_MATCH`, `CONSENT_DENIED`, `SEARCH_FAILED`.

---

## 9. Configuration

`.env.example` (commit this; never commit `.env`):

```
SERPAPI_KEY=
IMGBB_KEY=
RPC_URL_AMOY=https://rpc-amoy.polygon.technology
RPC_URL_LOCAL=http://127.0.0.1:8545
PRIVATE_KEY=            # testnet-only key, never a real one
CONTRACT_ADDRESS=
MATCH_THRESHOLD=0.45
MAX_CANDIDATES=15
```

Fail fast with a clear message if a required key is missing for the chosen path.

---

## 10. Acceptance criteria

The build is done when all of these pass:

1. `pip install -r requirements.txt` works from a clean venv on Linux and macOS.
2. `facechain enroll` creates a consent record and enrolled encoding for one subject.
3. `facechain scan` with no consent record exits `CONSENT_DENIED`.
4. `facechain deploy --network local` deploys against Anvil/Ganache and writes the deployment file.
5. `facechain deploy --network amoy` deploys to Polygon Amoy; address is visible on the Amoy explorer.
6. `facechain scan --subject <you> --image <your photo>` performs a live search, produces `search_raw.json` with a real provider response, finds ≥1 verified match, writes `evidence.json`, and anchors it. Transaction hash printed with an explorer link.
7. `facechain verify` on that evidence prints `VERIFIED ✓`.
8. **Tamper test** (`scripts/tamper_test.sh`): copy the evidence, change one character in `match.page_url`, run `verify` → prints `TAMPERED ✗` and exits non-zero.
9. Re-running `anchor` on the same evidence reverts with `AlreadyAnchored`, handled gracefully.
10. `pytest` passes; the canonical-hash test asserts a fixed known hash.
11. `--provider offline` replays a saved `search_raw.json` so the pipeline is testable without API keys or network.

---

## 11. README requirements

The task explicitly grades the README. It must cover:

- **What it does** — one paragraph plus the pipeline diagram
- **Architecture** — the three stages, what each produces
- **Setup** — Python version, install, model download, API keys, faucet link for Amoy
- **Usage** — every CLI command with real example output
- **Which blockchain and why** — Polygon Amoy testnet, chain id 80002, contract address, explorer link, why a testnet was chosen
- **How verification works** — canonicalization rules, what's hashed, what tamper-evidence does and doesn't prove
- **Demo transcript** — the successful run and the tamper test, with terminal output pasted in
- **Ethics and scope** — consent gate, what's never stored, why this shouldn't be pointed at strangers
- **Known limitations** — §12
- **License** — MIT

---

## 12. Known limitations (write these honestly in the README)

- Reverse image search returns *visually similar pages*, not *identity matches*. The face re-verification step is what upgrades a hit to a match, and it's imperfect in both directions.
- Coverage depends entirely on the search provider's index. Instagram and Facebook are largely unindexed; LinkedIn, X, GitHub, news sites, and personal domains work far better. Expect no-match results on private individuals — that is correct behaviour, not a bug.
- Cosine threshold trades false positives against false negatives. `0.45` is tuned on a small sample and is not a production-grade decision boundary.
- Anchoring proves *"this exact record existed at this block time and hasn't changed since."* It does **not** prove the match is correct, that the page was authentic, or that the page still says the same thing today. Say this plainly.
- Linked content is mutable. The page can change or vanish after anchoring; only our snapshot's hash is fixed. Optionally mitigate by pinning the evidence JSON to IPFS and storing the CID in `uri`.
- Testnet finality and free RPC endpoints are unreliable; the local chain path exists so the demo always runs.
- Face recognition accuracy varies across demographics. Do not present this as an identification system.

---

## 13. Build order

Work in this sequence, commit at each step:

1. Scaffold repo, `requirements.txt`, config, CLI skeleton, `.gitignore`
2. `face.py` + tests against two photos of the same person and two of different people
3. `consent.py` + `enroll` command
4. `evidence.py` + canonical hash test (do this **before** the chain work — everything downstream depends on it)
5. Contract + `compile.py` + `deploy.py` + `anchor.py` + `verify.py`, all against local Anvil first
6. `scripts/tamper_test.sh` — get tamper-evidence provably working on local chain
7. `hosting.py`, then `search/serpapi_lens.py`, then `search/offline.py` from a captured response
8. `scrape.py` + `matcher.py`
9. `pipeline.py` wiring all three stages, `report.py`
10. Deploy to Amoy, run the full live demo, capture terminal output
11. README with the real transcripts pasted in

---

## 14. Stretch goals (only if the above is complete and demoed)

- Pin `evidence.json` to IPFS (web3.storage) and put the CID in the contract's `uri` field
- Second search provider for cross-checking, with agreement noted in the evidence record
- EIP-712 signed evidence so the submitter attests to the record, not just the tx sender
- `facechain audit` that walks all `recordIds` and re-verifies each against local evidence files
- Merkle-batch multiple runs into one anchor transaction to cut gas