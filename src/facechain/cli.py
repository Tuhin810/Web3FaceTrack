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
def enroll() -> None:
    """Record consent and enrol a subject."""
    _todo("enroll", "Phase 2")


@app.command()
def scan() -> None:
    """Run the full pipeline: detect, search, re-verify, anchor."""
    _todo("scan", "Phase 8")


@app.command()
def deploy() -> None:
    """Deploy MatchRegistry to a network."""
    _todo("deploy", "Phase 4")


@app.command()
def anchor() -> None:
    """Anchor an evidence record on chain."""
    _todo("anchor", "Phase 4")


@app.command()
def verify() -> None:
    """Verify an evidence record against its on-chain anchor."""
    _todo("verify", "Phase 4")


@app.command()
def report() -> None:
    """Print a human-readable summary of a run."""
    _todo("report", "Phase 8")


if __name__ == "__main__":
    app()
