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
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from eth_account import Account
from eth_tester import EthereumTester
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider


def make_handler(provider: EthereumTesterProvider):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # noqa: A003 -- quiet by default
            pass

        def do_POST(self) -> None:  # noqa: N802 -- BaseHTTPRequestHandler API
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            batch = isinstance(body, list)
            requests = body if batch else [body]

            responses = []
            for req in requests:
                try:
                    result = provider.make_request(req["method"], req.get("params", []))
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

    server = ThreadingHTTPServer((args.host, args.port), make_handler(provider))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
