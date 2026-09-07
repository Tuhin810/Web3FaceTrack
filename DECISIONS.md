# DECISIONS.md

Log of deviations from `Task.md` and of judgement calls the spec left open.
Format: **what** / **why** / **effect**.

---

## D1 — Python 3.12 via Homebrew (Phase 1)

**What:** The machine had only Python 3.9.6. Installed `python@3.12` with Homebrew and
created `.venv` from it.
**Why:** `Task.md` §3 requires 3.11+, and the §5.1 signatures use `X | Y` union syntax,
which 3.9 rejects at parse time.
**Effect:** None on the spec. `pyproject.toml` declares `requires-python = ">=3.11"`.

---

## D2 — insightface installed cleanly; plans B and C unused (Phase 1)

**What:** `insightface==1.0.1` installed from a prebuilt wheel on macOS arm64. No fallback
to a hand-rolled onnxruntime wrapper or to `face_recognition`/dlib was needed.
**Why:** The spec names `face_recognition` as the fallback. It would have been a genuine
deviation, not a drop-in: dlib produces **128-d** embeddings compared by Euclidean
distance, whereas §5.1 specifies a **512-d** vector compared by cosine, and dlib's HOG
detector returns no confidence score, so `MIN_DET_SCORE` would have no meaning.
**Effect:** The spec's contract holds exactly. `FaceBackend` keeps the seam open, so a
fallback can still be dropped in without touching callers.

---

## D3 — Only detection and recognition sub-models are loaded (Phase 1)

**What:** `FaceAnalysis(allowed_modules=["detection", "recognition"])`, so `genderage.onnx`
and the two landmark models are skipped.
**Why:** Two reasons. This pipeline runs face inference over photographs of third parties
scraped during stage 2 re-verification, and inferring their gender and age is not
something the task needs or should do. It also cuts model load time and memory.
**Effect:** Faster startup, and no demographic attributes are ever computed. Consistent
with the ethics posture in `Task.md` §2.1.

---

## D4 — Padded retry for tight-cropped images (Phase 1)

**What:** When the first detection pass returns zero faces, `detect_faces()` retries once
on a copy padded by 0.6× the long edge (replicated border) and upscaled to 640×640, then
maps the resulting boxes back into original-image coordinates.
**Why:** SCRFD needs context around a face. The bundled 112×112 pre-aligned crop
(`Tom_Hanks_54745.png`) detects as **zero faces** unpadded, and at **0.805** padded.
Profile pictures, `og:image` avatars and search thumbnails are routinely shaped exactly
like that, so without this, stage 2 would silently score them as "no face" and discard
real matches.
**Effect:** Not in the spec; a strict addition. Costs one extra inference pass only on
images that would otherwise have failed. Covered by
`test_tight_crop_recovered_by_padded_retry` and a bbox-round-trip test.

---

## D5 — `primary_face()` selects by bbox area, not detection score

**What:** Among faces clearing `MIN_DET_SCORE`, the largest by bbox area wins; ties break
on score.
**Why:** This is what §5.1 specifies, and it is right: in a group photo the subject is the
large face in front, while a sharp, well-lit background face can easily out-score them.
**Effect:** Measured on the bundled six-person group photo, the selected face is 15,729 px²
at score 0.920 — not the highest-scoring face. A warning is logged whenever more than one
face clears the threshold, as the spec requires.

**Observed caveat, worth carrying into Phase 7:** this selection is *unstable across image
transformations* on multi-face photos. Degrading the group photo (JPEG q25, quarter-size,
rotation) changed which face was selected — measured bbox areas ranged from 1,008 px² to
18,240 px² across variants. So when stage 2 compares a scraped group photo against the
query, `primary_face()` alone can compare the wrong person. Stage 2 must therefore score
the query against **every** detected face on a candidate image, not just its primary one.

---

## D6 — `MATCH_THRESHOLD` is still provisional at 0.45

**What:** Left at the spec's suggested `0.45`. **The Phase 1 tuning gate is NOT yet closed.**

