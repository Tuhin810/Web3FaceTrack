"""Typed errors. Every failure the user can cause has a named exception here.

Phase 10 hardens these into a full taxonomy with exit codes; for now the rule is
simply that no bare traceback should ever reach the CLI user.
"""


class FaceChainError(Exception):
    """Base for every error this package raises deliberately."""


class ImageDecodeError(FaceChainError):
    """Bytes or path could not be decoded as an image."""


class NoFaceDetected(FaceChainError):
    """The detector found no faces at all."""


class LowConfidenceFace(FaceChainError):
    """Faces were found, but the best detection scored below MIN_DET_SCORE."""

    def __init__(self, best_score: float, threshold: float) -> None:
        super().__init__(
            f"best detection score {best_score:.3f} is below MIN_DET_SCORE {threshold:.2f}"
        )
        self.best_score = best_score
        self.threshold = threshold


class ConfigError(FaceChainError):
    """A required setting is missing or invalid for the chosen path."""


class ConsentError(FaceChainError):
    """Base for enrolment and consent-gate failures."""


class ConsentDenied(ConsentError):
    """The consent gate refused the run. Maps to status CONSENT_DENIED.

    ``reason`` is a short machine-ish tag; the message is what the user reads.
    """

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


class AlreadyEnrolled(ConsentError):
    """A subject with this id is already enrolled."""


class EvidenceError(FaceChainError):
    """The evidence record is malformed, unserialisable, or unreadable."""
