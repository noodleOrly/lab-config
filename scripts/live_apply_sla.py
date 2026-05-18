#!/usr/bin/env python3
"""Live-apply IP SLA config to PE1-PE5 and ACDC via EVE-NG console telnet.

Connects to each node's console port, enters conf t, pushes the full SLA
block, exits and saves. Run on the EVE-NG host after sync_eve_configs.py.

Usage:
  python3 live_apply_sla.py [PE1|PE2|PE3|PE4|PE5|ACDC ...]  # subset
  python3 live_apply_sla.py                                   # all
"""
import socket, time, sys, re, subprocess

HOST = "127.0.0.1"
BASE_PORT = 32768


def node_console_port(nid):
    try:
        out = subprocess.check_output(['ps', 'aux'], text=True)
        for line in out.splitlines():
            if f' -D {nid} ' in line and ('qemu_wrapper' in line or 'dynamips_wrapper' in line):
                m = re.search(r'-C (\d+)', line)
                if m:
                    return int(m.group(1))
    except Exception:
        pass
    return BASE_PORT + nid

LO  = {1: "172.16.10.1", 2: "172.16.10.2", 3: "172.16.10.3",
       4: "172.16.10.4", 5: "172.16.10.5"}
ACDC_LO = "172.16.21.1"


def _core_sla(src_n):
    lines = ["ip sla responder"]
    for dst_n in range(1, 6):
        if dst_n == src_n:
            continue
        echo    = src_n * 10 + dst_n
        jitter  = 1000 + echo
        dst_ip  = LO[dst_n]
        src_ip  = LO[src_n]
        lines += [
            f"ip sla {echo}",
            f" icmp-echo {dst_ip} source-interface Loopback0",
            f" description CORE-PE{src_n} - CORE-PE{dst_n} ECHO",
            " frequency 60",
            f"ip sla schedule {echo} life forever start-time now",
            f"ip sla {jitter}",
            f" udp-jitter {dst_ip} 5000 source-ip {src_ip} num-packets 20",
            f" description CORE-PE{src_n} - CORE-PE{dst_n} JITTER",
            " frequency 60",
            f"ip sla schedule {jitter} life forever start-time now",
        ]
    lines += [
        "ip sla 600",
        f" icmp-echo {ACDC_LO} source-interface Loopback0",
        f" description CUST-ACDC-PE{src_n} - CUST-ACDC ECHO",
        " frequency 60",
        "ip sla schedule 600 life forever start-time now",
        "ip sla 1600",
        f" udp-jitter {ACDC_LO} 5000 source-ip {LO[src_n]} num-packets 20",
        f" description CUST-ACDC-PE{src_n} - CUST-ACDC JITTER",
        " frequency 60",
        "ip sla schedule 1600 life forever start-time now",
    ]
    return lines


def _acdc_sla():
    lines = ["ip sla responder"]
    for pe_n in range(1, 6):
        echo   = 500 + pe_n
        jitter = 1500 + pe_n
        pe_ip  = LO[pe_n]
        lines += [
            f"ip sla {echo}",
            f" icmp-echo {pe_ip} source-interface Loopback0",
            f" description CUST-ACDC - CUST-ACDC-PE{pe_n} ECHO",
            " frequency 60",
            f"ip sla schedule {echo} life forever start-time now",
            f"ip sla {jitter}",
            f" udp-jitter {pe_ip} 5000 source-ip {ACDC_LO} num-packets 20",
            f" description CUST-ACDC - CUST-ACDC-PE{pe_n} JITTER",
            " frequency 60",
            f"ip sla schedule {jitter} life forever start-time now",
        ]
    return lines


ALL_NODES = [
    (4,  "PE1",  _core_sla(1)),
    (5,  "PE2",  _core_sla(2)),
    (6,  "PE3",  _core_sla(3)),
    (7,  "PE4",  _core_sla(4)),
    (8,  "PE5",  _core_sla(5)),
    (14, "ACDC", _acdc_sla()),
]


