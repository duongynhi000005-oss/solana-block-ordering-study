"""Controlled probe transaction builder for testing Solana leader scheduler ordering rules."""

import hashlib
import struct
import time
from dataclasses import dataclass
from typing import Dict, List


DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS = [
    1_000,       # P0: 0.001 lamports / CU
    10_000,      # P1: 0.010 lamports / CU
    50_000,      # P2: 0.050 lamports / CU
    100_000,     # P3: 0.100 lamports / CU
    250_000,     # P4: 0.250 lamports / CU
    500_000,     # P5: 0.500 lamports / CU
    1_000_000,   # P6: 1.000 lamports / CU
    2_500_000,   # P7: 2.500 lamports / CU
]


@dataclass
class ProbeTransactionSpec:
    probe_index: int
    send_order: int
    target_slot: int
    target_leader: str
    lock_mode: str  # "independent" or "contended_shared_pda"
    writable_account_tag: str
    cu_limit: int
    cu_price_micro_lamports: int
    expected_fee_lamports: int
    expected_priority_per_cost: float
    memo_payload: str
    wire_digest_hex: str


def build_probe_burst(
    target_slot: int,
    target_leader: str,
    cu_limit: int = 15_000,
    ladder: List[int] = DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS,
    reverse_send_order: bool = True,
    lock_mode: str = "contended_shared_pda",
) -> List[ProbeTransactionSpec]:
    """
    Construct a controlled burst of probe transactions for a specific validator's 4-slot window.

    Why reverse_send_order=True by default:
    If we dispatch probes in ascending priority order (lowest fee first, highest fee last) with a
    2ms stagger, any validator running a strict FIFO arrival scheduler will land them in order
    [P0, P1, ..., P7] (Kendall tau = -1.0 against fee/cost). Conversely, a priority-queue scheduler
    (Agave banking stage / Firedancer pack tile) that buffers or re-sorts contending transactions
    will invert the arrival order into [P7, P6, ..., P0] (Kendall tau = +1.0 against fee/cost).
    """
    ordered_ladder = list(ladder)
    if reverse_send_order:
        # Send lowest priority first (send_order=0 has lowest cu_price)
        send_sequence = list(enumerate(ordered_ladder))
    else:
        send_sequence = list(enumerate(reversed(ordered_ladder)))

    probes: List[ProbeTransactionSpec] = []
    for send_ord, (idx, micro_price) in enumerate(send_sequence):
        prio_fee = (cu_limit * micro_price + 999_999) // 1_000_000
        total_fee = 5_000 + prio_fee
        ppc = round(total_fee / max(1, cu_limit), 6)
        acct_tag = (
            f"SharedStateLockPDA_{target_slot}"
            if lock_mode == "contended_shared_pda"
            else f"IsolatedStatePDA_{target_slot}_{send_ord}"
        )
        memo = (
            f"PROBE|slot={target_slot}|leader={target_leader[:8]}|"
            f"send={send_ord}|cu_limit={cu_limit}|cu_price={micro_price}|mode={lock_mode}"
        )
        # Build deterministic ComputeBudget + Memo wire payload digest
        cb_limit_ix = struct.pack("<BI", 2, cu_limit)
        cb_price_ix = struct.pack("<BQ", 3, micro_price)
        wire_bytes = cb_limit_ix + cb_price_ix + memo.encode("utf-8")
        digest = hashlib.sha256(wire_bytes).hexdigest()

        probes.append(
            ProbeTransactionSpec(
                probe_index=idx,
                send_order=send_ord,
                target_slot=target_slot,
                target_leader=target_leader,
                lock_mode=lock_mode,
                writable_account_tag=acct_tag,
                cu_limit=cu_limit,
                cu_price_micro_lamports=micro_price,
                expected_fee_lamports=total_fee,
                expected_priority_per_cost=ppc,
                memo_payload=memo,
                wire_digest_hex=digest,
            )
        )
    return probes
