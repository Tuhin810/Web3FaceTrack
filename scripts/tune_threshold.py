"""Tune MATCH_THRESHOLD on real photographs.

Usage:
    python scripts/tune_threshold.py data/tuning

Expects one directory per person, two or more photos each:

    data/tuning/
      alice/  a1.jpg a2.jpg a3.jpg
      bob/    b1.jpg b2.jpg

Every within-person pair is a positive, every across-person pair a negative. The script
prints both distributions and the separation between them, then reports the threshold
that maximises accuracy and the most conservative one that admits no false positive.

`data/` is gitignored, so tuning photographs never enter version control.
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from pathlib import Path

from facechain.face import MATCH_THRESHOLD, FaceEncoding, primary_face, similarity

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def load_people(root: Path) -> dict[str, list[tuple[str, FaceEncoding]]]:
    people: dict[str, list[tuple[str, FaceEncoding]]] = {}
    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        encodings = []
        for img in sorted(person_dir.iterdir()):
            if img.suffix.lower() not in IMAGE_SUFFIXES:
                continue
            try:
                encodings.append((img.name, primary_face(img)))
            except Exception as exc:  # noqa: BLE001 -- report and continue
                print(f"  skip {person_dir.name}/{img.name}: {exc}")
        if encodings:
            people[person_dir.name] = encodings
    return people


def describe(label: str, scores: list[float]) -> None:
    if not scores:
        print(f"{label}: none")
        return
    s = sorted(scores)
    n = len(s)
    print(
        f"{label}: n={n}  min={s[0]:+.3f}  p05={s[int(n * 0.05)]:+.3f}  "
        f"median={s[n // 2]:+.3f}  p95={s[min(n - 1, int(n * 0.95))]:+.3f}  max={s[-1]:+.3f}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Tune the face match threshold on real pairs.")
    ap.add_argument("root", type=Path, help="directory of per-person subdirectories")
    ap.add_argument("--verbose", action="store_true", help="print every pair score")
    args = ap.parse_args()
    logging.basicConfig(level=logging.ERROR)

    if not args.root.is_dir():
        print(f"not a directory: {args.root}", file=sys.stderr)
        return 2

    print(f"loading from {args.root} ...")
    people = load_people(args.root)
    if not people:
        print("no usable images found", file=sys.stderr)
        return 2
    for name, encs in people.items():
        print(f"  {name}: {len(encs)} photo(s)")

    positives: list[float] = []
    negatives: list[float] = []

    for name, encs in people.items():
        for (n1, a), (n2, b) in itertools.combinations(encs, 2):
            score = similarity(a, b)
            positives.append(score)
            if args.verbose:
                print(f"  + {name}/{n1} vs {name}/{n2}: {score:+.3f}")

    for (p1, e1), (p2, e2) in itertools.combinations(people.items(), 2):
        for n1, a in e1:
            for n2, b in e2:
                score = similarity(a, b)
                negatives.append(score)
                if args.verbose:
                    print(f"  - {p1}/{n1} vs {p2}/{n2}: {score:+.3f}")

    print()
    describe("same person    ", positives)
    describe("different person", negatives)

    if not positives or not negatives:
        print("\nNeed at least two people, with two or more photos of at least one.")
        return 2

    lo, hi = min(positives), max(negatives)
    print(f"\nseparation: lowest positive {lo:+.3f} vs highest negative {hi:+.3f} "
          f"-> gap {lo - hi:+.3f}")

    # Sweep candidate thresholds and score each one.
    best = None
    for i in range(-100, 101):
        t = i / 100
        tp = sum(s >= t for s in positives)
        fn = len(positives) - tp
        fp = sum(s >= t for s in negatives)
        tn = len(negatives) - fp
        acc = (tp + tn) / (len(positives) + len(negatives))
        if best is None or acc > best[1]:
            best = (t, acc, tp, fn, fp, tn)

    t, acc, tp, fn, fp, tn = best
    print(f"best accuracy   : threshold {t:.2f} -> {acc:.1%}  (TP={tp} FN={fn} FP={fp} TN={tn})")

    safe = round(hi + 0.01, 2)
    missed = sum(s < safe for s in positives)
    print(f"zero-false-positive: threshold {safe:.2f} -> misses {missed}/{len(positives)} true pairs")

    print(f"\ncurrent MATCH_THRESHOLD = {MATCH_THRESHOLD:.2f}")
    cur_fp = sum(s >= MATCH_THRESHOLD for s in negatives)
    cur_fn = sum(s < MATCH_THRESHOLD for s in positives)
    print(f"  at current value: {cur_fp} false positive(s), {cur_fn} false negative(s)")
    print("\nRecord the chosen value and these distributions in DECISIONS.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
