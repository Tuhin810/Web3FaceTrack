"""Contract deployment -- TASK.md 7.

Writes `out/deployment.<network>.json` with everything a clean clone needs to run
`verify` against an already-deployed contract: address, ABI, chain id, deployer, tx
hash, block number. The ABI is committed; the private key never is.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

from ..config import Settings, get_settings
from ..errors import ChainError
from .compile import compile_contract, write_abi

log = logging.getLogger(__name__)

NETWORKS = {"local", "amoy"}
AMOY_CHAIN_ID = 80002
AMOY_EXPLORER = "https://amoy.polygonscan.com"


@dataclass(frozen=True)
class Deployment:
    network: str
    chain_id: int
    address: str
    abi: list[dict]
    deployer: str
    tx_hash: str
    block_number: int
    solc_version: str

    def explorer_url(self) -> str | None:
        if self.network == "amoy":
            return f"{AMOY_EXPLORER}/address/{self.address}"
        return None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rpc_url(network: str, settings: Settings) -> str:
    if network == "local":
        return settings.rpc_url_local
    if network == "amoy":
        return settings.rpc_url_amoy
    raise ChainError(f"unknown network {network!r}; expected one of {sorted(NETWORKS)}")


def get_web3(network: str, settings: Settings | None = None) -> Web3:
    settings = settings or get_settings()
    url = _rpc_url(network, settings)
    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 15}))
    # Amoy is a POA-derived chain; its extraData field overflows the standard 32 bytes
    # unless this middleware is installed, breaking block/receipt decoding.
    w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if not w3.is_connected():
        raise ChainError(
            f"cannot reach {network} RPC at {url}. "
            + (
                "Start a local node first (e.g. `anvil`)."
                if network == "local"
                else "Check RPC_URL_AMOY and your network connection."
            )
        )
    return w3


def deploy(
    network: str,
    settings: Settings | None = None,
    *,
    w3: Web3 | None = None,
    private_key: str | None = None,
) -> Deployment:
    """Deploy MatchRegistry.

    ``w3`` and ``private_key`` let tests deploy against an in-memory eth-tester chain
    through the exact same code path used for real networks -- so a passing test here
    is evidence the real-network path works too, not a separate reimplementation of it.
    """
    settings = settings or get_settings()
    if network not in NETWORKS and w3 is None:
        raise ChainError(f"unknown network {network!r}; expected one of {sorted(NETWORKS)}")

    w3 = w3 or get_web3(network, settings)
    private_key = private_key or settings.require("private_key", f"deploy to {network}")
    account = w3.eth.account.from_key(private_key)

    compiled = compile_contract()
    contract = w3.eth.contract(abi=compiled["abi"], bytecode=compiled["bytecode"])

    nonce = w3.eth.get_transaction_count(account.address)
    tx = contract.constructor().build_transaction(
        {"from": account.address, "nonce": nonce, "chainId": w3.eth.chain_id}
    )
    signed = w3.eth.account.sign_transaction(tx, private_key=private_key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt.status != 1:
        raise ChainError(f"deployment transaction {tx_hash.hex()} reverted")
    if not receipt.contractAddress:
        raise ChainError(f"deployment transaction {tx_hash.hex()} produced no contract address")

    deployment = Deployment(
        network=network,
        chain_id=w3.eth.chain_id,
        address=receipt.contractAddress,
        abi=compiled["abi"],
        deployer=account.address,
        tx_hash="0x" + tx_hash.hex().removeprefix("0x"),
        block_number=receipt.blockNumber,
        solc_version=compiled["solc_version"],
    )
    log.info("deployed %s to %s at %s (block %d)", compiled["contract_name"], network,
              deployment.address, deployment.block_number)
    return deployment


def deployment_path(network: str, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    return settings.out_dir / f"deployment.{network}.json"


def write_deployment(deployment: Deployment, settings: Settings | None = None) -> Path:
    settings = settings or get_settings()
    path = deployment_path(deployment.network, settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(deployment.to_dict(), indent=2) + "\n", encoding="utf-8")
    write_abi(
        {"abi": deployment.abi},
        settings.out_dir / f"MatchRegistry.abi.{deployment.network}.json",
    )
    return path


def load_deployment(network: str, settings: Settings | None = None) -> Deployment:
    settings = settings or get_settings()
    path = deployment_path(network, settings)
    if not path.is_file():
        raise ChainError(
            f"no deployment found for network {network!r} at {path}. "
            f"Run: facechain deploy --network {network}"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return Deployment(**data)
