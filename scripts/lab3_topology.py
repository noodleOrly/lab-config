#!/usr/bin/env python3
"""LAB-3 topology mutation: add 4 MikroTik CHR site routers (ACDC_SITE_A,
ACDC_SITE_B, SWANS_SITE_A, SWANS_SITE_B), the 4 matching bridges, and the
extra PA-2FE-TX slot on ACDC and SWANS so each can wire two sites off
fa1/0 and fa1/1.

Idempotent. Backs up the .unl before writing.
"""
import re, time, os, sys, shutil

LAB_FILE = "/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl"

# (id, name, uuid, x, y, parent-bridge-id)
# Names use underscores, not hyphens, to avoid EVE-NG node-name regex issues.
NEW_MTIK = [
    (19, "ACDC_SITE_A",  "a1b2c3d4-aaaa-1111-1111-111111111111", 900,  840, 22),
    (20, "ACDC_SITE_B",  "a1b2c3d4-aaaa-2222-2222-222222222222", 1000, 840, 23),
    (21, "SWANS_SITE_A", "a1b2c3d4-aaaa-3333-3333-333333333333", 1100, 840, 24),
    (22, "SWANS_SITE_B", "a1b2c3d4-aaaa-4444-4444-444444444444", 1200, 840, 25),
]

# (id, name, x, y) - new bridges connecting parent CE <-> site
NEW_BRIDGES = [
    (22, "net-acdc-site-a",  870,  790),
    (23, "net-acdc-site-b",  970,  790),
    (24, "net-swans-site-a", 1070, 790),
    (25, "net-swans-site-b", 1170, 790),
]

# parent CE id, slot config (single PA-2FE-TX in slot 1) and the two
# interfaces 16=fa1/0, 17=fa1/1 connected to the matching bridges.
PARENT_CE = [
    # (node_id, name, [(slot_id, module)], [(if_id, if_name, network_id), ...])
    (14, "ACDC",  [(1, "PA-2FE-TX")], [(16, "fa1/0", 22), (17, "fa1/1", 23)]),
    (15, "SWANS", [(1, "PA-2FE-TX")], [(16, "fa1/0", 24), (17, "fa1/1", 25)]),
]


def make_mtik_node_xml(nid, name, uuid, x, y, network_id):
    """Mirror the existing CPE pattern (CPE1 = id 9). MikroTik CHR 7.7,
    e1000-82545em NICs, 4 NICs by default (we only wire ether1)."""
    return (
        f'      <node id="{nid}" name="{name}" type="qemu" template="mikrotik" '
        f'image="mikrotik-chr-7.7" console="telnet" cpu="1" cpulimit="1" '
        f'ram="256" ethernet="4" uuid="{uuid}" '
        f'qemu_options="-machine type=pc,accel=kvm -serial mon:stdio -nographic '
        f'-no-user-config -nodefaults -display none -vga std -rtc base=utc" '
        f'qemu_version="2.12.0" qemu_arch="x86_64" qemu_nic="e1000-82545em" '
        f'delay="0" icon="Router.png" config="1" left="{x}" top="{y}">\n'
        f'        <interface id="0" name="ether1" type="ethernet" network_id="{network_id}"/>\n'
        f'      </node>\n'
    )


def make_bridge_xml(bid, name, x, y):
    return (
        f'      <network id="{bid}" type="bridge" name="{name}" '
        f'left="{x}" top="{y}" visibility="0" icon="lan.png"/>\n'
    )


def insert_into_node(xml: str, node_id: int, new_slots, new_ifaces) -> str:
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
        return xml

    iface_match = re.search(r'(\s*)<interface id=', body)
    if iface_match and add_slots:
        ins_at = iface_match.start(1) + 1
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

    # 1. New bridges
    for bid, name, x, y in NEW_BRIDGES:
        if re.search(rf'<network id="{bid}"', xml):
            print(f"  bridge id={bid} {name}: already present")
            continue
        new = make_bridge_xml(bid, name, x, y)
        xml = re.sub(r'(\s*</networks>)', new + r'\1', xml, count=1)
        print(f"  + bridge id={bid} {name}")

    # 2. New MikroTik nodes
    for nid, name, uuid, x, y, bid in NEW_MTIK:
        if re.search(rf'<node id="{nid}"', xml):
            print(f"  node id={nid} {name}: already present")
            continue
        new = make_mtik_node_xml(nid, name, uuid, x, y, bid)
        xml = re.sub(r'(\s*</nodes>)', new + r'\1', xml, count=1)
        print(f"  + node id={nid} {name} -> bridge {bid}")

    # 3. Add slot 1 PA-2FE-TX + fa1/0 + fa1/1 to ACDC and SWANS
    for nid, name, slots, ifaces in PARENT_CE:
        xml = insert_into_node(xml, nid, slots, ifaces)
        print(f"  + {name} slot 1 (PA-2FE-TX) + fa1/0 + fa1/1")

    # 4. Add empty <config id> blocks for new MikroTik nodes (sync_eve_configs needs these)
    for nid, name, *rest in NEW_MTIK:
        if re.search(rf'<config id="{nid}">', xml):
            print(f"  config block id={nid}: already present")
            continue
        block = f'      <config id="{nid}"></config>\n'
        xml = re.sub(r'(\s*</configs>)', block + r'\1', xml, count=1)
        print(f"  + config block id={nid}")

    with open(LAB_FILE, "w") as f:
        f.write(xml)
    print(f"  wrote {LAB_FILE} ({os.path.getsize(LAB_FILE)} bytes)")


if __name__ == "__main__":
    main()
