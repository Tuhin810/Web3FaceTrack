# Quick start — for reviewers

**Five minutes, no API keys, no blockchain, no internet after install.**

Everything in Part 1 runs offline against a real search response captured and committed
to this repo. Parts 2 and 3 add the blockchain and live search if you want them.

---

## Part 1 — Install and run (5 min, no credentials)

### 1. Install

Needs **Python 3.11+** (the code uses `X | Y` type syntax, which 3.10 cannot parse).

```bash
python3 --version                 # must be 3.11 or newer
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .
.venv/bin/facechain --help
```

First run downloads the face model (~280 MB) to `~/.insightface/`. That happens once, on
the first command that needs it, and takes a minute or two.

### 2. Run the test suite

```bash
.venv/bin/python -m pytest -q -m "not model and not network"
```

Expect **206 passed**. This subset deliberately needs no API key and no internet — if any
of it started requiring credentials, that would be a bug. The full suite
(`pytest -q`, 221 tests) additionally uses the model and the network.

### 3. Provide a photo

**The repo contains no photographs.** That is deliberate: this tool identifies real people,
and committing anyone's face — or shipping a stranger's photo for reviewers to run face
recognition against — would contradict the consent model it exists to demonstrate.

Use a photo of **yourself**, or of someone who has agreed. Any clear, front-facing image:

```bash
cp ~/Desktop/my_photo.jpg query.jpg
```

