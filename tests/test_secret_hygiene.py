"""Secret-hygiene regression tests -- TASK.md 2.1, 9.

These exist because `.gitignore` is a promise about the future, not a fact about the
past: once a key or a consent record is committed, ignoring the path does not undo it.
These assertions fail loudly if that ever changes.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=False
    ).stdout


def _tracked_files() -> list[str]:
    return [line for line in _git("ls-files").splitlines() if line]


# --- nothing sensitive is tracked ---------------------------------------------------


def test_no_sensitive_paths_are_tracked():
    """data/ holds consent records and face encodings; out/ holds run artifacts."""
    offenders = [f for f in _tracked_files() if re.match(r"^(data|out)/", f) or f == ".env"]
    assert offenders == [], f"sensitive paths are tracked: {offenders}"


def test_no_sensitive_paths_were_ever_committed():
    """`.gitignore` does not retroactively remove anything from history."""
    added = _git("log", "--all", "--pretty=format:", "--name-only", "--diff-filter=A")
    offenders = {
        line
        for line in added.splitlines()
        if line and (re.match(r"^(data|out)/", line) or line == ".env")
    }
    assert offenders == set(), f"sensitive paths exist in git history: {sorted(offenders)}"


def test_no_face_encodings_are_tracked():
    """A .npz here would be a stored biometric template (TASK.md 2.1)."""
    assert [f for f in _tracked_files() if f.endswith(".npz")] == []


def test_gitignore_covers_the_required_paths():
    """TASK.md 2.1 names these explicitly."""
    gitignore = (REPO_ROOT / ".gitignore").read_text()
    for required in ("data/consent/", "data/enrolled/", "out/", ".env"):
        assert required in gitignore, f".gitignore must cover {required}"


# --- no credentials in tracked content ----------------------------------------------

# Shapes, not values: hardcoding a real key to test for it would itself commit the key.
CREDENTIAL_PATTERNS = [
    (r"\bapi_key\s*[=:]\s*[\"'][A-Za-z0-9]{16,}[\"']", "inline api_key literal"),
    (r"\bSERPAPI_KEY\s*=\s*[A-Za-z0-9]{16,}", "SERPAPI_KEY with a value"),
    (r"\bIMGBB_KEY\s*=\s*[A-Za-z0-9]{16,}", "IMGBB_KEY with a value"),
    (r"\bPRIVATE_KEY\s*=\s*(0x)?[0-9a-fA-F]{64}", "PRIVATE_KEY with a value"),
    (r"\b0x[0-9a-fA-F]{64}\b", "bare 32-byte hex value (private key shape)"),
]

# A 0x-prefixed 32-byte hex value is the shape of BOTH a private key and an evidence
# hash / record id, and the latter are legitimately documented in DECISIONS.md and
# asserted in tests. Distinguishing them by regex alone is not possible, so the check
# looks at the surrounding line for words that only make sense for a public hash.
HASH_CONTEXT_WORDS = (
    "hash",
    "record_id",
    "record id",
    "keccak",
    "sha",
    "evidence",
    "anchor",
    # Transaction hashes and addresses appear in README transcripts. They are public
    # blockchain data by definition -- a tx hash is not a secret.
    "tx ",
    "tx:",
    "submitter",
    "explorer",
)


@pytest.mark.parametrize("pattern,label", CREDENTIAL_PATTERNS)
def test_no_credentials_in_tracked_files(pattern, label):
    compiled = re.compile(pattern)
    offenders = []
    for name in _tracked_files():
        path = REPO_ROOT / name
        if not path.is_file() or path.suffix in {".png", ".jpg", ".jpeg", ".onnx", ".npz"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            match = compiled.search(line)
            if not match:
                continue
            # Look at nearby lines too, not just this one: a documented hash is often
            # alone inside a fenced code block, with the explanation above it.
            context = " ".join(lines[max(0, i - 3) : i + 4]).lower()
            if name.startswith("tests/") and any(
                w in context for w in ("fake", "secret", "0" * 16, "a" * 16)
            ):
                continue
            if any(w in context for w in HASH_CONTEXT_WORDS):
                continue
            offenders.append(f"{name}:{i + 1}: {match.group(0)[:60]}")
    assert offenders == [], f"possible {label} in tracked files: {offenders}"


def test_env_example_has_no_filled_in_values():
    """.env.example is committed; it must be a template, never a populated config."""
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        line = line.split("#")[0].strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() in {"RPC_URL_AMOY", "RPC_URL_LOCAL", "MATCH_THRESHOLD", "MAX_CANDIDATES"}:
            continue  # non-secret defaults are fine
        assert value.strip() == "", f".env.example has a value for {key.strip()}"


# --- the committed search fixture ----------------------------------------------------


def test_committed_fixture_contains_no_api_key():
    """SerpAPI echoes request parameters back; confirm the key is not among them."""
    fixture = REPO_ROOT / "tests" / "fixtures" / "serpapi_google_lens_response.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    blob = json.dumps(data).lower()
    assert "api_key" not in blob
    assert "apikey" not in blob


def test_run_artifacts_do_not_contain_credentials(tmp_path, monkeypatch):
    """A run directory is what a user is most likely to share or attach to a bug report."""
    from facechain.config import Settings, set_settings
    from facechain.evidence import (
        MatchInfo,
        QueryInfo,
        SearchInfo,
        build_evidence,
        write_evidence,
    )

    settings = Settings(
        data_dir=tmp_path / "data",
        out_dir=tmp_path / "out",
        serpapi_key="SECRETSERPKEY1234567890",
        imgbb_key="SECRETIMGBBKEY1234567890",
        private_key="0x" + "ab" * 32,
    )
    set_settings(settings)
    try:
        evidence = build_evidence(
            run_id="r",
            subject_id="s",
            created_at="2026-01-01T00:00:00Z",
            query=QueryInfo("e" * 64, "0" * 16, "m", 0.9),
            search=SearchInfo("p", "https://i.ibb.co/x/q.png", 1, 1, 1, "f" * 64),
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
        write_evidence(tmp_path / "out" / "run", evidence)
        for artifact in (tmp_path / "out" / "run").glob("*.json"):
            content = artifact.read_text(encoding="utf-8")
            assert "SECRETSERPKEY" not in content, f"{artifact.name} leaks the SerpAPI key"
            assert "SECRETIMGBBKEY" not in content, f"{artifact.name} leaks the imgbb key"
            assert "ab" * 32 not in content, f"{artifact.name} leaks the private key"
    finally:
        set_settings(Settings())
