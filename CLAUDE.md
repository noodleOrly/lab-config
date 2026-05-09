# lab-config — Claude Code Project Context

Source-of-truth configs and deploy tooling for a 22-node EVE-NG lab (`IRIS_BGP_ISIS_Lab.unl`).
Edit `configs/*.txt` here, sync to the EVE-NG host, optionally live-apply or wipe-and-reload.

## Topology

22 nodes, four platform families:

| Role | Devices | Platform | Image |
|---|---|---|---|
| Gateway / PE for FreeBSD | 7206VXR | Cisco c7200 (dynamips) | IOS 15.2(4)S2 adv-ent |
| PE / P | PE1-5 | Cisco c7200 (dynamips) | same |
| MikroTik CPE | CPE1-5 | MikroTik CHR (qemu) | RouterOS 7.7 |
| Cisco CE for VRF | ACDC, SWANS, SEPULTURA, NIN | Cisco c7200 (dynamips) | same |
| Customer branch site | ACDC_SITE_A/B, SWANS_SITE_A/B | MikroTik CHR (qemu) | RouterOS 7.7 |
| Route reflector | RR1, RR2 | Juniper vSRX-NG (qemu) | Junos 22.2R1 |
| Customer host | freebsd13 | FreeBSD 13.5 (qemu) | RELEASE-amd64 cloud image |

- ISIS area `49.0001`, level-2-only, metric-style wide. New CE NETs: `49.0001.0000.AC10.150X.00` (X = 1..4)
- iBGP AS 65001; RR1 reflects to PE1/PE2/PE3 + 7206VXR, RR2 reflects to PE3/PE4/PE5 + 7206VXR (PE3 and 7206VXR dual-homed); RR1 ↔ RR2 cluster-peer through 7206VXR
- BGP families: `ipv4-unicast` (existing) **and** `vpnv4-unicast` (LAB-2). RRs reflect both to all clients except the MikroTik CPEs.
- MPLS LDP on every IS-IS interface in the Cisco core (7206VXR, PE1-5, plus the 4 new Cisco CEs). LDP router-id from `Loopback0`.
- Loopbacks:
  - PEs `172.16.10.{1..5}/32`, MikroTik CPEs `172.16.20.{1..5}/32` (statically redistributed by their PE — RouterOS base has no IS-IS)
  - RRs `172.16.254.{1,2}/32`, 7206VXR `172.16.254.254/32`
  - **New CEs `172.16.21.{1..4}/32`** (in IS-IS via direct adjacency to PE4); each CE also has `Loopback100 192.168.100.1/24` not in IS-IS, only reachable through the matching VRF
- Interconnects: core ISIS /30s on `10.0.0.0/24` and `10.0.1.0/24`, PE↔MikroTik-CPE /30s on `10.0.2.0/24`. **New PE4↔CE links use `10.0.21.0/24` (global VLAN 10) and `10.0.22.0/24` (per-VRF VLAN 20).**
- 7206VXR ↔ FreeBSD trunk (fa4/0): VLANs 1803/1804/1805/1806 carry `100.112.1.0/28` (one /30 per VRF)
- All nodes ship syslog to `10.2.0.114` and SNMP community `public RO`

### MPLS L3VPN customer mapping (LAB-2)

| Customer | VLAN (FreeBSD↔7206VXR) | RD / RT | 7206VXR sub-int | FreeBSD FIB | PE4 ↔ CE physical | CE Lo0 | CE Lo100 |
|---|---|---|---|---|---|---|---|
| ACDC | 1803 | 65001:1803 | fa4/0.1803 (100.112.1.1/30) | 2 | fa4/0 ↔ ACDC fa0/0 | 172.16.21.1 | 192.168.100.1/24 |
| SWANS | 1804 | 65001:1804 | fa4/0.1804 (100.112.1.5/30) | 3 | fa4/1 ↔ SWANS fa0/0 | 172.16.21.2 | 192.168.100.1/24 |
| SEPULTURA | 1805 | 65001:1805 | fa4/0.1805 (100.112.1.9/30) | 4 | fa5/0 ↔ SEPULTURA fa0/0 | 172.16.21.3 | 192.168.100.1/24 |
| NIN | 1806 | 65001:1806 | fa4/0.1806 (100.112.1.13/30) | 5 | fa5/1 ↔ NIN fa0/0 | 172.16.21.4 | 192.168.100.1/24 |

