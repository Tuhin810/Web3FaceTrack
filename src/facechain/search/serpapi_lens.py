"""SerpAPI Google Lens provider -- TASK.md 5.2, 3.

The verbatim raw response is what makes the search step auditable (TASK.md 2.2): every
field SerpAPI returned is dumped to disk by the caller (pipeline.py), unfiltered. This
module's job is only to make the HTTP call and reshape entries into SearchCandidate --
never to decide which ones matter. That filtering happens in matcher.py, downstream.
"""

from __future__ import annotations

import logging

import httpx

from ..config import Settings, get_settings
from ..errors import SearchError
from .base import SearchCandidate

log = logging.getLogger(__name__)

ENDPOINT = "https://serpapi.com/search.json"
DEFAULT_TIMEOUT = 30.0


NAME = "serpapi:google_lens"


def extract_candidates(data: dict, source: str = NAME) -> list[SearchCandidate]:
    """Reshape a SerpAPI google_lens response into SearchCandidates.

    Free function, not a method, specifically so `offline.py` can replay a captured
    response through the identical extraction logic without needing a live API key --
    a replay must parse exactly as the corresponding live call would have, not through
    a separate reimplementation that could quietly drift from this one.
    """
    out: list[SearchCandidate] = []
    seen_urls: set[str] = set()

    # visual_matches is Lens's own ranked list -- image-similarity driven, the primary
    # signal for this engine. organic_results is folded in too (TASK.md 5.2 step 3:
    # "do not discard the rest"), since a page can be a genuine hit without appearing
    # in visual_matches.
    for bucket in ("visual_matches", "organic_results"):
        for entry in data.get(bucket, []):
            url = entry.get("link")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            out.append(
                SearchCandidate(
                    page_url=url,
                    thumbnail_url=entry.get("thumbnail"),
                    title=entry.get("title"),
                    source=source,
                    raw=entry,
                )
            )
    return out


class SerpApiLensProvider:
    name = NAME

    def __init__(self, settings: Settings | None = None):
        self._settings = settings or get_settings()

    def search_by_image(self, image_url: str) -> tuple[list[SearchCandidate], dict]:
        """Returns (candidates, raw_response). The caller dumps raw_response verbatim."""
        key = self._settings.require("serpapi_key", "run a live reverse-image search")
        try:
            resp = httpx.get(
                ENDPOINT,
                params={"engine": "google_lens", "url": image_url, "api_key": key},
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            raise SearchError(f"SerpAPI request failed: {exc}") from exc
        except ValueError as exc:  # not valid JSON
            raise SearchError(f"SerpAPI returned a non-JSON response: {exc}") from exc

        status = data.get("search_metadata", {}).get("status")
        if status not in (None, "Success"):
            raise SearchError(
                f"SerpAPI search did not succeed (status={status}): "
                f"{data.get('error', 'no error field')}"
            )

        candidates = extract_candidates(data, source=self.name)
        log.info("SerpAPI google_lens: %d candidate(s) for %s", len(candidates), image_url)
        return candidates, data
