#!/usr/bin/env bash
# Tamper-evidence proof -- TASK.md 10.8, acceptance AC8.
#
# Deploys a throwaway MatchRegistry, enrols a demo subject, anchors a real evidence
# record, then demonstrates that ANY change to that record is detected on verification:
#
#   1. one character changed in match.page_url  (shifts the record's own identity --
#      TASK.md 10.8's literal case; see DECISIONS.md D25 for why this manifests as
#      "no record found" rather than a hash mismatch, and why that still counts)
#   2. a changed match.similarity value          (same record id, different hash --
#      the "ordinary" tamper case, with both hashes shown side by side)
#   3. the untouched record reformatted          (different bytes on disk, same
#      content -- must still verify: proves canonicalisation is doing real work,
#      not just that any byte difference trips a false alarm)
#
# Requires: FACECHAIN_PRIVATE_KEY set to a funded key on the target network, and a
# reachable chain at --network (local: a running `anvil`; amoy: internet + funds).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

FACECHAIN="${FACECHAIN_BIN:-.venv/bin/facechain}"
NETWORK="${1:-local}"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

pass=0
fail=0

check() {
  local desc="$1" expected_exit="$2"; shift 2
  echo
  echo "--- $desc"
  set +e
  "$@"
  local actual=$?
  set -e
  if [ "$actual" -eq "$expected_exit" ] || { [ "$expected_exit" = "nonzero" ] && [ "$actual" -ne 0 ]; }; then
    echo "PASS (exit $actual)"
    pass=$((pass + 1))
  else
    echo "FAIL: expected exit $expected_exit, got $actual"
    fail=$((fail + 1))
  fi
}

echo "=== tamper_test.sh -- network: $NETWORK ==="

if [ -z "${PRIVATE_KEY:-}" ] && [ -z "${FACECHAIN_SKIP_KEY_CHECK:-}" ]; then
  echo "PRIVATE_KEY is not set. This test deploys and anchors for real, so it needs a" >&2
  echo "funded testnet-only key (see .env.example). Aborting rather than silently" >&2
  echo "skipping -- a tamper test that didn't run must not report success." >&2
  exit 2
fi

echo
echo "--- deploying a throwaway MatchRegistry to $NETWORK"
"$FACECHAIN" deploy --network "$NETWORK"

echo
echo "--- enrolling demo subject (throwaway consent record, deleted at the end)"
DEMO_SUBJECT="tampertest_$$"
DEMO_IMAGE="test.png"
if [ ! -f "$DEMO_IMAGE" ]; then
  echo "no $DEMO_IMAGE in repo root -- point this at any consented, enrollable photo:" >&2
  echo "  DEMO_IMAGE=/path/to/photo.jpg $0" >&2
  exit 2
fi
cleanup_subject() { .venv/bin/facechain revoke --subject "$DEMO_SUBJECT" >/dev/null 2>&1 || true; }
trap 'cleanup_subject; rm -rf "$WORK_DIR"' EXIT

"$FACECHAIN" enroll --subject "$DEMO_SUBJECT" --image "$DEMO_IMAGE" \
  --consent-statement "Throwaway enrolment for the tamper-evidence test script." >/dev/null

echo
echo "--- building and anchoring a real evidence record"
.venv/bin/python - "$WORK_DIR/evidence.json" "$DEMO_SUBJECT" "$DEMO_IMAGE" <<'PY'
import sys
from facechain.evidence import (
    build_evidence, MatchInfo, QueryInfo, SearchInfo, new_run_id,
    sha256_file, phash, write_evidence,
)
from facechain.face import primary_face

out_path, subject, image = sys.argv[1], sys.argv[2], sys.argv[3]
face = primary_face(image)
ev = build_evidence(
    run_id=new_run_id(),
    subject_id=subject,
    query=QueryInfo(sha256_file(image), phash(image), face.model, face.det_score),
    search=SearchInfo("offline:tamper_test", "n/a", 1, 1, 1, "0" * 64),
    match=MatchInfo(
        page_url="https://example.test/tamper-test-subject",
        page_title="Tamper test fixture",
        page_text_sha256="1" * 64,
        matched_image_url="https://example.test/tamper-test-subject.jpg",
        matched_image_sha256=sha256_file(image),
        similarity=0.61,
        match_threshold=0.45,
        fetched_at="2026-09-02T00:00:00Z",
    ),
)
import pathlib
write_evidence(pathlib.Path(out_path).parent, ev)
PY

"$FACECHAIN" anchor --evidence "$WORK_DIR/evidence.json" --network "$NETWORK"

echo
echo "--- baseline: verifying the untouched, freshly anchored record"
check "baseline VERIFIED" 0 \
  "$FACECHAIN" verify --evidence "$WORK_DIR/evidence.json" --network "$NETWORK"

# --- case 1: one character of match.page_url -----------------------------------------
.venv/bin/python - "$WORK_DIR/evidence.json" "$WORK_DIR/tampered_url.json" <<'PY'
import json, sys
ev = json.load(open(sys.argv[1], encoding="utf-8"))
ev["match"]["page_url"] += "X"  # one character appended
json.dump(ev, open(sys.argv[2], "w", encoding="utf-8"))
PY
check "TASK.md 10.8 case: match.page_url changed by one character" nonzero \
  "$FACECHAIN" verify --evidence "$WORK_DIR/tampered_url.json" --network "$NETWORK"

# --- case 2: a value that changes the hash but not the record id ---------------------
.venv/bin/python - "$WORK_DIR/evidence.json" "$WORK_DIR/tampered_similarity.json" <<'PY'
import json, sys
ev = json.load(open(sys.argv[1], encoding="utf-8"))
ev["match"]["similarity"] = 0.999999
json.dump(ev, open(sys.argv[2], "w", encoding="utf-8"))
PY
check "same record id, changed match.similarity (both hashes shown)" nonzero \
  "$FACECHAIN" verify --evidence "$WORK_DIR/tampered_similarity.json" --network "$NETWORK"

# --- case 3: reformatted but byte-for-byte-equivalent content ------------------------
.venv/bin/python - "$WORK_DIR/evidence.json" "$WORK_DIR/reformatted.json" <<'PY'
import json, sys
ev = json.load(open(sys.argv[1], encoding="utf-8"))
json.dump(dict(reversed(list(ev.items()))), open(sys.argv[2], "w", encoding="utf-8"), indent=4)
PY
check "reformatted (different bytes, same content) still verifies" 0 \
  "$FACECHAIN" verify --evidence "$WORK_DIR/reformatted.json" --network "$NETWORK"

echo
echo "=== $pass passed, $fail failed ==="
if [ "$fail" -ne 0 ]; then
  exit 1
fi
