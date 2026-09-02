"""Evidence records and canonical hashing -- TASK.md 6.

The on-chain anchor is only meaningful if the same evidence produces the same hash on
every machine, forever. That makes canonicalisation the load-bearing part of this file:

1. ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
2. encode UTF-8
3. ``keccak256`` -- via ``Web3.keccak``, which is Keccak-256, *not* SHA3-256

``evidence.json`` is written as exactly those canonical bytes. A pretty-printed copy is
written alongside for humans and is never hashed.

What is deliberately absent from the record: face vectors, raw images, and any scraped
third-party face data. Hashes and URLs only (TASK.md 2.1).
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from web3 import Web3

from .errors import EvidenceError

_HEX64 = re.compile(r"[0-9a-f]{64}")

SCHEMA = "facechain-verify/evidence/1"
PIPELINE_VERSION = "0.1.0"

# Canonical JSON settings, in one place so the test can assert on them.
_JSON_KWARGS: dict[str, Any] = {
    "sort_keys": True,
    "separators": (",", ":"),
    "ensure_ascii": False,
}


# --- primitives -------------------------------------------------------------------


def utc_now() -> str:
    """ISO 8601 UTC, second precision, always 'Z'-suffixed."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    """``2026-09-02T11-04-33Z-8f3a1c`` -- sortable, filesystem-safe, collision-resistant."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    return f"{stamp}-{secrets.token_hex(3)}"


def sha256_bytes(data: bytes) -> str:
    """Lowercase hex SHA-256, no prefix. Used for content digests inside the record."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """Digest of text as UTF-8. Page text is hashed, never stored verbatim."""
    return sha256_bytes(text.encode("utf-8"))


def phash(image: bytes | str | Path, hash_size: int = 8) -> str:
    """Perceptual hash (DCT), returned as 16 lowercase hex chars.

    Implemented here rather than pulled from a library on purpose: this value goes into a
    hashed, anchored record, so the algorithm must be pinned and documented rather than
    free to change under a dependency upgrade.

    Definition: greyscale -> resize to 32x32 (INTER_AREA) -> 2D DCT -> take the top-left
    ``hash_size x hash_size`` block -> compare each coefficient against the median of that
    block *excluding* the DC term -> bits row-major, MSB first.
    """
    from .face import load_image

    img = load_image(image)
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(grey, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    block = dct[:hash_size, :hash_size]

    # The DC term carries overall brightness and would skew the median.
    median = float(np.median(np.delete(block.flatten(), 0)))
    bits = (block > median).flatten()

    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:0{hash_size * hash_size // 4}x}"


# --- canonicalisation -------------------------------------------------------------


def canonical_json(obj: Any) -> bytes:
    """The exact bytes that get hashed and written to disk.

    ``ensure_ascii=False`` keeps non-ASCII characters literal, so the UTF-8 encoding step
    is what fixes their byte representation. Page titles are full of such characters, and
    this is the most likely place for cross-machine drift to hide.
    """
    try:
        return json.dumps(obj, **_JSON_KWARGS).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"evidence is not canonically serialisable: {exc}") from exc


def evidence_hash(evidence: dict) -> str:
    """``0x``-prefixed keccak256 of the canonical bytes."""
    return "0x" + Web3.keccak(canonical_json(evidence)).hex().removeprefix("0x")


def record_id(image_sha256: str, page_url: str) -> str:
    """``keccak256(image_sha256 + "|" + page_url)``, UTF-8 -- TASK.md 6.

    Identifies *this subject image found on this page*, so re-anchoring the same finding
    collides deliberately and the contract's AlreadyAnchored guard fires.
    """
    if not image_sha256 or not page_url:
        raise EvidenceError("record_id needs both an image digest and a page url")

    # The "a|b" concatenation the spec mandates is only unambiguous while the left side
    # cannot contain the separator: otherwise ("a", "b|c") and ("a|b", "c") both render
    # as "a|b|c" and collide. A SHA-256 hex digest never contains "|", so enforcing the
    # digest's shape is what makes the construction safe. Validated rather than
    # re-designed, because changing the format would invalidate every anchored record.
    if not _HEX64.fullmatch(image_sha256):
        raise EvidenceError(
            f"image_sha256 must be 64 lowercase hex characters, got {image_sha256!r}"
        )
    payload = f"{image_sha256}|{page_url}".encode()
    return "0x" + Web3.keccak(payload).hex().removeprefix("0x")


def record_id_for(evidence: dict) -> str:
    """Derive the record id from a record's own contents."""
    try:
        return record_id(evidence["query"]["image_sha256"], evidence["match"]["page_url"])
    except (KeyError, TypeError) as exc:
        raise EvidenceError(f"evidence is missing fields needed for record_id: {exc}") from exc


