"""Search provider tests -- TASK.md 5.2, acceptance AC11."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from facechain.config import Settings
from facechain.errors import SearchError
from facechain.search.base import SearchCandidate
from facechain.search.offline import DEFAULT_FIXTURE, OfflineProvider
from facechain.search.serpapi_lens import NAME, extract_candidates

FIXTURE = Path(__file__).parent / "fixtures" / "serpapi_google_lens_response.json"


@pytest.fixture
def raw_response() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- offline provider: the AC11 path -----------------------------------------------


def test_offline_provider_needs_no_settings_at_all():
    """AC11: replay works on a machine with no .env / no keys configured."""
    no_keys = Settings(serpapi_key=None, imgbb_key=None, private_key=None)
    provider = OfflineProvider(fixture_path=FIXTURE)
    candidates, raw = provider.search_by_image("ignored")
    assert candidates
    assert raw  # the full raw response is available too, for search_raw.json


def test_offline_provider_ignores_the_requested_url():
    """A replay always returns the fixture's content, regardless of what URL is asked for."""
    provider = OfflineProvider(fixture_path=FIXTURE)
    a, _ = provider.search_by_image("https://example.com/one.jpg")
    b, _ = provider.search_by_image("https://example.com/two.jpg")
    assert [c.page_url for c in a] == [c.page_url for c in b]


def test_offline_provider_source_is_tagged_offline():
    provider = OfflineProvider(fixture_path=FIXTURE)
    candidates, _ = provider.search_by_image("ignored")
    assert all(c.source == "offline:replay" for c in candidates)


def test_offline_provider_default_fixture_path_exists():
    """The bundled fixture ships in the repo, so a clean clone works out of the box."""
    assert DEFAULT_FIXTURE.is_file()


def test_offline_provider_reports_missing_fixture_clearly(tmp_path):
    provider = OfflineProvider(fixture_path=tmp_path / "nope.json")
    with pytest.raises(SearchError, match="no offline fixture"):
        provider.search_by_image("ignored")


def test_offline_provider_reports_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json")
    with pytest.raises(SearchError, match="not valid JSON"):
        OfflineProvider(fixture_path=p).search_by_image("ignored")


def test_offline_replay_matches_what_live_extraction_would_produce(raw_response):
    """The replay must not be a parallel reimplementation that can drift from the live
    provider's parsing -- both must extract the same candidates from the same bytes."""
    live_shape = extract_candidates(raw_response, source=NAME)
    offline_candidates, _ = OfflineProvider(fixture_path=FIXTURE).search_by_image("ignored")
    assert [c.page_url for c in live_shape] == [c.page_url for c in offline_candidates]
    assert [c.raw for c in live_shape] == [c.raw for c in offline_candidates]


# --- extraction logic (shared by live and offline) ----------------------------------


def test_extract_candidates_from_the_real_captured_response(raw_response):
    candidates = extract_candidates(raw_response)
    assert len(candidates) > 0
    assert all(isinstance(c, SearchCandidate) for c in candidates)
    assert all(c.page_url.startswith("http") for c in candidates)
    assert all(c.source == NAME for c in candidates)


def test_extract_candidates_deduplicates_across_buckets():
    data = {
        "visual_matches": [{"link": "https://x.test/a", "title": "A"}],
        "organic_results": [{"link": "https://x.test/a", "title": "A dup"}],
    }
    candidates = extract_candidates(data)
    assert len(candidates) == 1
    assert candidates[0].title == "A"  # first occurrence wins


def test_extract_candidates_skips_entries_without_a_link():
    data = {"visual_matches": [{"title": "no link here"}, {"link": "https://x.test/b"}]}
    candidates = extract_candidates(data)
    assert len(candidates) == 1


def test_extract_candidates_preserves_raw_entry_verbatim():
    """TASK.md 2.2: `raw` must be the provider's own entry, unmodified."""
    entry = {"link": "https://x.test/c", "title": "T", "extra_field": {"nested": True}}
    candidates = extract_candidates({"visual_matches": [entry]})
    assert candidates[0].raw == entry
    assert candidates[0].raw is not entry or candidates[0].raw == entry  # content, at minimum


def test_extract_candidates_handles_missing_buckets_gracefully():
    assert extract_candidates({}) == []
    assert extract_candidates({"visual_matches": []}) == []


def test_extract_candidates_carries_thumbnail_when_present():
    data = {"visual_matches": [{"link": "https://x.test/d", "thumbnail": "https://x.test/thumb.jpg"}]}
    assert extract_candidates(data)[0].thumbnail_url == "https://x.test/thumb.jpg"


def test_extract_candidates_thumbnail_none_when_absent():
    data = {"visual_matches": [{"link": "https://x.test/e"}]}
    assert extract_candidates(data)[0].thumbnail_url is None


# --- real-response shape sanity (documents what the captured fixture looks like) ----


def test_captured_fixture_reports_success(raw_response):
    assert raw_response.get("search_metadata", {}).get("status") == "Success"


def test_captured_fixture_has_visual_matches(raw_response):
    assert len(raw_response.get("visual_matches", [])) > 0
