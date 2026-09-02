"""Human-readable run reports -- TASK.md 8.

Reports are built **only from the files in a run directory**, never from an in-memory
RunResult. That is a deliberate constraint, not an inconvenience: if a report can be
regenerated from disk alone, the run directory provably contains everything needed to
audit the run. Anything the report cannot show is something the artifacts failed to
capture.
"""

from __future__ import annotations

import json
from pathlib import Path

from .errors import FaceChainError
from .evidence import evidence_hash, has_match, load_evidence, record_id_for
from .status import Status

AMOY_EXPLORER = "https://amoy.polygonscan.com"


def _explorer_tx_url(tx_hash: str, network: str = "amoy") -> str | None:
    return f"{AMOY_EXPLORER}/tx/{tx_hash}" if network == "amoy" else None


def build_report(run_dir: str | Path, network: str = "local") -> str:
    """Render a run directory as a readable summary."""
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FaceChainError(f"no such run directory: {run_dir}")

    result_path = run_dir / "result.json"
    if not result_path.is_file():
        raise FaceChainError(f"{run_dir} has no result.json -- not a complete run directory")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    status = result.get("status", "UNKNOWN")

    lines: list[str] = [
        "=" * 64,
        f"  facechain run report -- {result.get('run_id', run_dir.name)}",
        "=" * 64,
        f"status   : {status}",
    ]
    if result.get("message"):
        lines.append(f"detail   : {result['message']}")

    search_raw = run_dir / "search_raw.json"
    if search_raw.is_file():
        lines.append(
            f"raw search response: {search_raw.name} ({search_raw.stat().st_size:,} bytes)"
        )

    evidence_path = run_dir / "evidence.json"
    if evidence_path.is_file():
        evidence = load_evidence(evidence_path)
        lines += _evidence_lines(evidence)
    else:
        lines.append("")
        lines.append("no evidence.json written (the run ended before stage 2 completed)")

    if result.get("anchor_tx"):
        lines += [
            "",
            "on-chain anchor",
            "---------------",
            f"  tx hash  : {result['anchor_tx']}",
            f"  block    : {result.get('anchor_block', 'unknown')}",
        ]
        explorer = _explorer_tx_url(result["anchor_tx"], network)
        if explorer:
            lines.append(f"  explorer : {explorer}")
    elif status == Status.MATCHED_NOT_ANCHORED.value:
        lines += [
            "",
            (
                f"not anchored -- run `facechain anchor --evidence {evidence_path}` "
                f"to anchor this evidence."
            ),
        ]

    lines.append("=" * 64)
    return "\n".join(lines)


def _evidence_lines(evidence: dict) -> list[str]:
    query = evidence.get("query", {})
    search = evidence.get("search", {})
    lines = [
        "",
        "query",
        "-----",
        f"  subject    : {evidence.get('subject_id')}",
        f"  image sha  : {query.get('image_sha256', '')[:16]}...",
        f"  image phash: {query.get('image_phash')}",
        f"  face model : {query.get('face_model')}  (det_score {query.get('det_score')})",
        "",
        "search",
        "------",
        f"  provider   : {search.get('provider')}",
        f"  hosted url : {search.get('hosted_query_url')}",
        (
            f"  candidates : {search.get('candidates_returned')} returned, "
            f"{search.get('candidates_fetched')} fetched, "
            f"{search.get('candidates_matched')} matched"
        ),
    ]

    if has_match(evidence):
        match = evidence["match"]
        lines += [
            "",
            "verified match",
            "--------------",
            f"  page       : {match.get('page_url')}",
            f"  title      : {match.get('page_title')}",
            f"  image      : {match.get('matched_image_url')}",
            f"  similarity : {match.get('similarity')}  (threshold {match.get('match_threshold')})",
            f"  fetched at : {match.get('fetched_at')}",
            "",
            "evidence",
            "--------",
            f"  record id  : {record_id_for(evidence)}",
            f"  hash       : {evidence_hash(evidence)}",
        ]
    else:
        lines += [
            "",
            "no verified match",
            "-----------------",
            "  No candidate page contained a face matching the subject above the",
            "  threshold. This is a valid outcome, not a failure (TASK.md 2.2).",
            "",
            "evidence",
            "--------",
            f"  hash       : {evidence_hash(evidence)}",
            "  record id  : n/a (nothing to anchor without a match)",
        ]
    return lines
