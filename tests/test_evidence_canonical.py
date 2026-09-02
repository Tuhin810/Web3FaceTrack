"""Canonical hashing tests -- TASK.md 6, acceptance AC10.

The known-hash test is the point of this file. If serialisation ever changes, it must
fail loudly rather than silently start producing different hashes -- records already
anchored on chain would otherwise stop verifying with no explanation.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from web3 import Web3

from facechain.errors import EvidenceError
from facechain.evidence import (
    SCHEMA,
    MatchInfo,
    QueryInfo,
    SearchInfo,
    build_evidence,
    canonical_json,
    evidence_hash,
    has_match,
    load_evidence,
    new_run_id,
    phash,
    record_id,
    record_id_for,
    sha256_bytes,
    sha256_text,
    utc_now,
    write_evidence,
)

FIXTURE = Path(__file__).parent / "fixtures" / "evidence_known_good.json"

# Frozen on 2026-09-02 from the fixture below. Do not update these to match new output:
# if they fail, canonicalisation changed and that is a breaking change to the anchor.
KNOWN_EVIDENCE_HASH = "0xa075bde44c4015e476bb8a06ce3ff3bc9920f790288323afbb4a460db2f9732d"
KNOWN_RECORD_ID = "0xb14597effc1e43d15844b51096d2f8d35f2d9a3ca0a381376b1b8472385cb29c"


@pytest.fixture
def known_evidence() -> dict:
    return build_evidence(
        run_id="2026-09-02T11-04-33Z-8f3a1c",
        subject_id="tuhin",
        created_at="2026-09-02T11:04:33Z",
        query=QueryInfo(
            image_sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            image_phash="c6f6718c0073e0fd",
            face_model="insightface/buffalo_l",
            det_score=0.94,
        ),
        search=SearchInfo(
            provider="serpapi:google_lens",
            hosted_query_url="https://i.ibb.co/example/query.png",
            candidates_returned=42,
            candidates_fetched=15,
            candidates_matched=1,
            search_raw_sha256="9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
        ),
        match=MatchInfo(
            page_url="https://github.com/Tuhin810",
            page_title="Tuhin810 - Overview",
            page_text_sha256="2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae",
            matched_image_url="https://avatars.githubusercontent.com/u/111550237?v=4",
            matched_image_sha256="fcde2b2edba56bf408601fb721fe9b5c338d10ee429ea04fae5511b68fbf8fb9",
            similarity=0.612,
            match_threshold=0.45,
            fetched_at="2026-09-02T11:04:29Z",
        ),
    )


# --- the known-good anchor --------------------------------------------------------


def test_known_evidence_hash_is_stable(known_evidence):
    """AC10. A change here means already-anchored records would stop verifying."""
    assert evidence_hash(known_evidence) == KNOWN_EVIDENCE_HASH


def test_known_record_id_is_stable(known_evidence):
    assert record_id_for(known_evidence) == KNOWN_RECORD_ID


def test_committed_fixture_bytes_are_unchanged(known_evidence):
    """The fixture on disk must be byte-identical to freshly built canonical output."""
    assert FIXTURE.read_bytes() == canonical_json(known_evidence)


def test_fixture_file_hashes_to_the_known_value():
    """Recomputing from the file, as `facechain verify` does, gives the same hash."""
    assert evidence_hash(load_evidence(FIXTURE)) == KNOWN_EVIDENCE_HASH


# --- canonicalisation rules -------------------------------------------------------


def test_key_order_does_not_affect_the_hash(known_evidence):
    """sort_keys means insertion order is irrelevant -- reordering is not tampering."""
    reversed_keys = dict(reversed(list(known_evidence.items())))
    assert list(reversed_keys) != list(known_evidence)
    assert evidence_hash(reversed_keys) == KNOWN_EVIDENCE_HASH


def test_reformatting_the_file_does_not_break_verification(known_evidence, tmp_path):
    """A pretty-printed copy still verifies: whitespace is not content."""
    p = tmp_path / "pretty.json"
    p.write_text(json.dumps(known_evidence, indent=4, sort_keys=False), encoding="utf-8")
    assert evidence_hash(load_evidence(p)) == KNOWN_EVIDENCE_HASH


def test_canonical_output_has_no_whitespace(known_evidence):
    raw = canonical_json(known_evidence)
    assert b", " not in raw and b": " not in raw
    assert b"\n" not in raw


def test_canonical_output_is_sorted(known_evidence):
    parsed = json.loads(canonical_json(known_evidence))
    assert list(parsed) == sorted(parsed)


def test_non_ascii_is_kept_literal_not_escaped():
    """ensure_ascii=False: the UTF-8 encoding step fixes the bytes, not a \\u escape."""
    raw = canonical_json({"title": "Tuhin — Café 東京"})
    assert "—".encode("utf-8") in raw
    assert b"\\u" not in raw


def test_unicode_hash_is_stable_across_equivalent_objects():
    a = canonical_json({"title": "Café"})
    b = canonical_json({"title": "Café"})
    assert a == b


def test_unicode_normalisation_is_not_applied():
    """Decomposed and precomposed forms are different bytes, so different hashes.

    Documented rather than fixed: NFC-normalising would silently alter a scraped page
    title, and the record should hash what was actually observed.
    """
    precomposed = canonical_json({"t": "Café"})
    decomposed = canonical_json({"t": "Café"})
    assert precomposed != decomposed


def test_hash_is_keccak_not_sha3():
    """Web3.keccak is Keccak-256. SHA3-256 differs and would break every anchor."""
    import hashlib

    assert Web3.keccak(b"").hex().removeprefix("0x") == (
        "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    )
    assert Web3.keccak(b"").hex().removeprefix("0x") != hashlib.sha3_256(b"").hexdigest()


def test_hashes_are_0x_prefixed(known_evidence):
    """bytes32 values go straight to the contract, so the prefix must be consistent."""
    for value in (evidence_hash(known_evidence), record_id_for(known_evidence)):
        assert value.startswith("0x")
        assert len(value) == 66


# --- tamper sensitivity -----------------------------------------------------------


@pytest.mark.parametrize(
    "path,new",
    [
        (("match", "page_url"), "https://github.com/Tuhin811"),  # one character
        (("match", "similarity"), 0.613),
        (("query", "image_sha256"), "0" * 64),
        (("subject_id",), "someone_else"),
        (("search", "candidates_returned"), 43),
        (("created_at",), "2026-09-02T11:04:34Z"),
    ],
)
def test_any_field_change_changes_the_hash(known_evidence, path, new):
    target = known_evidence
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = new
    assert evidence_hash(known_evidence) != KNOWN_EVIDENCE_HASH


def test_changing_page_url_changes_the_record_id(known_evidence):
    """Phase 5's tamper test relies on this: the id itself moves."""
    known_evidence["match"]["page_url"] = "https://github.com/Tuhin811"
    assert record_id_for(known_evidence) != KNOWN_RECORD_ID


