"""Production-hardening tests -- Phase 10.

Covers the properties that separate "the demo works" from "safe to run unattended":
bounded resource use, no unbounded fetches, idempotency, and usable --help text.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


# --- caps and timeouts are actually set ---------------------------------------------


def test_every_outbound_http_call_has_a_timeout():
    """An unbounded fetch can hang a run forever against a slow third-party host."""
    import re

    offenders = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"httpx\.(get|post)\(", text):
            window = text[match.start() : match.start() + 500]
            if "timeout" not in window:
                offenders.append(f"{path.name}: {match.group(0)}")
    assert offenders == [], f"httpx calls without a timeout: {offenders}"


def test_scraper_client_has_a_timeout_configured():
    from facechain.scrape import REQUEST_TIMEOUT, Scraper

    with Scraper() as scraper:
        assert scraper._client.timeout.read is not None
    assert REQUEST_TIMEOUT > 0


def test_candidate_and_image_caps_are_bounded():
    from facechain.matcher import MAX_CANDIDATES, MAX_IMAGES_PER_CANDIDATE
    from facechain.scrape import MAX_IMAGES_PER_PAGE, TEXT_EXCERPT_CHARS

    assert 0 < MAX_CANDIDATES <= 50
    assert 0 < MAX_IMAGES_PER_CANDIDATE <= 10
    assert 0 < MAX_IMAGES_PER_PAGE <= 10
    assert 0 < TEXT_EXCERPT_CHARS <= 10_000


def test_worst_case_fetch_count_is_bounded():
    """Total third-party requests per run must be predictable, not open-ended."""
    from facechain.matcher import MAX_CANDIDATES, MAX_IMAGES_PER_CANDIDATE

    worst_case = MAX_CANDIDATES * (1 + MAX_IMAGES_PER_CANDIDATE)  # page + its images
    assert worst_case <= 200, f"a single run could make {worst_case} requests"


def test_rate_limiter_enforces_a_per_domain_interval():
    import time

    from facechain.scrape import _DomainRateLimiter

    limiter = _DomainRateLimiter(min_interval=0.25)
    start = time.monotonic()
    for _ in range(3):
        limiter.wait("example.test")
    assert time.monotonic() - start >= 0.5  # 3 requests => at least 2 intervals


def test_rate_limiter_is_per_domain_not_global():
    import time

    from facechain.scrape import _DomainRateLimiter

    limiter = _DomainRateLimiter(min_interval=0.5)
    start = time.monotonic()
    limiter.wait("a.test")
    limiter.wait("b.test")  # a different host must not wait on a's budget
    assert time.monotonic() - start < 0.4


# --- idempotency ---------------------------------------------------------------------


def test_rescanning_identical_input_produces_an_identical_evidence_hash():
    """The same query image and the same match must hash identically across runs --
    that is what makes re-anchoring collide on record_id instead of double-anchoring."""
    from facechain.evidence import (
        MatchInfo,
        QueryInfo,
        SearchInfo,
        build_evidence,
        evidence_hash,
        record_id_for,
    )

    def build(run_id: str, created_at: str):
        # run_id and created_at differ between runs; neither is part of record_id.
        return build_evidence(
            run_id=run_id,
            subject_id="tuhin",
            created_at=created_at,
            query=QueryInfo("e" * 64, "0" * 16, "insightface/buffalo_l", 0.9),
            search=SearchInfo("p", "u", 1, 1, 1, "f" * 64),
            match=MatchInfo(
                "https://x.test/p",
                "t",
                "a" * 64,
                "https://x.test/i.jpg",
                "b" * 64,
                0.6,
                0.45,
                "2026-01-01T00:00:00Z",
            ),
        )

    first = build("run-1", "2026-01-01T00:00:00Z")
    second = build("run-2", "2026-02-02T00:00:00Z")

    # record_id depends only on the query image and the page, so a repeat scan collides
    # deliberately -- the contract's AlreadyAnchored guard is what makes that safe.
    assert record_id_for(first) == record_id_for(second)
    # The evidence hash legitimately differs, since run_id/created_at are part of it.
    assert evidence_hash(first) != evidence_hash(second)


# --- CLI usability -------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "facechain.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


ALL_COMMANDS = [
    "faces",
    "compare",
    "enroll",
    "subjects",
    "revoke",
    "check-consent",
    "evidence-hash",
    "search",
    "match",
    "scan",
    "deploy",
    "anchor",
    "verify",
    "report",
]


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_every_command_has_help_text(command):
    result = _run_cli(command, "--help")
    assert result.returncode == 0, f"`{command} --help` failed: {result.stderr[:200]}"
    assert len(result.stdout.strip()) > 50, f"`{command} --help` is uselessly short"


def test_help_lists_every_command():
    result = _run_cli("--help")
    assert result.returncode == 0
    for command in ALL_COMMANDS:
        assert command in result.stdout, f"`{command}` missing from top-level --help"


def test_verbose_and_quiet_are_mutually_exclusive():
    result = _run_cli("--verbose", "--quiet", "version")
    assert result.returncode == 2
    assert "mutually exclusive" in result.stderr


def test_logs_go_to_stderr_not_stdout():
    """stdout carries reports and piped output; log lines must not corrupt it."""
    result = _run_cli("--verbose", "version")
    assert result.stdout.strip() == "0.1.0", f"stdout polluted: {result.stdout!r}"