**Measured so far** (buffalo_l, 7 distinct faces from insightface's bundled samples):

| Distribution | n | min | median | max |
|---|---|---|---|---|
| Different people (all cross-pairs) | 21 | −0.084 | −0.010 | **+0.213** |
| Same image, degraded (see below) | 10 | **+0.844** | +0.956 | +1.000 |

Degraded-copy scores: jpeg q25 +0.923, jpeg q10 +0.844, half size +0.959, upscaled 2×
+0.996, dark +0.940, bright +0.872, grayscale +1.000, rotated 8° +0.952, blurred +0.967,
horizontally flipped +0.961.

**Why this is not yet sufficient:** the second row is *robustness to image degradation*,
not *identity across genuinely different photographs*. Real same-person pairs — different
day, pose, lighting, age, camera — score far lower than degraded copies of one photo,
typically 0.4–0.8 for ArcFace-class models. That is exactly the region where the 0.45
boundary lives, so the current data cannot validate it.

**What is fair to conclude now:** the negative distribution is tightly clustered near zero
and tops out at +0.213, so 0.45 carries a comfortable margin against false positives on
this (small, non-adversarial) sample. The false-*negative* rate is entirely unmeasured.

**To close the gate:** `scripts/tune_threshold.py data/tuning` over a directory of
per-person photo folders (≥10 same-person pairs, ≥10 different-person pairs, per the
Phase 1 gate). It prints both distributions, the separation, the accuracy-optimal
threshold, and the most conservative zero-false-positive threshold. Update this section
with the real table and the final value.

---

## D7 — Both opencv builds are installed (Phase 1)

**What:** `requirements.txt` asks for `opencv-python-headless`, but `insightface` declares
a hard dependency on `opencv-python`, so both land in the environment.
**Why:** Not resolvable without vendoring or patching insightface's metadata.
**Effect:** Harmless locally; wasted image size and a GUI-linked build in a container.
Revisit at Phase 10 when the Linux install is containerised.

---

## D8 — Consent authorises a face, not a subject id (Phase 2)

**What:** `check_consent()` loads the enrolled encoding and requires the *query* face to
match it above `MATCH_THRESHOLD`. Passing `--subject tuhin` is not sufficient.
**Why:** `Task.md` §2.1 says the pipeline refuses to run unless the query image "maps to
an enrolled subject". A name check alone would let anyone point the pipeline at a
stranger's photograph by borrowing an enrolled id — which is the exact abuse the consent
gate exists to prevent.
**Effect:** Denial reason `face_mismatch`. Note this couples the gate to `MATCH_THRESHOLD`,
so the D6 tuning result changes gate behaviour too: too high a threshold locks the subject
out of their own pipeline. Worth re-checking once real tuning data exists.

---

## D9 — The gate runs before any network activity (Phase 2)

**What:** The consent check is a standalone function called before hosting, search, or
fetching, and a test monkeypatches `socket` to assert no connection is attempted.
**Why:** §2.1 requires refusal, but ordering is what gives refusal meaning. A run denied
*after* the query image had been uploaded to imgbb would already have published the
subject's photograph to a third party — failing at the one moment that mattered.
**Effect:** `test_gate_runs_before_any_network_activity` fails loudly if a future refactor
moves the upload earlier.

---

## D10 — Enrolment stores no photograph (Phase 2)

**What:** `enroll()` derives the encoding and writes only `consent.json` plus an `.npz`
holding the vector, bbox, det score and model id. The enrolment image is never copied
into `data/`.
**Why:** §2.1 forbids committing face encodings, consent records or query images. Not
storing the photograph at all is stronger than relying on `.gitignore`.
**Effect:** `test_enroll_never_stores_the_photograph` asserts only `.json` and `.npz` files
appear under `data/`.

---

## D11 — Consent can be revoked (Phase 2)

**What:** Added `revoke()` and a `revoked_at` field. Revocation stamps the consent record
and **deletes the enrolled encoding**; the gate then refuses with reason `revoked`.
**Why:** Not requested by the spec. But consent that cannot be withdrawn is not consent,
and the README has to make an honest ethics claim in Phase 11. Deleting the vector rather
than just flagging it means withdrawn consent leaves no face data on disk.
**Effect:** The consent record is retained as an audit trail of what was agreed and when;
only the biometric data is destroyed.

---

## D12 — Credentials are validated per path, not at import (Phase 2)

**What:** Every credential in `Settings` is optional. Code that needs one calls
`settings.require("serpapi_key", "run a live search")`, which names the env var and the
reason.
**Why:** §9 says fail fast if a required key is missing *for the chosen path*. Validating
globally would break `--provider offline` on a machine with no `.env` — and that path is
what makes CI (Phase 10) and a clean-clone judge run possible.
**Effect:** AC11 stays reachable without credentials.

---

## D13 — Real-subject validation of the engine (Phase 1/2, measured on `test.png`)

Run against the project owner's own photograph (348×348, single face, det_score 0.835,
face occupying only 3,339 px² — a small face in frame).

**Consent gate, live:** enrolled subject passes at +1.0000; a different individual is
refused at −0.061; a six-person group of strangers refused at −0.048. AC2/AC3 confirmed
outside the test suite.

**Degradation robustness** (same photo, damaged the way web images are):

| Variant | similarity | | Variant | similarity |
|---|---|---|---|---|
| original | +1.0000 | | dark | +0.8696 |
| jpeg q40 | +0.8615 | | bright | +0.9525 |
| **jpeg q15** | **+0.5791** | | rotated 10° | +0.9737 |
| half size | +0.8957 | | mirrored | +0.9434 |
| 150px thumbnail | +0.8036 | | tight face crop | +0.9020 |
| grayscale | +0.9482 | | crop +25px margin | +0.9918 |

All twelve clear the 0.45 boundary.

**Two findings that matter downstream:**

1. **Heavy JPEG compression is the weak point.** At quality 15 the score falls to +0.579 —
   still a match, but the margin over 0.45 has shrunk to 0.13 from a typical ~0.45. Stage 2
   will meet aggressively recompressed images routinely, so this, combined with a genuinely
   different photograph (already a harder case), is where false negatives will come from.
   Worth preferring the highest-resolution image variant a page offers.

2. **D4's padded retry is confirmed necessary on real data.** The exact face box from this
   photo is a 53×63 crop. Detection on it **without** the retry returns **zero faces**;
   with padding it detects at 0.718 and matches the source at +0.9020. Profile avatars and
   search thumbnails are shaped exactly like this, so without D4 stage 2 would discard them
   silently.

**Still not closed:** every row above is a derivative of one photograph. Genuine
same-person pairs — different day, camera, pose — remain unmeasured, so D6 stands.

---

## D14 — Phase 9 demo target confirmed: the GitHub profile (reconnaissance)

`test.png` turned out to be **byte-identical** to the live avatar at
`https://avatars.githubusercontent.com/u/111550237?v=4` (similarity +1.0000), i.e. the
subject's actual GitHub profile picture, publicly hosted.

Verified for the live demo:

- `https://github.com/Tuhin810` returns HTTP 200 and carries
  `og:image = https://avatars.githubusercontent.com/u/111550237?v=4?s=400` and
  `og:title = "Tuhin810 - Overview"` — precisely the fields `scrape.py` extracts (§5.2).
- `github.com/robots.txt` does **not** disallow `/Tuhin810` for `User-agent: *`. Profile
  pages are crawlable; the Disallow list covers `/*/*/commits/`, `/*/tree/`, `/gist/` and
  similar, none of which we need.

So AC6 has a plausible live target. Remaining unknown: whether Google Lens actually
returns the profile page for this image. That is only answerable in Phase 9 with a real
SerpAPI call, and a no-match is still a valid outcome (§2.2).

**Demo-strength caveat:** if the query image is the *same file* as the one on the page,
stage 2's re-verification proves little — it compares an image with itself. A stronger and
more honest demo uses a *different* photograph of the subject as the query, so the face
re-verification does real work in upgrading a visual hit to an identity match. Worth
capturing a second photo before Phase 9.

---

## D15 — `robots.txt` fetching must validate content type (Phase 7 hazard)

**Found during D14 reconnaissance:** `https://avatars.githubusercontent.com/robots.txt`
returns **HTTP 200 with `content-type: image/png`** — that host serves *any* path as an
image. A naive `urllib.robotparser` would be fed PNG bytes and derive nonsense rules,
either blocking every fetch or permitting everything, silently.

