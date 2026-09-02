"""Search provider interface -- TASK.md 5.2.

Every provider returns the same shape, and `raw` always carries the provider's own,
unmodified entry -- not a subset of fields -- so a verbatim dump of the full response is
possible without any provider-specific reconstruction later (TASK.md 2.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class SearchCandidate:
    page_url: str
    thumbnail_url: str | None
    title: str | None
    source: str  # e.g. "serpapi:google_lens", "offline:<original source>"
    raw: dict[str, Any]  # the provider's own entry, verbatim


@runtime_checkable
class SearchProvider(Protocol):
    name: str

    def search_by_image(self, image_url: str) -> list[SearchCandidate]:
        """Reverse image search. Returns candidates in the provider's own order."""
        ...
