#!/usr/bin/env python3
"""Sync repo lab configs into EVE-NG: per-node tmp/startup-config + base64 in .unl XML."""
import base64, os, re, shutil, sys

LAB_UUID = "04fce5a2-b313-4dc6-8a38-a38c79249d8a"
LAB_FILE = "/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl"
TMP_BASE = f"/opt/unetlab/tmp/0/{LAB_UUID}"
SRC_DIR  = "/tmp/lab-configs/configs"

NODES = [
    (1,  "7206VXR.txt"),
    (2,  "RR1.txt"),
    (3,  "RR2.txt"),
    (4,  "PE1.txt"),
    (5,  "PE2.txt"),
    (6,  "PE3.txt"),
    (7,  "PE4.txt"),
    (8,  "PE5.txt"),
    (9,  "CPE1.txt"),
    (10, "CPE2.txt"),
    (11, "CPE3.txt"),
    (12, "CPE4.txt"),
    (13, "CPE5.txt"),
]

# 1) Update each tmp/<id>/startup-config
for nid, fname in NODES:
    src = os.path.join(SRC_DIR, fname)
    dst_dir = os.path.join(TMP_BASE, str(nid))
    dst = os.path.join(dst_dir, "startup-config")
    if not os.path.isdir(dst_dir):
        print(f"  SKIP node {nid}: {dst_dir} does not exist")
        continue
    shutil.copy(src, dst)
    # Permissions: original was root:unl 0664
    os.chmod(dst, 0o664)
    # chown root:unl
    import grp
    try:
        unl_gid = grp.getgrnam("unl").gr_gid
        os.chown(dst, 0, unl_gid)
    except KeyError:
        pass
    print(f"  wrote {dst} ({os.path.getsize(dst)} bytes)")

# 2) Update .unl XML <config id="N">...</config>
xml = open(LAB_FILE).read()
total_changes = 0
for nid, fname in NODES:
    raw = open(os.path.join(SRC_DIR, fname), "rb").read()
    b64 = base64.b64encode(raw).decode()
    pat = re.compile(rf'(<config id="{nid}">)[^<]*(</config>)', re.DOTALL)
    new_xml, n = pat.subn(rf'\g<1>{b64}\g<2>', xml)
    if n != 1:
        print(f"  WARN: {n} replacements for node {nid} (expected 1)")
    xml = new_xml
    total_changes += n

with open(LAB_FILE, "w") as f:
    f.write(xml)
print(f"  rewrote {LAB_FILE}: {total_changes} <config> blocks updated, {os.path.getsize(LAB_FILE)} bytes")

# Spot-check: decode PE1's new <config id="4"> and look for "lldp run"
m = re.search(r'<config id="4">([^<]+)</config>', open(LAB_FILE).read())
if m:
    decoded = base64.b64decode(m.group(1)).decode()
    print(f"  spot-check PE1 has 'lldp run': {'lldp run' in decoded}")
