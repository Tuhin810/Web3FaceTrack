"""Stage 2 orchestration -- TASK.md 5.2 steps 3-7.

Turns a list of search candidates into ranked, face-verified matches:

1. Prioritise likely social/profile domains, but keep the rest (TASK.md 5.2 step 3) --
   nothing is discarded, only reordered, up to MAX_CANDIDATES.
2. For each candidate: fetch the page (robots-honouring, rate-limited -- scrape.py),
   fetch up to 5 images from it.
3. For each fetched image, detect and compare **every** face on it, not just the
   largest. DECISIONS.md D5: on a degraded copy of a multi-face image, which face
   `primary_face()` selects as largest is unstable -- a group photo scraped from the
   web is exactly that case, so comparing only the primary face risks silently
   comparing the query against the wrong person while the right one sits unchecked in
   the same frame.
4. A candidate passes if any image, any face, scores >= threshold. Record the best.

Ethics constraint that shapes the whole module (TASK.md 2.1): every third-party image
byte fetched here lives only in a local variable for the duration of one comparison and
is never written to disk or embedded in anything returned. Nothing in this file opens a
file handle for writing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

from .errors import ScrapeError
from .evidence import sha256_bytes
from .face import FaceEncoding, detect_faces, primary_face, similarity
from .scrape import Scraper, image_meets_min_dimension
from .search.base import SearchCandidate

log = logging.getLogger(__name__)

MAX_CANDIDATES = 15
MAX_IMAGES_PER_CANDIDATE = 5

# TASK.md 5.2 step 3: filter to these first, but do not discard the rest.
PRIORITY_DOMAINS = (
    "instagram.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
    "facebook.com",
    "github.com",
    "medium.com",
)


@dataclass(frozen=True)
class VerifiedMatch:
    page_url: str
    matched_image_url: str
    similarity: float
    page_title: str | None
    page_text_excerpt: str
    matched_image_sha256: str
    fetched_at: str  # ISO 8601 UTC


@dataclass(frozen=True)
class MatchRunStats:
    """Counts that feed the evidence record and the run report (TASK.md 6, 2.2)."""

    candidates_returned: int
    candidates_fetched: int
    candidates_matched: int


def _is_priority(candidate: SearchCandidate) -> bool:
    host = urlparse(candidate.page_url).netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in PRIORITY_DOMAINS)


def rank_candidates(
    candidates: list[SearchCandidate], max_candidates: int = MAX_CANDIDATES
) -> list[SearchCandidate]:
    """Priority-domain candidates first, in their original relative order; the rest
    follow, also in their original order. Nothing is dropped by this step alone --
    only `max_candidates` truncates, per TASK.md 5.2 step 3.
    """
    priority = [c for c in candidates if _is_priority(c)]
    rest = [c for c in candidates if not _is_priority(c)]
    return (priority + rest)[:max_candidates]


def _score_image_against_query(image_bytes: bytes, query: FaceEncoding) -> tuple[float, int] | None:
    """Best similarity across every face in the image, and how many faces were found.

    Returns None if the image cannot be decoded or contains no face at all -- both are
    "this image contributes nothing", not an error worth interrupting the run for.
    """
    try:
        faces = detect_faces(image_bytes)
    except Exception as exc:  # noqa: BLE001 -- a single bad image must not abort the run
        log.debug("could not decode/detect faces in candidate image: %s", exc)
        return None
    if not faces:
        return None
    best = max(similarity(query, f) for f in faces)
    return best, len(faces)


def verify_candidate(
    candidate: SearchCandidate,
    query: FaceEncoding,
    scraper: Scraper,
    match_threshold: float,
) -> VerifiedMatch | None:
    """Fetch one candidate page and its images, score every face against the query.

    Returns None if the page could not be fetched, was disallowed, or no image on it
    reaches match_threshold -- a candidate not passing is not an error.
    """
    try:
        page = scraper.fetch_page(candidate.page_url)
    except ScrapeError as exc:
        log.info("skipping candidate %s: %s", candidate.page_url, exc)
        return None

    best_score = -1.0
    best_url: str | None = None
    best_bytes: bytes | None = None

    for image_url in page.image_urls[:MAX_IMAGES_PER_CANDIDATE]:
        try:
            data = scraper.fetch_image_bytes(image_url)
        except ScrapeError as exc:
            log.debug("skipping image %s: %s", image_url, exc)
            continue
        if not image_meets_min_dimension(data):
            continue

        scored = _score_image_against_query(data, query)
        # `data` (and any face vectors derived from it) go out of scope at the end of
        # this loop iteration -- nothing here is written to disk or retained past the
        # comparison, per TASK.md 2.1.
        if scored is None:
            continue
        score, n_faces = scored
        if n_faces > 1:
            log.debug("%s: %d faces detected, scored against the best match", image_url, n_faces)
        if score > best_score:
            best_score, best_url, best_bytes = score, image_url, data

    if best_url is None or best_score < match_threshold:
        return None

    return VerifiedMatch(
        page_url=candidate.page_url,
        matched_image_url=best_url,
        similarity=best_score,
        page_title=page.og_title or page.title,
        page_text_excerpt=page.text_excerpt,
        matched_image_sha256=sha256_bytes(best_bytes),
        fetched_at=page.fetched_at,
    )


def find_matches(
    candidates: list[SearchCandidate],
    query_image: bytes | str,
    match_threshold: float,
    max_candidates: int = MAX_CANDIDATES,
    scraper: Scraper | None = None,
) -> tuple[list[VerifiedMatch], MatchRunStats]:
    """The full stage-2 sweep: rank, fetch, verify, return matches ranked by score."""
    query = primary_face(query_image)
    ranked = rank_candidates(candidates, max_candidates)

    own_scraper = scraper is None
    scraper = scraper or Scraper()
    try:
        matches: list[VerifiedMatch] = []
        fetched = 0
        for candidate in ranked:
            fetched += 1
            result = verify_candidate(candidate, query, scraper, match_threshold)
            if result is not None:
                matches.append(result)
    finally:
        if own_scraper:
            scraper.close()

    matches.sort(key=lambda m: m.similarity, reverse=True)
    stats = MatchRunStats(
        candidates_returned=len(candidates),
        candidates_fetched=fetched,
        candidates_matched=len(matches),
    )
    return matches, stats
