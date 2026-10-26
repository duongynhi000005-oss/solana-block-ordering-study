"""CLI entrypoint for Inside the Block: Solana Validator Scheduler Ordering Suite."""

import argparse
import os
import sys
from typing import List

from src.spend_guard import SpendGuard, DEFAULT_MAX_SPEND_LAMPORTS, load_isolated_keypair
from src.probe_builder import build_probe_burst, DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS
from src.block_verifier import load_raw_dataset, verify_slot_via_rpc


def run_cli(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inside the Block: Solana Mainnet Validator Scheduler Measurement & Verification Suite"
    )
    parser.add_argument(
        "--mode",
        choices=["dry-run", "live"],
        default=os.environ.get("MODE", "dry-run"),
        help="Execution mode: 'dry-run' (default, builds probes & simulates spend without broadcasting) or 'live'.",
    )
    parser.add_argument(
        "--live-send",
        action="store_true",
        help="Explicit safety flag required alongside --mode live to broadcast real transactions on Mainnet.",
    )
    parser.add_argument(
        "--max-spend-lamports",
        type=int,
        default=int(os.environ.get("MAX_SPEND_LAMPORTS", DEFAULT_MAX_SPEND_LAMPORTS)),
        help="Strict fee spend ceiling in lamports (default: 50,000,000 = 0.05 SOL).",
    )
    parser.add_argument(
        "--verify-raw-data",
        action="store_true",
        help="Verify recorded Mainnet dataset and print empirical scheduler ordering metrics.",
    )
    parser.add_argument(
        "--live-rpc-check",
        action="store_true",
        help="Cross-check recorded blockhashes & signatures against live Solana Mainnet getBlock RPC.",
    )
    args = parser.parse_args(argv)

    is_live = args.mode == "live"
    if is_live and not args.live_send:
        print(
            "[SAFETY ABORT] --mode=live requires the explicit --live-send flag to prevent accidental SOL spend.",
            file=sys.stderr,
        )
        return 2

    guard = SpendGuard(max_spend_lamports=args.max_spend_lamports)
    dataset = load_raw_dataset()
    validators = dataset.get("validators", [])

    print("=" * 88)
    print(f"SOLANA MAINNET VALIDATOR SCHEDULER STUDY | MODE: {args.mode.upper()}")
    print(f"Alpenglow Regime : {dataset.get('alpenglow_regime')}")
    print(f"Spend Cap Ceiling: {guard.max_spend_lamports:,} lamports ({guard.max_spend_lamports / 1e9:.4f} SOL)")
    print(f"Validators Loaded: {len(validators)} across {dataset.get('distinct_client_versions_count')} client versions")
    print("=" * 88)

    if is_live:
        key_bytes = load_isolated_keypair()
        print(f"[KEY ISOLATION] Loaded external keypair ({len(key_bytes)} bytes) outside repository tree.")

    for v in validators:
        vid = v["validator_id"]
        pubkey = v["identity_pubkey"]
        cver = v["client_version"]
        cfam = v["client_family"]
        for sm in v.get("slot_measurements", []):
            slot = sm["slot"]
            probes = build_probe_burst(
                target_slot=slot,
                target_leader=pubkey,
                cu_limit=15_000,
                ladder=DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS,
                reverse_send_order=True,
                lock_mode="contended_shared_pda",
            )
            rec = guard.authorize_and_record(
                slot=slot,
                validator_identity=pubkey,
                cu_limit=15_000,
                cu_price_micro_lamports_ladder=DEFAULT_PRIORITY_LADDER_MICRO_LAMPORTS,
                dry_run=(not is_live),
            )
            m = sm["metrics"]
            print(
                f"[{vid}] Slot {slot} | Client={cver:<13} | NonVoteTxs={m['non_vote_non_jito_txs']:4d} | "
                f"GlobalTau(Fee/Cost)={m['global_kendall_tau_ppc']:+.4f} | "
                f"SharedLockMonotone(Fee)={m['shared_lock_fee_monotone']*100:5.1f}% | "
                f"SameSenderMonotone(Fee)={m['same_sender_fee_monotone']*100:5.1f}% | "
                f"ProbeBatchCost={rec.total_fee_lamports:,} lamports"
            )
            if args.live_rpc_check:
                sample_sigs = [t["signature"] for t in sm["sample_transactions_top25"][:5]]
                ok, msg = verify_slot_via_rpc(slot, sm["blockhash"], sample_sigs)
                print(f"   └── Live RPC Check: {'PASS' if ok else 'FAIL'} - {msg}")

    print("-" * 88)
    print(
        f"CUMULATIVE PROBE SPEND ({'DRY-RUN SIMULATED' if not is_live else 'LIVE'}): "
        f"{guard.spent_lamports:,} / {guard.max_spend_lamports:,} lamports "
        f"({guard.spent_sol:.6f} SOL <= 0.050000 SOL cap)"
    )
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