def test_record_id_is_order_sensitive():
    """keccak(a|b) must not equal keccak(b|a)."""
    assert record_id("a" * 64, "b" * 64) != record_id("b" * 64, "a" * 64)


def test_record_id_rejects_a_non_digest_left_side():
    """Guards the separator ambiguity in keccak(a + "|" + b).

    ("a", "b|c") and ("a|b", "c") both render as "a|b|c" and would collide. A SHA-256
    hex digest cannot contain "|", so validating its shape is what closes the hole.
    """
    with pytest.raises(EvidenceError, match="64 lowercase hex"):
        record_id("a|b", "https://example.com")
    with pytest.raises(EvidenceError, match="64 lowercase hex"):
        record_id("not-a-digest", "https://example.com")
    with pytest.raises(EvidenceError, match="64 lowercase hex"):
        record_id("A" * 64, "https://example.com")  # uppercase


def test_record_id_accepts_pipes_in_the_url():
    """Only the left side is constrained; URLs may legitimately contain '|'."""
    digest = "e" * 64
    assert record_id(digest, "https://x.test/a|b") != record_id(digest, "https://x.test/ab")


def test_record_id_requires_both_parts():
    with pytest.raises(EvidenceError):
        record_id("", "https://example.com")
    with pytest.raises(EvidenceError):
        record_id("a" * 64, "")


# --- record shape -----------------------------------------------------------------


def test_record_never_contains_face_vectors(known_evidence):
    """TASK.md 2.1: hashes and URLs only -- no biometric data in the anchored record."""
    blob = canonical_json(known_evidence).decode("utf-8").lower()
    for banned in ("vector", "embedding", "encoding", "descriptor", "landmark"):
        assert banned not in blob


def test_record_has_the_documented_shape(known_evidence):
    assert known_evidence["schema"] == SCHEMA
    assert set(known_evidence) == {
        "schema", "run_id", "created_at", "subject_id",
        "query", "search", "match", "pipeline_version",
    }
    assert set(known_evidence["query"]) == {
        "image_sha256", "image_phash", "face_model", "det_score"
    }
    assert set(known_evidence["search"]) == {
        "provider", "hosted_query_url", "candidates_returned",
        "candidates_fetched", "candidates_matched", "search_raw_sha256",
    }
    assert set(known_evidence["match"]) == {
        "page_url", "page_title", "page_text_sha256", "matched_image_url",
        "matched_image_sha256", "similarity", "match_threshold", "fetched_at",
    }


