// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract MatchRegistry {
    struct Record {
        bytes32 evidenceHash;
        address submitter;
        uint64  timestamp;
        string  uri;          // optional off-chain pointer (IPFS CID), may be ""
    }

    mapping(bytes32 => Record) private _records;
    bytes32[] public recordIds;

    event MatchAnchored(
        bytes32 indexed recordId,
        bytes32 indexed evidenceHash,
        address indexed submitter,
        uint64  timestamp,
        string  uri
    );

    error AlreadyAnchored(bytes32 recordId);
    error NotFound(bytes32 recordId);

    function anchor(bytes32 recordId, bytes32 evidenceHash, string calldata uri) external {
        if (_records[recordId].timestamp != 0) revert AlreadyAnchored(recordId);
        _records[recordId] = Record(evidenceHash, msg.sender, uint64(block.timestamp), uri);
        recordIds.push(recordId);
        emit MatchAnchored(recordId, evidenceHash, msg.sender, uint64(block.timestamp), uri);
    }

    function get(bytes32 recordId) external view returns (Record memory r) {
        r = _records[recordId];
        if (r.timestamp == 0) revert NotFound(recordId);
    }

    function verify(bytes32 recordId, bytes32 evidenceHash) external view returns (bool) {
        Record storage r = _records[recordId];
        return r.timestamp != 0 && r.evidenceHash == evidenceHash;
    }

    function count() external view returns (uint256) {
        return recordIds.length;
    }
}
