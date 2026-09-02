"""Full pipeline wiring -- TASK.md 8.

Runs stages 1 -> 2 -> 3 and writes a complete run directory. The ordering constraints
that matter, and why:

1. **The consent gate runs first, before anything leaves the machine.** Not just before
   the search -- before the query image is uploaded to an image host. A run denied after
   the upload would already have published the subject's photo to a third party
   (DECISIONS.md D9).
2. **Artifacts are written on every terminal outcome, including failures.** TASK.md 2.2
   requires a clean NO_MATCH to still produce its run artifacts, and the same reasoning
   applies to SEARCH_FAILED: a run that produced no evidence of what it attempted is not
   auditable.
3. **Anchoring is the last step and is allowed to fail without losing the run.** The
   evidence is already written and hashed by then; a chain outage downgrades the status
   to MATCHED_NOT_ANCHORED rather than discarding a successful match.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, get_settings
from .consent import check_consent
from .errors import (
    AlreadyAnchoredError,
    ConsentDenied,
    HostingError,
    SearchError,
)
from .evidence import (
    MatchInfo,
    QueryInfo,
    SearchInfo,
    build_evidence,
    evidence_hash,
    new_run_id,
    phash,
    record_id_for,
    sha256_bytes,
    sha256_file,
    sha256_text,
    write_evidence,
)
from .logging_setup import set_run_id
from .matcher import find_matches
from .status import Status

log = logging.getLogger(__name__)

SEARCH_RAW_FILENAME = "search_raw.json"
RESULT_FILENAME = "result.json"


@dataclass
class RunResult:
    """Everything the CLI and report need, without re-reading the run directory."""

    status: Status
    run_id: str
    run_dir: Path
    message: str = ""
    evidence: dict | None = None
    evidence_path: Path | None = None
    anchor_tx: str | None = None
    anchor_block: int | None = None
    record_id: str | None = None
    evidence_hash: str | None = None

    @property
    def ok(self) -> bool:
        return self.status.ok


def _write_result(result: RunResult) -> None:
    """A small machine-readable summary of the run's outcome.

    Separate from evidence.json on purpose: evidence.json is the canonical, hashed,
    anchored artifact and must contain exactly the TASK.md 6 fields and nothing else.
    Run metadata like the anchoring transaction hash belongs alongside it, not inside it.
    """
    payload = {
        "status": result.status.value,
        "run_id": result.run_id,
        "message": result.message,
        "record_id": result.record_id,
        "evidence_hash": result.evidence_hash,
        "anchor_tx": result.anchor_tx,
        "anchor_block": result.anchor_block,
    }
    (result.run_dir / RESULT_FILENAME).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_scan(
    subject_id: str,
    image: str | Path,
    provider_name: str = "offline",
    anchor_enabled: bool = True,
    network: str = "local",
    settings: Settings | None = None,
) -> RunResult:
    """Stage 1 -> 2 -> 3. Always returns a RunResult; never raises for an expected outcome."""
    settings = settings or get_settings()
    run_id = new_run_id()
    set_run_id(run_id)  # every log line from here on is attributable to this run
    run_dir = settings.out_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    image_path = Path(image)

    log.info("run %s starting (subject=%s, provider=%s)", run_id, subject_id, provider_name)

    # --- Stage 1: consent gate, before any network activity whatsoever ---------------
    try:
        consent = check_consent(subject_id, image_path, settings=settings)
    except ConsentDenied as exc:
        result = RunResult(
            status=Status.CONSENT_DENIED, run_id=run_id, run_dir=run_dir, message=str(exc)
        )
        _write_result(result)
        return result

    query_face = consent.query_face
    query = QueryInfo(
        image_sha256=sha256_file(image_path),
        image_phash=phash(image_path),
        face_model=query_face.model,
        det_score=query_face.det_score,
    )

    # --- Stage 2: host, search, re-verify --------------------------------------------
    hosted_url = "offline-replay"
    try:
        provider, hosted_url = _build_provider(provider_name, image_path, settings)
        candidates, raw_response = provider.search_by_image(hosted_url)
    except (SearchError, HostingError) as exc:
        raw_path = run_dir / SEARCH_RAW_FILENAME
        raw_path.write_text(
            json.dumps({"error": str(exc), "provider": provider_name}, indent=2),
            encoding="utf-8",
        )
        result = RunResult(
            status=Status.SEARCH_FAILED, run_id=run_id, run_dir=run_dir, message=str(exc)
        )
        _write_result(result)
        return result

    # TASK.md 2.2: the complete raw response, verbatim and unfiltered -- this is the
    # evidence that the search step was real.
    raw_bytes = json.dumps(raw_response, indent=2, ensure_ascii=False).encode("utf-8")
    (run_dir / SEARCH_RAW_FILENAME).write_bytes(raw_bytes)

    matches, stats = find_matches(
        candidates, str(image_path), settings.match_threshold, settings.max_candidates
    )

    search_info = SearchInfo(
        provider=provider.name,
        hosted_query_url=hosted_url,
        candidates_returned=stats.candidates_returned,
        candidates_fetched=stats.candidates_fetched,
        candidates_matched=stats.candidates_matched,
        search_raw_sha256=sha256_bytes(raw_bytes),
    )

    best = matches[0] if matches else None
    match_info = (
        None
        if best is None
        else MatchInfo(
            page_url=best.page_url,
            page_title=best.page_title,
            page_text_sha256=sha256_text(best.page_text_excerpt),
            matched_image_url=best.matched_image_url,
            matched_image_sha256=best.matched_image_sha256,
            similarity=best.similarity,
            match_threshold=settings.match_threshold,
            fetched_at=best.fetched_at,
        )
    )

    evidence = build_evidence(
        run_id=run_id, subject_id=subject_id, query=query, search=search_info, match=match_info
    )
    evidence_path = write_evidence(run_dir, evidence)

    if match_info is None:
        # TASK.md 2.2: a clean no-match is a valid outcome with full artifacts written.
        result = RunResult(
            status=Status.NO_MATCH,
            run_id=run_id,
            run_dir=run_dir,
            message=(
                f"no candidate passed face re-verification "
                f"({stats.candidates_fetched} fetched of {stats.candidates_returned} returned)"
            ),
            evidence=evidence,
            evidence_path=evidence_path,
            evidence_hash=evidence_hash(evidence),
        )
        _write_result(result)
        return result

    result = RunResult(
        status=Status.MATCHED_NOT_ANCHORED,
        run_id=run_id,
        run_dir=run_dir,
        message=f"matched {best.page_url} at similarity {best.similarity:.3f}",
        evidence=evidence,
        evidence_path=evidence_path,
        evidence_hash=evidence_hash(evidence),
        record_id=record_id_for(evidence),
    )

    # --- Stage 3: anchor -------------------------------------------------------------
    if not anchor_enabled:
        result.message += " (anchoring skipped: --no-anchor)"
        _write_result(result)
        return result

    from .chain.anchor import anchor as do_anchor

    try:
        anchored = do_anchor(network, evidence, settings=settings)
        result.status = Status.MATCHED_AND_ANCHORED
        result.anchor_tx = anchored.tx_hash
        result.anchor_block = anchored.block_number
    except AlreadyAnchoredError:
        # Not a failure: this exact evidence is already on chain, which is the correct
        # outcome of re-running an identical scan (TASK.md 10.9).
        result.status = Status.MATCHED_AND_ANCHORED
        result.message += " (already anchored on a previous run)"
    except Exception as exc:  # noqa: BLE001 -- deliberately broad, see below
        # The match and its evidence are already written and hashed. A chain outage
        # must not discard that -- it downgrades the status, and the evidence stays
        # anchorable later via `facechain anchor`.
        result.message += f" (anchoring failed: {exc})"
        log.warning("run %s: anchoring failed: %s", run_id, exc)

    _write_result(result)
    return result


def _build_provider(provider_name: str, image_path: Path, settings: Settings):
    """Returns (provider, hosted_url). Hosting only happens for live providers -- the
    offline path must never upload anything (that is what makes AC11 runnable with no
    keys and no network).
    """
    if provider_name == "offline":
        from .search.offline import OfflineProvider

        return OfflineProvider(), "offline-replay"

    if provider_name == "serpapi":
        from .hosting import upload_query_image
        from .search.serpapi_lens import SerpApiLensProvider

        hosted = upload_query_image(image_path, settings=settings)
        return SerpApiLensProvider(settings=settings), hosted.url

    raise SearchError(f"unknown provider {provider_name!r}; expected 'serpapi' or 'offline'")
