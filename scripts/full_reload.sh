#!/bin/bash
# Wipe + reload every node from /tmp/lab-configs/configs/*.txt.
# Run on EVE-NG host AFTER sync_eve_configs.py has updated startup-configs and the .unl.
set -u
LAB=/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl
UUID=04fce5a2-b313-4dc6-8a38-a38c79249d8a
TMPBASE=/opt/unetlab/tmp/0/$UUID
SRCDIR=/tmp/lab-configs/configs

# id name txtname  (Junos nodes need iso rebuild)
CISCO=(  "1:7206VXR" "4:PE1" "5:PE2" "6:PE3" "7:PE4" "8:PE5"
         "14:ACDC" "15:SWANS" "16:SEPULTURA" "17:NIN" )
JUNOS=(  "2:RR1" "3:RR2" )
MTIK=(   "9:CPE1" "10:CPE2" "11:CPE3" "12:CPE4" "13:CPE5" )
# FreeBSD (id 18) is intentionally NOT wiped here -- it would erase the
# customised qcow2. To reset it, restage the image and re-run freebsd_inject.sh.
FREEBSD=( "18:freebsd13" )

stopwipe () {
    local nid=$1 name=$2
    echo "=== $name (node $nid): stop ==="
    /opt/unetlab/wrappers/unl_wrapper -a stop -T 0 -F $LAB -D $nid 2>&1 | tail -3
    sleep 2
    echo "=== $name: wipe ==="
    /opt/unetlab/wrappers/unl_wrapper -a wipe -T 0 -F $LAB -D $nid 2>&1 | tail -3
    sleep 1
}

stage_junos () {
    local nid=$1 name=$2
    local ndir=$TMPBASE/$nid
    local src=$SRCDIR/${name}.txt
    cp $src $ndir/juniper.conf
    cp $src $ndir/startup-config
    chown root:unl $ndir/juniper.conf $ndir/startup-config
    chmod 0664 $ndir/juniper.conf $ndir/startup-config
    local isodir=/tmp/iso-build-$nid
    rm -rf $isodir; mkdir -p $isodir
    cp $ndir/juniper.conf $isodir/juniper.conf
    genisoimage -quiet -l -J -r -V config -o $ndir/config.iso $isodir/
    chown root:unl $ndir/config.iso
    chmod 0664 $ndir/config.iso
    rm -rf $isodir
}

start () {
    local nid=$1 name=$2
    echo "=== $name: start ==="
    /opt/unetlab/wrappers/unl_wrapper -a start -T 0 -F $LAB -D $nid 2>&1 | tail -3
}

# Phase 1: stop+wipe everything
for entry in "${CISCO[@]}" "${JUNOS[@]}" "${MTIK[@]}"; do
    nid=${entry%%:*}; name=${entry##*:}
    stopwipe $nid $name
done

# Phase 2: re-stage Junos config (.iso + juniper.conf), Cisco/MikroTik already have startup-config from sync
for entry in "${JUNOS[@]}"; do
    nid=${entry%%:*}; name=${entry##*:}
    stage_junos $nid $name
done

# Phase 3: start everything (Cisco/Junos/MikroTik wiped+started, FreeBSD just started)
for entry in "${CISCO[@]}" "${JUNOS[@]}" "${MTIK[@]}" "${FREEBSD[@]}"; do
    nid=${entry%%:*}; name=${entry##*:}
    start $nid $name
    sleep 1
done

echo
echo "All 18 nodes started. Cisco/MikroTik converge in ~2 min, Junos ~6 min for cloud-init commit, FreeBSD ~1 min."
