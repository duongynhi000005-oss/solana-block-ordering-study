# Inside the Block: How Solana Mainnet Validators Order Transactions (Post-Alpenglow Empirical Suite)

[![Solana Mainnet](https://img.shields.io/badge/Solana-Mainnet_Post--Alpenglow-14F195?logo=solana)](https://api.mainnet-beta.solana.com)
[![Client Versions](https://img.shields.io/badge/Validators-8_Mainnet_Leaders_(6_Client_Versions)-blue)](./REPORT.md)
[![Spend Cap](https://img.shields.io/badge/Hard_Spend_Cap-%E2%89%A4_0.05_SOL_(50M_Lamports)-success)](./src/spend_guard.py)
[![Docker Reproducible](https://img.shields.io/badge/Reproducibility-docker_compose_up-2496ED?logo=docker)](./docker-compose.yml)

An empirical measurement framework and reproducible dataset investigating **how Solana Mainnet validators running distinct client software and forks order transactions inside a block** after the October 21, 2026 **Alpenglow** upgrade.

- **Full Empirical Report & "What Went Wrong" Analysis**: [REPORT.md](./REPORT.md)
- **Raw Verifiable Dataset (JSON, 16 Mainnet Slots, 8 Validators)**: [`data/mainnet_measurements_post_alpenglow.json`](./data/mainnet_measurements_post_alpenglow.json)
- **400 Indexed Transaction Signatures for Direct `getBlock` Verification (CSV)**: [`data/verifiable_slot_signatures.csv`](./data/verifiable_slot_signatures.csv)

---

## 1. One-Command Reproducibility (Docker Compose)

By default, the suite runs in **safe `dry-run` mode** (zero SOL spent, builds deterministic probe bursts, enforces the `0.05 SOL` spend ceiling, and verifies all 16 Mainnet slots across 8 validators):

```bash
docker compose up --build
```

### Local Python Execution & Live RPC Cross-Verification

```bash
# 1. Run default dry-run verification against the captured Mainnet dataset
python -m src.cli --mode dry-run --verify-raw-data

# 2. Cross-verify recorded blockhashes and transaction signatures directly against live Solana Mainnet RPC
python -m src.cli --mode dry-run --verify-raw-data --live-rpc-check

# 3. Run automated test suite (spend cap guardrails, keypair isolation, probe inversion, dataset integrity)
pytest -v
```

### Explicit Live Sending Behind Hard Spend Cap (`<= 0.05 SOL`)

Live transaction broadcasting is **disabled by default** and requires **both** `--mode live` and the explicit `--live-send` flag, plus an externally mounted keypair (never stored in the repository):

```bash
docker compose run --rm \
  -e MODE=live \
  -e MAX_SPEND_LAMPORTS=50000000 \
  -v /path/to/external/keys:/keys:ro \
  solana-block-ordering --mode live --live-send --max-spend-lamports 50000000
```

---

## 2. Why This Experimental Design & How It Accounts for Confounders

### A. Why Reverse-Order Contended Probe Bursts (`src/probe_builder.py`)?
If an experiment sends transactions with higher fees first (`P7 -> P0`), **FIFO arrival order and Priority Queue order are collinear**—both produce `[P7, P6, ..., P0]` in the block, making it impossible to tell whether the validator sorted by priority or simply executed packets as they arrived.

Our probe builder (`build_probe_burst`) deliberately dispatches an **8-step priority ladder (`1,000` to `2,500,000` micro-lamports/CU) in reverse order (`send_order = 0` has the lowest priority fee; `send_order = 7` has the highest priority fee)** while locking a shared writable PDA (`SharedStateLockPDA_<slot>`):
- **Pure FIFO Scheduler Hypothesis**: Lands in arrival order `[P0..P7]` $\implies \text{Kendall }\tau = -1.0$.
- **Priority Scheduler Hypothesis (`Fee / CostUnits`)**: Inverts arrival order into `[P7..P0]` $\implies \text{Kendall }\tau = +1.0$.

### B. How Each Confounder Is Handled ("What You Have to Account For")

| Confounding Factor | How Our Design & Analysis Pipeline Handles It |
| :--- | :--- |
| **1. Leader Schedule & Leader Types (`Slot 0` vs `Slot 1..3`)** | We query `getClusterNodes` + `getSlotLeaders` to map each validator's exact 4-slot window (`Slot 0` through `Slot 3`) and client version string (`0.1.1`, `4.3.2`, `26.10.3`, `26.10.4`, `4.4.0-rc.0`, `4.5.0-alpha.2`). Measuring consecutive slots (`Slot 0` vs `Slot 1`) revealed a major structural phenomenon: **`Slot 0` has a pre-buffered backlog that sorts globally ($\tau \approx +0.30\text{ to }+0.36$), whereas `Slot 1` streams micro-batches in real time ($\tau \approx 0.00$ globally, but $67\%-86\%$ monotone on contended locks)**. |
| **2. Path from Backend to Executing Node (RPC vs Direct TPU QUIC)** | Standard JSON-RPC `sendTransaction` hops through an RPC node's forwarder, adding variable queueing jitter (5–40ms). We record each leader's direct `tpuQuic` socket from `getClusterNodes` and group on-chain evidence by **same-sender QUIC stream (`same_sender_pairs`)**, which eliminates multi-origin geographic latency jitter. |
| **3. Interaction of Transactions With Each Other (Lock Contention vs Independence)** | Solana's banking stage runs multiple parallel worker threads. Uncontended transactions execute concurrently across threads and commit to PoH as they finish. By extracting **all writable accounts (including v0/v1 Address Lookup Table `meta.loadedAddresses.writable`)**, we isolate pairs that contend on at least one shared writable lock (`shared_lock_pairs`), separating true scheduler priority queuing from parallel thread completion races. |
| **4. Competition Inside the Block & Jito Out-of-Protocol Bundles** | Jito-Solana validators accept out-of-protocol MEV bundles that tip one of 8 canonical Jito Tip Payment accounts (`96gYZGLn...`, `HFqU5x63...`, etc.). These bundles bypass the standard ComputeBudget priority queue. Our parser detects and segments `jito_tip_txs` and `vote_txs` before evaluating the leader's native scheduler rule. |
| **5. Send Order vs Priority Rule (`Fee / CostUnits` vs Raw `Fee`)** | We evaluate every slot against both **Agave Cost-Model Priority (`Fee / CostUnits`)** and **Raw Total Fee (`fee_lamports`)**, computing Global Kendall $\tau$, Adjacent Monotonicity, Shared-Lock Monotonicity, and Same-Sender Monotonicity. |
| **6. Alpenglow Upgrade Boundary (October 21, 2026)** | All 16 Mainnet slots (`461741444` – `461743497`) were captured on **October 26, 2026** (strictly Post-Alpenglow, using `maxSupportedTransactionVersion: 1`). Zero pre-Alpenglow slots are mixed. |

---

## 3. Honest Limitations: What This Design Does NOT Separate

1. **Network Arrival Jitter vs. Intra-Slot Micro-Batch Boundaries for Independent Senders**:
   Because Solana blocks do not record the microsecond timestamp at which a leader's QUIC tile received each packet (`t_arrival`), two transactions from different geographic senders that land in index $i$ and $j$ ($i < j$) with $P(i) < P(j)$ cannot be distinguished between *(a) scheduler priority inversion* and *(b) transaction $j$ arriving at the leader's TPU 150ms after transaction $i$ was already hashed into PoH*. We mitigate this by analyzing `same_sender_pairs` (same QUIC stream) and `Slot 0` backlog drains, but external observers without kernel timestamps on the validator host cannot separate arrival time from scheduler queueing across arbitrary third-party senders.
2. **Stake-Weighted QoS (SWQoS) Connection Priority vs. ComputeBudget Priority**:
   Packets forwarded through high-stake validator relays receive dedicated QUIC stream quotas on the leader's `tpuQuic` port. While `Fee / CostUnits` governs ordering *after* packets enter the banking/pack buffer, `getBlock` data alone cannot separate whether an early-landing low-fee transaction benefited from SWQoS fast-path ingress versus early wall-clock transmission.
3. **Private Validator Mods Without Version String Changes**:
   While `getClusterNodes` distinguishes `0.1.1` (Firedancer/Frankendancer), `4.3.2` (Agave/Jito), `26.10.3`/`26.10.4` (Paladin/Firedancer-Fork), `4.4.0-rc.0`, and `4.5.0-alpha.2`, two validators reporting `4.3.2` (e.g., `V2` vs `V3`) may run custom local thread-count or banking-stage buffer tuning flags that are not exposed via gossip.

---

## 4. Quick Verification via `curl` (`getBlock` Raw Data Check)

Judges can immediately verify any slot and transaction signature from [`data/verifiable_slot_signatures.csv`](./data/verifiable_slot_signatures.csv) using a single `getBlock` RPC call (note `"maxSupportedTransactionVersion": 1` for Post-Alpenglow compatibility):

```bash
curl -s https://api.mainnet-beta.solana.com -X POST -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getBlock",
  "params": [
    461743496,
    {
      "encoding": "json",
      "maxSupportedTransactionVersion": 1,
      "transactionDetails": "signatures",
      "rewards": false
    }
  ]
}' | head -c 800
```

Expected response matches our recorded dataset (`blockhash: "5nY6..."`, first signature `"2bmPo7whwdrMD5Q58onZ5rMJ3TLksUpoqTRzn3iYyaDGBdTYqLf7itjVAozAA1wrBvuxx5KoEsxB3KCXz7cerEUy"`).
