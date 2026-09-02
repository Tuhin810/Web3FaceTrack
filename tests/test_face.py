"""Stage 1 tests -- TASK.md 5.1."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from conftest import StubBackend, make_encoding

from facechain import face as facemod
from facechain.errors import ImageDecodeError, LowConfidenceFace, NoFaceDetected
from facechain.face import (
    EMBEDDING_DIM,
    MATCH_THRESHOLD,
    MIN_DET_SCORE,
    detect_faces,
    is_match,
    load_image,
    primary_face,
    select_primary,
    similarity,
)


@pytest.fixture
def stub(monkeypatch):
    """Install a stub backend for the duration of a test."""

    def _install(faces):
        backend = StubBackend(faces)
        monkeypatch.setattr(facemod, "_backend", backend)
        return backend

    return _install


@pytest.fixture
def any_image(tmp_path):
    """A real decodable file. Content is irrelevant when a stub backend is installed."""
    p = tmp_path / "img.png"
    cv2.imwrite(str(p), np.full((64, 64, 3), 127, dtype=np.uint8))
    return p


# --- similarity maths -------------------------------------------------------------


def test_similarity_of_identical_encodings_is_one():
    e = make_encoding()
    assert similarity(e, e) == pytest.approx(1.0, abs=1e-6)


def test_similarity_of_opposite_vectors_is_minus_one():
    v = np.ones(EMBEDDING_DIM, dtype=np.float32)
    assert similarity(make_encoding(v), make_encoding(-v)) == pytest.approx(-1.0, abs=1e-6)


def test_similarity_of_orthogonal_vectors_is_zero():
    a = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    a[0] = 1.0
    b = np.zeros(EMBEDDING_DIM, dtype=np.float32)
    b[1] = 1.0
    assert similarity(make_encoding(a), make_encoding(b)) == pytest.approx(0.0, abs=1e-6)


def test_similarity_is_symmetric():
    rng = np.random.default_rng(0)
    a = make_encoding(rng.normal(size=EMBEDDING_DIM))
    b = make_encoding(rng.normal(size=EMBEDDING_DIM))
    assert similarity(a, b) == pytest.approx(similarity(b, a), abs=1e-7)


def test_similarity_stays_in_range():
    rng = np.random.default_rng(1)
    for _ in range(50):
        a = make_encoding(rng.normal(size=EMBEDDING_DIM))
        b = make_encoding(rng.normal(size=EMBEDDING_DIM))
        assert -1.0 <= similarity(a, b) <= 1.0


def test_comparing_across_models_is_refused():
    """Cosine distance between two different embedding spaces is meaningless."""
    a = make_encoding(model="insightface/buffalo_l")
    b = make_encoding(model="dlib/resnet_v1")
    with pytest.raises(ValueError, match="different models"):
        similarity(a, b)


def test_is_match_respects_threshold():
    a = make_encoding()
    assert is_match(a, a, threshold=MATCH_THRESHOLD)
    assert not is_match(a, make_encoding(-a.vector), threshold=MATCH_THRESHOLD)


# --- primary_face selection rules -------------------------------------------------


def test_primary_face_picks_largest_not_highest_scoring(stub, any_image):
    """TASK.md 5.1: largest bbox wins. A sharp background face must not hijack the subject."""
    small_sharp = make_encoding(bbox=(0, 0, 20, 20), det_score=0.99)
    big_ok = make_encoding(bbox=(0, 0, 200, 200), det_score=0.70)
    stub([small_sharp, big_ok])
    assert primary_face(any_image).bbox == (0, 0, 200, 200)


def test_primary_face_ignores_faces_below_min_det_score(stub, any_image):
    """A huge low-confidence blob must lose to a smaller confident face."""
    big_unsure = make_encoding(bbox=(0, 0, 500, 500), det_score=MIN_DET_SCORE - 0.01)
    small_sure = make_encoding(bbox=(0, 0, 30, 30), det_score=0.95)
    stub([big_unsure, small_sure])
    assert primary_face(any_image).bbox == (0, 0, 30, 30)


def test_primary_face_warns_when_multiple_faces(stub, any_image, caplog):
    stub([make_encoding(bbox=(0, 0, 20, 20)), make_encoding(bbox=(0, 0, 40, 40))])
    with caplog.at_level("WARNING"):
        primary_face(any_image)
    assert "faces above MIN_DET_SCORE" in caplog.text


def test_primary_face_does_not_warn_for_single_face(stub, any_image, caplog):
    stub([make_encoding()])
    with caplog.at_level("WARNING"):
        primary_face(any_image)
    assert caplog.text == ""


def test_primary_face_raises_when_no_faces(stub, any_image):
    stub([])
    with pytest.raises(NoFaceDetected):
        primary_face(any_image)


def test_primary_face_raises_when_all_below_threshold(stub, any_image):
    stub([make_encoding(det_score=0.42), make_encoding(det_score=0.11)])
    with pytest.raises(LowConfidenceFace) as exc:
        primary_face(any_image)
    assert exc.value.best_score == pytest.approx(0.42)
    assert exc.value.threshold == MIN_DET_SCORE


def test_detect_faces_sorted_by_score_descending(stub, any_image):
    stub([make_encoding(det_score=s) for s in (0.7, 0.95, 0.8)])
    assert [f.det_score for f in detect_faces(any_image)] == [0.95, 0.8, 0.7]


# --- image loading ----------------------------------------------------------------


def test_load_image_accepts_bytes_and_path_identically(any_image):
    from_path = load_image(any_image)
    from_bytes = load_image(any_image.read_bytes())
    assert np.array_equal(from_path, from_bytes)


def test_load_image_returns_bgr_uint8(any_image):
    arr = load_image(any_image)
    assert arr.dtype == np.uint8 and arr.ndim == 3 and arr.shape[2] == 3


def test_load_image_rejects_missing_file(tmp_path):
    with pytest.raises(ImageDecodeError, match="no such image file"):
        load_image(tmp_path / "nope.jpg")


def test_load_image_rejects_empty_bytes():
    with pytest.raises(ImageDecodeError, match="empty image data"):
        load_image(b"")


def test_load_image_rejects_non_image_bytes():
    with pytest.raises(ImageDecodeError, match="could not decode"):
        load_image(b"this is definitely not a JPEG")


# --- real inference ---------------------------------------------------------------


@pytest.mark.model
def test_detects_every_face_in_group_photo(group_photo):
    faces = detect_faces(group_photo)
    assert len(faces) == 6
    assert all(f.det_score >= MIN_DET_SCORE for f in faces)


@pytest.mark.model
def test_encoding_shape_and_normalization(group_photo):
    """The evidence record's meaning depends on this contract holding exactly."""
    f = primary_face(group_photo)
    assert f.vector.shape == (EMBEDDING_DIM,)
    assert f.vector.dtype == np.float32
    assert float(np.linalg.norm(f.vector)) == pytest.approx(1.0, abs=1e-5)
    assert f.model == "insightface/buffalo_l"


