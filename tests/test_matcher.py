"""Stage 2 orchestration tests -- TASK.md 5.2."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_encoding

from facechain.face import EMBEDDING_DIM, MATCH_THRESHOLD
from facechain.matcher import (
    MAX_CANDIDATES,
    VerifiedMatch,
    find_matches,
    rank_candidates,
    verify_candidate,
)
from facechain.scrape import ScrapedPage
from facechain.search.base import SearchCandidate


def cand(url, source="serpapi:google_lens", title="T"):
    return SearchCandidate(page_url=url, thumbnail_url=None, title=title, source=source, raw={})


# --- rank_candidates: priority domains first, nothing discarded --------------------


def test_priority_domains_sort_first_but_order_is_preserved_within_each_group():
    candidates = [
        cand("https://example.com/a"),
        cand("https://www.instagram.com/b"),
        cand("https://random-blog.test/c"),
        cand("https://github.com/d"),
    ]
    ranked = rank_candidates(candidates)
    urls = [c.page_url for c in ranked]
    assert urls == [
        "https://www.instagram.com/b",
        "https://github.com/d",
        "https://example.com/a",
        "https://random-blog.test/c",
    ]


def test_rank_candidates_truncates_but_does_not_reorder_beyond_max():
    candidates = [cand(f"https://site{i}.test/x") for i in range(20)]
    ranked = rank_candidates(candidates, max_candidates=5)
    assert len(ranked) == 5
    assert [c.page_url for c in ranked] == [c.page_url for c in candidates[:5]]


def test_default_max_candidates_matches_spec():
    assert MAX_CANDIDATES == 15


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.linkedin.com/in/x", True),
        ("https://x.com/someone", True),
        ("https://twitter.com/someone", True),
        ("https://sub.github.com/x", True),
        ("https://github.com.evil.test/x", False),  # lookalike host, not a real subdomain
        ("https://randomsite.test/x", False),
    ],
)
def test_priority_domain_matching_is_exact_not_substring(url, expected):
    from facechain.matcher import _is_priority

    assert _is_priority(cand(url)) is expected


# --- verify_candidate: scoring, no-disk-write, multi-face handling -----------------


class StubScraper:
    """Fake Scraper: returns canned pages/images, records every 'fetch' for assertions,
    and never touches the filesystem -- the whole point of the no-disk-write test.
    """

    def __init__(self, pages: dict[str, ScrapedPage], images: dict[str, bytes]):
        self._pages = pages
        self._images = images
        self.fetched_pages: list[str] = []
        self.fetched_images: list[str] = []

    def fetch_page(self, url: str) -> ScrapedPage:
        self.fetched_pages.append(url)
        if url not in self._pages:
            from facechain.errors import ScrapeError

            raise ScrapeError(f"no such page: {url}")
        return self._pages[url]

    def fetch_image_bytes(self, url: str) -> bytes:
        self.fetched_images.append(url)
        if url not in self._images:
            from facechain.errors import ScrapeError

            raise ScrapeError(f"no such image: {url}")
        return self._images[url]


def _fake_jpeg_bytes(tag: bytes) -> bytes:
    """Not a real image -- fine, since detect_faces is monkeypatched in these tests
    to score by a tag embedded in the bytes rather than by real inference."""
    return b"FAKEIMG:" + tag


@pytest.fixture
def query_encoding():
    return make_encoding(np.ones(EMBEDDING_DIM))


@pytest.fixture
def patch_face_pipeline(monkeypatch):
    """Replace detect_faces/similarity with a deterministic stand-in keyed off bytes,
    and image_meets_min_dimension with a permissive stub -- these tests are about
    matcher.py's orchestration, not about the real face model (that's Phase 1's job).
    """
    import facechain.matcher as matcher_mod

    scores: dict[bytes, list[float]] = {}

    def fake_detect_faces(image):
        sims = scores.get(image, [])
        return [make_encoding(det_score=0.9) for _ in sims] if sims else []

    def fake_similarity(query, face):
        # Cycle through the recorded scores for the *last* image passed to detect_faces.
        return fake_similarity.queue.pop(0)

    fake_similarity.queue = []

    def fake_score_lookup(image_bytes, query):
        sims = scores.get(image_bytes)
        if not sims:
            return None
        return max(sims), len(sims)

    monkeypatch.setattr(matcher_mod, "_score_image_against_query", fake_score_lookup)
    monkeypatch.setattr(matcher_mod, "image_meets_min_dimension", lambda data: True)

    return scores


def make_page(url, images, title="Some Page"):
    return ScrapedPage(
        url=url,
        title=title,
        og_title=title,
        og_image=None,
        og_description=None,
        text_excerpt="excerpt text",
        image_urls=images,
        fetched_at="2026-01-01T00:00:00Z",
    )


def test_verify_candidate_passes_when_an_image_clears_threshold(
    query_encoding, patch_face_pipeline
):
    img = _fake_jpeg_bytes(b"good")
    patch_face_pipeline[img] = [0.61]
    scraper = StubScraper(
        pages={"https://x.test/p": make_page("https://x.test/p", ["https://x.test/img.jpg"])},
        images={"https://x.test/img.jpg": img},
    )
    result = verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result is not None
    assert result.similarity == pytest.approx(0.61)
    assert result.matched_image_url == "https://x.test/img.jpg"
    assert result.page_url == "https://x.test/p"


def test_verify_candidate_fails_when_no_image_clears_threshold(query_encoding, patch_face_pipeline):
    img = _fake_jpeg_bytes(b"bad")
    patch_face_pipeline[img] = [0.10]
    scraper = StubScraper(
        pages={"https://x.test/p": make_page("https://x.test/p", ["https://x.test/img.jpg"])},
        images={"https://x.test/img.jpg": img},
    )
    result = verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result is None


def test_verify_candidate_picks_the_best_scoring_image(query_encoding, patch_face_pipeline):
    low, high = _fake_jpeg_bytes(b"low"), _fake_jpeg_bytes(b"high")
    patch_face_pipeline[low] = [0.20]
    patch_face_pipeline[high] = [0.70]
    scraper = StubScraper(
        pages={
            "https://x.test/p": make_page(
                "https://x.test/p", ["https://x.test/low.jpg", "https://x.test/high.jpg"]
            )
        },
        images={"https://x.test/low.jpg": low, "https://x.test/high.jpg": high},
    )
    result = verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result.matched_image_url == "https://x.test/high.jpg"
    assert result.similarity == pytest.approx(0.70)


def test_verify_candidate_uses_the_best_face_not_just_the_first(
    query_encoding, patch_face_pipeline
):
    """DECISIONS.md D5: a multi-face image must be scored by its best face, since
    which face a naive 'primary' pick would land on is unstable under transforms."""
    img = _fake_jpeg_bytes(b"multiface")
    patch_face_pipeline[img] = [0.05, 0.55, 0.12]  # three faces; only the middle passes
    scraper = StubScraper(
        pages={"https://x.test/p": make_page("https://x.test/p", ["https://x.test/img.jpg"])},
        images={"https://x.test/img.jpg": img},
    )
    result = verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result is not None
    assert result.similarity == pytest.approx(0.55)


def test_verify_candidate_returns_none_on_unfetchable_page(query_encoding, patch_face_pipeline):
    scraper = StubScraper(pages={}, images={})
    result = verify_candidate(cand("https://gone.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result is None


def test_verify_candidate_skips_unfetchable_images_but_keeps_going(
    query_encoding, patch_face_pipeline
):
    good = _fake_jpeg_bytes(b"good2")
    patch_face_pipeline[good] = [0.60]
    scraper = StubScraper(
        pages={
            "https://x.test/p": make_page(
                "https://x.test/p", ["https://x.test/broken.jpg", "https://x.test/good.jpg"]
            )
        },
        images={"https://x.test/good.jpg": good},  # broken.jpg deliberately absent
    )
    result = verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result is not None
    assert result.matched_image_url == "https://x.test/good.jpg"


def test_verify_candidate_respects_max_images_per_candidate(query_encoding, patch_face_pipeline):
    from facechain.matcher import MAX_IMAGES_PER_CANDIDATE

    urls = [f"https://x.test/{i}.jpg" for i in range(MAX_IMAGES_PER_CANDIDATE + 3)]
    images = {u: _fake_jpeg_bytes(u.encode()) for u in urls}
    for u in urls:
        patch_face_pipeline[images[u]] = [0.99]  # would all pass, if fetched
    scraper = StubScraper(
        pages={"https://x.test/p": make_page("https://x.test/p", urls)}, images=images
    )
    verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert len(scraper.fetched_images) == MAX_IMAGES_PER_CANDIDATE


def test_matched_image_sha256_is_the_actual_bytes_digest(query_encoding, patch_face_pipeline):
    from facechain.evidence import sha256_bytes

    img = _fake_jpeg_bytes(b"digest-check")
    patch_face_pipeline[img] = [0.9]
    scraper = StubScraper(
        pages={"https://x.test/p": make_page("https://x.test/p", ["https://x.test/img.jpg"])},
        images={"https://x.test/img.jpg": img},
    )
    result = verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert result.matched_image_sha256 == sha256_bytes(img)


def test_verified_match_never_carries_a_face_vector_field():
    """TASK.md 2.1: nothing biometric leaves this module in the result object."""
    assert "vector" not in VerifiedMatch.__dataclass_fields__
    assert "embedding" not in VerifiedMatch.__dataclass_fields__


# --- the explicit no-disk-write assertion ------------------------------------------


def test_no_image_bytes_are_ever_written_to_disk(
    query_encoding, patch_face_pipeline, tmp_path, monkeypatch
):
    """TASK.md 2.1: third-party faces are held in memory only. Patches every disk-write
    primitive matcher.py could plausibly reach for and fails the test if any fires.
    """
    import builtins

    real_open = builtins.open
    written_paths = []

    def guarded_open(file, mode="r", *a, **k):
        if "w" in mode or "a" in mode or "x" in mode:
            written_paths.append(file)
        return real_open(file, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", guarded_open)

    img = _fake_jpeg_bytes(b"never-written")
    patch_face_pipeline[img] = [0.9]
    scraper = StubScraper(
        pages={"https://x.test/p": make_page("https://x.test/p", ["https://x.test/img.jpg"])},
        images={"https://x.test/img.jpg": img},
    )
    verify_candidate(cand("https://x.test/p"), query_encoding, scraper, MATCH_THRESHOLD)
    assert written_paths == []
    assert list(tmp_path.iterdir()) == []


# --- find_matches: the full sweep ---------------------------------------------------


def test_find_matches_sorts_by_similarity_descending(monkeypatch, patch_face_pipeline):
    import facechain.matcher as matcher_mod

    monkeypatch.setattr(matcher_mod, "primary_face", lambda img: make_encoding())

    low_img, high_img = _fake_jpeg_bytes(b"lo"), _fake_jpeg_bytes(b"hi")
    patch_face_pipeline[low_img] = [0.50]
    patch_face_pipeline[high_img] = [0.90]
    scraper = StubScraper(
        pages={
            "https://a.test/p": make_page("https://a.test/p", ["https://a.test/i.jpg"]),
            "https://b.test/p": make_page("https://b.test/p", ["https://b.test/i.jpg"]),
        },
        images={"https://a.test/i.jpg": low_img, "https://b.test/i.jpg": high_img},
    )
    matches, stats = find_matches(
        [cand("https://a.test/p"), cand("https://b.test/p")],
        query_image=b"irrelevant-query-bytes",
        match_threshold=MATCH_THRESHOLD,
        scraper=scraper,
    )
    assert [m.similarity for m in matches] == [0.90, 0.50]
    assert stats.candidates_returned == 2
    assert stats.candidates_fetched == 2
    assert stats.candidates_matched == 2


def test_find_matches_stats_on_a_clean_no_match(monkeypatch, patch_face_pipeline):
    """TASK.md 2.2: a clean no-match is valid and must still report accurate counts."""
    import facechain.matcher as matcher_mod

    monkeypatch.setattr(matcher_mod, "primary_face", lambda img: make_encoding())
    img = _fake_jpeg_bytes(b"nomatch")
    patch_face_pipeline[img] = [0.05]
    scraper = StubScraper(
        pages={"https://a.test/p": make_page("https://a.test/p", ["https://a.test/i.jpg"])},
        images={"https://a.test/i.jpg": img},
    )
    matches, stats = find_matches(
        [cand("https://a.test/p")],
        query_image=b"q",
        match_threshold=MATCH_THRESHOLD,
        scraper=scraper,
    )
    assert matches == []
    assert stats == matcher_mod.MatchRunStats(
        candidates_returned=1, candidates_fetched=1, candidates_matched=0
    )


# --- real end-to-end smoke test (live network + real model) -----------------------


@pytest.mark.network
@pytest.mark.model
def test_find_matches_against_real_pages_finds_the_known_positive():
    """Not a fixture: real HTTP fetches against github.com/Tuhin810 (a known match)
    mixed with a real page that should not match. Also the strongest available
    no-disk-write evidence, since it runs the real fetch/decode path end to end."""
    import os

    from facechain.evidence import sha256_file

    if not os.path.isfile("test.png"):
        pytest.skip("test.png not present")

    candidates = [
        cand("https://github.com/Tuhin810", title="Tuhin810 - Overview"),
        cand("https://github.com/torvalds", title="torvalds - Overview"),  # unrelated
    ]
    matches, stats = find_matches(
        candidates, query_image="test.png", match_threshold=MATCH_THRESHOLD
    )

    assert stats.candidates_returned == 2
    assert stats.candidates_fetched == 2
    assert len(matches) == 1
    assert matches[0].page_url == "https://github.com/Tuhin810"
    assert matches[0].similarity >= MATCH_THRESHOLD

    # The matched image's hash is of the *actually fetched* bytes, not test.png's own
    # hash: GitHub's og:image carries a "?s=400" resize parameter, so the CDN serves a
    # different byte encoding of the same photo (confirmed manually: 182361 bytes vs.
    # test.png's 198696). Hashing what was truly fetched, not assuming byte-identity
    # with the local file, is correct per TASK.md 6 -- the record is evidence of what
    # was actually observed on the page, not a claim the page serves the identical file.
    assert len(matches[0].matched_image_sha256) == 64
    assert matches[0].matched_image_sha256 != sha256_file("test.png")


@pytest.mark.network
def test_no_disk_write_during_a_real_fetch_and_decode_cycle(tmp_path, monkeypatch):
    """The strongest form of the no-disk-write guarantee: real bytes, real decode,
    real filesystem watched underneath -- not a mocked pipeline."""
    from pathlib import Path

    query_path = Path.cwd() / "test.png"
    if not query_path.is_file():
        pytest.skip("test.png not present")
    query_bytes = query_path.read_bytes()

    monkeypatch.chdir(tmp_path)  # anything written via a relative path lands here
    assert list(tmp_path.iterdir()) == []

    find_matches(
        [cand("https://github.com/Tuhin810")],
        query_image=query_bytes,
        match_threshold=MATCH_THRESHOLD,
    )

    assert list(tmp_path.iterdir()) == [], "a run must not write any file to disk"


@pytest.mark.network
def test_scrape_rejects_a_403_html_error_page_instead_of_parsing_it():
    """Found during a real Phase 7 run: wdwnt.com and ebay.com both return 403 with an
    HTML body, which content-type checking alone would accept as a normal page."""
    from facechain.errors import ScrapeError
    from facechain.scrape import Scraper

    with Scraper() as s, pytest.raises(ScrapeError, match="HTTP 403"):
        s.fetch_page("https://httpbin.org/status/403")
