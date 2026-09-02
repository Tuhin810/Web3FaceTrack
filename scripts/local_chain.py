"""A minimal local JSON-RPC chain for development and CI, standing in for Anvil/Ganache.

No local-chain binary (Anvil, Ganache) is installed on this development machine and
none is guaranteed to be on a CI runner either. `eth-tester`'s `EthereumTesterProvider`
already implements the full standard JSON-RPC method dispatch used by web3.py (that is
literally what it exists for -- see its `make_request`), so this script just puts an
HTTP JSON-RPC front end on it. Anything speaking to `http://127.0.0.1:8545` -- the CLI
included -- cannot tell the difference from a real node.

This is not a substitute for testing against Anvil before Phase 9's live demo: gas
estimation, block timing and EVM version behaviour can differ subtly between py-evm and
Anvil's Rust EVM. It exists so the full `facechain deploy/anchor/verify` CLI path (not
just the injected-provider unit tests) can be exercised for real without that tool.

Usage:
    .venv/bin/python scripts/local_chain.py [--port 8545] [--fund 0xPRIVATE_KEY ...]

Prints the funded account addresses and exits 0 when SIGINT/SIGTERM is received.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eth_tester import EthereumTester
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

# JSON-RPC encodes every integer as a hex string ("0x1c"), but
# EthereumTesterProvider.make_request expects Python-native types: it is designed to sit
# *inside* a Web3 instance whose middleware performs that conversion, not to be fed raw
# wire-format parameters. Serving it over HTTP puts us on the wire side of that boundary,
# so the conversion has to happen here instead.
_QUANTITY_FIELDS = frozenset(
    {
        "value", "nonce", "gas", "gasLimit", "gasPrice", "chainId", "type",
        "maxFeePerGas", "maxPriorityFeePerGas", "maxFeePerBlobGas",
        # eth_getLogs filter bounds, after camelCase -> snake_case conversion. Block
        # *tags* ("latest", "earliest") are left alone: _to_native only converts
        # 0x-prefixed strings.
        "from_block", "to_block",
    }
)
_BLOCK_TAGS = frozenset({"latest", "earliest", "pending", "safe", "finalized"})


def _to_native(value):
    if isinstance(value, str) and value.startswith("0x") and len(value) <= 34:
        # Short 0x values are quantities (amounts, counts). Longer ones are data or
        # addresses -- 20-byte addresses and 32-byte hashes must stay as strings.
        try:
            return int(value, 16)
        except ValueError:
            return value
    return value


def normalize_params(method: str, params, default_sender: str | None = None):
    """Convert JSON-RPC wire format into what eth-tester's provider expects.

    Also supplies a default `from` on calls that omit it: eth-tester rejects an
    `eth_call` without a sender ("Transaction is missing the required keys: 'from'"),
    whereas real nodes happily execute a view call with no sender. `facechain verify`
    makes exactly such a call, so without this the shim would diverge from the node it
    is standing in for.
    """
    if not isinstance(params, list):
        return params

    if method in ("eth_call", "eth_estimateGas") and default_sender:
        params = [
            {**item, "from": item.get("from", default_sender)}
            if isinstance(item, dict)
            else item
            for item in params
        ]

    # eth_getLogs takes a filter object whose keys are camelCase on the wire
    # (fromBlock/toBlock/blockHash) but snake_case in eth-tester's API. Without this,
    # `facechain verify` cannot find the MatchAnchored event and reports the anchoring
    # block as "unknown".
    if method in ("eth_getLogs", "eth_newFilter"):
        params = [_snake_keys(item) if isinstance(item, dict) else item for item in params]

    out = []
    for item in params:
        if isinstance(item, dict):
            out.append(
                {
                    k: (_to_native(v) if k in _QUANTITY_FIELDS else v)
                    for k, v in item.items()
                }
            )
        elif isinstance(item, str) and item.startswith("0x") and len(item) <= 18:
            # A bare block number, e.g. eth_getBlockByNumber("0x1", False).
            out.append(_to_native(item) if item not in _BLOCK_TAGS else item)
        else:
            out.append(item)
    return out


def _snake(name: str) -> str:
    return "".join("_" + c.lower() if c.isupper() else c for c in name)


def _snake_keys(obj: dict) -> dict:
    return {_snake(k): v for k, v in obj.items()}


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(word.title() for word in rest)


def to_wire(value):
    """Convert eth-tester's internal representation into JSON-RPC wire format.

    The reverse of `normalize_params`, and needed for the same reason: eth-tester
    returns snake_case keys and native ints (`{"base_fee_per_gas": 875000000}`), while
    JSON-RPC -- and therefore every web3 client -- expects camelCase keys and
    hex-encoded quantities (`{"baseFeePerGas": "0x34630b8a"}`). Without this, web3
    raises `KeyError: 'baseFeePerGas'` on the first block it reads.
    """
    if isinstance(value, bool):
        return value  # bool is an int subclass; must be checked first
    if isinstance(value, int):
        return hex(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, dict):
        return {_camel(k): to_wire(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_wire(v) for v in value]
    return value


def make_handler(provider: EthereumTesterProvider, default_sender: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            batch = isinstance(body, list)
            requests = body if batch else [body]

            responses = []
            for req in requests:
                try:
                    raw = provider.make_request(
                        req["method"],
                        normalize_params(req["method"], req.get("params", []), default_sender),
                    )
                    result = dict(raw)
                    if "result" in result:
                        result["result"] = to_wire(result["result"])
                except Exception as exc:  # noqa: BLE001 -- surface as a JSON-RPC error
                    result = {
                        "id": req.get("id", 0),
                        "jsonrpc": "2.0",
                        "error": {"code": -32000, "message": str(exc)},
                    }
                result.setdefault("id", req.get("id", 0))
                responses.append(result)

            payload = json.dumps(responses if batch else responses[0]).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    return Handler


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8545)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--fund", metavar="0xPRIVATE_KEY", action="append", default=[],
        help="import and fund this key with 1000 ETH (repeatable)",
    )
    args = ap.parse_args()

    tester = EthereumTester()
    provider = EthereumTesterProvider(tester)
    w3 = Web3(provider)

    funder = w3.eth.accounts[0]
    for pk in args.fund:
        pk = pk if pk.startswith("0x") else "0x" + pk
        addr = tester.add_account(pk)
        w3.eth.send_transaction(
            {"from": funder, "to": addr, "value": w3.to_wei(1000, "ether")}
        )
        print(f"funded {addr}  (1000 ETH)")

    print(f"chain id: {w3.eth.chain_id}")
    print(f"listening on http://{args.host}:{args.port}  (Ctrl+C to stop)")
    sys.stdout.flush()

    server = ThreadingHTTPServer(
        (args.host, args.port), make_handler(provider, default_sender=funder)
    )
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