**Decision:** `scrape.py` must check the response content type is `text/*` and the status
is 200 before parsing, and treat anything else as "no robots file" (default allow, log the
anomaly). Also cache per-host so the 1 req/sec budget is not spent re-fetching it.

**Why it matters:** image CDNs are exactly the hosts stage 2 fetches from most, so this is
a common case, not an exotic one.

---

## D16 — `record_id` validates that the left operand is a digest (Phase 3)

**What:** `record_id()` rejects any `image_sha256` that is not exactly 64 lowercase hex
characters.

**Why:** `Task.md` §6 specifies `keccak256(query.image_sha256 + "|" + match.page_url)`.
That concatenation is ambiguous in the general case — `("a", "b|c")` and `("a|b", "c")`
both render as `a|b|c` and produce an identical record id. A test written to assert the
separator was unambiguous **failed**, which is how this surfaced.

It is not exploitable in practice, because the left operand is always a SHA-256 hex
digest and cannot contain `|`. So the correct fix is to *enforce the invariant the format
relies on*, not to redesign the format: changing the construction would alter every
record id and invalidate anything already anchored.

**Effect:** The spec's format is preserved byte-for-byte. URLs may still contain `|`,
since only the left side is constrained.

---

## D17 — pHash is implemented in-repo, not taken from a library (Phase 3)

**What:** A DCT perceptual hash written against numpy/OpenCV rather than the `imagehash`
package. Definition: greyscale → 32×32 (INTER_AREA) → 2-D DCT → top-left 8×8 → compare
each coefficient to the median of that block *excluding the DC term* → 64 bits, row-major,
MSB first → 16 hex characters.

**Why:** This value is inside a hashed, anchored record. A dependency free to change its
algorithm across versions would silently change evidence hashes, breaking the §2.3
reproducibility claim. Pinning the algorithm in-repo makes it auditable and stable.

**Effect:** No extra dependency. Measured: stable across runs, and moves ≤6 of 64 bits
under JPEG q40 recompression.

---

## D18 — Floats are rounded before hashing (Phase 3)

**What:** `similarity` and `match_threshold` are rounded to 6 decimal places, `det_score`
to 4, inside `build_evidence`.

**Why:** Two machines can compute `0.6120000000000001` and `0.612` for the same cosine
similarity. Those serialise to different JSON bytes and therefore to different hashes,
which would break §2.3 in a way that is very hard to diagnose after the fact.

**Effect:** `test_floats_are_rounded_for_reproducibility` asserts both spellings hash
identically. Precision retained is far beyond what the threshold decision needs.

---

## D19 — Verification re-canonicalises rather than hashing the file bytes (Phase 3)

**What:** `load_evidence()` parses the JSON, and hashing runs over the re-serialised
canonical form — not over the raw bytes on disk.

**Why:** It separates *formatting* from *content*. A pretty-printed or re-indented copy
still verifies, while changing any value does not. Hashing raw file bytes would make
trivial reformatting look identical to tampering, which would weaken the Phase 5 demo
rather than strengthen it.

**Effect:** Covered by `test_reformatting_the_file_does_not_break_verification` and by six
parametrised field-mutation tests.

---

## D20 — Reproducibility verified across interpreters (Phase 3, closes part of §2.3)

Canonical bytes for the committed fixture are **byte-identical (1017 bytes, sha256
`444423e5…`) on CPython 3.9 and 3.12**, and the evidence hash is unchanged across
randomised `PYTHONHASHSEED`, `LC_ALL=C` vs `en_US.UTF-8`, and `TZ=Asia/Tokyo` vs
`America/New_York`.

An **independent reimplementation** using only `json` + `Web3.keccak`, touching no project
code, produces the same hash:

```
0xa075bde44c4015e476bb8a06ce3ff3bc9920f790288323afbb4a460db2f9732d
```

That last check is the meaningful one: any third party can recompute the anchored hash
from the published record without trusting this codebase. Full cross-*machine*
confirmation still belongs to Phase 10's container run.

---

## D21 — No local chain binary installed; eth-tester substitutes for Anvil (Phase 4)

**What:** `Task.md` §3 and §13 call for testing against Anvil or Ganache first. Neither
is installed on this machine, and installing Foundry via Homebrew was declined. Phase 4
was instead built and tested against `eth-tester`/`py-evm`, an in-memory EVM available as
a pure Python dependency.

**Why this is a fair substitute, not a shortcut:** `deploy()`, `anchor()`, and `verify()`
all accept an injected `w3: Web3` and `private_key`. The test suite passes an
`EthereumTesterProvider`-backed `Web3` through the *exact same code path* a real network
uses — `build_transaction` → `sign_transaction` → `send_raw_transaction` →
`wait_for_transaction_receipt`. Nothing about production usage is stubbed or mocked; only
the RPC transport is swapped.

**What this does NOT cover, and what changes with real Anvil:**
- Anvil is a separate OS process reachable over HTTP, so it also exercises `get_web3()`'s
  connection and error-handling path (`ChainError` on unreachable RPC) — verified
  separately by pointing the CLI at `http://127.0.0.1:8545` with nothing listening.
- Gas estimation, block timing, and EVM version quirks can differ subtly between py-evm
  and Anvil's Rust EVM (revm). Nothing in the contract is version-sensitive, but this is
  worth a real run before calling Phase 4 fully closed.
- The **CLI-level** `deploy`/`anchor`/`verify` commands have not been run end-to-end,
  since they only take a network name and always go through `get_web3()`'s HTTP path —
  they cannot accept the injected test provider. Confirmed instead: the CLI's error
  handling is correct when no chain is reachable (`ChainError`, clean message, exit 1).

**To close properly:** install Anvil (`brew install foundry` or
`curl -L https://foundry.paradigm.xyz | bash && foundryup`) and re-run
`facechain deploy --network local` → `facechain anchor` → `facechain verify` against it,
plus `scripts/tamper_test.sh` (Phase 5). This environment also has **no general internet
access** (DNS resolution fails for external hosts), so this and Amoy deployment (Phase 9)
must happen on the developer's own machine regardless.

---

## D22 — `is_anchored()` uses `get()`, not `verify()`, as the existence probe

