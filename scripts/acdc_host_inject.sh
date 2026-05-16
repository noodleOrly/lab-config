#!/bin/bash
# Inject /boot/loader.conf, /etc/rc.conf, etc. into the ACDC_HOST FreeBSD qcow2.
# Run on the EVE-NG host AFTER lab4_topology.py and BEFORE first boot of node 23.
#
# Targets the per-node qcow2 so freebsd13 (node 18) is not affected.
# Same libguestfs caveat as freebsd_inject.sh: guestmount currently fails on
# this host (kernel/qemu mismatch). Fallback: VNC console at first boot.
set -u

LAB_UUID="04fce5a2-b313-4dc6-8a38-a38c79249d8a"
NODE_ID=23
QCOW="/opt/unetlab/tmp/0/${LAB_UUID}/${NODE_ID}/virtioa.qcow2"
SRC="/tmp/lab-configs/configs/freebsd_acdc_host.txt"
MNT="/mnt/acdc-host-inject"

[ -f "$SRC" ] || { echo "ERROR: $SRC not found — run sync prep first"; exit 2; }

if [ ! -f "$QCOW" ]; then
    echo "ERROR: $QCOW not found."
    echo "  Start (then immediately stop) node ${NODE_ID} in EVE-NG once so"
    echo "  EVE-NG copies the base image to the per-node directory, then re-run."
    exit 2
fi

if ! command -v guestmount >/dev/null 2>&1; then
    echo "guestmount not available (libguestfs broken on this host)."
    echo ""
    echo "Manual first-boot procedure via EVE-NG VNC (display :${NODE_ID}, port 59${NODE_ID}):"
    echo "  1. Start node ${NODE_ID} (ACDC_HOST) in EVE-NG."
    echo "  2. Connect with: vncviewer 10.2.0.147:59${NODE_ID}"
    echo "     (or EVE-NG web GUI -> node context menu -> VNC)"
    echo "  3. Log in as root (no password on first boot of base image)."
    echo "  4. Paste the following commands:"
    echo ""
    echo "---- /boot/loader.conf ----"
    awk '/^@@FILE: \/boot\/loader.conf/{p=1;next} /^@@/{p=0} p{print}' "$SRC"
    echo ""
    echo "---- /etc/rc.conf ----"
    awk '/^@@FILE: \/etc\/rc.conf/{p=1;next} /^@@/{p=0} p{print}' "$SRC"
    echo ""
    echo "  5. Then run:"
    echo "     echo 'PermitRootLogin yes' >> /etc/ssh/sshd_config"
    echo "     echo 'PasswordAuthentication yes' >> /etc/ssh/sshd_config"
    echo "     echo 'ttyu0   \"/usr/libexec/getty 3wire\" vt100 onifconsole secure' >> /etc/ttys"
    echo "     echo '*.notice @10.2.0.114' >> /etc/syslog.conf"
    echo "     echo 'lab123' | pw usermod root -h 0"
    echo "     reboot"
    exit 3
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"; guestunmount "$MNT" 2>/dev/null; rmdir "$MNT" 2>/dev/null' EXIT

awk -v outdir="$STAGE" '
    /^@@FILE:/ {
        path=$2
        sub("^/", "", path)
        gsub("/", "__", path)
        out = outdir "/" path
        getline
        printing=1
        next
    }
    /^@@CMD:/ { printing=0; next }
    /^@@/     { printing=0; next }
    printing  { print > out }
' "$SRC"

mkdir -p "$MNT"
echo "+ guestmount $QCOW -> $MNT"
guestmount -a "$QCOW" -m /dev/sda3 --rw "$MNT" || guestmount -a "$QCOW" -i --rw "$MNT"

cp "$STAGE/boot__loader.conf"   "$MNT/boot/loader.conf"
cp "$STAGE/etc__rc.conf"        "$MNT/etc/rc.conf"
mkdir -p "$MNT/etc/ssh/sshd_config.d"
cp "$STAGE/etc__ssh__sshd_config.d__lab.conf" "$MNT/etc/ssh/sshd_config.d/lab.conf"

sed -i '/^ttyu0/d' "$MNT/etc/ttys"
cat "$STAGE/etc__ttys.add" >> "$MNT/etc/ttys"

cat "$STAGE/etc__syslog.conf.add" >> "$MNT/etc/syslog.conf"

ROOT_HASH='$6$freebsd_lab$XwTu1aYBJqGoUgqYRfH7bpgD8K0wM81Ud3jL3i4vNk2fX9D2u/4tNh.MYoPBjTGtaoqRyrFa8pLhRT4G5VLkW.'
sed -i -E "s|^(root):[^:]*:|\1:${ROOT_HASH//\$/\\\$}:|" "$MNT/etc/master.passwd"
rm -f "$MNT/etc/spwd.db" "$MNT/etc/pwd.db"
touch "$MNT/.passwd_dirty"

guestunmount "$MNT"
echo "OK: loader.conf, rc.conf, ssh, ttys, syslog applied to node ${NODE_ID}"
echo "    next: start node ${NODE_ID} (ACDC_HOST) via EVE-NG"
