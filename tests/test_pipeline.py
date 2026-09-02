"""Pipeline and report tests -- TASK.md 8.

Covers all five statuses TASK.md 8 defines, and the constraint that a report can be
rebuilt from a run directory alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from conftest import make_encoding

from facechain import pipeline as pipeline_mod
from facechain.config import Settings, set_settings
from facechain.errors import FaceChainError, SearchError
from facechain.evidence import evidence_hash, has_match, load_evidence
from facechain.matcher import MatchRunStats, VerifiedMatch
from facechain.report import build_report
from facechain.status import Status

STATEMENT = "I consent to this demo."


@pytest.fixture
def settings(tmp_path):
    s = Settings(data_dir=tmp_path / "data", out_dir=tmp_path / "out")
    set_settings(s)
    yield s
    set_settings(Settings())


@pytest.fixture
def enrolled(settings, monkeypatch, tmp_path):
    """An enrolled subject with a stubbed face pipeline (no model needed)."""
    from facechain import consent as consent_mod

    face = make_encoding(np.ones(512))
    monkeypatch.setattr(consent_mod, "primary_face", lambda image: face)

    image = tmp_path / "query.jpg"
    image.write_bytes(b"fake image bytes")
    consent_mod.enroll("tuhin", image, STATEMENT, settings=settings)

    # The pipeline hashes the query image and computes its phash; stub the phash since
    # the bytes above aren't a decodable image.
    monkeypatch.setattr(pipeline_mod, "phash", lambda p: "0" * 16)
    return image


def _stub_provider(monkeypatch, candidates=(), raw=None, error=None):
    class P:
        name = "offline:replay"

        def search_by_image(self, url):
            if error:
                raise error
            return list(candidates), (raw if raw is not None else {"visual_matches": []})

    def build(name, image_path, settings):
        if error and isinstance(error, SearchError) and name == "unknown":
            raise error
        return P(), "offline-replay"

    monkeypatch.setattr(pipeline_mod, "_build_provider", build)


def _stub_matches(monkeypatch, matches, stats):
    monkeypatch.setattr(pipeline_mod, "find_matches", lambda *a, **k: (matches, stats))


def a_match(similarity=0.61):
    return VerifiedMatch(
        page_url="https://github.com/Tuhin810",
        matched_image_url="https://avatars.githubusercontent.com/u/111550237?v=4",
        similarity=similarity,
        page_title="Tuhin810 - Overview",
        page_text_excerpt="some page text",
        matched_image_sha256="a" * 64,
        fetched_at="2026-09-02T00:00:00Z",
    )


# --- the five statuses --------------------------------------------------------------


def test_consent_denied_when_subject_not_enrolled(settings, tmp_path, monkeypatch):
    """AC3, and the artifacts must still exist for an audit trail."""
    from facechain import consent as consent_mod

    monkeypatch.setattr(consent_mod, "primary_face", lambda image: make_encoding())
    image = tmp_path / "q.jpg"
    image.write_bytes(b"x")

    result = pipeline_mod.run_scan("nobody", image, settings=settings)
    assert result.status is Status.CONSENT_DENIED
    assert not result.ok
    assert (result.run_dir / "result.json").is_file()
    assert result.evidence is None


def test_consent_gate_runs_before_any_upload(settings, tmp_path, monkeypatch):
    """TASK.md 2.1 / DECISIONS D9: a denied run must not have published the photo."""
    from facechain import consent as consent_mod

    monkeypatch.setattr(consent_mod, "primary_face", lambda image: make_encoding())

    def explode(*a, **k):
        raise AssertionError("the provider/upload path ran despite consent being denied")

    monkeypatch.setattr(pipeline_mod, "_build_provider", explode)

    image = tmp_path / "q.jpg"
    image.write_bytes(b"x")
    result = pipeline_mod.run_scan("nobody", image, settings=settings)
    assert result.status is Status.CONSENT_DENIED


def test_search_failed_still_writes_artifacts(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch, error=SearchError("provider exploded"))
    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)

    assert result.status is Status.SEARCH_FAILED
    assert not result.ok
    assert "provider exploded" in result.message
    assert (result.run_dir / "search_raw.json").is_file()
    assert (result.run_dir / "result.json").is_file()


def test_no_match_is_a_success_with_full_artifacts(settings, enrolled, monkeypatch):
    """TASK.md 2.2: a clean no-match is a valid, demonstrable outcome."""
    _stub_provider(monkeypatch, raw={"visual_matches": [{"link": "https://x.test/a"}]})
    _stub_matches(monkeypatch, [], MatchRunStats(1, 1, 0))

    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)
    assert result.status is Status.NO_MATCH
    assert result.ok, "NO_MATCH must exit zero"
    assert (result.run_dir / "evidence.json").is_file()
    assert (result.run_dir / "search_raw.json").is_file()

    evidence = load_evidence(result.run_dir / "evidence.json")
    assert not has_match(evidence)
    assert evidence["search"]["candidates_matched"] == 0


def test_matched_not_anchored_when_anchoring_disabled(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))

    result = pipeline_mod.run_scan("tuhin", enrolled, anchor_enabled=False, settings=settings)
    assert result.status is Status.MATCHED_NOT_ANCHORED
    assert result.ok
    assert "--no-anchor" in result.message
    assert result.record_id is not None


def test_matched_and_anchored(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))

    class FakeAnchor:
        tx_hash = "0x" + "ab" * 32
        block_number = 42

    monkeypatch.setattr("facechain.chain.anchor.anchor", lambda *a, **k: FakeAnchor())
    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)

    assert result.status is Status.MATCHED_AND_ANCHORED
    assert result.anchor_tx == FakeAnchor.tx_hash
    assert result.anchor_block == 42
    written = json.loads((result.run_dir / "result.json").read_text())
    assert written["anchor_tx"] == FakeAnchor.tx_hash


def test_already_anchored_is_not_a_failure(settings, enrolled, monkeypatch):
    """AC9: re-anchoring identical evidence is the correct outcome of a repeat run."""
    from facechain.errors import AlreadyAnchoredError

    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))

    def already(*a, **k):
        raise AlreadyAnchoredError("0x" + "cd" * 32)

    monkeypatch.setattr("facechain.chain.anchor.anchor", already)
    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)

    assert result.status is Status.MATCHED_AND_ANCHORED
    assert "already anchored" in result.message


def test_chain_failure_downgrades_but_keeps_the_evidence(settings, enrolled, monkeypatch):
    """A chain outage must not discard a successful match."""
    from facechain.errors import ChainError

    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))

    def boom(*a, **k):
        raise ChainError("no RPC reachable")

    monkeypatch.setattr("facechain.chain.anchor.anchor", boom)
    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)

    assert result.status is Status.MATCHED_NOT_ANCHORED
    assert result.ok, "a chain outage should not fail a run that found a real match"
    assert "anchoring failed" in result.message
    assert (result.run_dir / "evidence.json").is_file()


def test_all_five_statuses_are_reachable():
    """Guards against a status being defined but never produced by the pipeline."""
    produced = {
        Status.CONSENT_DENIED,
        Status.SEARCH_FAILED,
        Status.NO_MATCH,
        Status.MATCHED_NOT_ANCHORED,
        Status.MATCHED_AND_ANCHORED,
    }
    assert produced == set(Status)


# --- artifacts and evidence integrity ------------------------------------------------


def test_search_raw_is_written_verbatim(settings, enrolled, monkeypatch):
    """TASK.md 2.2: the complete raw response, unfiltered."""
    raw = {
        "visual_matches": [{"link": "https://x.test/a", "odd_field": {"deep": [1, 2]}}],
        "search_metadata": {"status": "Success"},
    }
    _stub_provider(monkeypatch, raw=raw)
    _stub_matches(monkeypatch, [], MatchRunStats(1, 1, 0))

    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)
    written = json.loads((result.run_dir / "search_raw.json").read_text(encoding="utf-8"))
    assert written == raw


def test_evidence_hash_in_result_matches_the_written_evidence(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))
    result = pipeline_mod.run_scan("tuhin", enrolled, anchor_enabled=False, settings=settings)

    on_disk = load_evidence(result.run_dir / "evidence.json")
    assert result.evidence_hash == evidence_hash(on_disk)


def test_evidence_never_contains_biometric_data(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))
    result = pipeline_mod.run_scan("tuhin", enrolled, anchor_enabled=False, settings=settings)

    blob = (result.run_dir / "evidence.json").read_text(encoding="utf-8").lower()
    for banned in ("vector", "embedding", "encoding", "descriptor"):
        assert banned not in blob


def test_run_directories_are_unique_per_run(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [], MatchRunStats(0, 0, 0))
    a = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)
    b = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)
    assert a.run_dir != b.run_dir


# --- report: rebuilt from disk alone --------------------------------------------------


def test_report_is_rebuilt_from_the_run_directory_alone(settings, enrolled, monkeypatch):
    """If a report needs anything beyond the run directory, the artifacts are incomplete."""
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match(0.77)], MatchRunStats(5, 3, 1))
    result = pipeline_mod.run_scan("tuhin", enrolled, anchor_enabled=False, settings=settings)

    text = build_report(result.run_dir)
    assert "MATCHED_NOT_ANCHORED" in text
    assert "https://github.com/Tuhin810" in text
    assert "0.77" in text
    assert "5 returned, 3 fetched, 1 matched" in text
    assert result.evidence_hash in text


def test_report_on_a_no_match_run_explains_it_is_valid(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [], MatchRunStats(9, 4, 0))
    result = pipeline_mod.run_scan("tuhin", enrolled, settings=settings)

    text = build_report(result.run_dir)
    assert "NO_MATCH" in text
    assert "valid outcome" in text
    assert "n/a" in text  # no record id without a match


def test_report_shows_explorer_link_for_amoy(settings, enrolled, monkeypatch):
    _stub_provider(monkeypatch)
    _stub_matches(monkeypatch, [a_match()], MatchRunStats(2, 2, 1))

    class FakeAnchor:
        tx_hash = "0x" + "ef" * 32
        block_number = 7

    monkeypatch.setattr("facechain.chain.anchor.anchor", lambda *a, **k: FakeAnchor())
    result = pipeline_mod.run_scan("tuhin", enrolled, network="amoy", settings=settings)

    text = build_report(result.run_dir, network="amoy")
    assert "amoy.polygonscan.com/tx/" in text
    assert FakeAnchor.tx_hash in text


def test_report_rejects_a_directory_that_is_not_a_run(tmp_path):
    with pytest.raises(FaceChainError, match=r"no result\.json"):
        build_report(tmp_path)


def test_report_rejects_a_missing_directory(tmp_path):
    with pytest.raises(FaceChainError, match="no such run directory"):
        build_report(tmp_path / "absent")
