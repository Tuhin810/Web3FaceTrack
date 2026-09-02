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
