# HOPEFX — Known Gaps vs. Institutional Reference Stack

This document honestly describes features that are commonly cited in
institutional-grade trading platforms but are **not yet implemented** in
HOPEFX.  Each entry explains what *is* in place today, what is missing, and
what would be required to close the gap.

---

## 1. FPGA Acceleration

| | |
|---|---|
| **Status** | ❌ Not implemented |
| **Current state** | A dead feature flag (`enable_fpga: false`) in `core/mcc/master_control.py` and `config/ultimate_config.yaml`.  The flag has no runtime effect. |
| **What's needed** | Bare-metal server with a Xilinx Alveo / Intel Stratix FPGA PCIe card; OpenCL or HLS kernel for order-book processing; PCIe DMA driver integration with the C++ shim (`brokers/cpp_shim_connector.py`). |
| **Why it matters** | Citadel / Two Sigma use FPGAs to achieve <1 µs tick-to-order latency.  The current Python + C++ shim path is ~200 µs best-case. |
| **ETA** | Not planned.  Requires hardware procurement and kernel engineering beyond the current scope. |

---

## 2. DPDK / Kernel-Bypass Networking

| | |
|---|---|
| **Status** | ❌ Not implemented |
| **Current state** | Standard Linux TCP stack with sysctl tuning (`deployment/lowlatency/setup-lowlatency.sh`).  The low-latency README explicitly labels DPDK as a *future* item under "Kernel bypass". |
| **What's needed** | Bare-metal server (DPDK does not work inside VMs without SR-IOV); Solarflare XtremeScale or Mellanox ConnectX-5 NIC; rewrite C++ shim to use `rte_eth` API instead of BSD sockets. |
| **Current latency** | 0.5–2 ms on co-located VPS (host networking + CPU pinning). |
| **With DPDK** | ~1 µs NIC-to-application (for gold on CME this is not a meaningful advantage). |
| **ETA** | Not planned for gold trading.  High-frequency FX / equities would benefit. |

---

## 3. kdb+ / Tick-Columnar Storage

| | |
|---|---|
| **Status** | ❌ Not implemented |
| **Current state** | TimescaleDB-backed `data_layer/tick_store.py` (compressed hypertables) + Redis streams for live ticks + PostgreSQL for trade/order history.  This covers the functional requirements for gold trading. |
| **What kdb+ adds** | 100× query speed for vector/time-series analytics over billion-row tick histories via q/kdb+.  Useful for intraday signal research at HFT tick depth. |
| **ETA** | Not planned.  TimescaleDB is sufficient for the current gold-only strategy universe. |

---

## 4. Formal Verification (TLA+ / Coq / Lean)

| | |
|---|---|
| **Status** | ❌ Not implemented |
| **Current state** | No mathematical proofs of correctness for any subsystem.  Testing (pytest, property-based tests) is the primary correctness mechanism. |
| **What it provides** | Mathematical proof that core state machines (kill switch, position manager, circuit breaker) cannot enter illegal states under all possible interleavings. |
| **What's needed** | TLA+ specs for `kill_switch.py`, `execution/position_manager.py`, `risk/circuit_breakers.py`; model checking with TLC or Apalache. |
| **ETA** | Not planned.  High engineering effort for incremental safety gain given the existing test coverage. |

---

## 5. Hardware Security Module (HSM) — default is software

| | |
|---|---|
| **Status** | ⚠️ Software-only by default |
| **Current state** | `security/vault.py` (`HSMVault`) implements AES-256 keys in OS process memory using PBKDF2-HMAC-SHA256.  Hardware backends (YubiKey HSM 2, AWS CloudHSM, Azure Key Vault) are available as opt-in via `hsm_type=` constructor argument but require external hardware/credentials. |
| **Risk** | Keys are extractable from a memory dump or core file.  A compromised host exposes all API credentials. |
| **Mitigation** | Set `hsm_type='cloudhsm'` with AWS KMS or Azure Key Vault + set `CLOUD_HSM_PROVIDER` env var.  This delegates key storage to a FIPS 140-2 Level 3 boundary. |

