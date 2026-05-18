#!/usr/bin/env bash
# setup.sh — deploy IRIS BGP/ISIS lab to a fresh EVE-NG server.
# Run as root from the directory where the tarball was extracted.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAB_UUID="04fce5a2-b313-4dc6-8a38-a38c79249d8a"
LAB_NAME="IRIS_BGP_ISIS_Lab.unl"
TMP_BASE="/opt/unetlab/tmp/0/$LAB_UUID"

die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run as root"
[ -d /opt/unetlab ]   || die "Not an EVE-NG host (/opt/unetlab missing)"

echo "=== IRIS BGP/ISIS Lab Setup ==="
echo "  host : $(hostname -f 2>/dev/null || hostname)"
echo "  date : $(date)"
echo

# ── 1. Images ────────────────────────────────────────────────────────────────
echo "[1/5] Installing node images..."

mkdir -p /opt/unetlab/addons/dynamips
cp "$SCRIPT_DIR/images/dynamips/c7200-adventerprisek9-mz.152-4.S2.image" \
   /opt/unetlab/addons/dynamips/
echo "  c7200 IOS      : done"

mkdir -p /opt/unetlab/addons/qemu/mikrotik-chr-7.7
cp "$SCRIPT_DIR/images/qemu/mikrotik-chr-7.7/hda.qcow2" \
   /opt/unetlab/addons/qemu/mikrotik-chr-7.7/
echo "  MikroTik CHR   : done"

mkdir -p /opt/unetlab/addons/qemu/vsrxng-22.2R1
cp "$SCRIPT_DIR/images/qemu/vsrxng-22.2R1/virtioa.qcow2" \
   /opt/unetlab/addons/qemu/vsrxng-22.2R1/
echo "  vSRX-NG 22.2R1 : done"

mkdir -p /opt/unetlab/addons/qemu/freebsd-13.5
if [ -f /opt/unetlab/addons/qemu/freebsd-13.5/virtioa.qcow2 ]; then
    echo "  FreeBSD 13.5   : already present, skipping"
else
    echo "  FreeBSD 13.5   : decompressing (~10-15 min)..."
    xz -dk --stdout \
       "$SCRIPT_DIR/images/qemu/freebsd-13.5/FreeBSD-13.5-RELEASE-amd64.qcow2.xz" \
       > /opt/unetlab/addons/qemu/freebsd-13.5/virtioa.qcow2
    echo "  FreeBSD 13.5   : done ($(du -sh /opt/unetlab/addons/qemu/freebsd-13.5/virtioa.qcow2 | cut -f1))"
fi

# ── 2. Permissions ───────────────────────────────────────────────────────────
echo "[2/5] Fixing EVE-NG image permissions..."
/opt/unetlab/wrappers/unl_wrapper -a fixpermissions 2>/dev/null || true
echo "  done"

# ── 3. Lab file ──────────────────────────────────────────────────────────────
echo "[3/5] Installing lab file..."
cp "$SCRIPT_DIR/$LAB_NAME" /opt/unetlab/labs/
chmod 644 /opt/unetlab/labs/$LAB_NAME
echo "  /opt/unetlab/labs/$LAB_NAME"

# ── 4. Scripts and configs ───────────────────────────────────────────────────
echo "[4/5] Installing scripts and configs..."
mkdir -p /opt/iris-lab
cp -r "$SCRIPT_DIR/scripts/." /opt/iris-lab/
cp -r "$SCRIPT_DIR/configs"   /opt/iris-lab/
chmod +x /opt/iris-lab/*.sh /opt/iris-lab/*.py 2>/dev/null || true
echo "  /opt/iris-lab/"

# ── 5. Seed startup configs ──────────────────────────────────────────────────
echo "[5/5] Seeding per-node startup configs..."
# sync_eve_configs.py reads from /tmp/lab-configs/configs — point it at ours
mkdir -p /tmp/lab-configs
ln -sfn /opt/iris-lab/configs /tmp/lab-configs/configs

# Pre-create node tmp dirs for Cisco + MikroTik nodes so sync can write
# startup-config immediately (EVE-NG picks it up on node start).
mkdir -p "$TMP_BASE"
for id in 1 4 5 6 7 8 9 10 11 12 13 14 15 16 17 19 20 21 22; do
    mkdir -p "$TMP_BASE/$id"
done
getent group unl &>/dev/null && chown -R root:unl "$TMP_BASE" 2>/dev/null || true

cd /opt/iris-lab && python3 sync_eve_configs.py

# ── Done ─────────────────────────────────────────────────────────────────────
echo
echo "════════════════════════════════════════════════════════"
echo " Setup complete."
echo "════════════════════════════════════════════════════════"
echo
echo " NEXT STEPS"
echo " ──────────"
echo " 1. Open the EVE-NG web UI → open '$LAB_NAME' → Start All Nodes"
echo
echo " 2. Cisco / MikroTik nodes start immediately."
echo "    Junos RRs take ~6 min for cloud-init first-boot commit:"
echo "      watch ls /opt/unetlab/tmp/0/$LAB_UUID/{2,3}/.configured"
echo "    Then reset each RR once .configured appears:"
echo "      bash /opt/iris-lab/rr_reset.sh 2 RR1"
echo "      bash /opt/iris-lab/rr_reset.sh 3 RR2"
echo
echo " 3. FreeBSD nodes need first-boot config:"
echo "    freebsd13  (node 18): VNC via EVE-NG web UI → set /boot/loader.conf"
echo "    freebsd14  (node 24): python3 /opt/iris-lab/freebsd14_firstboot.py --wait"
echo "    ACDC_HOST  (node 23): bash /opt/iris-lab/acdc_host_inject.sh"
echo
echo " 4. Live-apply Cisco running config:"
echo "    python3 /opt/iris-lab/live_apply.py"
echo "    python3 /opt/iris-lab/live_apply_sla.py"
echo
echo " Console telnet: 32769 (7206VXR) … 32792 (freebsd14)"
echo " Syslog / NetFlow target in configs: 10.2.0.114"
echo
