"""Command line interface -- TASK.md 8.

Commands are registered here from the start so each stage is independently runnable as
it lands. Unimplemented ones fail loudly with the phase that will deliver them, rather
than pretending to work.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

from . import __version__
from .errors import ConsentDenied, FaceChainError
from .status import Status

# Exit codes. 0 success, 1 generic failure, 2 usage/not-implemented, 3 consent refused.
EXIT_CONSENT_DENIED = 3

app = typer.Typer(
    add_completion=False,
    help="Consent-scoped face identification with on-chain evidence anchoring.",
)


def _todo(command: str, phase: str) -> None:
    typer.secho(f"'{command}' is not implemented yet (lands in {phase}).", fg="yellow", err=True)
    raise typer.Exit(code=2)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def version() -> None:
    """Print the pipeline version."""
    typer.echo(__version__)


@app.command()
def faces(
    image: Path = typer.Option(..., "--image", exists=True, help="Image to analyse."),
) -> None:
    """Detect and report faces in an image (stage 1, for inspection and tuning)."""
    from .face import MIN_DET_SCORE, detect_faces, select_primary

    found = detect_faces(image)
    if not found:
        typer.secho("no faces detected", fg="red", err=True)
        raise typer.Exit(code=1)

    chosen = select_primary(found)
    typer.echo(f"{len(found)} face(s) detected in {image.name}  [MIN_DET_SCORE={MIN_DET_SCORE}]")
    for i, f in enumerate(found, 1):
        mark = "<- primary" if f is chosen else ""
        typer.echo(f"  {i}. score={f.det_score:.3f}  bbox={f.bbox}  area={f.area:>7d} px^2 {mark}")
    typer.echo(f"model: {chosen.model}  embedding: {chosen.vector.shape[0]}-d, L2-normalized")


@app.command()
def compare(
    a: Path = typer.Option(..., "--a", exists=True, help="First image."),
    b: Path = typer.Option(..., "--b", exists=True, help="Second image."),
) -> None:
    """Cosine similarity between the primary faces of two images (stage 1)."""
    from .face import MATCH_THRESHOLD, primary_face, similarity

    score = similarity(primary_face(a), primary_face(b))
    verdict = "MATCH" if score >= MATCH_THRESHOLD else "NO MATCH"
    colour = "green" if score >= MATCH_THRESHOLD else "red"
    typer.echo(f"similarity: {score:+.4f}   threshold: {MATCH_THRESHOLD:.2f}")
    typer.secho(verdict, fg=colour, bold=True)


@app.command()
def enroll(
    subject: str = typer.Option(..., "--subject", help="Subject id (letters, digits, - and _)."),
    image: Path = typer.Option(..., "--image", exists=True, help="Enrolment photograph."),
    consent_statement: str = typer.Option(
        ..., "--consent-statement", help="The subject's own words agreeing to this use."
    ),
    display_name: str = typer.Option(None, "--display-name", help="Human-readable name."),
    scope: str = typer.Option(None, "--scope", help="What the subject consented to."),
    overwrite: bool = typer.Option(False, "--overwrite", help="Replace an existing enrolment."),
) -> None:
    """Record consent and enrol a subject."""
    from .consent import DEFAULT_SCOPE, enroll as do_enroll

    record = do_enroll(
        subject_id=subject,
        image=image,
        consent_statement=consent_statement,
        display_name=display_name,
        scope=scope or DEFAULT_SCOPE,
        overwrite=overwrite,
    )
    typer.secho(f"enrolled {record.subject_id} ({record.display_name})", fg="green", bold=True)
    typer.echo(f"  consented : {record.date}")
    typer.echo(f"  scope     : {record.scope}")
    typer.echo(f"  model     : {record.model}")
    typer.echo("  stored    : consent record + face encoding only (no photograph kept)")


@app.command()
def subjects() -> None:
    """List enrolled subjects."""
    from .consent import list_subjects

    found = list_subjects()
    if not found:
        typer.echo("no subjects enrolled")
        return
    for r in found:
        state = "active" if r.is_active else f"REVOKED {r.revoked_at}"
        typer.echo(f"{r.subject_id:<16} {r.display_name:<24} {r.date}  [{state}]")


@app.command()
def revoke(
    subject: str = typer.Option(..., "--subject", help="Subject id to revoke."),
) -> None:
    """Withdraw consent and delete the subject's enrolled face encoding."""
    from .consent import revoke as do_revoke

    record = do_revoke(subject)
    typer.secho(f"consent revoked for {record.subject_id} at {record.revoked_at}", fg="yellow")
    typer.echo("  enrolled face encoding deleted")


