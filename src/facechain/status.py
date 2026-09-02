"""Pipeline exit statuses -- TASK.md 8."""

from __future__ import annotations

from enum import StrEnum


class Status(StrEnum):
    MATCHED_AND_ANCHORED = "MATCHED_AND_ANCHORED"
    MATCHED_NOT_ANCHORED = "MATCHED_NOT_ANCHORED"
    NO_MATCH = "NO_MATCH"
    CONSENT_DENIED = "CONSENT_DENIED"
    SEARCH_FAILED = "SEARCH_FAILED"

    @property
    def ok(self) -> bool:
        """Whether this status should exit zero.

        NO_MATCH is a success: TASK.md 2.2 calls a clean no-match a valid, demonstrable
        outcome, not a failure.
        """
        return self in {
            Status.MATCHED_AND_ANCHORED,
            Status.MATCHED_NOT_ANCHORED,
            Status.NO_MATCH,
        }
