"""Chain tests -- TASK.md 7, acceptance AC4, AC7, AC9.

Runs against an in-memory eth-tester chain (see conftest_chain.py) rather than Anvil,
since no local-chain binary is installed here. Same deploy/anchor/verify code path a
real network uses.
"""

from __future__ import annotations

import pytest
from conftest_chain import eth_tester_w3, funded_account

from facechain.chain.anchor import anchor, is_anchored
from facechain.chain.compile import compile_contract
from facechain.chain.deploy import deploy
from facechain.chain.verify import verify, verify_or_raise
from facechain.errors import AlreadyAnchoredError, RecordNotFoundError, TamperedError
from facechain.evidence import (
    MatchInfo,
    QueryInfo,
    SearchInfo,
    build_evidence,
    evidence_hash,
    record_id_for,
)


def make_evidence(page_url="https://github.com/Tuhin810", similarity=0.61):
    return build_evidence(
        run_id="2026-09-02T11-04-33Z-8f3a1c",
        subject_id="tuhin",
        created_at="2026-09-02T11:04:33Z",
        query=QueryInfo("e" * 64, "c6f6718c0073e0fd", "insightface/buffalo_l", 0.94),
        search=SearchInfo("serpapi:google_lens", "https://i.ibb.co/x/q.png", 42, 15, 1, "f" * 64),
        match=MatchInfo(
            page_url,
            "Tuhin810 - Overview",
            "a" * 64,
            "https://avatars.githubusercontent.com/u/111550237?v=4",
            "b" * 64,
            similarity,
            0.45,
            "2026-09-02T11:04:29Z",
        ),
    )


# --- compile ------------------------------------------------------------------------


def test_compile_produces_the_documented_interface():
    c = compile_contract()
    names = {e["name"] for e in c["abi"] if e.get("type") in ("function", "error", "event")}
    assert names == {
        "anchor",
        "get",
        "verify",
        "count",
        "recordIds",
        "AlreadyAnchored",
        "NotFound",
        "MatchAnchored",
    }
    assert c["solc_version"] == "0.8.24"
    assert c["bytecode"].startswith("0x")


# --- deploy ---------------------------------------------------------------------------


def test_deploy_produces_a_live_contract(eth_tester_w3, funded_account):
    """AC4-equivalent: deploy against a local chain and confirm the contract exists."""
    addr, pk = funded_account
    d = deploy("local", w3=eth_tester_w3, private_key=pk)
    assert eth_tester_w3.eth.get_code(d.address) != b""
    assert d.deployer.lower() == addr.lower()
    assert d.block_number > 0
    assert d.abi and d.chain_id == eth_tester_w3.eth.chain_id


def test_fresh_contract_has_zero_records(eth_tester_w3, funded_account):
    _, pk = funded_account
    d = deploy("local", w3=eth_tester_w3, private_key=pk)
    contract = eth_tester_w3.eth.contract(address=d.address, abi=d.abi)
    assert contract.functions.count().call() == 0


# --- anchor + verify happy path ------------------------------------------------------


@pytest.fixture
def deployed(eth_tester_w3, funded_account):
    _, pk = funded_account
    return deploy("local", w3=eth_tester_w3, private_key=pk), pk


def test_anchor_then_verify_succeeds(eth_tester_w3, deployed):
    """AC7: verify on freshly anchored evidence prints VERIFIED (verified=True here)."""
    d, pk = deployed
    ev = make_evidence()

    result = anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    assert result.record_id == record_id_for(ev)
    assert result.evidence_hash == evidence_hash(ev)
    assert result.tx_hash.startswith("0x")

    v = verify("local", ev, w3=eth_tester_w3, deployment=d)
    assert v.verified
    assert v.record_id == result.record_id
    assert v.on_chain_hash.lower() == evidence_hash(ev).lower()
    assert v.submitter.lower() == result.submitter.lower()
    assert v.block_number == result.block_number
    assert "VERIFIED" in v.summary()


def test_verify_or_raise_passes_through_on_success(eth_tester_w3, deployed):
    d, pk = deployed
    ev = make_evidence()
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    result = verify_or_raise("local", ev, w3=eth_tester_w3, deployment=d)
    assert result.verified


