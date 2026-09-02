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