@pytest.mark.model
def test_encoding_vector_is_immutable(group_photo):
    """Callers must not be able to corrupt a cached encoding in place."""
    f = primary_face(group_photo)
    with pytest.raises(ValueError):
        f.vector[0] = 99.0


@pytest.mark.model
def test_same_image_encodes_deterministically(group_photo):
    a, b = primary_face(group_photo), primary_face(group_photo)
    assert similarity(a, b) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.model
def test_different_people_score_below_threshold(group_photo, tight_crop):
    """Six strangers plus one more: no cross-pair may reach MATCH_THRESHOLD."""
    others = detect_faces(group_photo)
    subject = primary_face(tight_crop)
    scores = [similarity(subject, o) for o in others]
    assert max(scores) < MATCH_THRESHOLD, f"false positive at {max(scores):.3f}"


@pytest.mark.model
def test_group_photo_faces_are_all_distinct_people(group_photo):
    faces = detect_faces(group_photo)
    for i, a in enumerate(faces):
        for b in faces[i + 1 :]:
            assert similarity(a, b) < MATCH_THRESHOLD


@pytest.mark.model
def test_tight_crop_recovered_by_padded_retry(tight_crop):
    """A pre-aligned avatar detects as zero faces on the first pass; the retry saves it."""
    raw = facemod.get_backend().detect(load_image(tight_crop))
    assert raw == []
    assert primary_face(tight_crop).det_score >= MIN_DET_SCORE


@pytest.mark.model
def test_tight_crop_bbox_maps_back_into_original_frame(tight_crop):
    """Padded-retry coordinates must be translated back, not left in padded space."""
    img = load_image(tight_crop)
    h, w = img.shape[:2]
    x1, y1, x2, y2 = primary_face(tight_crop).bbox
    assert 0 <= x1 < x2 <= w
    assert 0 <= y1 < y2 <= h


@pytest.mark.model
def test_no_face_image_raises(tmp_path):
    p = tmp_path / "blank.png"
    cv2.imwrite(str(p), np.full((480, 480, 3), 200, dtype=np.uint8))
    with pytest.raises(NoFaceDetected):
        primary_face(p)


# --- select_primary (same rule, no inference) --------------------------------------


def test_select_primary_matches_primary_face(stub, any_image):
    """The extracted rule must agree with the full path, or the CLI would mislabel."""
    faces = [
        make_encoding(bbox=(0, 0, 20, 20), det_score=0.99),
        make_encoding(bbox=(0, 0, 200, 200), det_score=0.70),
    ]
    stub(faces)
    assert select_primary(detect_faces(any_image)) is select_primary(faces)
    assert select_primary(faces).bbox == primary_face(any_image).bbox


def test_select_primary_returns_an_object_from_the_input_list():
    """Identity matters: the CLI marks the primary row by `is`."""
    faces = [make_encoding(bbox=(0, 0, 30, 30))]
    assert select_primary(faces) is faces[0]


def test_select_primary_raises_on_empty_list():
    with pytest.raises(NoFaceDetected):
        select_primary([])


def test_select_primary_reports_best_score_when_all_low():
    """LowConfidenceFace must name the best score, regardless of list order."""
    with pytest.raises(LowConfidenceFace) as exc:
        select_primary([make_encoding(det_score=0.10), make_encoding(det_score=0.55)])
    assert exc.value.best_score == pytest.approx(0.55)