def test_verify_reports_the_correct_submitter(eth_tester_w3, deployed):
    d, pk = deployed
    ev = make_evidence()
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    from eth_account import Account

    submitter = Account.from_key(pk).address
    v = verify("local", ev, w3=eth_tester_w3, deployment=d)
    assert v.submitter.lower() == submitter.lower()


def test_verify_before_anchoring_raises_not_found(eth_tester_w3, deployed):
    d, _ = deployed
    with pytest.raises(RecordNotFoundError):
        verify("local", make_evidence(), w3=eth_tester_w3, deployment=d)


# --- tamper evidence ------------------------------------------------------------------


def test_verify_detects_a_changed_page_url(eth_tester_w3, deployed):
    """Foundation for the Phase 5 tamper_test.sh script."""
    d, pk = deployed
    original = make_evidence(page_url="https://github.com/Tuhin810")
    anchor("local", original, w3=eth_tester_w3, private_key=pk, deployment=d)

    tampered = make_evidence(page_url="https://github.com/Tuhin811")  # one character
    # A changed page_url moves the record id too, so this must raise NotFound: the
    # tampered record was never anchored under its own (new) id. This is itself a
    # tamper-evidence property, distinct from "same id, different hash".
    with pytest.raises(RecordNotFoundError):
        verify("local", tampered, w3=eth_tester_w3, deployment=d)


def test_verify_detects_a_changed_similarity_same_id(eth_tester_w3, deployed):
    """Changing a field that is NOT part of record_id: same id, different hash."""
    d, pk = deployed
    original = make_evidence(similarity=0.61)
    anchor("local", original, w3=eth_tester_w3, private_key=pk, deployment=d)

    tampered = make_evidence(similarity=0.99)
    assert record_id_for(tampered) == record_id_for(original)  # same id...
    assert evidence_hash(tampered) != evidence_hash(original)  # ...different hash

    v = verify("local", tampered, w3=eth_tester_w3, deployment=d)
    assert not v.verified
    assert "TAMPERED" in v.summary()
    assert v.recomputed_hash != v.on_chain_hash

    with pytest.raises(TamperedError):
        verify_or_raise("local", tampered, w3=eth_tester_w3, deployment=d)


# --- AlreadyAnchored, handled gracefully (AC9) -----------------------------------------


def test_anchor_twice_raises_already_anchored_not_a_raw_revert(eth_tester_w3, deployed):
    """AC9: re-anchoring must be handled gracefully, not surfaced as an opaque RPC error."""
    d, pk = deployed
    ev = make_evidence()
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)

    with pytest.raises(AlreadyAnchoredError) as exc:
        anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    assert exc.value.record_id == record_id_for(ev)
    assert "already anchored" in str(exc.value)


def test_is_anchored_reflects_contract_state(eth_tester_w3, deployed):
    d, pk = deployed
    contract = eth_tester_w3.eth.contract(address=d.address, abi=d.abi)
    ev = make_evidence()
    rid = record_id_for(ev)
    assert not is_anchored(contract, rid)
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    assert is_anchored(contract, rid)


def test_second_anchor_does_not_change_count(eth_tester_w3, deployed):
    d, pk = deployed
    contract = eth_tester_w3.eth.contract(address=d.address, abi=d.abi)
    ev = make_evidence()
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    assert contract.functions.count().call() == 1
    with pytest.raises(AlreadyAnchoredError):
        anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)
    assert contract.functions.count().call() == 1  # unchanged -- no partial write


def test_different_records_can_both_be_anchored(eth_tester_w3, deployed):
    d, pk = deployed
    contract = eth_tester_w3.eth.contract(address=d.address, abi=d.abi)
    for slug in ("a", "b"):
        anchor(
            "local",
            make_evidence(page_url=f"https://github.com/{slug}"),
            w3=eth_tester_w3,
            private_key=pk,
            deployment=d,
        )
    assert contract.functions.count().call() == 2


# --- deployment persistence -----------------------------------------------------------


def test_write_and_load_deployment_roundtrip(tmp_path, eth_tester_w3, funded_account):
    from facechain.chain.deploy import load_deployment, write_deployment
    from facechain.config import Settings

    _, pk = funded_account
    settings = Settings(data_dir=tmp_path / "data", out_dir=tmp_path / "out")
    d = deploy("local", settings=settings, w3=eth_tester_w3, private_key=pk)
    write_deployment(d, settings=settings)

    loaded = load_deployment("local", settings=settings)
    assert loaded.address == d.address
    assert loaded.abi == d.abi
    assert loaded.tx_hash == d.tx_hash