@app.command("check-consent")
def check_consent_cmd(
    subject: str = typer.Option(..., "--subject", help="Subject id."),
    image: Path = typer.Option(..., "--image", exists=True, help="Query image to authorise."),
) -> None:
    """Run the consent gate alone, without starting a pipeline run."""
    from .consent import check_consent

    result = check_consent(subject, image)
    typer.secho("CONSENT OK", fg="green", bold=True)
    typer.echo(f"  subject    : {result.record.subject_id} ({result.record.display_name})")
    typer.echo(f"  similarity : {result.similarity:+.4f}")
    typer.echo(f"  statement  : {result.record.statement}")


@app.command("evidence-hash")
def evidence_hash_cmd(
    evidence: Path = typer.Option(..., "--evidence", exists=True, help="evidence.json"),
) -> None:
    """Recompute the canonical hash and record id of an evidence file (stage 3)."""
    from .evidence import canonical_json, evidence_hash, has_match, load_evidence, record_id_for

    record = load_evidence(evidence)
    raw = canonical_json(record)
    typer.echo(f"canonical bytes : {len(raw)}")
    typer.echo(f"evidence_hash   : {evidence_hash(record)}")
    if has_match(record):
        typer.echo(f"record_id       : {record_id_for(record)}")
    else:
        typer.secho("record_id       : n/a (NO_MATCH record, nothing to anchor)", fg="yellow")


@app.command()
def scan() -> None:
    """Run the full pipeline: detect, search, re-verify, anchor."""
    _todo("scan", "Phase 8")


@app.command()
def deploy(
    network: str = typer.Option(..., "--network", help="amoy or local."),
) -> None:
    """Compile and deploy MatchRegistry to a network."""
    from .chain.deploy import deploy as do_deploy, write_deployment

    d = do_deploy(network)
    path = write_deployment(d)
    typer.secho(f"deployed to {network} (chain id {d.chain_id})", fg="green", bold=True)
    typer.echo(f"  address : {d.address}")
    typer.echo(f"  tx      : {d.tx_hash}")
    typer.echo(f"  block   : {d.block_number}")
    if d.explorer_url():
        typer.echo(f"  explorer: {d.explorer_url()}")
    typer.echo(f"  written : {path}")


@app.command()
def anchor(
    evidence: Path = typer.Option(..., "--evidence", exists=True, help="evidence.json"),
    network: str = typer.Option("local", "--network", help="amoy or local."),
    uri: str = typer.Option("", "--uri", help="optional off-chain pointer (e.g. an IPFS CID)."),
) -> None:
    """Anchor an evidence record on chain."""
    from .chain.anchor import anchor as do_anchor
    from .evidence import load_evidence

    result = do_anchor(network, load_evidence(evidence), uri=uri)
    typer.secho("ANCHORED", fg="green", bold=True)
    typer.echo(f"  record id : {result.record_id}")
    typer.echo(f"  tx hash   : {result.tx_hash}")
    typer.echo(f"  block     : {result.block_number}")
    typer.echo(f"  submitter : {result.submitter}")


@app.command()
def verify(
    evidence: Path = typer.Option(..., "--evidence", exists=True, help="evidence.json"),
    network: str = typer.Option("local", "--network", help="amoy or local."),
) -> None:
    """Verify an evidence record against its on-chain anchor."""
    from .chain.verify import verify as do_verify
    from .evidence import load_evidence

    result = do_verify(network, load_evidence(evidence))
    typer.secho(result.summary(), fg="green" if result.verified else "red", bold=True)
    if not result.verified:
        raise typer.Exit(code=1)


@app.command()
def report() -> None:
    """Print a human-readable summary of a run."""
    _todo("report", "Phase 8")


def run() -> None:
    """Console-script entry point.

    Domain errors are expected outcomes, not crashes: TASK.md 8 requires every command
    to exit non-zero with a readable message, so no traceback reaches the user.
    """
    try:
        app()
    except ConsentDenied as exc:
        typer.secho(f"{Status.CONSENT_DENIED.value}: {exc}", fg="red", bold=True, err=True)
        raise SystemExit(EXIT_CONSENT_DENIED) from None
    except FaceChainError as exc:
        typer.secho(f"{type(exc).__name__}: {exc}", fg="red", bold=True, err=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    run()
