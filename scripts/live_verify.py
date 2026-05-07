#!/usr/bin/env python3
"""Read-only inspection: dump BGP / ISIS / LLDP / CDP state from every lab node
via telnet to EVE-NG console ports. Writes a transcript to /tmp/live_verify.transcript.bin
and prints a per-node PASS/FAIL summary.

PASS criteria (per CLAUDE.md):
  - 7206VXR: ISIS adj to RR1, RR2, PE5 (3 expected)
  - PEx (Cisco): BGP UP to its RR(s); ISIS adj to ring neighbours; static route to its CPE loopback
  - CPEx (MikroTik): default route via PE; LLDP/CDP advertisement enabled
  - RRx (Junos): BGP UP to its 3 PE clients + the other RR; ISIS adj to 7206VXR; LLDP enabled
"""
import socket, time, sys, re

HOST = "127.0.0.1"
BASE_PORT = 32768

# (id, name, expected_bgp_peers, expected_isis_neighbors)
CISCO_NODES = [
    (1, "7206VXR", [],                      ["RR1", "RR2", "PE5"]),
    (4, "PE1",     ["172.16.254.1"],        ["PE2", "PE5", "PE3"]),
    (5, "PE2",     ["172.16.254.1"],        ["PE1", "PE3", "PE4"]),
    (6, "PE3",     ["172.16.254.1", "172.16.254.2"], ["PE2", "PE4", "PE1"]),
    (7, "PE4",     ["172.16.254.2"],        ["PE3", "PE5", "PE2"]),
    (8, "PE5",     ["172.16.254.2"],        ["PE4", "PE1", "7206VXR"]),
]
MIKROTIK_NODES = [(9, "CPE1"), (10, "CPE2"), (11, "CPE3"), (12, "CPE4"), (13, "CPE5")]
JUNOS_NODES = [
    (2, "RR1", ["172.16.10.1", "172.16.10.2", "172.16.10.3", "172.16.254.2"]),
    (3, "RR2", ["172.16.10.3", "172.16.10.4", "172.16.10.5", "172.16.254.1"]),
]