def test_deployment_file_never_contains_a_private_key(tmp_path, eth_tester_w3, funded_account):
    import json

    from facechain.chain.deploy import deployment_path, write_deployment
    from facechain.config import Settings

    _, pk = funded_account
    settings = Settings(data_dir=tmp_path / "data", out_dir=tmp_path / "out")
    d = deploy("local", settings=settings, w3=eth_tester_w3, private_key=pk)
    write_deployment(d, settings=settings)

    raw = deployment_path("local", settings).read_text()
    assert pk.lower() not in raw.lower()
    assert pk[2:].lower() not in raw.lower()
    json.loads(raw)  # must still be valid JSON


# --- verify_report / TamperReport -- CLI-facing VERIFIED/TAMPERED verdict, AC8 --------


def test_report_verified_on_untouched_evidence(eth_tester_w3, deployed):
    from facechain.chain.verify import verify_report

    d, pk = deployed
    ev = make_evidence()
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)

    report = verify_report("local", ev, w3=eth_tester_w3, deployment=d)
    assert report.verified
    assert report.reason == "ok"
    assert "VERIFIED" in report.summary()


def test_report_tampered_on_changed_similarity(eth_tester_w3, deployed):
    """Same record id, different hash -- the 'ordinary' tamper case."""
    from facechain.chain.verify import verify_report

    d, pk = deployed
    original = make_evidence(similarity=0.61)
    anchor("local", original, w3=eth_tester_w3, private_key=pk, deployment=d)

    tampered = make_evidence(similarity=0.99)
    report = verify_report("local", tampered, w3=eth_tester_w3, deployment=d)
    assert not report.verified
    assert report.reason == "hash_mismatch"
    assert report.on_chain_hash is not None
    assert report.recomputed_hash != report.on_chain_hash
    assert "TAMPERED" in report.summary()
    assert report.recomputed_hash in report.summary()
    assert report.on_chain_hash in report.summary()


def test_report_tampered_on_changed_page_url(eth_tester_w3, deployed):
    """AC8's literal case: one character of match.page_url changes record_id itself.

    This is the tension documented in DECISIONS.md D25: the mutated evidence points at
    a record id that was never anchored, so the low-level verify() raises
    RecordNotFoundError -- but verify_report() must still report TAMPERED here, because
    that is what TASK.md 10.8 requires the tamper test to demonstrate.
    """
    from facechain.chain.verify import verify_report

    d, pk = deployed
    original = make_evidence(page_url="https://github.com/Tuhin810")
    anchor("local", original, w3=eth_tester_w3, private_key=pk, deployment=d)

    tampered = make_evidence(page_url="https://github.com/Tuhin811")  # one character
    report = verify_report("local", tampered, w3=eth_tester_w3, deployment=d)
    assert not report.verified
    assert report.reason == "record_not_found"
    assert report.on_chain_hash is None
    assert "TAMPERED" in report.summary()
    assert report.record_id != record_id_for(original)


def test_report_on_evidence_never_anchored_is_also_tampered(eth_tester_w3, deployed):
    """Cannot be distinguished from a shifted-identity tamper at the chain level --
    documented as an accepted limitation, not silently glossed over."""
    from facechain.chain.verify import verify_report

    d, _ = deployed
    report = verify_report("local", make_evidence(), w3=eth_tester_w3, deployment=d)
    assert not report.verified
    assert report.reason == "record_not_found"


def test_report_survives_key_order_and_whitespace_changes(eth_tester_w3, deployed):
    """The second tamper_test.sh case: reformatting must NOT read as tampering."""
    import json

    from facechain.chain.verify import verify_report
    from facechain.evidence import canonical_json

    d, pk = deployed
    ev = make_evidence()
    anchor("local", ev, w3=eth_tester_w3, private_key=pk, deployment=d)

    reformatted = json.loads(
        json.dumps(dict(reversed(list(ev.items()))), indent=4, sort_keys=False)
    )
    assert canonical_json(reformatted) == canonical_json(ev)  # sanity: same content

    report = verify_report("local", reformatted, w3=eth_tester_w3, deployment=d)
    assert report.verified
    assert report.reason == "ok"
