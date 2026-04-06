# HOPEFX Low-Latency Deployment Guide

## Target venues and recommended VPS locations

| Venue | Exchange DC | Recommended VPS |
|---|---|---|
| CME COMEX GC futures | Equinix NY4 (Secaucus NJ) | Vultr New Jersey / AWS us-east-1 |
| ByBit XAUUSDT perps | AWS Tokyo (ap-northeast-1) | Vultr Tokyo / AWS ap-northeast-1 |
| IBKR FIX | Equinix NY5 / LD4 | Vultr New Jersey or London |
| OANDA | AWS us-east-1 | Vultr New Jersey |

Co-location (physical rack in Equinix NY4) reduces CME round-trip from ~1ms to ~50–200μs.
For a VPS in the same AWS region as the venue, expect 0.5–2ms — sufficient for gold strategies.

## Setup steps

### 1. Provision VPS
Minimum spec for full stack:
- 4 vCPU (dedicated, not shared)
- 8 GB RAM
- NVMe SSD
- 1 Gbps network
- Ubuntu 22.04 LTS

### 2. Run low-latency setup script
```bash
git clone https://github.com/HACKLOVE340/HOPEFX-AI-TRADING.git
cd HOPEFX-AI-TRADING
sudo NIC=eth0 TRADING_CORE=2 IRQ_CORE=3 bash deployment/lowlatency/setup-lowlatency.sh
sudo reboot
```

### 3. Verify tuning
```bash
# THP disabled
cat /sys/kernel/mm/transparent_hugepage/enabled
# expected: always madvise [never]

# CPU governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
# expected: performance

# TCP settings
sysctl net.ipv4.tcp_slow_start_after_idle net.ipv4.tcp_low_latency
# expected: 0, 1
```

### 4. Configure .env
```bash
cp .env.example .env
# Set CME, ZMQ, and low-latency vars — see .env.example [Low-Latency] section
```

### 5. Start with low-latency overlay
```bash
docker compose -f docker-compose.yml -f docker-compose.lowlatency.yml up -d
```

## CPU pinning strategy

```
Core 0-1  →  OS, Redis, PostgreSQL, API
Core 2    →  Trading engine (TRADING_CORE=2)
Core 3    →  C++ execution shim + NIC IRQs (CPP_SHIM_CORE=3, IRQ_CORE=3)
Core 4+   →  ML inference, retraining (if available)
```

## Expected latency improvements

| Baseline (no tuning) | After sysctl tuning | After CPU pinning | After host networking |
|---|---|---|---|
| 5–50ms | 2–10ms | 1–5ms | 0.5–2ms |

Co-location at Equinix NY4 (CME): 50–200μs additional reduction.

## Kernel bypass (future)

Full DPDK/kernel bypass requires:
1. A bare-metal server (not a VM) with a supported NIC (Solarflare XtremeScale, Mellanox ConnectX-5)
2. Rewriting the C++ shim to use DPDK's `rte_eth` API instead of standard sockets
3. Pinning the DPDK poll-mode driver to a dedicated isolated core (`isolcpus=3` in GRUB)

This reduces NIC-to-application latency from ~5μs to ~1μs.
For gold trading on CME, the current setup (host networking + CPU pinning) is sufficient.