**What:** Existence of a record is checked via `get(id)` succeeding vs. reverting, not
via `verify(id, someHash)` returning true.

**Why:** An earlier version probed with `verify(id, 0x00...00)`, reasoning that a real
hash is (almost) never all-zero, so a `True` result would mean the id is occupied. This
is wrong: `verify()` returns true **only when the probe hash matches exactly**, so it
returns `False` for both "unanchored" and "anchored under a different hash" — it can
never confirm existence without already knowing the stored hash. This was caught by
`test_anchor_twice_raises_already_anchored_not_a_raw_revert`: the pre-flight check
silently passed a duplicate anchor through to the chain, which reverted for real, and the
post-failure re-check made the same mistake and mis-reported it as a generic `ChainError`
instead of `AlreadyAnchoredError`.

**Effect:** `get()` is existence-by-exception rather than existence-by-value, which is
correct for any Solidity revert regardless of provider. AC9 now passes.

---

## D23 — Block number for `verify` output comes from the anchoring event, not the chain tip

**What:** `verify()` reads `MatchAnchored`'s indexed `recordId` via `get_logs` to find the
block the record was anchored in.

**Why:** The `Record` struct only stores a `uint64 timestamp`, not a block number. Using
`w3.eth.block_number` (the current chain tip) would silently misreport an old anchor as
having just happened — worse than showing nothing, since it looks correct at a glance.
Falls back to `-1` ("unknown") if the log cannot be found, e.g. against a provider that
prunes old logs, rather than repeating the same wrong assumption.

---

## D24 — `tx_hash.hex()` in web3 8.x omits the `0x` prefix

**What:** `deploy()` and `anchor()` build the hash string as
`"0x" + tx_hash.hex().removeprefix("0x")`.

**Why:** web3 8.0.0's `HexBytes.hex()` returns bytes without a leading `0x` (unlike
earlier web3 versions, where this varied). An initial conditional assuming `.hex()`
sometimes already included the prefix was dead code — `.hex()` always returns `str`, so
the condition was always false and the prefix was silently dropped. Caught immediately
by `result.tx_hash.startswith("0x")` in the roundtrip test.

---

## D25 — Mutating `match.page_url` shifts record identity, not just the hash (Phase 5)

**What:** `Task.md` §10.8 prescribes: copy the evidence, change one character in
`match.page_url`, run `verify`, expect `TAMPERED ✗` and a non-zero exit. Under §6's own
formula, `record_id = keccak256(image_sha256 + "|" + page_url)`, so that exact edit
changes the record id the evidence claims for itself. `get(record_id)` then reverts
`NotFound` -- there is no on-chain hash to show "side by side" the way a same-id,
different-hash tamper would produce.

**Why this is not a bug to route around:** it is what a correct implementation of §6's
own formula does. A field mutation that moves the identity is, if anything, *more*
detected than one that only moves the hash — the tampered file no longer even points at
a real record.

**Resolution:** `verify()` keeps its honest, already-tested behaviour (raises
`RecordNotFoundError` — this is also the correct response to "you haven't anchored yet",
a genuinely different situation the low-level function cannot and should not conflate).
A new `verify_report()` wraps it for the CLI and the tamper test: it catches
`RecordNotFoundError` and folds it into the same `TAMPERED ✗` verdict §10.8 asks for,
with a `reason` field (`"hash_mismatch"` vs. `"record_not_found"`) preserved for anyone
who wants the detail, and an explanation printed in the summary either way.

**Accepted limitation, stated rather than hidden:** at the chain level, "tampered so its
identity shifted" and "never anchored at all" are indistinguishable — both are "no record
under this id". `verify_report()` reports both as `TAMPERED ✗`. `tamper_test.sh` avoids
ambiguity by anchoring the original record first and checking a genuine baseline
`VERIFIED` before running any tamper case.

`tamper_test.sh` runs both forms, plus the reformatting case: (1) the §10.8 page_url
mutation → `TAMPERED ✗` via `record_not_found`, (2) a `match.similarity` mutation → the
literal "both hashes side by side" case via `hash_mismatch`, (3) a key-order/whitespace
reformat of the *unmodified* record → still `VERIFIED`, proving canonicalisation is
doing real work rather than any byte difference tripping a false alarm.

---

## D26 — `scripts/local_chain.py`: an HTTP JSON-RPC shim over eth-tester (Phase 5, partial)

**What:** Built a minimal `http.server`-based JSON-RPC front end over
`EthereumTesterProvider`, since no Anvil/Ganache binary is installed and this sandbox has
no general internet access. It correctly speaks JSON-RPC for read calls (confirmed:
`eth_chainId` over real HTTP returns the right value), but contract deployment through it
fails: `Web3RPCError: Value must be a positive integer. Got: 0x0` during gas estimation.

**Root cause, as far as diagnosed:** `EthereumTesterProvider.make_request()` behaves
differently depending on whether it is called in-process, inside its own `Web3`
instance's middleware onion (which normalises outgoing transaction fields before the
provider ever sees them — this is the path all 20 chain tests use, and it works), versus
being invoked directly on parameters that already round-tripped through a *different*
`Web3`'s (the CLI's `HTTPProvider`) JSON-RPC wire encoding. Something in that second path
produces a `"value": "0x0"` that eth-tester's internal gas estimator rejects. Not resolved
-- diagnosing eth-tester's own middleware-vs-wire-format handling further was a deep,
low-value rabbit hole relative to just installing Anvil.

**Effect:** `local_chain.py` is left in the repo as a documented, best-effort dev
convenience (reads work; contract deployment does not). It is not relied on by any test
or gate. The real closure evidence for AC4/AC7/AC8/AC9 is the 20 injected-provider tests
in `test_chain_roundtrip.py`, which exercise the exact same `deploy()`/`anchor()`/
`verify()` code path a real network uses — see D21. Installing Anvil remains the
recommended way to get a genuinely live local-chain CLI run before Phase 9.

---

## D27 — Google Lens matched the scene, not the face (Phase 6, real live call)

**What:** A real SerpAPI `google_lens` call against the subject's own hosted photo
returned 67 candidates. **Zero mention** the subject's name or GitHub anywhere in the
results. The matches are dominated by Harry Potter retail/costume content: Instagram
posts, eBay/Amazon/Walmart Gryffindor-robe listings, Universal Studios merchandise pages.

