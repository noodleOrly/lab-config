#!/bin/bash
# Wipe + restart one Junos node with refreshed juniper.conf and config.iso
# Usage: rr_reset.sh <node_id> <name>
set -e
NID=$1
NAME=$2
LAB=/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl
NDIR=/opt/unetlab/tmp/0/04fce5a2-b313-4dc6-8a38-a38c79249d8a/$NID
SRC=/tmp/lab-configs/configs/${NAME}.txt

echo "=== $NAME (node $NID): stop ==="
/opt/unetlab/wrappers/unl_wrapper -a stop -T 0 -F $LAB -D $NID 2>&1
sleep 3

echo "=== $NAME: wipe ==="
/opt/unetlab/wrappers/unl_wrapper -a wipe -T 0 -F $LAB -D $NID 2>&1
sleep 2

echo "=== $NAME: tmp after wipe ==="
ls -la $NDIR 2>/dev/null

echo "=== $NAME: refresh juniper.conf + startup-config from repo ==="
cp $SRC $NDIR/juniper.conf
cp $SRC $NDIR/startup-config
chown root:unl $NDIR/juniper.conf $NDIR/startup-config
chmod 0664 $NDIR/juniper.conf $NDIR/startup-config
ls -la $NDIR/juniper.conf $NDIR/startup-config

echo "=== $NAME: rebuild config.iso from juniper.conf ==="
ISODIR=/tmp/iso-build-$NID
rm -rf $ISODIR
mkdir -p $ISODIR
cp $NDIR/juniper.conf $ISODIR/juniper.conf
genisoimage -quiet -l -J -r -V config -o $NDIR/config.iso $ISODIR/
chown root:unl $NDIR/config.iso
chmod 0664 $NDIR/config.iso
ls -la $NDIR/config.iso

echo "=== $NAME: start ==="
/opt/unetlab/wrappers/unl_wrapper -a start -T 0 -F $LAB -D $NID 2>&1
echo "Done. Wait 2-3 min for vSRX boot + first commit."
