"""Block ordering verifier and statistical evaluator for Solana Mainnet measurements."""

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


def load_raw_dataset(path: Optional[str] = None) -> Dict[str, Any]:
    default_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "mainnet_measurements_post_alpenglow.json"
    )
    target = path or default_path
    with open(target, "r", encoding="utf-8") as f:
        return json.load(f)


def compute_kendall_tau(values: List[float]) -> float:
    """Compute Kendall rank correlation against descending priority rule (index 0 = highest)."""
    n = len(values)
    if n < 2:
        return 0.0
    concordant = 0
    discordant = 0
    for i in range(n):
        for j in range(i + 1, n):
            if values[i] > values[j]:
                concordant += 1
            elif values[i] < values[j]:
                discordant += 1
    total = concordant + discordant
    return round((concordant - discordant) / total, 4) if total > 0 else 0.0


def verify_slot_via_rpc(
    slot: int,
    expected_blockhash: str,
    expected_signatures: List[str],
    rpc_url: str = "https://api.mainnet-beta.solana.com",
) -> Tuple[bool, str]:
    """Verify a recorded Mainnet slot and its transaction signatures directly via Solana RPC getBlock."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBlock",
        "params": [
            slot,
            {
                "encoding": "json",
                "maxSupportedTransactionVersion": 1,
                "transactionDetails": "signatures",
                "rewards": False,
            },
        ],
    }
    req = urllib.request.Request(
        rpc_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        res = json.loads(resp.read().decode("utf-8"))

    blk = res.get("result")
    if not blk:
        return False, f"Slot {slot} not returned by RPC: {res.get('error')}"

    actual_bh = blk.get("blockhash")
    if actual_bh != expected_blockhash:
        return False, f"Blockhash mismatch on slot {slot}: expected {expected_blockhash}, got {actual_bh}"

    onchain_sigs = set(blk.get("signatures") or [])
    missing = [s for s in expected_signatures if s not in onchain_sigs]
    if missing:
        return False, f"Missing {len(missing)} signatures in slot {slot}"

    return True, f"Verified slot {slot} (blockhash={actual_bh[:12]}..., {len(onchain_sigs)} total txs)"