**Why:** The photo is a mirror selfie inside a Harry Potter merchandise store, wearing a
Gryffindor robe, holding a phone. The face occupies roughly **2.7% of the frame** (3,339
of 121,104 px², measured in D13). Google Lens's visual-similarity matching is dominated by
the largest, most distinctive visual elements in an image — here, the robe and the shop
interior, not the small face.

**Consequence for Phase 9 (AC6):** this specific photo is unlikely to surface the
subject's GitHub profile through live search, even though that page is public and
crawlable (D14). This is not a pipeline defect — it's the exact behaviour §12 warns about
("reverse image search returns visually similar pages, not identity matches"), and it's a
demonstrable finding in its own right for the README's limitations section, not something
to hide.

**What actually helps:** a query photo with the *face* as the visually dominant subject
-- a face-forward headshot or a typical LinkedIn/GitHub-style profile picture, not a
scene photo with a small face -- is far more likely to trigger a genuine identity-driven
Lens match. Worth choosing a second, tighter query photo before Phase 9's live demo run,
per D14's caveat about a same-image test proving nothing anyway.

**Kept as the permanent fixture regardless:** this response is exactly the kind of
messy, real, non-cherry-picked result the pipeline needs to handle -- lots of irrelevant
retail candidates that stage 2's face re-verification (Phase 7) must correctly reject.
`tests/fixtures/serpapi_google_lens_response.json`, 67 candidates, 85KB, committed as-is.

---

## D28 — Offline replay shares extraction code with the live provider (Phase 6)

**What:** `search/serpapi_lens.py` exposes a module-level `extract_candidates(data,
source)` function; both `SerpApiLensProvider` and `OfflineProvider` call it on the exact
same response shape. `offline.py` does not reimplement parsing.

**Why:** A replay that reimplements extraction independently can silently drift from
what a live call actually produces -- passing offline tests would stop being evidence
the live path works. `test_offline_replay_matches_what_live_extraction_would_produce`
asserts both paths, given the same bytes, produce identical candidates.

---

## D29 — A missing imgbb key must fall back, not raise `ConfigError` uncaught (Phase 6)

**What:** `_upload_imgbb()` now catches `ConfigError` from `settings.require()` and
re-raises as `HostingError`, which `upload_query_image()`'s except clause actually
catches.

**Why:** Found by `test_imgbb_missing_key_falls_back_to_0x0`: with no `IMGBB_KEY`
configured, the original code let `ConfigError` propagate straight out of
`upload_query_image`, skipping the 0x0.st fallback entirely -- exactly the scenario
§9's "fail fast... for the chosen path" is supposed to allow gracefully, not crash on.
"No imgbb key" and "imgbb rejected the request" are both just reasons imgbb didn't work,
and both must fall through to the same fallback.

---

## D30 — Real, live coverage in Phase 6, not fixture-only

Distinct from unit tests, these calls hit real external services during development,
using the credentials already present in `.env`:

- **`hosting.upload_query_image`** uploaded `test.png` to imgbb for real; the returned
  URL was fetched back over HTTP and confirmed to serve the image (200).
- **`search.serpapi_lens`** made a real `google_lens` call against that hosted URL and
  parsed a genuine 67-candidate response (see D27).
- **`test_live_imgbb_upload_returns_a_fetchable_url`** and the SerpAPI call are marked
  `@pytest.mark.network` and skip cleanly when no key is configured, so the default test
  run (`pytest -m "not model and not network"`, 127 tests) needs neither credentials nor
  internet, consistent with AC11's clean-clone requirement.

---

## D31 — Every face on a candidate image is scored, not just the "primary" one (Phase 7)

**What:** `matcher._score_image_against_query()` runs `detect_faces()` on each fetched
image and takes the **best** similarity across *all* detected faces, never
`primary_face()`'s largest-bbox pick.

**Why:** D5 (Phase 1) measured that `primary_face()`'s selection is unstable across
image transforms on multi-face photos — degrading a group photo changed which face was
selected. A group photo scraped from a real page is exactly that case: comparing only
the "primary" face risks silently comparing the query against the wrong person while the
right one sits unchecked in the same frame. `test_verify_candidate_uses_the_best_face_not_just_the_first`
proves a middle face in a 3-face image is what gets picked when it's the only one that
passes.

---

## D32 — A 4xx response with an HTML body is not a successfully fetched page (Phase 7)

**What:** `fetch_page()` and `fetch_image_bytes()` now check `resp.status_code == 200`
explicitly, raising `ScrapeError` otherwise -- separate from `_get()`'s retry logic,
which only treats 429/5xx as possibly transient and returns everything else as-is.

**Why:** Found during a real Phase 7 run against the 67-candidate offline fixture:
`wdwnt.com` and `ebay.com` both returned HTTP 403 for their actual candidate pages, and
both responses carried `content-type: text/html` -- so without a status check, an error
or block page would be silently parsed as if it were the real content. Content-type
alone was not a sufficient gate. Regression-tested against a real `httpbin.org` 403.

---

## D33 — Real end-to-end proof, not just mocked orchestration (Phase 7)

Two tests hit live infrastructure end to end, no fixture involved:

- `test_find_matches_against_real_pages_finds_the_known_positive` — a real
  `find_matches()` run against `github.com/Tuhin810` (real page fetch, real face
  detection, real cosine comparison) correctly returns it as a `VerifiedMatch` above
  threshold, while `github.com/torvalds` (a real, unrelated profile) is correctly
  rejected. This is the actual claim of the task -- "turning a fuzzy reverse-image hit
  into a confirmed match" -- demonstrated for real, not asserted from a stub.
- `test_no_disk_write_during_a_real_fetch_and_decode_cycle` — the same real fetch/decode
  path, watched via `tmp_path` with the working directory redirected there, confirms
  zero files are written during a genuine third-party image fetch and comparison.

Also discovered: the matched image's SHA-256 is **not** the same as `test.png`'s own
hash. GitHub's `og:image` carries a `?s=400` resize parameter, so the CDN serves a
differently-encoded 182,361-byte variant of the same photo, versus the local file's
198,696 bytes. Confirmed correct behaviour, not a bug: TASK.md 6 hashes what was
actually fetched and observed, not a claim that the page serves a byte-identical copy
of any particular local file.

