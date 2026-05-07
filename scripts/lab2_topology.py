#!/usr/bin/env python3
"""LAB-2 topology mutation: add 4 Cisco CEs (ACDC/SWANS/SEPULTURA/NIN), a
FreeBSD host, the matching networks (PE4<->CE bridges, 7206VXR<->FreeBSD
trunk), and the extra interface slots on PE4 (PA-2FE-TX in slots 4 and 5)
and 7206VXR (PA-FE-TX in slot 4) to the .unl XML.

Idempotent: if any of the additions already exist, they are skipped.
Backs up to .unl.bak.<epoch> before writing.
"""
import re, time, os, sys, shutil

LAB_FILE = "/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl"

# (id, name, x, y)
NEW_CISCO_CE = [
    (14, "ACDC",      900,  720),
    (15, "SWANS",     1000, 720),
    (16, "SEPULTURA", 1100, 720),
    (17, "NIN",       1200, 720),
]

FREEBSD_NODE_ID   = 18
FREEBSD_NAME      = "freebsd13"
FREEBSD_X, FREEBSD_Y = 80, 660

# (id, name, x, y) - new bridges
NEW_BRIDGES = [
    (17, "net-pe4-acdc",      870,  680),
    (18, "net-pe4-swans",     970,  680),
    (19, "net-pe4-sepultura", 1070, 680),
    (20, "net-pe4-nin",       1170, 680),
    (21, "net-gw-freebsd",    150,  600),
]

# PE4 = node id 7. Add slots 4+5 (PA-2FE-TX) and interfaces 64,65,80,81.
PE4_NEW_SLOTS = [
    (4, "PA-2FE-TX"),
    (5, "PA-2FE-TX"),
]
PE4_NEW_IFACES = [
    (64, "fa4/0", 17),  # to ACDC
    (65, "fa4/1", 18),  # to SWANS
    (80, "fa5/0", 19),  # to SEPULTURA
    (81, "fa5/1", 20),  # to NIN
]

# 7206VXR = node id 1. Add slot 4 (PA-FE-TX), interface 64 (fa4/0) to FreeBSD trunk.
GW_NEW_SLOTS = [(4, "PA-FE-TX")]
GW_NEW_IFACES = [(64, "fa4/0", 21)]


def make_cisco_ce_node_xml(nid, name, x, y, network_id):
    return (
        f'      <node id="{nid}" name="{name}" type="dynamips" template="c7200" '
        f'image="c7200-adventerprisek9-mz.152-4.S2.image" idlepc="0x62f21000" '
        f'nvram="128" ram="256" console="" delay="0" icon="Router.png" '
        f'config="1" left="{x}" top="{y}">\n'
        f'        <interface id="0" name="fa0/0" type="ethernet" network_id="{network_id}"/>\n'
        f'      </node>\n'
    )


def make_freebsd_node_xml():
    return (
        f'      <node id="{FREEBSD_NODE_ID}" name="{FREEBSD_NAME}" type="qemu" '
        f'template="freebsd" image="freebsd-13.5" console="telnet" '
        f'cpu="2" cpulimit="1" ram="2048" ethernet="2" '
        f'qemu_options="-machine type=pc,accel=kvm -nographic -no-user-config -nodefaults -rtc base=utc -serial mon:stdio" '
        f'qemu_version="2.12.0" qemu_arch="x86_64" qemu_nic="e1000-82545em" '
        f'delay="0" icon="Server.png" config="0" left="{FREEBSD_X}" top="{FREEBSD_Y}">\n'
        f'        <interface id="0" name="em0" type="ethernet" network_id="1"/>\n'
        f'        <interface id="1" name="em1" type="ethernet" network_id="21"/>\n'
        f'      </node>\n'
    )


def make_bridge_xml(bid, name, x, y):
    return (
        f'      <network id="{bid}" type="bridge" name="{name}" '
        f'left="{x}" top="{y}" visibility="0" icon="lan.png"/>\n'
    )


