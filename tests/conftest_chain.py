"""Shared eth-tester fixtures for chain tests.

An in-memory EVM (`eth-tester`/`py-evm`) stands in for Anvil here, since no local-chain
binary is installed on this machine. deploy()/anchor()/verify() accept an injected `w3`
and `private_key`, so this exercises the identical code path a real network would use --
not a parallel implementation of it.
"""

from __future__ import annotations

import pytest
from eth_account import Account
from eth_tester import EthereumTester
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider


@pytest.fixture
def eth_tester_w3():
    return Web3(EthereumTesterProvider(EthereumTester()))


@pytest.fixture
def funded_account(eth_tester_w3):
    """A fresh keypair, funded from eth-tester's pre-funded default account."""
    account = Account.create()
    pk = account.key.hex()
    if not pk.startswith("0x"):
        pk = "0x" + pk
    eth_tester_w3.eth.send_transaction(
        {
            "from": eth_tester_w3.eth.accounts[0],
            "to": account.address,
            "value": eth_tester_w3.to_wei(10, "ether"),
        }
    )
    return account.address, pk