Each PE4↔CE link is a single physical port carrying 802.1Q with two sub-interfaces:
- **VLAN 10 (global)**: `10.0.21.X/30`, IS-IS adjacency, MPLS LDP — carries CE `Lo0` advertisement and label distribution.
- **VLAN 20 (per-VRF)**: `10.0.22.X/30`, no IGP — carries customer traffic; PE4 has a per-VRF static `192.168.100.0/24 → 10.0.22.X+1`. CE has a global default `0.0.0.0/0 → 10.0.22.X` so reply traffic to 100.112.1.0/28 (FreeBSD) leaves via the VRF path.

### Customer branch sites (LAB-3)

ACDC and SWANS each host two MikroTik CHR sites on a fresh PA-2FE-TX in slot 1 (`fa1/0` + `fa1/1`). The sites are pure CPEs — no MPLS, no IS-IS, just a default route back to the parent CE.

| Site | Parent CE | PE-CE link | Site LAN |
|---|---|---|---|
| ACDC_SITE_A | ACDC fa1/0 | 10.100.0.0/30 (.1=ACDC, .2=site) | 192.168.101.0/24 (lo .1) |
| ACDC_SITE_B | ACDC fa1/1 | 10.100.0.4/30 (.5=ACDC, .6=site) | 192.168.102.0/24 (lo .1) |
| SWANS_SITE_A | SWANS fa1/0 | 10.101.0.0/30 (.1=SWANS, .2=site) | 192.168.103.0/24 (lo .1) |
| SWANS_SITE_B | SWANS fa1/1 | 10.101.0.4/30 (.5=SWANS, .6=site) | 192.168.104.0/24 (lo .1) |

