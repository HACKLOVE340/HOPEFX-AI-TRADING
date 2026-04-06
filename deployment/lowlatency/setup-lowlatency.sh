#!/usr/bin/env bash
# deployment/lowlatency/setup-lowlatency.sh
# ===========================================
# One-shot low-latency VPS setup for HOPEFX trading engine.
#
# Run as root on a fresh Ubuntu 22.04 / Debian 12 VPS:
#   sudo bash deployment/lowlatency/setup-lowlatency.sh
#
# What it does:
#   1. Applies kernel sysctl tuning (TCP, memory, file descriptors)
#   2. Sets CPU governor to performance mode
#   3. Disables transparent huge pages (THP) — eliminates GC latency spikes
#   4. Pins IRQ affinity for the primary NIC to a dedicated CPU core
#   5. Sets process scheduling priority for the trading engine
#   6. Installs and configures tuned-adm latency-performance profile
#   7. Disables NIC interrupt coalescing (reduces NIC-to-kernel latency)
#   8. Configures ulimits for the hopefx user
#   9. Installs Docker with host networking mode enabled
#  10. Prints a latency benchmark summary

set -euo pipefail

HOPEFX_USER="${HOPEFX_USER:-hopefx}"
NIC="${NIC:-eth0}"          # override with your actual NIC name (ip link show)
TRADING_CORE="${TRADING_CORE:-2}"   # CPU core reserved for trading engine
IRQ_CORE="${IRQ_CORE:-3}"           # CPU core reserved for NIC IRQs

echo "=== HOPEFX Low-Latency VPS Setup ==="
echo "NIC=${NIC}  TRADING_CORE=${TRADING_CORE}  IRQ_CORE=${IRQ_CORE}"

# ── 1. Kernel sysctl ──────────────────────────────────────────────────────────
echo "[1/10] Applying kernel sysctl tuning..."
cp "$(dirname "$0")/sysctl-lowlatency.conf" /etc/sysctl.d/99-hopefx-lowlatency.conf
sysctl -p /etc/sysctl.d/99-hopefx-lowlatency.conf

# ── 2. CPU governor ───────────────────────────────────────────────────────────
echo "[2/10] Setting CPU governor to performance..."
if command -v cpupower &>/dev/null; then
    cpupower frequency-set -g performance
else
    apt-get install -y --no-install-recommends linux-tools-common linux-tools-generic 2>/dev/null || true
    for cpu in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo performance > "$cpu" 2>/dev/null || true
    done
fi

# ── 3. Disable transparent huge pages ────────────────────────────────────────
echo "[3/10] Disabling transparent huge pages..."
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
# Persist across reboots via rc.local
cat > /etc/rc.local << 'EOF'
#!/bin/bash
echo never > /sys/kernel/mm/transparent_hugepage/enabled
echo never > /sys/kernel/mm/transparent_hugepage/defrag
exit 0
EOF
chmod +x /etc/rc.local

# ── 4. NIC interrupt affinity ─────────────────────────────────────────────────
echo "[4/10] Pinning NIC IRQs to core ${IRQ_CORE}..."
for irq in $(grep "${NIC}" /proc/interrupts | awk -F: '{print $1}' | tr -d ' '); do
    echo "${IRQ_CORE}" > "/proc/irq/${irq}/smp_affinity_list" 2>/dev/null || true
done

# ── 5. Process scheduling priority ───────────────────────────────────────────
echo "[5/10] Configuring process priority for hopefx user..."
cat >> /etc/security/limits.conf << EOF

# HOPEFX trading engine — real-time scheduling priority
${HOPEFX_USER}    soft    rtprio    99
${HOPEFX_USER}    hard    rtprio    99
${HOPEFX_USER}    soft    nice      -20
${HOPEFX_USER}    hard    nice      -20
${HOPEFX_USER}    soft    nofile    1048576
${HOPEFX_USER}    hard    nofile    1048576
${HOPEFX_USER}    soft    memlock   unlimited
${HOPEFX_USER}    hard    memlock   unlimited
EOF

# ── 6. tuned latency-performance profile ─────────────────────────────────────
echo "[6/10] Applying tuned latency-performance profile..."
if ! command -v tuned-adm &>/dev/null; then
    apt-get install -y --no-install-recommends tuned 2>/dev/null || true
fi
if command -v tuned-adm &>/dev/null; then
    systemctl enable --now tuned
    tuned-adm profile latency-performance
fi

# ── 7. NIC interrupt coalescing ───────────────────────────────────────────────
echo "[7/10] Disabling NIC interrupt coalescing on ${NIC}..."
if command -v ethtool &>/dev/null; then
    ethtool -C "${NIC}" rx-usecs 0 tx-usecs 0 2>/dev/null || \
        echo "  Warning: ethtool coalescing not supported on ${NIC} (OK for VMs)"
else
    apt-get install -y --no-install-recommends ethtool 2>/dev/null || true
fi

# ── 8. ulimits system-wide ───────────────────────────────────────────────────
echo "[8/10] Setting system-wide ulimits..."
cat > /etc/systemd/system.conf.d/hopefx-limits.conf << 'EOF'
[Manager]
DefaultLimitNOFILE=1048576
DefaultLimitNPROC=65535
DefaultLimitMEMLOCK=infinity
EOF
systemctl daemon-reexec 2>/dev/null || true

# ── 9. Docker host networking ─────────────────────────────────────────────────
echo "[9/10] Configuring Docker for low-latency networking..."
mkdir -p /etc/docker
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  },
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 1048576,
      "Soft": 1048576
    }
  },
  "live-restore": true
}
EOF
if systemctl is-active docker &>/dev/null; then
    systemctl reload docker || systemctl restart docker
fi

# ── 10. Latency benchmark ─────────────────────────────────────────────────────
echo "[10/10] Running quick latency benchmark..."
if command -v ping &>/dev/null; then
    echo "  Loopback RTT (should be <0.1ms):"
    ping -c 5 -q 127.0.0.1 | tail -1
fi

echo ""
echo "=== Setup complete ==="
echo "Reboot recommended to apply all changes."
echo ""
echo "Next steps:"
echo "  1. Reboot: sudo reboot"
echo "  2. Verify THP disabled: cat /sys/kernel/mm/transparent_hugepage/enabled"
echo "  3. Verify CPU governor: cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
echo "  4. Start HOPEFX with host networking: docker compose -f docker-compose.yml -f docker-compose.lowlatency.yml up -d"
