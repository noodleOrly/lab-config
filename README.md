# lab-config

EVE-NG lab `IRIS_BGP_ISIS_Lab` — 13 nodes, iBGP/IS-IS in AS 65001, with Cisco c7200 PEs, MikroTik CHR CPEs, and Juniper vSRX-NG route reflectors.

```
configs/                  # Per-device startup configs (Cisco IOS, RouterOS, Junos)
topology/
  IRIS_BGP_ISIS_Lab.unl   # EVE-NG lab XML (canonical store; <config> blocks are base64)
scripts/                  # Run these on the EVE-NG host
  sync_eve_configs.py     # Push configs/ → tmp/<id>/startup-config + .unl <config> base64
  rr_reset.sh             # Stop+wipe+start a Junos node so cloud-init reloads juniper.conf
  live_apply.py           # Console-driven CDP/LLDP push (Cisco / MikroTik / Junos)
```

See `CLAUDE.md` for topology details, EVE-NG paths, console port map, deploy workflow, credentials, and per-platform gotchas (Cisco c7200 IOS lacks LLDP; Junos drops `plain-text-password-value` and a couple of host-inbound-traffic entries silently).