Site LANs are reachable from the matching customer VRF on FreeBSD (`setfib 2 ping 192.168.101.1`) via two static routes hop-by-hop:
- PE4 in VRF: `ip route vrf ACDC 192.168.10X.0/24 10.0.22.2` (next-hop = ACDC's VLAN-20 customer side)
- ACDC in global: `ip route 192.168.10X.0/24 10.100.0.{2,6}` (next-hop = site's ether1)

Same pattern for SWANS via `10.0.22.6` and `10.101.0.{2,6}`.

## Hosts and access

| Host | Address | OS | Purpose |
|---|---|---|---|
| EVE-NG | `root@10.2.0.147` | Ubuntu 20.04 + EVE-NG | Lab hypervisor |
| Syslog target | `10.2.0.114` | — | Lab nodes ship syslog here |

```bash
# From this Mac (direct, no jump host):
ssh -i ~/.ssh/id_irisdce root@10.2.0.147
```

GitHub access from this Mac uses SSH-over-443 (port 22 is firewalled). Remote URL is `ssh://git@ssh.github.com:443/noodleOrly/lab-config.git`.

## EVE-NG paths

- Lab XML (canonical store): `/opt/unetlab/labs/IRIS_BGP_ISIS_Lab.unl` — contains 13 base64-encoded `<config id="N">` blocks
- Lab UUID: `04fce5a2-b313-4dc6-8a38-a38c79249d8a`
- Per-node runtime tree: `/opt/unetlab/tmp/0/<uuid>/<id>/`
  - Cisco dynamips: `startup-config` (fed via `-C startup-config`), NVRAM/disk images
  - Junos qemu: `juniper.conf` + `config.iso` (cloud-init mounts iso at first boot), `virtioa.qcow2`
  - MikroTik qemu: `startup-config`, `hda.qcow2`
- Console telnet ports: `32768 + node_id` on `127.0.0.1` of the EVE-NG host

| ID | Name | Port | ID | Name | Port |
|---|---|---|---|---|---|
| 1 | 7206VXR | 32769 | 12 | CPE4 | 32780 |
| 2 | RR1 | 32770 | 13 | CPE5 | 32781 |
| 3 | RR2 | 32771 | 14 | ACDC | 32782 |
| 4 | PE1 | 32772 | 15 | SWANS | 32783 |
| 5 | PE2 | 32773 | 16 | SEPULTURA | 32784 |
| 6 | PE3 | 32774 | 17 | NIN | 32785 |
| 7 | PE4 | 32775 | 18 | freebsd13 | 32786 |
| 8 | PE5 | 32776 | 19 | ACDC_SITE_A | 32787 |
| 9 | CPE1 | 32777 | 20 | ACDC_SITE_B | 32788 |
| 10 | CPE2 | 32778 | 21 | SWANS_SITE_A | 32789 |
| 11 | CPE3 | 32779 | 22 | SWANS_SITE_B | 32790 |

## Credentials (lab-only)

- Cisco IOS: enable secret `lab`, vty `lab`, console at priv 15
- MikroTik: `admin / lab123`
- Junos: `admin / lab123` (and `root / lab123` after first commit) — stored as `encrypted-password "$6$junoslab$..."`
- FreeBSD: `root / lab123` is the lab-default. The running host has been renamed to `dev-mario-vpoll-01.cornelissen.co.za` and re-keyed for routine SSH access — use `ssh -i ~/.ssh/id_vpoller iris@10.2.0.139` (this is the path `scripts/lab3_verify.sh` uses).

## Deploy workflow

Source of truth is `configs/*.txt`. The scripts live in `scripts/` and run **on the EVE-NG host** (paths reference `/opt/unetlab/...`).

```bash
# 1. Stage configs on EVE-NG
tar -czf /tmp/lab-configs.tgz -C . configs/
scp -i ~/.ssh/id_irisdce /tmp/lab-configs.tgz root@10.2.0.147:/tmp/
ssh -i ~/.ssh/id_irisdce root@10.2.0.147 \
  "rm -rf /tmp/lab-configs && mkdir /tmp/lab-configs && cd /tmp/lab-configs && tar -xzf /tmp/lab-configs.tgz"

# 2. Sync repo into EVE-NG (writes tmp/<id>/startup-config + base64-replaces <config id> in .unl)
ssh -i ~/.ssh/id_irisdce root@10.2.0.147 "python3 /tmp/sync_eve_configs.py"

# 3a. Cisco / MikroTik: live-apply via console — running config picks it up immediately
ssh -i ~/.ssh/id_irisdce root@10.2.0.147 "python3 /tmp/live_apply.py"

# 3b. Junos: stop + wipe + start so cloud-init reloads juniper.conf from config.iso
ssh -i ~/.ssh/id_irisdce root@10.2.0.147 "/tmp/rr_reset.sh 2 RR1"   # or 3 RR2 — takes ~6 min for boot + commit
```

Scripts have hard-coded `LAB_UUID` / `LAB_FILE` — update these for any other lab.

## Per-platform constraints (gotchas — keep in mind when editing configs)

### Cisco c7200 / IOS 15.2(4)S2 advanced enterprise
- **No LLDP** on this image — `lldp run` returns "Invalid input". CDP is default-on; explicit `cdp run` retained in startup-configs for clarity.
- Warm-boot persistence: `wr mem` writes NVRAM. Cold-boot / Wipe re-reads `<config>` from `.unl` — use `sync_eve_configs.py` to make repo edits survive a Wipe.

### Juniper vSRX-NG / Junos 22.2R1
- **Use `encrypted-password "$6$..."`, not `plain-text-password-value`** — the latter is silently dropped at commit, leaving the surrounding `user { ... }` block ineffective and admin never created. Hash with `openssl passwd -6 -salt junoslab lab123`.
- **`isis` is not valid in `host-inbound-traffic protocols`** — ISIS uses link-local OSI frames that bypass IP host-inbound. Only IP-based protocols belong here.
- **`lldp` in `host-inbound-traffic protocols` is silently dropped** — LLDP is L2 link-local. The top-level `protocols lldp interface all` is what enables it.
- **Intrazone trust→trust policy is required for inbound sessions to lo0** — `host-inbound-traffic { system-services { ping }; protocols { bgp } }` only governs the host-inbound check *after* a flow session is created. With no security policies, the default-deny blocks fresh inbound session creation, so packets reach lo0 on the wire but are silently dropped (no `show security flow session` entry). PE↔RR BGP works because the RR initiates outbound TCP and the SYN-ACK matches that session, but RR1↔RR2 BGP and ICMP need an explicit `from-zone trust to-zone trust permit-all` policy (kept in both RR configs).
- **VPNv4 RR without LDP needs `resolution-ribs inet.0` plus `keep all`** (LAB-2). By default Junos resolves VPNv4 next-hops in `inet.3` (LDP-populated). The vSRX RRs don't run LDP, so without `set routing-options resolution rib bgp.l3vpn.0 resolution-ribs inet.0` the routes land in `bgp.l3vpn.0` as Hidden / "Next hop type: Unusable" and aren't reflected. Also need `set protocols bgp group INTERNAL keep all` so routes whose RT doesn't match a local VRF aren't discarded. Both kept in `RR{1,2}.txt`.
- Cloud-init creates `<tmp>/<id>/.configured` when the first-boot commit completes — useful for polling. Boot+commit ≈ 6 min from `start`.

### EVE-NG host (Ubuntu 20.04 + EVE-NG)
- **`PA-2FE-TX` is not in the stock c7200 template or `__node.php` slot dispatcher** — `scripts/eve_setup.sh` patches both (idempotently). Required for PE4 in LAB-2 (two PA-2FE-TX cards in slots 4 and 5, four physical ports for the new Cisco CEs).
- Run `scripts/eve_setup.sh` once on the EVE-NG host before deploying LAB-2 topology. Without it, dynamips silently omits slots 4/5 and EVE-NG warns "invalid ethernet interface (20014)".
- libguestfs (`guestmount`/`guestfish`) currently fails on this host with "appliance closed connection" — kernel/qemu mismatch. FreeBSD qcow2 customisation falls back to first-boot console configuration.

### MikroTik CHR
- CDP/LLDP/MNDP via `/ip neighbor discovery-settings set protocol=cdp,lldp,mndp`. Default interface list (all non-dynamic) is fine.
- No IS-IS in base package — loopbacks are statically redistributed by the connected PE.

### FreeBSD 13.5 (qemu)
- Uses `e1000-82545em` NICs (overridden in `.unl` per-node so interfaces are `em0`/`em1`, not `vtnet*` from the global template).
- `/boot/loader.conf` must set `net.fibs="6"` so FIBs 2..5 (one per customer VRF) exist; default is 1.
- `/boot/loader.conf` also enables serial console (`boot_multicons="YES"`, `console="comconsole,vidconsole"`) so EVE-NG console-port automation works.
- Per-FIB default routes (`route_vlan1803default="default 100.112.1.1 -fib 2"` etc.) are how customer-bound traffic is steered to the right VRF; `setfib N` is how you choose at runtime.
- Image is **not** auto-injected by `sync_eve_configs.py`. Use `scripts/freebsd_inject.sh` (or first-boot console session) to apply `/etc/rc.conf`, `/boot/loader.conf`, etc., into the qcow2.
- **Known unresolved (LAB-2)**: `scripts/freebsd_inject.sh` relies on libguestfs which is broken on this EVE-NG host (see EVE-NG section). The qcow2 also defaults to vidconsole only, so the EVE-NG telnet console (port 32786) is silent on first boot. Workaround: connect to the FreeBSD VM via the EVE-NG web GUI's VNC viewer for the initial config session, then write `/boot/loader.conf` with `boot_multicons="YES"; console="comconsole,vidconsole"` and reboot — subsequent sessions go via serial.

## Known caveats
- LLDP has no neighbours in the lab today: the only LLDP-capable speakers (RRs, CPEs) aren't directly connected — they go through c7200 PEs which lack LLDP and don't relay it.
- Live device state can drift from `configs/*.txt` if anyone edits via console. Re-running `sync_eve_configs.py` + appropriate live-apply or wipe restores alignment.
