"""Strict fee spend ceiling and keypair isolation guardrails for Solana Mainnet."""

import os
import json
from dataclasses import dataclass, field
from typing import List, Optional


class SpendCapExceededError(RuntimeError):
    """Raised when a projected transaction batch would exceed the 0.05 SOL spend cap."""


class KeyIsolationError(RuntimeError):
    """Raised when live sending is requested without an externally mounted keypair."""


DEFAULT_MAX_SPEND_LAMPORTS = 50_000_000  # 0.05 SOL hard ceiling


@dataclass
class SpendLedgerRecord:
    slot: int
    validator_identity: str
    tx_count: int
    base_fee_lamports: int
    priority_fee_lamports: int
    total_fee_lamports: int
    dry_run: bool


@dataclass
class SpendGuard:
    max_spend_lamports: int = DEFAULT_MAX_SPEND_LAMPORTS
    spent_lamports: int = 0
    history: List[SpendLedgerRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.max_spend_lamports <= 0 or self.max_spend_lamports > DEFAULT_MAX_SPEND_LAMPORTS:
            raise ValueError(
                f"max_spend_lamports ({self.max_spend_lamports}) must be in (0, {DEFAULT_MAX_SPEND_LAMPORTS}] "
                "(0.05 SOL ceiling required by experiment specification)."
            )

    @property
    def remaining_lamports(self) -> int:
        return max(0, self.max_spend_lamports - self.spent_lamports)

    @property
    def spent_sol(self) -> float:
        return self.spent_lamports / 1_000_000_000.0

    def estimate_probe_batch_cost(
        self,
        cu_limit: int,
        cu_price_micro_lamports_ladder: List[int],
        signatures_per_tx: int = 1,
    ) -> int:
        """Compute exact lamport cost (base fee + ComputeBudget priority fee) for a probe burst."""
        total = 0
        for micro_price in cu_price_micro_lamports_ladder:
            base_fee = signatures_per_tx * 5_000
            prio_fee = (cu_limit * micro_price + 999_999) // 1_000_000
            total += base_fee + prio_fee
        return total

    def authorize_and_record(
        self,
        slot: int,
        validator_identity: str,
        cu_limit: int,
        cu_price_micro_lamports_ladder: List[int],
        dry_run: bool = True,
    ) -> SpendLedgerRecord:
        batch_cost = self.estimate_probe_batch_cost(cu_limit, cu_price_micro_lamports_ladder)
        base_cost = len(cu_price_micro_lamports_ladder) * 5_000
        prio_cost = batch_cost - base_cost

        if self.spent_lamports + batch_cost > self.max_spend_lamports:
            raise SpendCapExceededError(
                f"ABORT: Batch of {len(cu_price_micro_lamports_ladder)} txs costs {batch_cost} lamports, "
                f"which would push cumulative spend to {self.spent_lamports + batch_cost} lamports "
                f"(exceeding hard cap of {self.max_spend_lamports} lamports / 0.05 SOL)."
            )

        self.spent_lamports += batch_cost
        rec = SpendLedgerRecord(
            slot=slot,
            validator_identity=validator_identity,
            tx_count=len(cu_price_micro_lamports_ladder),
            base_fee_lamports=base_cost,
            priority_fee_lamports=prio_cost,
            total_fee_lamports=batch_cost,
            dry_run=dry_run,
        )
        self.history.append(rec)
        return rec


def load_isolated_keypair(keypair_path: Optional[str] = None, env_var: str = "SOLANA_PRIVATE_KEY_B58") -> bytes:
    """Load keypair strictly from volume mount or environment variable. Never from repo tree."""
    env_val = os.environ.get(env_var, "").strip()
    if env_val:
        return env_val.encode("utf-8")

    path = keypair_path or os.environ.get("KEYPAIR_PATH", "/keys/id.json")
    abs_repo = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    abs_key = os.path.abspath(path)

    if abs_key.startswith(abs_repo) and not abs_key.startswith(os.path.join(abs_repo, "keys_mount")):
        raise KeyIsolationError(
            f"SECURITY VIOLATION: Refusing to load keypair from inside repository tree ({abs_key}). "
            "Mount keys via Docker volume (-v /host/keys:/keys:ro) or set SOLANA_PRIVATE_KEY_B58."
        )

    if not os.path.exists(abs_key):
        raise KeyIsolationError(
            f"Live sending requires an external keypair at {abs_key} or {env_var} env var."
        )

    with open(abs_key, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) not in (32, 64):
        raise KeyIsolationError("Invalid Solana keypair JSON format (expected 64-byte array).")
    return bytes(data)
