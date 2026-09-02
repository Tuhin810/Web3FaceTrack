"""Enrolment and the consent gate -- TASK.md 2.1.

This pipeline identifies real people from photographs, so it runs only against subjects
who have consented. Two rules shape everything here:

1. **The gate is checked before any network activity.** Not merely before the search --
   before the query image is uploaded to an image host. A denied run that had already
   published the subject's photo to a third party would have failed at the only moment
   that mattered.

2. **Naming a subject is not consent.** ``--subject tuhin`` with a stranger's photo must
   be refused, so the gate compares the query face against the enrolled encoding and
   requires a match. The consent record authorises a *face*, not a string.

Nothing written here may be committed: ``data/consent/`` and ``data/enrolled/`` are
gitignored, and the enrolled vector never enters the evidence record.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .config import Settings, get_settings
from .errors import AlreadyEnrolled, ConsentDenied, ConsentError
from .face import FaceEncoding, primary_face, similarity

log = logging.getLogger(__name__)

CONSENT_SCHEMA = "facechain-verify/consent/1"
DEFAULT_SCOPE = "reverse-image-search-and-onchain-anchor"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ConsentRecord:
    """The per-subject consent document. Fields follow TASK.md 2.1."""

    schema: str
    subject_id: str
    display_name: str
    date: str  # ISO 8601 UTC, when consent was given
    scope: str
    statement: str
    model: str  # which encoder produced the enrolled vector
    revoked_at: str | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, data: dict) -> ConsentRecord:
        known = {f for f in cls.__dataclass_fields__}
        missing = known - set(data) - {"revoked_at"}
        if missing:
            raise ConsentError(f"consent record is missing fields: {sorted(missing)}")
        return cls(**{k: v for k, v in data.items() if k in known})


def _consent_path(subject_id: str, settings: Settings) -> Path:
    return settings.consent_dir / subject_id / "consent.json"


def _encoding_path(subject_id: str, settings: Settings) -> Path:
    return settings.enrolled_dir / subject_id / "encoding.npz"


def _validate_subject_id(subject_id: str) -> str:
    """Subject ids become directory names, so keep them boring."""
    cleaned = subject_id.strip()
    if not cleaned:
        raise ConsentError("subject id must not be empty")
    if not all(c.isalnum() or c in "-_" for c in cleaned):
        raise ConsentError(
            f"subject id {subject_id!r} may contain only letters, digits, '-' and '_'"
        )
    return cleaned


def is_enrolled(subject_id: str, settings: Settings | None = None) -> bool:
    settings = settings or get_settings()
    try:
        sid = _validate_subject_id(subject_id)
    except ConsentError:
        return False
    return _consent_path(sid, settings).is_file() and _encoding_path(sid, settings).is_file()


def list_subjects(settings: Settings | None = None) -> list[ConsentRecord]:
    settings = settings or get_settings()
    if not settings.consent_dir.is_dir():
        return []
    out = []
    for d in sorted(p for p in settings.consent_dir.iterdir() if p.is_dir()):
        if is_enrolled(d.name, settings):
            out.append(load_consent(d.name, settings))
    return out


def load_consent(subject_id: str, settings: Settings | None = None) -> ConsentRecord:
    settings = settings or get_settings()
    sid = _validate_subject_id(subject_id)
    path = _consent_path(sid, settings)
    if not path.is_file():
        raise ConsentDenied(
            f"no consent record for subject {sid!r}. Run: facechain enroll --subject {sid} ...",
            reason="not_enrolled",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConsentError(f"consent record for {sid!r} is not valid JSON: {exc}") from exc
    return ConsentRecord.from_dict(data)


def load_encoding(subject_id: str, settings: Settings | None = None) -> FaceEncoding:
    settings = settings or get_settings()
    sid = _validate_subject_id(subject_id)
    path = _encoding_path(sid, settings)
    if not path.is_file():
        raise ConsentDenied(
            f"subject {sid!r} has a consent record but no enrolled encoding",
            reason="not_enrolled",
        )
    with np.load(path, allow_pickle=False) as z:
        vector = np.asarray(z["vector"], dtype=np.float32)
        vector.flags.writeable = False
        return FaceEncoding(
            vector=vector,
            bbox=tuple(int(v) for v in z["bbox"]),
            det_score=float(z["det_score"]),
            model=str(z["model"].item()),
        )


def enroll(
    subject_id: str,
    image: bytes | str | Path,
    consent_statement: str,
    display_name: str | None = None,
    scope: str = DEFAULT_SCOPE,
    date: str | None = None,
    overwrite: bool = False,
    settings: Settings | None = None,
) -> ConsentRecord:
    """Record consent for a subject and store their face encoding.

    The enrolment photograph itself is never copied into ``data/`` -- only the derived
    encoding is kept, so the repository never holds a picture of anyone.
    """
    settings = settings or get_settings()
    sid = _validate_subject_id(subject_id)

    if not consent_statement or not consent_statement.strip():
        raise ConsentError("a non-empty consent statement is required to enrol a subject")

    if is_enrolled(sid, settings) and not overwrite:
        raise AlreadyEnrolled(
            f"subject {sid!r} is already enrolled; pass overwrite=True to replace"
        )

    encoding = primary_face(image)

    record = ConsentRecord(
        schema=CONSENT_SCHEMA,
        subject_id=sid,
        display_name=(display_name or sid).strip(),
        date=date or _utc_now(),
        scope=scope,
        statement=consent_statement.strip(),
        model=encoding.model,
    )

    consent_path = _consent_path(sid, settings)
    encoding_path = _encoding_path(sid, settings)
    consent_path.parent.mkdir(parents=True, exist_ok=True)
    encoding_path.parent.mkdir(parents=True, exist_ok=True)

    consent_path.write_text(record.to_json(), encoding="utf-8")
    np.savez(
        encoding_path,
        vector=encoding.vector,
        bbox=np.asarray(encoding.bbox, dtype=np.int32),
        det_score=np.float32(encoding.det_score),
        model=np.asarray(encoding.model),
    )
    log.info("enrolled subject %r (det_score=%.3f)", sid, encoding.det_score)
    return record


def revoke(subject_id: str, settings: Settings | None = None) -> ConsentRecord:
    """Mark consent withdrawn. The gate refuses the subject from then on.

    The enrolled encoding is deleted outright -- withdrawn consent should not leave a
    face vector sitting on disk.
    """
    settings = settings or get_settings()
    sid = _validate_subject_id(subject_id)
    record = load_consent(sid, settings)
    revoked = ConsentRecord(**{**asdict(record), "revoked_at": _utc_now()})
    _consent_path(sid, settings).write_text(revoked.to_json(), encoding="utf-8")

    encoding_path = _encoding_path(sid, settings)
    if encoding_path.is_file():
        encoding_path.unlink()
    log.info("revoked consent for subject %r and deleted the enrolled encoding", sid)
    return revoked


@dataclass(frozen=True)
class ConsentCheck:
    """Result of a passing gate check."""

    record: ConsentRecord
    similarity: float
    query_face: FaceEncoding
    enrolled_face: FaceEncoding


def check_consent(
    subject_id: str,
    query_image: bytes | str | Path,
    threshold: float | None = None,
    settings: Settings | None = None,
) -> ConsentCheck:
    """Authorise a run, or raise ``ConsentDenied``.

    Call this before uploading, searching, or fetching anything.
    """
    settings = settings or get_settings()
    threshold = settings.match_threshold if threshold is None else threshold
    sid = _validate_subject_id(subject_id)

    record = load_consent(sid, settings)
    if not record.is_active:
        raise ConsentDenied(
            f"consent for subject {sid!r} was revoked at {record.revoked_at}",
            reason="revoked",
        )

    enrolled = load_encoding(sid, settings)

    try:
        query = primary_face(query_image)
    except Exception as exc:
        raise ConsentDenied(
            f"cannot verify consent: no usable face in the query image ({exc})",
            reason="no_query_face",
        ) from exc

    if query.model != enrolled.model:
        raise ConsentDenied(
            f"subject {sid!r} was enrolled with {enrolled.model} but the query was encoded "
            f"with {query.model}; re-enrol to compare",
            reason="model_mismatch",
        )

    score = similarity(query, enrolled)
    if score < threshold:
        raise ConsentDenied(
            f"the query image does not match the enrolled face for {sid!r} "
            f"(similarity {score:.3f} < threshold {threshold:.2f}). "
            f"Consent authorises a face, not a subject id.",
            reason="face_mismatch",
        )

    log.info("consent gate passed for %r (similarity %.3f)", sid, score)
    return ConsentCheck(
        record=record, similarity=score, query_face=query, enrolled_face=enrolled
    )
