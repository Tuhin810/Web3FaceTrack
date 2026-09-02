"""Shared fixtures.

Face tests come in two kinds. Pure ones exercise the maths and the selection rules with
a stub backend and no model. Model-marked ones load buffalo_l and run real inference.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from facechain.face import EMBEDDING_DIM, MODEL_NAME, FaceEncoding

# insightface ships a group photo and a pre-aligned crop; they make good real-inference
# inputs without committing anyone's photograph to this repo.
_BUNDLED = Path(__file__).resolve().parents[1] / (
    ".venv/lib/python3.12/site-packages/insightface/data/images"
)


def _bundled(name: str) -> Path:
    p = _BUNDLED / name
    if not p.is_file():
        pytest.skip(f"bundled insightface sample not available: {name}")
    return p


@pytest.fixture
def group_photo() -> Path:
    """A six-person group photo."""
    return _bundled("t1.jpg")


@pytest.fixture
def tight_crop() -> Path:
    """A 112x112 pre-aligned face crop -- detects only via the padded retry path."""
    return _bundled("Tom_Hanks_54745.png")


def make_encoding(
    vector: np.ndarray | None = None,
    bbox: tuple[int, int, int, int] = (0, 0, 10, 10),
    det_score: float = 0.9,
    model: str = MODEL_NAME,
) -> FaceEncoding:
    """Build a FaceEncoding with an L2-normalized vector, for maths-only tests."""
    if vector is None:
        vector = np.ones(EMBEDDING_DIM, dtype=np.float32)
    vector = np.asarray(vector, dtype=np.float32)
    vector = vector / np.linalg.norm(vector)
    return FaceEncoding(vector=vector, bbox=bbox, det_score=det_score, model=model)


class StubBackend:
    """Returns a fixed face list, so selection rules can be tested without a model."""

    model_id = MODEL_NAME

    def __init__(self, faces: list[FaceEncoding]) -> None:
        self.faces = faces
        self.calls = 0

    def detect(self, image: np.ndarray) -> list[FaceEncoding]:
        self.calls += 1
        return list(self.faces)
