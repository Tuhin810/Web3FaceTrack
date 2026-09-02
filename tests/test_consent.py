"""Consent gate tests -- TASK.md 2.1, acceptance AC2/AC3."""

from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import make_encoding
from facechain import consent as consentmod
from facechain import face as facemod
from facechain.config import Settings, set_settings
from facechain.consent import (
    ConsentRecord,
    check_consent,
    enroll,
    is_enrolled,
    list_subjects,
    load_consent,
    load_encoding,
    revoke,
)
from facechain.errors import AlreadyEnrolled, ConsentDenied, ConsentError

STATEMENT = "I agree to my public profile photo being used for this demo."


@pytest.fixture
def settings(tmp_path):
    """Redirect all consent storage into a temp dir."""
    s = Settings(data_dir=tmp_path / "data", out_dir=tmp_path / "out")
    set_settings(s)
    yield s
    set_settings(Settings())


@pytest.fixture
def faces(monkeypatch):
    """Control which encoding `primary_face` returns, per image path."""
    rng = np.random.default_rng(7)
    subject = make_encoding(rng.normal(size=512))
    other = make_encoding(rng.normal(size=512))

    mapping = {"subject.jpg": subject, "other.jpg": other}

    def fake_primary(image):
        key = str(image).split("/")[-1]
        if key not in mapping:
            raise facemod.NoFaceDetected("no faces detected in image")
        return mapping[key]

    monkeypatch.setattr(consentmod, "primary_face", fake_primary)
    return type("F", (), {"subject": subject, "other": other, "mapping": mapping})


# --- enrolment --------------------------------------------------------------------


def test_enroll_writes_consent_and_encoding(settings, faces):
    record = enroll("tuhin", "subject.jpg", STATEMENT, display_name="Tuhin")

    assert record.subject_id == "tuhin"
    assert record.statement == STATEMENT
    assert record.is_active
    assert is_enrolled("tuhin")

    on_disk = json.loads((settings.consent_dir / "tuhin" / "consent.json").read_text())
    for field in ("schema", "subject_id", "display_name", "date", "scope", "statement"):
        assert field in on_disk, f"consent record must carry {field} (TASK.md 2.1)"


def test_enroll_never_stores_the_photograph(settings, faces, tmp_path):
    """Only the derived encoding is kept -- no picture of anyone enters data/."""
    enroll("tuhin", "subject.jpg", STATEMENT)
    stored = [p for p in settings.data_dir.rglob("*") if p.is_file()]
    suffixes = {p.suffix.lower() for p in stored}
    assert suffixes <= {".json", ".npz"}, f"unexpected files stored: {stored}"


def test_enrolled_encoding_round_trips(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    loaded = load_encoding("tuhin")
    assert loaded.vector.shape == (512,)
    assert loaded.vector.dtype == np.float32
    assert np.allclose(loaded.vector, faces.subject.vector, atol=1e-6)
    assert loaded.model == faces.subject.model


def test_enroll_rejects_empty_statement(settings, faces):
    with pytest.raises(ConsentError, match="consent statement"):
        enroll("tuhin", "subject.jpg", "   ")


def test_enroll_rejects_duplicate_without_overwrite(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    with pytest.raises(AlreadyEnrolled):
        enroll("tuhin", "subject.jpg", STATEMENT)
    enroll("tuhin", "subject.jpg", STATEMENT, overwrite=True)  # allowed explicitly


@pytest.mark.parametrize("bad", ["", "  ", "../escape", "has space", "semi;colon", "a/b"])
def test_enroll_rejects_unsafe_subject_ids(settings, faces, bad):
    """Subject ids become directory names."""
    with pytest.raises(ConsentError):
        enroll(bad, "subject.jpg", STATEMENT)


def test_list_subjects(settings, faces):
    assert list_subjects() == []
    enroll("tuhin", "subject.jpg", STATEMENT, display_name="Tuhin")
    assert [r.subject_id for r in list_subjects()] == ["tuhin"]


# --- the gate ---------------------------------------------------------------------


def test_gate_passes_for_enrolled_subject_with_their_own_face(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    result = check_consent("tuhin", "subject.jpg")
    assert result.similarity == pytest.approx(1.0, abs=1e-6)
    assert result.record.subject_id == "tuhin"


def test_gate_denies_when_not_enrolled(settings, faces):
    """AC3: scan with no consent record exits CONSENT_DENIED."""
    with pytest.raises(ConsentDenied) as exc:
        check_consent("tuhin", "subject.jpg")
    assert exc.value.reason == "not_enrolled"


def test_gate_denies_a_different_persons_photo(settings, faces):
    """Naming a subject is not consent: the record authorises a face."""
    enroll("tuhin", "subject.jpg", STATEMENT)
    with pytest.raises(ConsentDenied) as exc:
        check_consent("tuhin", "other.jpg")
    assert exc.value.reason == "face_mismatch"
    assert "authorises a face" in str(exc.value)


def test_gate_denies_when_query_has_no_face(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    with pytest.raises(ConsentDenied) as exc:
        check_consent("tuhin", "no_such_face.jpg")
    assert exc.value.reason == "no_query_face"


def test_gate_denies_after_revocation(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    revoke("tuhin")
    with pytest.raises(ConsentDenied) as exc:
        check_consent("tuhin", "subject.jpg")
    assert exc.value.reason == "revoked"


def test_revocation_deletes_the_enrolled_encoding(settings, faces):
    """Withdrawn consent must not leave a face vector on disk."""
    enroll("tuhin", "subject.jpg", STATEMENT)
    path = settings.enrolled_dir / "tuhin" / "encoding.npz"
    assert path.is_file()
    revoke("tuhin")
    assert not path.exists()
    assert load_consent("tuhin").revoked_at is not None


def test_gate_denies_on_model_mismatch(settings, faces, monkeypatch):
    """An encoding from another model would make the cosine score meaningless."""
    enroll("tuhin", "subject.jpg", STATEMENT)
    foreign = make_encoding(faces.subject.vector, model="dlib/resnet_v1")
    monkeypatch.setattr(consentmod, "primary_face", lambda image: foreign)
    with pytest.raises(ConsentDenied) as exc:
        check_consent("tuhin", "subject.jpg")
    assert exc.value.reason == "model_mismatch"


def test_gate_respects_explicit_threshold(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    with pytest.raises(ConsentDenied):
        check_consent("tuhin", "subject.jpg", threshold=1.01)


def test_gate_runs_before_any_network_activity(settings, faces, monkeypatch):
    """The gate must fail before the query image is uploaded anywhere.

    A denied run that had already published the subject's photo to an image host would
    have failed at the only moment that mattered (TASK.md 2.1).
    """
    import socket

    def explode(*a, **k):
        raise AssertionError("network access attempted during the consent gate")

    monkeypatch.setattr(socket, "socket", explode)
    monkeypatch.setattr(socket, "create_connection", explode)

    with pytest.raises(ConsentDenied):
        check_consent("tuhin", "subject.jpg")


# --- record integrity -------------------------------------------------------------


def test_corrupt_consent_json_is_reported_clearly(settings, faces):
    enroll("tuhin", "subject.jpg", STATEMENT)
    (settings.consent_dir / "tuhin" / "consent.json").write_text("{not json")
    with pytest.raises(ConsentError, match="not valid JSON"):
        load_consent("tuhin")


def test_consent_record_rejects_missing_fields():
    with pytest.raises(ConsentError, match="missing fields"):
        ConsentRecord.from_dict({"subject_id": "tuhin"})


def test_is_enrolled_false_for_bad_id(settings):
    assert not is_enrolled("../escape")