**Consequence for Phase 6's D27 finding:** running the offline 67-candidate fixture
(Harry Potter retail pages) through the real matcher end-to-end confirms 0/15 fetched
candidates match, correctly, via `facechain match --image test.png --provider offline`
-- reinforcing that this photo needs a face-forward replacement before Phase 9's live
AC6 demo.

---

## D34 — `result.json` is separate from `evidence.json` (Phase 8)

**What:** Each run directory holds `evidence.json` (canonical, hashed, anchored),
`evidence.pretty.json`, `search_raw.json`, and a new `result.json` carrying status,
message, record id, evidence hash, and anchoring tx/block.

**Why:** `evidence.json` must contain exactly the TASK.md §6 fields and nothing else --
its hash is what gets anchored, so any extra field changes the hash and breaks
verification against records anchored by a different build. Run metadata like the
anchoring transaction hash is genuinely useful but is *about* the run, not part of the
evidence, so it lives alongside rather than inside.

---

## D35 — Artifacts are written on every terminal outcome, failures included (Phase 8)

**What:** `CONSENT_DENIED` and `SEARCH_FAILED` both write a run directory with
`result.json` (and `search_raw.json` carrying the provider error, for the latter).

**Why:** TASK.md §2.2 requires a clean NO_MATCH to still produce artifacts. The same
reasoning extends to failures: a run that leaves no record of what it attempted is not
auditable, and "the pipeline refused" is exactly the kind of event a consent-gated system
should be able to evidence after the fact.

---

## D36 — A chain outage downgrades the status; it does not lose the run (Phase 8)

**What:** Anchoring is the last step. If it raises, the run keeps its written, hashed
evidence and reports `MATCHED_NOT_ANCHORED` with the failure appended to the message.
`AlreadyAnchoredError` is treated as success (`MATCHED_AND_ANCHORED`), since identical
evidence already being on chain is the correct result of a repeated scan (AC9).

**Why:** By the time anchoring runs, stage 1 and 2 have already done all the expensive
and privacy-sensitive work, and the evidence hash is fixed. Discarding a genuine match
because a free testnet RPC was briefly unreachable would be a bad trade -- the evidence
remains anchorable later with `facechain anchor`.

The `except Exception` around anchoring is deliberately broad and commented as such: it
wraps a network call to a third-party RPC, where an unanticipated provider-specific
exception type should degrade the run rather than crash it.

---

## D37 — Reports are built from the run directory alone, never from memory (Phase 8)

**What:** `report.build_report(run_dir)` reads only files on disk. `scan` renders its
final report by calling exactly the same function, on the directory it just wrote --
it does not use its own in-memory `RunResult` to render.

**Why:** It makes artifact completeness a property the code enforces rather than a claim.
If a report could reach into memory for something, a missing artifact would go unnoticed
until someone tried to audit an old run. `facechain report --run out/<run_id>` is
verified in tests to reproduce the full summary from a cold start.

---

## D38 — `revoke --purge`, added after the demo script leaked subject directories

**What:** `consent.purge()` and `facechain revoke --purge` delete a subject's consent
record *and* encoding, leaving nothing. Plain `revoke` still keeps the record as an
audit trail (D11).

**Why:** Found by running `scripts/run_demo.sh` twice and checking `data/`: each run left
a `data/consent/demo_<pid>/` directory behind, because revoke intentionally preserves the
record. Correct for a real subject, wrong for a throwaway demo one.

The more interesting point is that full erasure is not merely a demo convenience -- for a
genuine "delete everything you hold about me" request, removing the record is arguably
more correct than retaining it. So this is a real capability with an explicit flag, not a
hidden cleanup hack, and `test_purge_rejects_unsafe_subject_ids` ensures a path-traversing
id can never reach `shutil.rmtree`.

---

## D39 — A clearly-labelled synthetic fixture exercises the MATCHED path (Phase 8)

