#!/usr/bin/env bash
# Reproducible demo -- TASK.md 1 ("a reproducible demo").
#
# Runs the full pipeline offline: no API keys, no internet for the search step, no
# chain required. This is the path a judge can run from a clean clone (AC11).
#
# Usage:
#   scripts/run_demo.sh [path/to/photo.jpg]
#
# With no argument it uses ./test.png if present. The subject is enrolled from the same
# photo, so the consent gate passes -- the demo never runs against a non-consenting face.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

FACECHAIN="${FACECHAIN_BIN:-.venv/bin/facechain}"
IMAGE="${1:-test.png}"
SUBJECT="${DEMO_SUBJECT:-demo_$$}"

if [ ! -x "$FACECHAIN" ]; then
  echo "facechain not found at $FACECHAIN." >&2
  echo "Set up the venv first:  python3.12 -m venv .venv && .venv/bin/pip install -e ." >&2
  exit 2
fi

if [ ! -f "$IMAGE" ]; then
  echo "No query image at '$IMAGE'." >&2
  echo "Pass a photo of a consenting subject:  scripts/run_demo.sh /path/to/photo.jpg" >&2
  exit 2
fi

# --purge, not plain revoke: a throwaway demo subject should leave no trace behind.
cleanup() { "$FACECHAIN" revoke --subject "$SUBJECT" --purge >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> 1/4  Stage 1: detecting faces in $IMAGE"
"$FACECHAIN" faces --image "$IMAGE"

echo
echo "==> 2/4  Enrolling '$SUBJECT' (consent record + encoding only; no photo stored)"
"$FACECHAIN" enroll --subject "$SUBJECT" --image "$IMAGE" \
  --consent-statement "I consent to my own photograph being used for this demo run."

echo
echo "==> 3/4  Consent gate check"
"$FACECHAIN" check-consent --subject "$SUBJECT" --image "$IMAGE"

echo
echo "==> 4/4  Full pipeline (offline provider, no anchoring)"
echo "         A NO_MATCH here is a valid outcome, not a failure -- see TASK.md 2.2."
"$FACECHAIN" scan --subject "$SUBJECT" --image "$IMAGE" --provider offline --no-anchor

echo
echo "==> Demo complete. Run directories are under out/"
echo "    Re-render any run's report with:  $FACECHAIN report --run out/<run_id>"
