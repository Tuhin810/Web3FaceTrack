"""Offline replay provider -- TASK.md 5.2, 10.11.

Replays a previously captured `search_raw.json` (the exact shape SerpAPI returned,
verbatim). No network call, no API key -- this is what makes the pipeline runnable in
CI and from a clean clone with no credentials (AC11).

Uses the same extraction logic as the live provider so replayed candidates match what
a live run against that same response would have produced -- this is a *replay*, not a
separate reimplementation that could quietly drift from the real one.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..errors import SearchError
from .base import SearchCandidate
from .serpapi_lens import extract_candidates

log = logging.getLogger(__name__)

DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "serpapi_google_lens_response.json"
)


class OfflineProvider:
    name = "offline:replay"

    def __init__(self, fixture_path: Path | str | None = None):
        self.fixture_path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE

    def search_by_image(self, image_url: str) -> tuple[list[SearchCandidate], dict]:
        """`image_url` is accepted for interface compatibility but ignored: this
        provider always replays its fixture regardless of what URL was requested.
        """
        if not self.fixture_path.is_file():
            raise SearchError(
                f"no offline fixture at {self.fixture_path}. Capture one first with a "
                f"live serpapi provider run, or pass --fixture to point at a saved "
                f"search_raw.json."
            )
        try:
            data = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SearchError(
                f"offline fixture at {self.fixture_path} is not valid JSON: {exc}"
            ) from exc

        # Same extraction function the live provider uses (see serpapi_lens.py), so a
        # fixture replays exactly as the corresponding live call would have parsed it.
        candidates = extract_candidates(data, source=self.name)
        log.info("offline replay: %d candidate(s) from %s", len(candidates), self.fixture_path.name)
        return candidates, data