class Console:
    def __init__(self, port, name):
        self.s = socket.create_connection((HOST, port), timeout=10)
        self.s.settimeout(0.3)
        self.name = name
        self.buf  = b""

    def _read(self, t=0.5):
        end = time.time() + t
        while time.time() < end:
            try:
                d = self.s.recv(8192)
                if not d:
                    break
                self.buf += d
            except socket.timeout:
                pass

    def expect(self, patterns, timeout=15):
        end = time.time() + timeout
        pats = [p.encode() if isinstance(p, str) else p
                for p in ([patterns] if isinstance(patterns, (str, bytes)) else patterns)]
        while time.time() < end:
            for i, p in enumerate(pats):
                if re.search(p, self.buf, re.DOTALL):
                    return i
            try:
                d = self.s.recv(8192)
                if d:
                    self.buf += d
            except socket.timeout:
                pass
        return -1

    def sendline(self, line=""):
        self.s.sendall((line + "\r\n").encode())

    def drain(self, t=0.5):
        time.sleep(t)
        self._read(0.2)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def apply_node(nid, name, sla_lines):
    port = node_console_port(nid)
    print(f"\n=== {name} (port {port}) ===")
    c = Console(port, name)
    try:
        c.sendline("")
        c.drain(0.5)
        c.sendline("")
        i = c.expect([rb"#\s*$", rb">\s*$", rb"Press RETURN", rb"Username:"], timeout=8)
        if i == 2:
            c.sendline("")
            c.drain(2)
            i = c.expect([rb"#\s*$", rb">\s*$"], timeout=8)
        if i == 1:
            c.sendline("enable")
            c.expect([rb"Password:", rb"#\s*$"], timeout=5)
            if b"Password:" in c.buf[-200:]:
                c.sendline("lab")
                c.expect([rb"#\s*$"], timeout=5)
        elif i == -1:
            print(f"  no prompt; tail: {c.buf[-200:]!r}")
            return False

        c.sendline("terminal length 0")
        c.drain(0.5)
        c.sendline("configure terminal")
        if c.expect([rb"\(config\)#"], timeout=5) == -1:
            print("  conf t timed out")
            return False

        for line in sla_lines:
            c.sendline(line)
            c.drain(0.04)

        c.sendline("end")
        c.expect([rb"#\s*$"], timeout=5)
        c.sendline("write memory")
        i = c.expect([rb"\[OK\]", rb"Building configuration", rb"Overwrite"], timeout=25)
        if i == 2:
            c.sendline("")
            c.expect([rb"\[OK\]"], timeout=20)
        c.expect([rb"#\s*$"], timeout=15)

        c.sendline("show ip sla summary")
        c.drain(2)
        tail = c.buf[-1500:].decode(errors="replace")
        sla_ids = re.findall(r'^\s*(\d+)\s', tail, re.MULTILINE)
        print(f"  SLAs in summary: {', '.join(sla_ids) if sla_ids else '(none visible)'}")
        c.sendline("show ip sla responder")
        c.drain(1)
        resp_tail = c.buf[-400:].decode(errors="replace")
        print(f"  responder: {'enabled' if 'Enabled' in resp_tail else 'check manually'}")
        return bool(sla_ids)
    finally:
        c.close()


def main():
    filter_names = {a.upper() for a in sys.argv[1:]}
    nodes = [(nid, name, lines) for nid, name, lines in ALL_NODES
             if not filter_names or name.upper() in filter_names]
    if not nodes:
        print("No matching nodes. Available: PE1 PE2 PE3 PE4 PE5 ACDC")
        sys.exit(1)

    results = {}
    for nid, name, lines in nodes:
        try:
            results[name] = apply_node(nid, name, lines)
        except Exception as e:
            print(f"  {name}: EXCEPTION {e}")
            results[name] = False

    print("\n=== SUMMARY ===")
    for n, ok in results.items():
        print(f"  {'OK  ' if ok else 'FAIL'}  {n}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
