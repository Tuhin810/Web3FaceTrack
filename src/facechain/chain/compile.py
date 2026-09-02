"""Contract compilation -- TASK.md 7.

Pinned to solc 0.8.24, the version named in the spec. py-solc-x downloads and manages
solc binaries itself (not through the system package manager), so this has no external
tool dependency beyond what pip already installed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import solcx

from ..errors import ChainError

SOLC_VERSION = "0.8.24"
CONTRACT_NAME = "MatchRegistry"
REPO_ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = REPO_ROOT / "contracts" / f"{CONTRACT_NAME}.sol"


def ensure_solc_installed(version: str = SOLC_VERSION) -> None:
    installed = {str(v) for v in solcx.get_installed_solc_versions()}
    if version not in installed:
        solcx.install_solc(version)


def compile_contract(
    contract_path: Path = CONTRACT_PATH, version: str = SOLC_VERSION
) -> dict[str, Any]:
    """Compile MatchRegistry.sol and return its ABI and deployable bytecode.

    Returns ``{"abi": [...], "bytecode": "0x...", "solc_version": "0.8.24"}``.
    """
    if not contract_path.is_file():
        raise ChainError(f"contract source not found: {contract_path}")

    ensure_solc_installed(version)

    try:
        compiled = solcx.compile_files(
            [str(contract_path)],
            output_values=["abi", "bin"],
            solc_version=version,
        )
    except solcx.exceptions.SolcError as exc:
        raise ChainError(f"solc {version} failed to compile {contract_path.name}: {exc}") from exc

    # solcx keys the output by "<path-as-passed>:<ContractName>", and the path is not
    # normalised to what we passed in, so match on the contract name suffix instead of
    # reconstructing the exact key.
    matches = [v for k, v in compiled.items() if k.rsplit(":", 1)[-1] == CONTRACT_NAME]
    if not matches:
        raise ChainError(
            f"compiled output has no contract named {CONTRACT_NAME!r}; "
            f"found: {sorted(k.rsplit(':', 1)[-1] for k in compiled)}"
        )

    entry = matches[0]
    return {
        "abi": entry["abi"],
        "bytecode": "0x" + entry["bin"],
        "solc_version": version,
        "contract_name": CONTRACT_NAME,
    }


def write_abi(compiled: dict[str, Any], out_path: Path) -> Path:
    """Persist the ABI alone -- this is what's committed, never the private key."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(compiled["abi"], indent=2) + "\n", encoding="utf-8")
    return out_path
