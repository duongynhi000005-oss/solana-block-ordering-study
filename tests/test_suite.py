"""Unit and integration tests for Solana Mainnet Validator Scheduler Ordering Suite."""

import os
import pytest

from src.spend_guard import (
    SpendGuard,
    SpendCapExceededError,
    KeyIsolationError,
    DEFAULT_MAX_SPEND_LAMPORTS,
    load_isolated_keypair,
)
from src.probe_builder import build_probe_burst, DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS
from src.block_verifier import load_raw_dataset, compute_kendall_tau
from src.cli import run_cli


def test_spend_guard_enforces_0_05_sol_ceiling():
    guard = SpendGuard(max_spend_lamports=DEFAULT_MAX_SPEND_LAMPORTS)
    assert guard.max_spend_lamports == 50_000_000

    # Valid batch well within 0.05 SOL
    rec = guard.authorize_and_record(
        slot=461743496,
        validator_identity="AHZxzLeRGRfNVFrCmP58iJgEwbcXyZeAkZ32CmbfEmYR",
        cu_limit=15_000,
        cu_price_micro_lamports_ladder=DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS,
        dry_run=True,
    )
    assert rec.tx_count == 8
    assert guard.spent_lamports == rec.total_fee_lamports
    assert guard.spent_sol < 0.05

    # Huge priority ladder that breaches 0.05 SOL must raise SpendCapExceededError
    with pytest.raises(SpendCapExceededError):
        guard.authorize_and_record(
            slot=461743497,
            validator_identity="AHZxzLeRGRfNVFrCmP58iJgEwbcXyZeAkZ32CmbfEmYR",
            cu_limit=1_400_000,
            cu_price_micro_lamports_ladder=[50_000_000, 50_000_000],
            dry_run=True,
        )


def test_keypair_isolation_rejects_in_repo_keys():
    repo_file = os.path.abspath(__file__)
    with pytest.raises(KeyIsolationError):
        load_isolated_keypair(keypair_path=repo_file, env_var="NON_EXISTENT_ENV_KEY")


def test_probe_builder_reverse_send_order():
    probes = build_probe_burst(
        target_slot=461743496,
        target_leader="AHZxzLeRGRfNVFrCmP58iJgEwbcXyZeAkZ32CmbfEmYR",
        cu_limit=15_000,
        reverse_send_order=True,
        lock_mode="contended_shared_pda",
    )
    assert len(probes) == 8
    # Send order 0 has lowest priority fee; send order 7 has highest priority fee
    assert probes[0].send_order == 0
    assert probes[-1].send_order == 7
    assert probes[0].cu_price_micro_lamports < probes[-1].cu_price_micro_lamports
    assert probes[0].expected_priority_per_cost < probes[-1].expected_priority_per_cost


def test_raw_mainnet_dataset_completeness():
    data = load_raw_dataset()
    validators = data["validators"]
    # Minimum 6 validators spanning at least 3 distinct client versions required by spec
    assert len(validators) >= 6
    distinct_versions = {v["client_version"] for v in validators}
    assert len(distinct_versions) >= 3

    for v in validators:
        assert len(v["slot_measurements"]) >= 2
        for sm in v["slot_measurements"]:
            assert sm["slot"] > 460_000_000
            assert len(sm["blockhash"]) > 30
            assert len(sm["sample_transactions_top25"]) > 0
            sig0 = sm["sample_transactions_top25"][0]["signature"]
            assert len(sig0) >= 64


def test_cli_dry_run_default_and_live_guard():
    # Default dry-run succeeds with exit code 0
    assert run_cli(["--mode", "dry-run", "--verify-raw-data"]) == 0
    # Live mode without --live-send aborts with exit code 2
    assert run_cli(["--mode", "live"]) == 2