**What:** `tests/fixtures/search_raw_synthetic_known_positive.json` is a hand-built
2-candidate response (the subject's GitHub profile, plus an unrelated one) whose first
key is a `_SYNTHETIC` field explaining exactly what it is.

**Why:** The genuine captured response reaches `NO_MATCH` (D27), so without this the
`MATCHED_*` statuses could only ever be tested through stubs. TASK.md §2.2 forbids
hardcoded URLs and pre-picked results *inside the pipeline* -- this is test input
standing in for a provider, which is a different thing, and it is named and annotated so
it cannot be mistaken for a real capture. Phase 9's live demo must still use a real
provider response.

---

## D40 — `requirements.txt` was missing five runtime dependencies (Phase 10, AC1 break)

**What:** `requirements.txt` listed only the stage-1 face dependencies plus typer and
pytest. It was missing **httpx, selectolax, pydantic-settings, py-solc-x and web3** --
every dependency added after Phase 1 was installed ad hoc with `pip install` and never
recorded.

**How it was found:** an AST scan of `src/` for third-party imports, compared against
the pinned list -- not by a test failing, because the development venv had all of them
installed. AC1 ("`pip install -r requirements.txt` works from a clean venv") was silently
broken from Phase 6 onwards and would have failed for anyone cloning the repo.

**Fixed and verified:** a genuinely fresh venv now installs from `requirements.txt`,
imports every module in the package, and runs the full credential-free suite (206 tests)
green. CI runs this on Linux and macOS, Python 3.11 and 3.12, so it cannot regress
silently again.

---

## D41 — insightface prints to stdout; reports must not be corrupted by it (Phase 10)

**What:** Model loading is wrapped in `contextlib.redirect_stdout`, and per-inference
`FutureWarning`s from scikit-image (raised via insightface's `face_align`) are
suppressed. Under `--quiet` the library's output is discarded entirely; otherwise it is
redirected to **stderr**, where it stays available for debugging.

**Why:** insightface emits `Applied providers: ...` / `find model: ...` with bare
`print()` calls, i.e. to stdout -- the same stream carrying the run report. Every
command in this session had to be piped through `grep -v` to be readable, which was the
tell. TASK.md §7 asks for output that is clean and screenshot-friendly, and more
practically, anything piping `facechain report` would have received library chatter
interleaved with the report.

All logging goes to stderr for the same reason (`logging_setup.configure`).

---

## D42 — `run_id` on every log line via a ContextVar (Phase 10)

**What:** `logging_setup` attaches the active run id to every record through a
`logging.Filter` reading a `contextvars.ContextVar`, set once by `pipeline.run_scan`.

**Why:** Ambient context, not a parameter any of these functions act on -- threading a
run id through `scrape`, `matcher` and `consent` signatures would have added noise to
every call site to serve logging alone. Lines now read
`14:15:11 INFO [2026-09-02T20-45-11Z-6245f1] facechain.consent: ...`, so successive or
concurrent runs stay separable in a shared log.

---

## D43 — Lint configuration reflects real constraints, not defaults (Phase 10)

`ruff` reported 77 issues on first run. Rather than blanket-disabling, each class was
judged:

- **B008** (function call in argument default) is *ignored for `cli.py` only*: it is
  typer's required idiom (`x: T = typer.Option(...)`), not a defect.
- **F811/F401** are ignored under `tests/`: importing a pytest fixture for its
  side effect of being in scope reads to ruff as an unused, then redefined, name.
- **UP017** is ignored globally: `datetime.now(timezone.utc)` is more explicit than the
  `UTC` alias in code that writes timestamps into hashed, anchored records.
- Every remaining **BLE001** (`except Exception`) now carries a `noqa` with a written
  justification, so a future broad except cannot slip in unexamined.
- Everything else -- 60-odd import-ordering, string-concatenation, and line-length
  issues -- was fixed rather than suppressed.

**One real defect surfaced this way:** `F841` flagged an unused local in
`test_offline_provider_needs_no_settings_at_all`, which built a credential-free
`Settings` and then never used it -- the test's name claimed something it did not check.
It now installs a `Settings` subclass whose `require()` raises, so the offline path
reaching for *any* credential fails the test.

---

## D44 — Adversarial CLI probe: no bare traceback reaches the user (Phase 10)

Twelve deliberately malformed invocations (non-image files, path-traversing subject ids,
corrupt evidence, unknown providers/subjects, unreachable chain, non-run directories)
were run against the CLI. All twelve exited non-zero with a typed, readable error and
**zero tracebacks**. The 17-class hierarchy under `FaceChainError` is caught wholesale by
`cli.run()`, with `ConsentDenied` mapped to its own exit code 3.

**Known minor wrinkle, not fixed:** `facechain revoke --subject <unknown>` exits 3
(`CONSENT_DENIED`) because it loads the consent record first. The message is accurate
("no consent record for subject ..."), but the status is arguably better described as
"not found". Left as-is rather than restructuring `load_consent`'s contract for a
cosmetic code difference.

---

## D45 — Secret-hygiene audit findings (Phase 10)

Audited the working tree, **git history**, and run artifacts. Results:

- **No sensitive path was ever committed** -- `data/`, `out/`, `.env`, images and `.npz`
  encodings are absent from every commit, not merely gitignored now.
- **The real API keys appear nowhere** in tracked files or history.
- **`.env.example` was missing entirely** and had never been committed, despite §9
  requiring it. Recreated and committed, with per-path notes on which keys each command
  actually needs.
- **SerpAPI echoes capability URLs in its response.** `search_metadata.json_endpoint`
  (and `raw_html_file`) embed a token granting *unauthenticated* read access to that
  stored search -- confirmed live, HTTP 200 with no credentials. Verified the token is
  **per-search, not account-wide** (two searches produced different tokens), so the
  committed fixture exposes only the one response already deliberately committed. The
  API key itself is not echoed.
- **The subject's hosted photo URL is in the fixture** (`i.ibb.co/...`), and the imgbb
  upload expiry worked as designed: it now returns **404**. This validates setting
  `expiration` on uploads rather than relying on the URL being unguessable.

**Deliberately not redacted:** `search_raw.json` is written verbatim, because §2.2
requires exactly that as the evidence the search was real. The hygiene answer is that
`out/` is gitignored and never committed, not that the artifact is filtered.

These are now regression tests (`tests/test_secret_hygiene.py`, 12 tests) rather than a
one-off audit -- including a git-history check, since `.gitignore` cannot undo a past
commit.

---

## D46 — CI runs the checks that actually protect the acceptance criteria (Phase 10)

`.github/workflows/ci.yml`, three jobs:

- **test** -- matrix over {ubuntu, macos} x {3.11, 3.12}: clean-venv install from
  `requirements.txt` (AC1), the credential-free/network-free suite (AC11), the
  secret-hygiene audit with full history, and a canonical-hash assertion against the
  frozen literal, proving AC10/§2.3 cross-platform rather than merely cross-process.
- **lint** -- `ruff check` and `ruff format --check`.
- **demo** -- the offline provider end to end with no credentials, plus a check that
  stage 1 *refuses* a face-free image cleanly.

**No secrets are configured for the workflow, deliberately:** if any test outside the
`network` marker starts requiring an API key or the internet, CI fails. That makes AC11
a property CI enforces, not a claim.

The workflow generates its own synthetic image, because no photograph of a real person
is committed to this repository.

---

## D47 — `local_chain.py` completed: the wire/native boundary, in both directions

**Supersedes the "partial" verdict in D26.** The shim now works, and the CLI-level
`deploy` -> `anchor` -> `verify` -> tamper sequence runs for real against
`http://127.0.0.1:8545`, closing the gaps left open in Phases 4, 5 and 9-local.

**Root cause, properly diagnosed:** `EthereumTesterProvider.make_request()` expects
**Python-native types with snake_case keys** -- it is designed to sit *inside* a `Web3`
instance whose middleware translates to and from JSON-RPC wire format. Serving it over
HTTP puts the shim on the wire side of that boundary, so it must do the translation
itself. Four distinct conversions were needed, each found by running the real CLI:

1. **Request quantities**: `"value": "0x0"` -> `0`. Without it, gas estimation fails
   with `Value must be a positive integer. Got: 0x0`.
2. **Response shape**: eth-tester returns `{"base_fee_per_gas": 875000000}`; web3
   expects `{"baseFeePerGas": "0x34630b8a"}`. Without it, `KeyError: 'baseFeePerGas'`.
3. **Default sender**: eth-tester rejects an `eth_call` with no `from`, where a real
   node executes view calls anonymously. `facechain verify` makes exactly such a call.
4. **Filter keys and bounds**: `eth_getLogs` sends `fromBlock`/`toBlock` (camelCase,
   hex); eth-tester wants `from_block`/`to_block` (snake_case, int). Without it the
   `MatchAnchored` lookup silently returned nothing and `verify` printed
   `block: unknown` -- D23's fallback firing, which is exactly the "looks fine, is
   wrong" failure that fallback was designed to make visible rather than paper over.

**Still not a substitute for Anvil.** Gas accounting, block timing and EVM-version
behaviour are py-evm's, not revm's. This makes the *CLI path* genuinely exercisable
without a toolchain install; it does not make the local chain production-representative.

---

## D48 — `deploy` silently invalidates previously anchored evidence (found in Phase 9)

**What:** `facechain deploy` overwrites `out/deployment.<network>.json`. Evidence
anchored against the previous contract then fails to verify -- `verify` reads the new
address, finds no record under that id, and correctly reports `TAMPERED ✗`.

**How it was found:** capturing README transcripts. A `verify` that had printed
`VERIFIED ✓` minutes earlier began reporting `TAMPERED ✗`, because `tamper_test.sh` had
redeployed in between.

**Fixed in the script:** `tamper_test.sh` now saves and restores an existing deployment
file, since a test is not entitled to destroy the caller's deployment record.

**Not fixed in `deploy` itself, deliberately:** overwriting on redeploy is reasonable
default behaviour, and the alternative (refusing, or auto-versioning) is a product
decision beyond this task's scope. It is called out in the README's limitations instead,
because the failure mode is genuinely confusing: the evidence is intact and the hash is
correct, but it is being checked against a contract that never saw it.

---

## D49 — Phase 9 status: local chain fully demonstrated, Amoy blocked by the environment

Every acceptance criterion that does not require the public internet is now demonstrated
end to end through the real CLI, against a live HTTP chain:

- **AC4** deploy -> contract live, `deployment.local.json` written
- **AC6-equivalent (offline)** full `scan` -> `MATCHED_AND_ANCHORED`, real tx hash
- **AC7** `verify` -> `VERIFIED ✓` with block, timestamp, submitter
- **AC8** `tamper_test.sh` -> 4/4 cases pass
- **AC9** re-anchor -> `AlreadyAnchoredError`, exit 1, handled gracefully

**What remains genuinely undone, and why:**

- **AC5 (deploy to Polygon Amoy).** This sandbox has no DNS resolution for
  `rpc-amoy.polygon.technology` (verified: `curl` exit 6). It also needs a funded
  testnet key, which should be generated by the repository owner and never shared.
- **AC6 with a live SerpAPI search reaching a real match.** The live search *works*
  (Phase 6 made real calls), but returns Harry Potter retail pages rather than the
  subject's profile, because the face occupies ~2.7% of the frame (D27). A
  face-forward query photo is the fix, not a code change.

Both are single commands on a machine with internet and a funded key. The README states
plainly which criteria were demonstrated locally and which were not, rather than
implying a testnet deployment that did not happen.

---

## D50 — Thumbnail fallback when a candidate page is robots-disallowed (post-Phase 7)

**What:** When `fetch_page()` fails, `verify_candidate()` now falls back to the search
provider's own thumbnail rather than skipping the candidate. Matches found that way carry
`via_thumbnail=True`.

**Why, measured:** On a real live run, **14 of 15** candidates were Instagram, Facebook
and X pages that disallow crawling in `robots.txt`. Only one (GitHub) was actually
fetched. The pipeline reported "15 fetched, 0 matched" -- which read as *"we checked 15
pages and none matched you"* when the truth was *"we checked one."* That is a materially
different claim, and the more misleading one.

**Why the thumbnail is legitimate, not a robots workaround:** it is an asset the provider
already returned in an API response we paid for, served from its own CDN, and
`encrypted-tbn*.gstatic.com/robots.txt` explicitly carries `Allow: /images`. It reads data
we were given, rather than crawling a site that asked us not to. The fallback still runs
`scraper.allowed()` on the thumbnail URL before fetching.

**Weaker evidence, so it is labelled:** thumbnails are heavily recompressed, and page text
and title are unavailable, so `page_text_excerpt` is empty for such a match. The flag is
surfaced in the demo UI as "via search thumbnail — page not crawlable".

---

## D51 — `candidates_fetched` now counts what was examined, not what was attempted

**What:** `MatchRunStats` gained `candidates_unreachable`, and `candidates_fetched` counts
only candidates whose imagery could actually be examined (page or thumbnail).

**Why:** Same finding as D50. A count that includes candidates the pipeline was never
permitted to look at overstates what was verified, in an artifact whose whole purpose is
to be trustworthy.

---

## D52 — A test depended on a gitignored file's *identity* (found when it changed)

**What:** `test_find_matches_against_real_pages_finds_the_known_positive` asserted that
the repo's `test.png` matched `github.com/Tuhin810`. It now downloads the reference avatar
from that profile instead.

**Why:** `test.png` is gitignored, so its content is free to change -- and it did, when a
different person's photograph was dropped in during a demo. The test began failing while
saying nothing about the code, which is the worst failure mode a test has. A test that
needs a specific image must fetch it, not assume a mutable local file still contains it.

---

## D53 — `urllib.robotparser` and blank lines (noted, not fixed)

`encrypted-tbn0.gstatic.com/robots.txt` reads:

```
User-agent: *
Allow: /images

Disallow: /
```

`urllib.robotparser` treats the blank line as ending the record, so the trailing
`Disallow: /` lands in a group with no `User-agent` and is ignored -- our parser reports
*every* path on that host as allowed. Google's own spec is more permissive about blank
lines than RFC 9309, so both readings are defensible.

**No impact here:** the only paths we fetch on that host are `/images` thumbnails, which
are explicitly allowed under either reading. Recorded because a future change that fetched
some other path from an image CDN would be relying on a parser quirk rather than on
permission.
