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


class ChainError(FaceChainError):
    """Base for compile/deploy/anchor/verify failures."""


class AlreadyAnchoredError(ChainError):
    """The record id is already anchored on chain (maps to the contract's custom error)."""

    def __init__(self, record_id: str) -> None:
        super().__init__(f"record {record_id} is already anchored")
        self.record_id = record_id


class RecordNotFoundError(ChainError):
    """No record with this id exists on chain."""

    def __init__(self, record_id: str) -> None:
        super().__init__(f"no on-chain record for {record_id}")
        self.record_id = record_id


class TamperedError(ChainError):
    """The evidence's recomputed hash does not match what is anchored on chain."""

    def __init__(self, expected: str, on_chain: str) -> None:
        super().__init__(
            f"evidence hash does not match the anchored hash: "
            f"recomputed={expected} on_chain={on_chain}"
        )
        self.expected = expected
        self.on_chain = on_chain


class HostingError(FaceChainError):
    """Could not obtain a public URL for the query image."""


class SearchError(FaceChainError):
    """A search provider failed. Maps to status SEARCH_FAILED."""


class ScrapeError(FaceChainError):
    """A page could not be fetched or parsed. Non-fatal to a run -- the candidate is
    skipped and logged, not raised past the matcher."""


class MatcherError(FaceChainError):
    """Stage 2 orchestration failed in a way that is not a single candidate's fault."""
