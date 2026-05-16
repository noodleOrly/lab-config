#!/usr/bin/env python3
"""LAB-4 topology mutation: add ACDC_HOST (FreeBSD node 23) behind ACDC_SITE_A.

Adds:
  - bridge 26  net-acdc-host-a
  - node 23    ACDC_HOST (FreeBSD 13.5, em0 -> bridge 26)
  - ether2 (interface id=1) on ACDC_SITE_A (node 19) -> bridge 26

No routing changes needed: PE4 VRF ACDC and ACDC already have static routes
for 192.168.101.0/24 pointing through the ACDC_SITE_A uplink.

Idempotent. Backs up the .unl before writing.
"""
import re, time, os, sys, shutil

LAB_FILE = "/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl"

NEW_BRIDGE = (26, "net-acdc-host-a", 870, 960)

NEW_FREEBSD = (
    23,
    "ACDC_HOST",
    "b5c6d7e8-dddd-2300-4c4b-000000000023",
    900, 960,
    26,
)


def make_freebsd_node_xml(nid, name, uuid, x, y, network_id):
    """Mirror node 18 (freebsd13) pattern. config=0: not auto-injected by
    sync_eve_configs.py; use scripts/acdc_host_inject.sh instead."""
    return (
        f'      <node id="{nid}" name="{name}" type="qemu" template="freebsd" '
        f'image="freebsd-13.5" console="telnet" cpu="2" cpulimit="1" '
        f'ram="2048" ethernet="1" uuid="{uuid}" '
        f'qemu_options="-machine type=pc,accel=kvm -no-user-config -nodefaults '
        f'-rtc base=utc -vga std -vnc :{nid},password '
        f'-monitor tcp:127.0.0.1:44{nid:02d},server,nowait -boot order=c" '
        f'qemu_version="2.12.0" qemu_arch="x86_64" qemu_nic="e1000-82545em" '
        f'delay="0" icon="Server.png" config="0" left="{x}" top="{y}">\n'
        f'        <interface id="0" name="em0" type="ethernet" network_id="{network_id}"/>\n'
        f'      </node>\n'
    )


def make_bridge_xml(bid, name, x, y):
    return (
        f'      <network id="{bid}" type="bridge" name="{name}" '
        f'left="{x}" top="{y}" visibility="0" icon="lan.png"/>\n'
    )


def add_interface_to_node(xml, node_id, iface_id, iface_name, network_id):
    pat = re.compile(rf'(<node id="{node_id}"[^>]*>)(.*?)(</node>)', re.DOTALL)
    m = pat.search(xml)
    if not m:
        raise RuntimeError(f"node id={node_id} not found")
    open_tag, body, close_tag = m.group(1), m.group(2), m.group(3)

    if re.search(rf'<interface id="{iface_id}"', body):
        return xml, False

    new_iface = (
        f'        <interface id="{iface_id}" name="{iface_name}" '
        f'type="ethernet" network_id="{network_id}"/>\n'
    )
    body = body.rstrip() + "\n" + new_iface + "      "
    return xml[:m.start()] + open_tag + body + close_tag + xml[m.end():], True


def main():
    if not os.path.exists(LAB_FILE):
        print(f"ERROR: {LAB_FILE} not found", file=sys.stderr)
        sys.exit(2)

    backup = f"{LAB_FILE}.bak.{int(time.time())}"
    shutil.copy(LAB_FILE, backup)
    print(f"  backup -> {backup}")

    with open(LAB_FILE) as f:
        xml = f.read()

    # 1. New bridge
    bid, bname, bx, by = NEW_BRIDGE
    if re.search(rf'<network id="{bid}"', xml):
        print(f"  bridge id={bid} {bname}: already present")
    else:
        new = make_bridge_xml(bid, bname, bx, by)
        xml = re.sub(r'(\s*</networks>)', new + r'\1', xml, count=1)
        print(f"  + bridge id={bid} {bname}")

    # 2. New FreeBSD node
    nid, name, uuid, x, y, bridge_id = NEW_FREEBSD
    if re.search(rf'<node id="{nid}"', xml):
        print(f"  node id={nid} {name}: already present")
    else:
        new = make_freebsd_node_xml(nid, name, uuid, x, y, bridge_id)
        xml = re.sub(r'(\s*</nodes>)', new + r'\1', xml, count=1)
        print(f"  + node id={nid} {name} -> bridge {bridge_id}")

    # 3. Wire ACDC_SITE_A ether2 (interface id=1) -> bridge 26
    xml, changed = add_interface_to_node(xml, 19, 1, "eth2", bid)
    if changed:
        print(f"  + ACDC_SITE_A interface id=1 (ether2) -> bridge {bid}")
    else:
        print(f"  ACDC_SITE_A ether2: already present")

    with open(LAB_FILE, "w") as f:
        f.write(xml)
    print(f"  wrote {LAB_FILE} ({os.path.getsize(LAB_FILE)} bytes)")


if __name__ == "__main__":
    main()