def test_floats_are_rounded_for_reproducibility():
    """0.6120000000000001 and 0.612 must not produce different hashes."""
    def build(sim):
        return build_evidence(
            run_id="r", subject_id="s", created_at="2026-01-01T00:00:00Z",
            query=QueryInfo("a", "b", "m", 0.9),
            search=SearchInfo("p", "u", 1, 1, 1, "h"),
            match=MatchInfo("url", "t", "h", "iu", "ih", sim, 0.45, "2026-01-01T00:00:00Z"),
        )
    assert evidence_hash(build(0.612)) == evidence_hash(build(0.6120000000000001))


def test_no_match_record_is_still_valid(known_evidence):
    """TASK.md 2.2: a clean no-match writes artifacts too."""
    ev = build_evidence(
        run_id="r", subject_id="tuhin", created_at="2026-01-01T00:00:00Z",
        query=QueryInfo("a", "b", "m", 0.9),
        search=SearchInfo("p", "u", 42, 15, 0, "h"),
        match=None,
    )
    assert not has_match(ev)
    assert ev["match"] is None
    assert evidence_hash(ev).startswith("0x")


def test_record_id_unavailable_without_a_match():
    ev = build_evidence(
        run_id="r", subject_id="t", created_at="2026-01-01T00:00:00Z",
        query=QueryInfo("a", "b", "m", 0.9),
        search=SearchInfo("p", "u", 0, 0, 0, "h"), match=None,
    )
    with pytest.raises(EvidenceError):
        record_id_for(ev)


# --- persistence ------------------------------------------------------------------


def test_write_evidence_writes_canonical_bytes(tmp_path, known_evidence):
    path = write_evidence(tmp_path, known_evidence)
    assert path.read_bytes() == canonical_json(known_evidence)
    assert evidence_hash(load_evidence(path)) == KNOWN_EVIDENCE_HASH


def test_pretty_copy_exists_and_is_not_the_hashed_one(tmp_path, known_evidence):
    write_evidence(tmp_path, known_evidence)
    pretty = (tmp_path / "evidence.pretty.json").read_bytes()
    assert pretty != canonical_json(known_evidence)
    assert evidence_hash(json.loads(pretty)) == KNOWN_EVIDENCE_HASH


def test_load_evidence_reports_missing_file(tmp_path):
    with pytest.raises(EvidenceError, match="no evidence file"):
        load_evidence(tmp_path / "absent.json")


def test_load_evidence_reports_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{nope")
    with pytest.raises(EvidenceError, match="not valid UTF-8 JSON"):
        load_evidence(p)


def test_canonical_json_rejects_unserialisable():
    with pytest.raises(EvidenceError):
        canonical_json({"bad": object()})


# --- helpers ----------------------------------------------------------------------


def test_run_id_is_sortable_and_unique():
    ids = [new_run_id() for _ in range(5)]
    assert len(set(ids)) == 5
    assert all(i.startswith("20") and i.endswith(tuple("0123456789abcdef")) for i in ids)


def test_utc_now_format():
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", utc_now())


def test_sha256_helpers_agree():
    assert sha256_text("abc") == sha256_bytes(b"abc")
    assert sha256_bytes(b"") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


@pytest.mark.model
def test_phash_is_stable_and_survives_recompression(tmp_path):
    """pHash must track visual content, not exact bytes."""
    import cv2
    img = cv2.imread("test.png")
    if img is None:
        pytest.skip("test.png not present")
    base = phash("test.png")
    assert base == phash("test.png")
    assert len(base) == 16

    jpg = tmp_path / "q40.jpg"
    cv2.imwrite(str(jpg), img, [cv2.IMWRITE_JPEG_QUALITY, 40])
    differing = bin(int(base, 16) ^ int(phash(jpg), 16)).count("1")
    assert differing <= 6, f"phash moved {differing} bits under recompression"


@pytest.mark.model
def test_phash_differs_for_different_images():
    import cv2, numpy as np
    a = phash(cv2.imencode(".png", np.zeros((64, 64, 3), np.uint8))[1].tobytes())
    b = phash(cv2.imencode(".png", np.random.default_rng(0).integers(
        0, 255, (64, 64, 3), dtype=np.uint8))[1].tobytes())
    assert a != b