---

## 6. Hardware Circuit Breaker

| | |
|---|---|
| **Status** | ⚠️ Software-only |
| **Current state** | `kill_switch.py` provides a multi-trigger software kill switch (in-memory flag + Redis latch + file flag + K8s ConfigMap watcher).  If the Python process is OOM-killed or the host crashes, the switch cannot fire. |
| **Hardware equivalent** | Exchange-level *Cancel on Disconnect* (CoD) / *Auto-Liquidate on Disconnect* — a session-level order that cancels all working orders if the FIX session drops.  IBKR supports this natively (`reqGlobalCancel` on disconnect). |
| **Action** | Enable IBKR `cancelOnDisconnect=True` in the FIX session config.  For OANDA, set `heartbeat_interval` so the platform auto-cancels on missed heartbeats. |

---

## 7. Two-Phase Commit / Distributed Transactions

| | |
|---|---|
| **Status** | ✅ Fixed (in-memory rollback on Redis failure) |
| **Previous state** | `execution/position_manager.py` wrote to in-memory dict first, then Redis; Redis failure left state inconsistent. |
| **Current state** | `open_position` and `close_position` now roll back the in-memory state and raise `RuntimeError` if the Redis persist/remove fails.  Both stores stay consistent. |
| **Remaining gap** | PostgreSQL trade-log and Redis position state are still two independent writes.  A true distributed transaction (XA, saga, or outbox pattern) across both stores is not implemented. |

---

## 8. GIL / Deadlock Protection

| | |
|---|---|
| **Status** | ⚠️ Standard CPython threading |
| **Current state** | Asyncio event loop for I/O; `asyncio.Lock` for position mutations; `threading.Lock` for Redis pool and Prometheus.  No watchdog or deadlock detector. |
| **Risk** | A blocking C extension call (e.g. a slow sklearn model predict without `allow_threads`) can freeze the event loop.  A mis-ordered lock acquisition can deadlock. |
| **Mitigation in place** | ML inference runs in `asyncio.to_thread()` (off the event loop).  No nested locks in the hot path. |
| **Remaining gap** | No watchdog timer that kills/restarts a frozen event loop.  Add `asyncio.wait_for()` wrappers around any call that might block. |

---

## 9. Binary Wire Protocol (Protobuf / SBE)

| | |
|---|---|
| **Status** | ⚠️ JSON over Redis pub/sub (with optional msgpack + LZ4 for `DomainEvent`) |
| **Current state** | `core/event_bus.py` uses `json.dumps()` over Redis channels.  `DomainEvent` uses msgpack + LZ4 when those libraries are installed. |
| **What Protobuf/SBE adds** | 5–10× lower serialisation CPU; 2–3× smaller wire size; strict schema versioning. |
| **ETA** | Not planned.  JSON overhead is not the bottleneck for gold trading latencies in the 1–10 ms range. |

---

## 10. CFTC / Regulatory Reporting

| | |
|---|---|
| **Status** | ⚠️ Disabled by default; suppressed when `PROP_FIRM_MODE=true` |
| **Current state** | `compliance/regulatory_reporter.py` implements CFTC SDR (DTCC GTR), SEC CAT, and MiFID II report submission.  Enabled only when `REGULATORY_REPORTING_ENABLED=true` AND `PROP_FIRM_MODE=false`. |
| **Risk** | Any operator running live regulated swap trading with `REGULATORY_REPORTING_ENABLED=false` is not reporting as required by CFTC 17 CFR Part 45.  A startup warning is now emitted when `PROP_FIRM_MODE=true`. |
| **Action** | Set `REGULATORY_REPORTING_ENABLED=true` and configure `DTCC_GTR_API_KEY` / `CAT_API_KEY` before going live with reportable instruments. |

---

*Last updated: 2026-04.  Maintained by the HOPEFX engineering team.*