# --- building ---------------------------------------------------------------------


@dataclass(frozen=True)
class QueryInfo:
    image_sha256: str
    image_phash: str
    face_model: str
    det_score: float


@dataclass(frozen=True)
class SearchInfo:
    provider: str
    hosted_query_url: str
    candidates_returned: int
    candidates_fetched: int
    candidates_matched: int
    search_raw_sha256: str


@dataclass(frozen=True)
class MatchInfo:
    page_url: str
    page_title: str | None
    page_text_sha256: str
    matched_image_url: str
    matched_image_sha256: str
    similarity: float
    match_threshold: float
    fetched_at: str


def build_evidence(
    run_id: str,
    subject_id: str,
    query: QueryInfo,
    search: SearchInfo,
    match: MatchInfo | None,
    created_at: str | None = None,
    pipeline_version: str = PIPELINE_VERSION,
) -> dict:
    """Assemble the evidence record in the TASK.md 6 shape.

    ``match`` is None on a NO_MATCH run: the record is still written, so a clean no-match
    remains a demonstrable outcome (TASK.md 2.2). Only records carrying a match can be
    anchored, since ``record_id`` is derived from the page URL.

    Floats are rounded to fixed precision. Two machines can produce ``0.6120000000000001``
    and ``0.612`` for the same computation, and those serialise to different bytes and so
    to different hashes.
    """
    evidence: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": run_id,
        "created_at": created_at or utc_now(),
        "subject_id": subject_id,
        "query": {
            "image_sha256": query.image_sha256,
            "image_phash": query.image_phash,
            "face_model": query.face_model,
            "det_score": round(float(query.det_score), 4),
        },
        "search": {
            "provider": search.provider,
            "hosted_query_url": search.hosted_query_url,
            "candidates_returned": int(search.candidates_returned),
            "candidates_fetched": int(search.candidates_fetched),
            "candidates_matched": int(search.candidates_matched),
            "search_raw_sha256": search.search_raw_sha256,
        },
        "pipeline_version": pipeline_version,
    }

    evidence["match"] = (
        None
        if match is None
        else {
            "page_url": match.page_url,
            "page_title": match.page_title,
            "page_text_sha256": match.page_text_sha256,
            "matched_image_url": match.matched_image_url,
            "matched_image_sha256": match.matched_image_sha256,
            "similarity": round(float(match.similarity), 6),
            "match_threshold": round(float(match.match_threshold), 6),
            "fetched_at": match.fetched_at,
        }
    )
    return evidence


def has_match(evidence: dict) -> bool:
    return evidence.get("match") is not None


# --- persistence ------------------------------------------------------------------

EVIDENCE_FILENAME = "evidence.json"
PRETTY_FILENAME = "evidence.pretty.json"


def write_evidence(run_dir: str | Path, evidence: dict) -> Path:
    """Write the canonical bytes, plus a pretty copy that is never hashed."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    path = run_dir / EVIDENCE_FILENAME
    path.write_bytes(canonical_json(evidence))
    (run_dir / PRETTY_FILENAME).write_text(
        json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_evidence(path: str | Path) -> dict:
    """Read an evidence file.

    Verification re-hashes the *parsed and re-canonicalised* object rather than the raw
    bytes on disk, so a file that has been reformatted still verifies, while any change to
    a value does not. That is the property the tamper test in Phase 5 demonstrates.
    """
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"no evidence file at {path}")
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EvidenceError(f"evidence file at {path} is not valid UTF-8 JSON: {exc}") from exc
