"""Stage 1 — face detection and encoding.

Contract is fixed by TASK.md 5.1: a frozen ``FaceEncoding`` carrying an L2-normalized
float32 vector of shape (512,), the detection bbox, the detector's confidence, and the
model identity string that goes into the evidence record.

The backend sits behind ``FaceBackend`` so an alternative encoder can be swapped in
without any caller knowing. Only the recognition and detection sub-models are loaded:
buffalo_l also ships gender/age and landmark models, and this pipeline has no business
inferring demographic attributes about scraped third parties.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

import cv2
import numpy as np

from .errors import ImageDecodeError, LowConfidenceFace, NoFaceDetected

log = logging.getLogger(__name__)

# --- Tuned constants -------------------------------------------------------------
# MIN_DET_SCORE is the detector's own confidence floor: below this we do not trust that
# the crop is a face at all. MATCH_THRESHOLD is the identity decision boundary and is
# tuned on real pairs -- see DECISIONS.md for the distributions behind the value.
MIN_DET_SCORE = 0.60
MATCH_THRESHOLD = 0.45

EMBEDDING_DIM = 512
MODEL_NAME = "insightface/buffalo_l"


@dataclass(frozen=True, eq=False)
class FaceEncoding:
    """One detected face. ``vector`` is L2-normalized, so cosine similarity is a dot product."""

    vector: np.ndarray  # float32, L2-normalized, shape (512,)
    bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
    det_score: float
    model: str

    @property
    def area(self) -> int:
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)


@runtime_checkable
class FaceBackend(Protocol):
    """Swappable encoder. Implementations must return L2-normalized vectors."""

    model_id: str

    def detect(self, image: np.ndarray) -> list[FaceEncoding]:
        """Detect and encode every face in a BGR uint8 image."""
        ...


class InsightFaceBackend:
    """buffalo_l (SCRFD detector + ArcFace w600k_r50) on onnxruntime, CPU."""

    model_id = MODEL_NAME

    def __init__(self, det_size: tuple[int, int] = (640, 640)) -> None:
        self._det_size = det_size
        self._app = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        # Loading costs ~2s and ~200MB, so it is done once, lazily, and shared. The
        # lock matters because matcher.py will encode candidate images concurrently.
        if self._app is None:
            with self._lock:
                if self._app is None:
                    from insightface.app import FaceAnalysis

                    app = FaceAnalysis(
                        name="buffalo_l",
                        allowed_modules=["detection", "recognition"],
                        providers=["CPUExecutionProvider"],
                    )
                    app.prepare(ctx_id=-1, det_size=self._det_size)
                    self._app = app
                    log.debug("loaded %s det_size=%s", self.model_id, self._det_size)
        return self._app

    def detect(self, image: np.ndarray) -> list[FaceEncoding]:
        app = self._ensure_loaded()
        out: list[FaceEncoding] = []
        for f in app.get(image):
            vec = np.asarray(f.normed_embedding, dtype=np.float32)
            if vec.shape != (EMBEDDING_DIM,):
                raise ValueError(f"expected ({EMBEDDING_DIM},) embedding, got {vec.shape}")
            vec.flags.writeable = False
            x1, y1, x2, y2 = (int(v) for v in f.bbox)
            out.append(
                FaceEncoding(
                    vector=vec,
                    bbox=(x1, y1, x2, y2),
                    det_score=float(f.det_score),
                    model=self.model_id,
                )
            )
        return out


_backend: FaceBackend = InsightFaceBackend()


def set_backend(backend: FaceBackend) -> None:
    """Replace the active backend. Used by tests and by the fallback encoder."""
    global _backend
    _backend = backend


def get_backend() -> FaceBackend:
    return _backend


def load_image(image: bytes | str | Path) -> np.ndarray:
    """Decode to a BGR uint8 array.

    Accepts raw bytes so scraped images can be encoded straight from memory and never
    touch disk -- see TASK.md 2.1.
    """
    if isinstance(image, (str, Path)):
        path = Path(image)
        if not path.is_file():
            raise ImageDecodeError(f"no such image file: {path}")
        data = path.read_bytes()
        origin = str(path)
    else:
        data = image
        origin = f"<{len(image)} bytes>"

    if not data:
        raise ImageDecodeError(f"empty image data: {origin}")

    arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        raise ImageDecodeError(f"could not decode image: {origin}")
    return arr


# --- Tight-crop recovery ----------------------------------------------------------
# SCRFD needs context around a face. A pre-cropped avatar (a 112x112 aligned thumbnail,
# say) detects as zero faces even though it is nothing but a face. Profile pictures and
# search thumbnails are routinely shaped like that, so when a first pass finds nothing
# we retry once on a padded, upscaled copy and map the boxes back to original coords.
_PAD_RATIO = 0.6
_RETRY_SIZE = 640


def _detect_padded(image: np.ndarray) -> list[FaceEncoding]:
    h, w = image.shape[:2]
    pad = int(max(h, w) * _PAD_RATIO)
    padded = cv2.copyMakeBorder(image, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
    ph, pw = padded.shape[:2]
    scaled = cv2.resize(padded, (_RETRY_SIZE, _RETRY_SIZE), interpolation=cv2.INTER_CUBIC)
    sx, sy = _RETRY_SIZE / pw, _RETRY_SIZE / ph

    out: list[FaceEncoding] = []
    for f in _backend.detect(scaled):
        x1, y1, x2, y2 = f.bbox
        box = (
            max(0, min(w, int(x1 / sx) - pad)),
            max(0, min(h, int(y1 / sy) - pad)),
            max(0, min(w, int(x2 / sx) - pad)),
            max(0, min(h, int(y2 / sy) - pad)),
        )
        out.append(
            FaceEncoding(vector=f.vector, bbox=box, det_score=f.det_score, model=f.model)
        )
    return out


def detect_faces(image: bytes | str | Path) -> list[FaceEncoding]:
    """Every detected face, unfiltered, ordered by detection score descending."""
    arr = load_image(image)
    faces = _backend.detect(arr)
    if not faces:
        faces = _detect_padded(arr)
        if faces:
            log.debug("recovered %d face(s) from tight crop via padded retry", len(faces))
    return sorted(faces, key=lambda f: f.det_score, reverse=True)


def select_primary(faces: list[FaceEncoding]) -> FaceEncoding:
    """Apply the primary-face rule to an already-detected list.

    Separate from ``primary_face`` so callers holding a detection result can select
    without paying for a second inference pass.
    """
    if not faces:
        raise NoFaceDetected("no faces detected in image")

    confident = [f for f in faces if f.det_score >= MIN_DET_SCORE]
    if not confident:
        raise LowConfidenceFace(max(f.det_score for f in faces), MIN_DET_SCORE)

    if len(confident) > 1:
        log.warning(
            "%d faces above MIN_DET_SCORE; using the largest by bbox area (%d px^2)",
            len(confident),
            max(f.area for f in confident),
        )
    return max(confident, key=lambda f: (f.area, f.det_score))


def primary_face(image: bytes | str | Path) -> FaceEncoding:
    """The one face this image is 'about'.

    TASK.md 5.1: among faces clearing MIN_DET_SCORE, take the largest by bbox area --
    not the highest-scoring one. In a group photo the subject is the big face in front,
    while a sharp background face can easily out-score them.
    """
    return select_primary(detect_faces(image))


def similarity(a: FaceEncoding, b: FaceEncoding) -> float:
    """Cosine similarity in [-1, 1]. Higher means more likely the same person."""
    if a.model != b.model:
        raise ValueError(
            f"cannot compare encodings from different models: {a.model} vs {b.model}"
        )
    return float(np.clip(np.dot(a.vector, b.vector), -1.0, 1.0))


def is_match(a: FaceEncoding, b: FaceEncoding, threshold: float = MATCH_THRESHOLD) -> bool:
    """Whether two encodings clear the identity decision boundary."""
    return similarity(a, b) >= threshold
