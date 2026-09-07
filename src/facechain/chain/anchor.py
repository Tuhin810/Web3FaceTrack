"""Anchoring an evidence record on chain -- TASK.md 7.

Calls MatchRegistry.anchor(recordId, evidenceHash, uri). The contract reverts with a
custom error, AlreadyAnchored, on a duplicate -- TASK.md 10.9 requires that this is
handled gracefully rather than surfaced as a raw revert.

Custom-error *decoding* differs across providers: eth-tester, Anvil, and a real RPC
endpoint each shape a revert reason differently. Rather than parse that (fragile, and
untestable against providers not installed here), this does a pre-flight read via the
contract's own `verify()` view function, which returns a plain boolean and never
reverts. If a record already verifies against any hash, it exists, and the anchor call
is never attempted -- so no revert-parsing is needed at all, and the check behaves
identically on every provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from web3 import Web3

from ..config import Settings, get_settings
from ..errors import AlreadyAnchoredError, ChainError
from ..evidence import evidence_hash, record_id_for
from .deploy import Deployment, get_web3, load_deployment

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnchorResult:
    record_id: str
    evidence_hash: str
    tx_hash: str
    block_number: int
    submitter: str


def _contract(w3: Web3, deployment: Deployment):
    return w3.eth.contract(address=deployment.address, abi=deployment.abi)


def is_anchored(contract, record_id: str) -> bool:
    """True if a record exists under this id.

    `get()` reverts with NotFound when the id is unoccupied and returns a struct when
    it is anchored, so existence is success-vs-exception here -- not a value the ABI
    guarantees to compare a particular way. `verify(id, someHash)` looked tempting as a
    non-reverting probe, but it only returns true when the probe hash matches exactly,
    so it can never confirm existence without already knowing the stored hash; an
    earlier version of this function used verify() with an all-zero probe and it was
    simply wrong -- it returned False for both "unanchored" and "anchored", which let
    a second `anchor()` call reach the chain and revert instead of failing here.
    """
    try:
        contract.functions.get(record_id).call()
        return True
    except Exception:  # noqa: BLE001 -- provider-specific revert shapes for NotFound
        return False


def anchor(
    network: str,
    evidence: dict,
    uri: str = "",
    settings: Settings | None = None,
    *,
    w3: Web3 | None = None,
    private_key: str | None = None,
    deployment: Deployment | None = None,
) -> AnchorResult:
    """Anchor an evidence record. Raises AlreadyAnchoredError if this record id is anchored."""
    settings = settings or get_settings()
    rid = record_id_for(evidence)
    ehash = evidence_hash(evidence)

    w3 = w3 or get_web3(network, settings)
    deployment = deployment or load_deployment(network, settings)
    private_key = private_key or settings.require("private_key", f"anchor on {network}")
    account = w3.eth.account.from_key(private_key)

    contract = _contract(w3, deployment)

    if is_anchored(contract, rid):
        raise AlreadyAnchoredError(rid)

    try:
        tx = contract.functions.anchor(rid, ehash, uri).build_transaction(
            {
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address),
                "chainId": w3.eth.chain_id,
            }
        )
        signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    except Exception as exc:
        # A race: something else anchored this id between our pre-flight check and this
        # transaction. Re-check rather than assume -- the failure could be unrelated
        # (out of gas, RPC hiccup), and misreporting that would hide a real problem.
        if is_anchored(contract, rid):
            raise AlreadyAnchoredError(rid) from exc
        raise ChainError(f"anchor transaction failed: {exc}") from exc

    if receipt.status != 1:
        if is_anchored(contract, rid):
            raise AlreadyAnchoredError(rid)
        raise ChainError(f"anchor transaction {tx_hash.hex()} reverted")

    result = AnchorResult(
        record_id=rid,
        evidence_hash=ehash,
        tx_hash="0x" + tx_hash.hex().removeprefix("0x"),
        block_number=receipt.blockNumber,
        submitter=account.address,
    )
    log.debug("anchored %s at block %d (tx %s)", rid, result.block_number, result.tx_hash)
    return result