> Framing matters more than you'd expect. A face filling ~20% of the frame works well;
> a face at 3% of a busy scene gets ignored in favour of the background. See
> [Known limitations](README.md#known-limitations) for the measurements behind that.

### 4. Stage 1 — detect and encode the face

```bash
.venv/bin/facechain faces --image query.jpg
```

```
1 face(s) detected in query.jpg  [MIN_DET_SCORE=0.6]
  1. score=0.860  bbox=(169, 39, 340, 280)  area= 41211 px^2 <- primary
model: insightface/buffalo_l  embedding: 512-d, L2-normalized
```

### 5. The consent gate — try it *before* enrolling

```bash
.venv/bin/facechain scan --subject me --image query.jpg --provider offline
echo "exit code: $?"
```

```
status   : CONSENT_DENIED
detail   : no consent record for subject 'me'. Run: facechain enroll --subject me ...
exit code: 1
```

**The pipeline refuses to run on anyone who is not enrolled.** Note it still writes a run
directory — a refusal is an event worth evidencing.

### 6. Enrol, then run the full pipeline

```bash
.venv/bin/facechain enroll --subject me --image query.jpg \
  --consent-statement "I consent to my own photograph being used for this review."

.venv/bin/facechain scan --subject me --image query.jpg --provider offline --no-anchor
```

You will get a full report ending in **`NO_MATCH`**, and **that is the correct result.**
The offline provider replays a real 67-candidate Google Lens response captured from a
different subject, so none of those pages contain your face. Re-verification refusing to
confirm them is the system working — see
[`Task.md` §2.2](Task.md): *"A clean no-match is a valid, demonstrable outcome."*

### 7. Inspect what the run produced

```bash
ls out/
```

You will see **three** run directories by now — the two refused runs from step 5, plus
this one. A refused run contains only `result.json`; the completed run has everything:

```bash
RUN=$(ls -dt out/*/ | head -1)      # newest run
ls "$RUN"
```

| File | What it is |
|---|---|
| `evidence.json` | The canonical record — **exact bytes that get hashed** |
| `evidence.pretty.json` | Human-readable copy, never hashed |
| `search_raw.json` | The provider's complete response, **verbatim** (85 KB) |
| `result.json` | Status, message, hashes |

```bash
.venv/bin/facechain report --run "$RUN"                    # rebuilt from those files alone
.venv/bin/facechain evidence-hash --evidence "$RUN/evidence.json"
```

`report` reads **only** the run directory — nothing in memory, no re-running. If it can
rebuild the full summary from disk, the artifacts are provably complete.

### 8. Verify the reproducibility claim yourself

This recomputes the anchored hash using **only `json` and `Web3.keccak`** — none of this
project's code:

```bash
.venv/bin/python -c "
import json; from web3 import Web3
o=json.load(open('tests/fixtures/evidence_known_good.json',encoding='utf-8'))
raw=json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
print('0x'+Web3.keccak(raw).hex().removeprefix('0x'))"
```

Must print exactly:

```
0xa075bde44c4015e476bb8a06ce3ff3bc9920f790288323afbb4a460db2f9732d
```

That value is frozen as a literal in `tests/test_evidence_canonical.py`. Anyone can
recompute an anchored hash from a published record without trusting this codebase.

---

## Part 2 — The blockchain (5 min, still no API keys)

Anvil is the normal choice, but this repo ships a pure-Python local chain so you need no
toolchain install.

### 1. Start a chain and deploy

```bash
# terminal 1
KEY=0x$(openssl rand -hex 32)
echo "$KEY"                                    # copy this
.venv/bin/python scripts/local_chain.py --fund "$KEY"
```

```bash
# terminal 2
export PRIVATE_KEY=<the key printed above>
.venv/bin/facechain deploy --network local
```

### 2. Anchor and verify

```bash
.venv/bin/facechain anchor --evidence tests/fixtures/evidence_known_good.json --network local
.venv/bin/facechain verify --evidence tests/fixtures/evidence_known_good.json --network local
```

```
VERIFIED ✓
  record id      : 0xb14597effc1e43d15844b51096d2f8d35f2d9a3ca0a381376b1b8472385cb29c
  block          : 3
  anchored at    : 2026-09-02T21:04:24Z
  submitter      : 0x6b2f447AFF93656a0D3c4743f7a71325C4a51B77
  hash           : 0xa075bde44c4015e476bb8a06ce3ff3bc9920f790288323afbb4a460db2f9732d
```

### 3. Try to anchor it twice

```bash
.venv/bin/facechain anchor --evidence tests/fixtures/evidence_known_good.json --network local
echo "exit code: $?"
```

```
AlreadyAnchoredError: record 0xb14597ef... is already anchored
exit code: 1
```

The record id is derived from the content, so identical evidence cannot be anchored twice.

### 4. The tamper test

```bash
export PRIVATE_KEY=<the same key>
bash scripts/tamper_test.sh local
```

Runs four cases and prints **`4 passed, 0 failed`**:

| Case | Expected |
|---|---|
| Untouched record | `VERIFIED ✓` |
| One character changed in `match.page_url` | `TAMPERED ✗` |
| `match.similarity` changed | `TAMPERED ✗`, both hashes shown |
| **Reformatted, same content** | **`VERIFIED ✓`** |

The last case is the interesting one: reformatting does not break verification, but
changing any *value* does. That is canonicalisation doing real work, rather than any byte
difference tripping a false alarm.

---

## Part 3 — Live reverse-image search (optional, needs your own key)

Part 1 replays a **real** captured response, so you can confirm the search is genuine
without spending anything. To run it live, use your own free key from
[serpapi.com](https://serpapi.com):

```bash
cp .env.example .env
# add SERPAPI_KEY=... to .env
.venv/bin/facechain scan --subject me --image query.jpg --provider serpapi --no-anchor
```

A `NO_MATCH` is still the likely and correct outcome unless your photo is already indexed
by Google on a public page.

---

## Where to look in the code

| Concern | File |
|---|---|
| Face detection and encoding | [`src/facechain/face.py`](src/facechain/face.py) |
| Consent gate | [`src/facechain/consent.py`](src/facechain/consent.py) |
| Search providers | [`src/facechain/search/`](src/facechain/search/) |
| Scraping, robots, rate limits | [`src/facechain/scrape.py`](src/facechain/scrape.py) |
| Face re-verification (stage 2) | [`src/facechain/matcher.py`](src/facechain/matcher.py) |
| Canonical hashing | [`src/facechain/evidence.py`](src/facechain/evidence.py) |
| Contract and chain client | [`contracts/`](contracts/), [`src/facechain/chain/`](src/facechain/chain/) |
| **Every judgement call and deviation** | [`DECISIONS.md`](DECISIONS.md) |

`DECISIONS.md` is where the real engineering record lives: 53 entries, including the
defects found while building and what the evidence for each was.

---

## Troubleshooting

**`no faces detected`** — the face may be too small or too side-on. Try a closer, more
front-facing photo. Detection needs `det_score >= 0.60`.

**`CONSENT_DENIED` after enrolling** — the query face must match the enrolled face.
Consent authorises a *face*, not a subject id, so a different person's photo is refused
even under an enrolled name.

**`cannot reach local RPC at http://127.0.0.1:8545`** — the chain in terminal 1 is not
running.

**`PRIVATE_KEY is not set`** — `export PRIVATE_KEY=0x...` in the shell you are running
`deploy` / `anchor` from. Use a throwaway key; never a real one.

**First command is slow** — the model is downloading. Once only.

**Install fails on Python 3.10 or older** — 3.11+ is required.