def insert_into_node(xml: str, node_id: int, new_slots, new_ifaces) -> str:
    """Add slot/interface entries inside an existing <node id="N">...</node>."""
    pat = re.compile(rf'(<node id="{node_id}"[^>]*>)(.*?)(</node>)', re.DOTALL)
    m = pat.search(xml)
    if not m:
        raise RuntimeError(f"node id={node_id} not found")
    open_tag, body, close_tag = m.group(1), m.group(2), m.group(3)

    add_slots = ""
    for sid, mod in new_slots:
        if re.search(rf'<slot id="{sid}"', body):
            continue
        add_slots += f'        <slot id="{sid}" module="{mod}"/>\n'

    add_ifaces = ""
    for iid, ifname, netid in new_ifaces:
        if re.search(rf'<interface id="{iid}"', body):
            continue
        add_ifaces += f'        <interface id="{iid}" name="{ifname}" type="ethernet" network_id="{netid}"/>\n'

    if not add_slots and not add_ifaces:
        return xml  # already updated, idempotent

    # Slots come before interfaces in the existing pattern.
    # Find the first <interface> in body and insert slots before it; then append ifaces at end of body.
    iface_match = re.search(r'(\s*)<interface id=', body)
    if iface_match and add_slots:
        ins_at = iface_match.start(1) + 1  # after the leading whitespace newline
        body = body[:ins_at] + add_slots + body[ins_at:]
    elif add_slots:
        body = body + add_slots
    if add_ifaces:
        body = body.rstrip() + "\n" + add_ifaces + "      "

    return xml[:m.start()] + open_tag + body + close_tag + xml[m.end():]


def main():
    if not os.path.exists(LAB_FILE):
        print(f"ERROR: {LAB_FILE} not found", file=sys.stderr); sys.exit(2)
    backup = f"{LAB_FILE}.bak.{int(time.time())}"
    shutil.copy(LAB_FILE, backup)
    print(f"  backup -> {backup}")

    with open(LAB_FILE) as f:
        xml = f.read()

    # 1. Add new bridges (idempotent)
    for bid, name, x, y in NEW_BRIDGES:
        if re.search(rf'<network id="{bid}"', xml):
            print(f"  bridge id={bid} {name}: already present")
            continue
        # Insert before </networks>
        new = make_bridge_xml(bid, name, x, y)
        xml = re.sub(r'(\s*</networks>)', new + r'\1', xml, count=1)
        print(f"  + bridge id={bid} {name}")

    # 2. Add new Cisco CE nodes (each connected to its bridge)
    for (nid, name, x, y), (bid, _, _, _, _) in zip(
        NEW_CISCO_CE,
        [(b[0], b[1], b[2], b[3], None) for b in NEW_BRIDGES[:4]]
    ):
        if re.search(rf'<node id="{nid}"', xml):
            print(f"  node id={nid} {name}: already present")
            continue
        new = make_cisco_ce_node_xml(nid, name, x, y, bid)
        xml = re.sub(r'(\s*</nodes>)', new + r'\1', xml, count=1)
        print(f"  + node id={nid} {name} -> bridge {bid}")

    # 3. Add FreeBSD node
    if re.search(rf'<node id="{FREEBSD_NODE_ID}"', xml):
        print(f"  node id={FREEBSD_NODE_ID} freebsd13: already present")
    else:
        new = make_freebsd_node_xml()
        xml = re.sub(r'(\s*</nodes>)', new + r'\1', xml, count=1)
        print(f"  + node id={FREEBSD_NODE_ID} {FREEBSD_NAME}")

    # 4. Add new slots/interfaces to PE4 (id=7)
    xml = insert_into_node(xml, 7, PE4_NEW_SLOTS, PE4_NEW_IFACES)
    print("  + PE4 slot 4/5 (PA-2FE-TX) + 4 interfaces")

    # 5. Add new slot/interface to 7206VXR (id=1)
    xml = insert_into_node(xml, 1, GW_NEW_SLOTS, GW_NEW_IFACES)
    print("  + 7206VXR slot 4 (PA-FE-TX) + fa4/0 -> bridge 21")

    with open(LAB_FILE, "w") as f:
        f.write(xml)
    print(f"  wrote {LAB_FILE} ({os.path.getsize(LAB_FILE)} bytes)")


if __name__ == "__main__":
    main()
