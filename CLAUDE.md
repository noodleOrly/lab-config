# lab-config — Claude Code Project Context

Source-of-truth configs and deploy tooling for a 13-node EVE-NG lab (`IRIS_BGP_ISIS_Lab.unl`).
Edit `configs/*.txt` here, sync to the EVE-NG host, optionally live-apply or wipe-and-reload.

## Topology

13 nodes, three platform families:

| Role | Devices | Platform | Image |
|---|---|---|---|
| Gateway | 7206VXR | Cisco c7200 (dynamips) | IOS 15.2(4)S2 adv-ent |
| PE | PE1-5 | Cisco c7200 (dynamips) | same |
| CPE | CPE1-5 | MikroTik CHR (qemu) | RouterOS 7.7 |
| Route reflector | RR1, RR2 | Juniper vSRX-NG (qemu) | Junos 22.2R1 |

- ISIS area `49.0001`, level-2-only, metric-style wide
- iBGP AS 65001; RR1 reflects to PE1/PE2/PE3, RR2 reflects to PE3/PE4/PE5 (PE3 dual-homed); RRs cluster-peer through 7206VXR
- Loopbacks: PEs `172.16.10.{1..5}/32`, CPEs `172.16.20.{1..5}/32` (statically redistributed by their PE — RouterOS base has no IS-IS), RRs `172.16.254.{1,2}/32`, 7206VXR `172.16.254.254/32`
- Interconnects: ISIS /30s on `10.0.0.0/24`, PE↔CPE /30s on `10.0.2.0/24`
- All nodes ship syslog to `10.2.0.114` and SNMP community `public RO`

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
| 1 | 7206VXR | 32769 | 8 | PE5 | 32776 |
| 2 | RR1 | 32770 | 9 | CPE1 | 32777 |
| 3 | RR2 | 32771 | 10 | CPE2 | 32778 |
| 4 | PE1 | 32772 | 11 | CPE3 | 32779 |
| 5 | PE2 | 32773 | 12 | CPE4 | 32780 |
| 6 | PE3 | 32774 | 13 | CPE5 | 32781 |
| 7 | PE4 | 32775 | | | |

## Credentials (lab-only)

- Cisco IOS: enable secret `lab`, vty `lab`, console at priv 15
- MikroTik: `admin / lab123`
- Junos: `admin / lab123` (and `root / lab123` after first commit) — stored as `encrypted-password "$6$junoslab$..."`

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
- Cloud-init creates `<tmp>/<id>/.configured` when the first-boot commit completes — useful for polling. Boot+commit ≈ 6 min from `start`.

### MikroTik CHR
- CDP/LLDP/MNDP via `/ip neighbor discovery-settings set protocol=cdp,lldp,mndp`. Default interface list (all non-dynamic) is fine.
- No IS-IS in base package — loopbacks are statically redistributed by the connected PE.

## Known caveats
- LLDP has no neighbours in the lab today: the only LLDP-capable speakers (RRs, CPEs) aren't directly connected — they go through c7200 PEs which lack LLDP and don't relay it.
- Live device state can drift from `configs/*.txt` if anyone edits via console. Re-running `sync_eve_configs.py` + appropriate live-apply or wipe restores alignment.
