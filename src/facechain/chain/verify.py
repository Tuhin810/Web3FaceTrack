"""On-chain verification -- TASK.md 7, "the whole point of the task."

1. Read evidence.json
2. Recompute evidence_hash and record_id from its contents
3. Call get(record_id) on chain
4. Compare recomputed hash vs on-chain hash
5. Report VERIFIED or TAMPERED

The hash is always recomputed from the evidence file's own contents, never trusted from
a value stored alongside it -- otherwise the tamper test in Phase 5 would prove nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from web3 import Web3
from web3.exceptions import ContractLogicError

from ..config import Settings, get_settings
from ..errors import ChainError, RecordNotFoundError, TamperedError
from ..evidence import evidence_hash, record_id_for
from .deploy import Deployment, get_web3, load_deployment


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    record_id: str
    recomputed_hash: str
    on_chain_hash: str
    block_number: int
    anchored_at: str  # ISO 8601 UTC
    submitter: str
    uri: str
    explorer_url: str | None

    def summary(self) -> str:
        verdict = "VERIFIED ✓" if self.verified else "TAMPERED ✗"
        lines = [
            verdict,
            f"  record id      : {self.record_id}",
            f"  block          : {self.block_number if self.block_number >= 0 else 'unknown'}",
            f"  anchored at    : {self.anchored_at}",
            f"  submitter      : {self.submitter}",
        ]
        if self.explorer_url:
            lines.append(f"  explorer       : {self.explorer_url}")
        if self.verified:
            lines.append(f"  hash           : {self.on_chain_hash}")
        else:
            lines.append(f"  recomputed hash: {self.recomputed_hash}")
            lines.append(f"  on-chain hash  : {self.on_chain_hash}")
        return "\n".join(lines)


def verify(
    network: str,
    evidence: dict,
    settings: Settings | None = None,
    *,
    w3: Web3 | None = None,
    deployment: Deployment | None = None,
) -> VerificationResult:
    """Recompute the evidence's hash and compare it against the on-chain record."""
    settings = settings or get_settings()
    rid = record_id_for(evidence)
    recomputed = evidence_hash(evidence)

    w3 = w3 or get_web3(network, settings)
    deployment = deployment or load_deployment(network, settings)
    contract = w3.eth.contract(address=deployment.address, abi=deployment.abi)

    try:
        record = contract.functions.get(rid).call()
    except ContractLogicError as exc:
        raise RecordNotFoundError(rid) from exc
    except Exception as exc:
        if "NotFound" in str(exc) or "revert" in str(exc).lower():
            raise RecordNotFoundError(rid) from exc
        raise ChainError(f"could not read record {rid} from chain: {exc}") from exc

    on_chain_hash, submitter, timestamp, uri = record
    on_chain_hex = Web3.to_hex(on_chain_hash)
    block_number = _anchored_block(contract, rid)

    result = VerificationResult(
        verified=(on_chain_hex.lower() == recomputed.lower()),
        record_id=rid,
        recomputed_hash=recomputed,
        on_chain_hash=on_chain_hex,
        block_number=block_number,
        anchored_at=datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        submitter=submitter,
        uri=uri,
        explorer_url=deployment.explorer_url(),
    )
    return result


def _anchored_block(contract, record_id: str) -> int:
    """The block the record was anchored in, from the indexed MatchAnchored event.

    The contract's Record struct keeps only a timestamp, not a block number, so this is
    the one place that number can come from. Falls back to -1 (rather than the current
    chain tip, which would misleadingly imply "just now") if the log cannot be found --
    e.g. a provider that has pruned old logs.
    """
    try:
        logs = contract.events.MatchAnchored.get_logs(
            argument_filters={"recordId": record_id}, from_block=0, to_block="latest"
        )
    except Exception:  # noqa: BLE001 -- log availability varies by provider (pruning,
        # rate limits, unsupported filters); none of it should fail a verification whose
        # actual answer -- does the hash match -- has already been obtained.
        return -1
    return logs[0].blockNumber if logs else -1


def verify_or_raise(*args, **kwargs) -> VerificationResult:
    """Same as verify(), but raises TamperedError instead of returning verified=False.

    Used where a non-zero exit on mismatch is the desired behaviour (the CLI and the
    tamper test), as opposed to callers that want to inspect the result either way.
    """
    result = verify(*args, **kwargs)
    if not result.verified:
        raise TamperedError(result.recomputed_hash, result.on_chain_hash)
    return result


@dataclass(frozen=True)
class TamperReport:
    """CLI-facing outcome: TASK.md 7's two possible verdicts, VERIFIED or TAMPERED.

    `verify()` is honest at the chain level: a hash mismatch and "no record at all" are
    different failures (RecordNotFoundError vs. verified=False), and Phase 4's tests
    rely on that distinction. But TASK.md 6 defines record_id as
    keccak(image_sha256 + "|" + page_url), so mutating page_url -- the exact one-field
    edit TASK.md 10.8 prescribes for the tamper test -- changes the record's identity,
    not just its hash. The mutated evidence then points at a record id that was never
    anchored, and `get()` reverts NotFound rather than returning a mismatched hash.

    That is still tamper evidence -- arguably stronger, since the tampered file no
    longer even claims to be the record it was copied from -- so this wrapper folds
    both failure modes into the single VERIFIED/TAMPERED verdict TASK.md 10.8 asks for,
    while keeping the reason visible for anyone who wants the detail.
    """

    verified: bool
    reason: str  # "ok" | "hash_mismatch" | "record_not_found"
    record_id: str
    recomputed_hash: str
    on_chain_hash: str | None
    detail: VerificationResult | None

    def summary(self) -> str:
        if self.verified:
            return self.detail.summary()
        if self.reason == "hash_mismatch":
            return self.detail.summary()
        return "\n".join(
            [
                "TAMPERED ✗",
                f"  record id      : {self.record_id}",
                f"  recomputed hash: {self.recomputed_hash}",
                "  on-chain hash  : (no record found under this id)",
                "  the evidence's own record_id no longer matches any anchored record --",
                "  either it was never anchored, or match.page_url or query.image_sha256",
                "  (the fields record_id is derived from) were altered after anchoring.",
            ]
        )


def verify_report(
    network: str,
    evidence: dict,
    settings: Settings | None = None,
    *,
    w3: Web3 | None = None,
    deployment: Deployment | None = None,
) -> TamperReport:
    """The CLI's entry point: always returns a report, never raises for a tamper finding."""
    rid = record_id_for(evidence)
    recomputed = evidence_hash(evidence)
    try:
        result = verify(network, evidence, settings, w3=w3, deployment=deployment)
    except RecordNotFoundError:
        return TamperReport(
            verified=False,
            reason="record_not_found",
            record_id=rid,
            recomputed_hash=recomputed,
            on_chain_hash=None,
            detail=None,
        )
    return TamperReport(
        verified=result.verified,
        reason="ok" if result.verified else "hash_mismatch",
        record_id=rid,
        recomputed_hash=recomputed,
        on_chain_hash=result.on_chain_hash,
        detail=result,
    )
