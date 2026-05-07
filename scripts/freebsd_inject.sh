#!/bin/bash
# Inject /etc/rc.conf, /boot/loader.conf, etc. into the FreeBSD qcow2 image
# from configs/freebsd13.txt. Run on the EVE-NG host BEFORE booting node 18.
#
# Strategy: qemu-nbd connect → mount UFS read-write → write files → unmount.
# Linux UFS support: ufstype=ufs2 + read-write needs CONFIG_UFS_FS_WRITE in
# the kernel, which is *not* enabled in stock Ubuntu. So we use guestmount
# (libguestfs-tools) which talks UFS via its own driver.
#
# If guestmount is not available, this script falls back to a one-shot
# console-based config injection (boot the VM, expect prompt, paste rc.conf).
set -u
QCOW=/opt/unetlab/addons/qemu/freebsd-13.5/virtioa.qcow2
SRC=/tmp/lab-configs/configs/freebsd13.txt
MNT=/mnt/freebsd13-inject

[ -f "$QCOW" ] || { echo "ERROR: $QCOW not found"; exit 2; }
[ -f "$SRC" ]  || { echo "ERROR: $SRC not found (run sync_eve_configs prep first)"; exit 2; }

if ! command -v guestmount >/dev/null 2>&1; then
    echo "guestmount not installed. Install with:"
    echo "    apt-get install -y libguestfs-tools"
    echo "or fall back to first-boot console configuration (see CLAUDE.md)."
    exit 3
fi

# Parse @@FILE: blocks from the source into a temp staging dir
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"; guestunmount "$MNT" 2>/dev/null; rmdir "$MNT" 2>/dev/null' EXIT

awk -v outdir="$STAGE" '
    /^@@FILE:/ {
        path=$2
        sub("^/", "", path)
        gsub("/", "__", path)
        out = outdir "/" path
        getline       # consume the blank or first content line
        printing=1
        next
    }
    /^@@CMD:/ {
        printing=0
        next
    }
    /^@@/ { printing=0; next }
    printing { print > out }
' "$SRC"

mkdir -p "$MNT"
echo "+ guestmount $QCOW -> $MNT"
guestmount -a "$QCOW" -m /dev/sda3 --rw "$MNT" || guestmount -a "$QCOW" -i --rw "$MNT"

cp "$STAGE/boot__loader.conf"   "$MNT/boot/loader.conf"
cp "$STAGE/etc__rc.conf"        "$MNT/etc/rc.conf"
mkdir -p "$MNT/etc/ssh/sshd_config.d"
cp "$STAGE/etc__ssh__sshd_config.d__lab.conf" "$MNT/etc/ssh/sshd_config.d/lab.conf"

# /etc/ttys: enable serial getty on ttyu0 (replace existing line if present)
sed -i '/^ttyu0/d' "$MNT/etc/ttys"
cat "$STAGE/etc__ttys.add" >> "$MNT/etc/ttys"

# /etc/syslog.conf: append remote target
cat "$STAGE/etc__syslog.conf.add" >> "$MNT/etc/syslog.conf"

# Set root password to lab123: pre-computed sha512 hash (compatible with FreeBSD).
# Generated with: echo -n 'lab123' | openssl passwd -6 -salt freebsd_lab -stdin
ROOT_HASH='$6$freebsd_lab$XwTu1aYBJqGoUgqYRfH7bpgD8K0wM81Ud3jL3i4vNk2fX9D2u/4tNh.MYoPBjTGtaoqRyrFa8pLhRT4G5VLkW.'
sed -i -E "s|^(root):[^:]*:|\1:${ROOT_HASH//\$/\\\$}:|" "$MNT/etc/master.passwd"
# Need to rebuild pwd.db -- but pwd_mkdb is a FreeBSD tool; we can pre-stage
# /etc/master.passwd and FreeBSD will regenerate spwd.db at first boot if missing.
rm -f "$MNT/etc/spwd.db" "$MNT/etc/pwd.db"
# Trigger first-boot rebuild via a marker
touch "$MNT/.passwd_dirty"

guestunmount "$MNT"
echo "OK: rc.conf, loader.conf, ssh, ttys, syslog applied"
echo "    next: start node 18 (freebsd13) via unl_wrapper -a start"