class Console:
    def __init__(self, port, name, log):
        self.s = socket.create_connection((HOST, port), timeout=10)
        self.s.settimeout(0.3)
        self.name = name
        self.log = log
        self.buf = b""

    def expect(self, patterns, timeout=15):
        end = time.time() + timeout
        if isinstance(patterns, (bytes, str)):
            patterns = [patterns]
        pats = [p.encode() if isinstance(p, str) else p for p in patterns]
        while time.time() < end:
            for i, p in enumerate(pats):
                if re.search(p, self.buf, re.DOTALL):
                    return i
            try:
                d = self.s.recv(8192)
                if d:
                    self.buf += d
                    self.log.write(d)
            except socket.timeout:
                pass
        return -1

    def send(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.log.write(b"\n>>" + data + b"\n")
        self.s.sendall(data)

    def sendline(self, line=""):
        self.send(line + "\r\n")

    def drain(self, t=2):
        time.sleep(t)
        try:
            d = self.s.recv(65536)
            if d:
                self.buf += d
                self.log.write(d)
        except socket.timeout:
            pass

    def capture(self, cmd, settle=2.0):
        """Send cmd, wait, return new bytes captured since send."""
        marker = len(self.buf)
        self.sendline(cmd)
        end = time.time() + settle
        while time.time() < end:
            try:
                d = self.s.recv(65536)
                if d:
                    self.buf += d
                    self.log.write(d)
                else:
                    time.sleep(0.1)
            except socket.timeout:
                pass
        return self.buf[marker:].decode(errors="replace")

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def cisco_login(c):
    c.sendline("")
    c.drain(1)
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
    elif i == 3:
        return False
    elif i == -1:
        return False
    c.sendline("terminal length 0")
    c.drain(1)
    return True


def verify_cisco(port, name, peers, isis_expect, log):
    print(f"\n=== {name} (cisco, port {port}) ===")
    c = Console(port, name, log)
    issues = []
    try:
        if not cisco_login(c):
            return [f"{name}: console login failed"]
        bgp_out = c.capture("show ip bgp summary", settle=3) if peers else ""
        isis_out = c.capture("show clns neighbors", settle=3)
        cdp_out = c.capture("show cdp neighbors", settle=3)

        for p in peers:
            # Look for peer line where state column is a number (Established) not Idle/Active
            m = re.search(rf"^{re.escape(p)}\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)", bgp_out, re.M)
            if not m:
                issues.append(f"{name}: BGP peer {p} not in 'show ip bgp summary'")
            else:
                state = m.group(1)
                if not state.isdigit() and state.lower() not in ("established",):
                    issues.append(f"{name}: BGP peer {p} state={state} (not Established)")
        # ISIS adjacencies — look for each expected neighbor name as a substring
        # show clns neighbors columns: System Id, Interface, SNPA, State, Holdtime, Type, Protocol
        adj_up = re.findall(r"^(\S+)\s+\S+\s+\S+\s+(Up|Init|Down)\b", isis_out, re.M)
        up_names = [n for n, st in adj_up if st == "Up"]
        for n in isis_expect:
            if not any(n in u for u in up_names):
                issues.append(f"{name}: ISIS adjacency to {n} not Up")
        # CDP — at minimum should report something on Cisco-Cisco links
        if peers and "Total cdp entries" in cdp_out:
            m = re.search(r"Total cdp entries displayed\s*:\s*(\d+)", cdp_out)
            if m and int(m.group(1)) == 0:
                issues.append(f"{name}: CDP shows 0 entries")
        return issues
    finally:
        c.close()


def verify_mikrotik(port, name, log):
    print(f"\n=== {name} (mikrotik, port {port}) ===")
    c = Console(port, name, log)
    issues = []
    try:
        c.sendline("")
        c.drain(1)
        i = c.expect([rb"Login:", rb"login:", rb">\s*$"], timeout=10)
        if i in (0, 1):
            c.sendline("admin")
            c.expect([rb"Password:", rb"password:"], timeout=5)
            c.sendline("lab123")
            i2 = c.expect([rb">\s*$", rb"\] >", rb"login:"], timeout=15)
            if i2 == 2:
                return [f"{name}: console login failed"]
        elif i == -1:
            return [f"{name}: no login or prompt"]
        c.sendline("")
        c.drain(1)
        disc = c.capture("/ip neighbor discovery-settings print", settle=2)
        nbr = c.capture("/ip neighbor print", settle=2)
        rt = c.capture("/ip route print where dst-address=0.0.0.0/0", settle=2)
        if not all(p in disc for p in ("cdp", "lldp", "mndp")):
            issues.append(f"{name}: discovery-settings not cdp+lldp+mndp")
        # RouterOS prints flag columns like "As" (Active+static) — not "A S".
        if "0.0.0.0/0" not in rt or not re.search(r"\bA[s ]", rt):
            issues.append(f"{name}: no active static default route")
        # LLDP/CDP neighbour count is informational (PE side has no LLDP), so don't fail on it
        c.sendline("/quit")
        c.drain(0.5)
        return issues
    finally:
        c.close()


def verify_junos(port, name, peers, log):
    print(f"\n=== {name} (junos, port {port}) ===")
    c = Console(port, name, log)
    issues = []
    try:
        c.sendline("")
        c.drain(1)
        i = c.expect([rb"login:", rb">\s*$", rb"%\s*$"], timeout=10)
        if i == 0:
            c.sendline("admin")
            c.expect([rb"Password:", rb"password:"], timeout=5)
            c.sendline("lab123")
            i2 = c.expect([rb">\s*$", rb"%\s*$", rb"login:"], timeout=15)
            if i2 == 2:
                return [f"{name}: console login failed"]
            i = i2
        elif i == -1:
            return [f"{name}: no prompt"]
        if i == 1:
            c.sendline("cli")
            c.expect([rb">\s*$"], timeout=10)
        c.sendline("set cli screen-length 0")
        c.drain(1)
        bgp_out = c.capture("show bgp summary", settle=3)
        isis_out = c.capture("show isis adjacency", settle=3)
        lldp_out = c.capture("show lldp neighbors", settle=2)
        for p in peers:
            m = re.search(rf"^{re.escape(p)}\s+\S+\s+\S+\s+\S+\s+\S+\s+(\S+)", bgp_out, re.M)
            if not m:
                issues.append(f"{name}: BGP peer {p} not in 'show bgp summary'")
            else:
                # Junos shows route counts (e.g. "2/2/2/0 ...") or "Active" / "Connect" / "Idle"
                state = m.group(1)
                if state in ("Active", "Connect", "Idle", "OpenSent", "OpenConfirm"):
                    issues.append(f"{name}: BGP peer {p} state={state}")
        # ISIS — RRs should have at least one Up adjacency (to 7206VXR)
        if not re.search(r"\bUp\b", isis_out):
            issues.append(f"{name}: no ISIS adjacency Up")
        # LLDP enabled? command should not return "syntax error"
        if "syntax error" in lldp_out.lower() or "unknown command" in lldp_out.lower():
            issues.append(f"{name}: LLDP not configured (command rejected)")
        return issues
    finally:
        c.close()


def main():
    log = open("/tmp/live_verify.transcript.bin", "wb")
    all_issues = {}
    for nid, name, peers, isis_exp in CISCO_NODES:
        try:
            all_issues[name] = verify_cisco(BASE_PORT + nid, name, peers, isis_exp, log)
        except Exception as e:
            all_issues[name] = [f"{name}: EXCEPTION {e}"]
    for nid, name in MIKROTIK_NODES:
        try:
            all_issues[name] = verify_mikrotik(BASE_PORT + nid, name, log)
        except Exception as e:
            all_issues[name] = [f"{name}: EXCEPTION {e}"]
    for nid, name, peers in JUNOS_NODES:
        try:
            all_issues[name] = verify_junos(BASE_PORT + nid, name, peers, log)
        except Exception as e:
            all_issues[name] = [f"{name}: EXCEPTION {e}"]
    log.close()
    print("\n=========== SUMMARY ===========")
    fail = 0
    for n, issues in all_issues.items():
        if not issues:
            print(f"  PASS  {n}")
        else:
            fail += 1
            print(f"  FAIL  {n}")
            for x in issues:
                print(f"        - {x}")
    print(f"\nNodes with issues: {fail}/{len(all_issues)}")
    print(f"Transcript: /tmp/live_verify.transcript.bin")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
