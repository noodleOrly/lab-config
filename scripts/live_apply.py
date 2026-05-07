#!/usr/bin/env python3
"""Live-apply CDP/LLDP to running lab nodes via telnet to EVE-NG console ports.
Idempotent: re-running is safe.
"""
import socket, time, sys, re

HOST = "127.0.0.1"
BASE_PORT = 32768

CISCO_NODES   = [(1, "7206VXR"), (4, "PE1"), (5, "PE2"), (6, "PE3"), (7, "PE4"), (8, "PE5")]
MIKROTIK_NODES = [(9, "CPE1"), (10, "CPE2"), (11, "CPE3"), (12, "CPE4"), (13, "CPE5")]
JUNOS_NODES    = [(2, "RR1"), (3, "RR2")]

class Console:
    def __init__(self, port, name, log):
        self.s = socket.create_connection((HOST, port), timeout=10)
        self.s.settimeout(0.3)
        self.name = name
        self.log = log
        self.buf = b""

    def read_a_bit(self, t=0.5):
        end = time.time() + t
        while time.time() < end:
            try:
                d = self.s.recv(8192)
                if not d:
                    break
                self.buf += d
            except socket.timeout:
                pass
        return self.buf

    def expect(self, patterns, timeout=15):
        """Wait until any pattern (regex bytes) appears in buffer or timeout."""
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
            except socket.timeout:
                pass
        return -1

    def send(self, data):
        if isinstance(data, str):
            data = data.encode()
        self.log.write(b">> " + data + b"\n")
        self.s.sendall(data)

    def sendline(self, line=""):
        self.send(line + "\r\n")

    def drain(self, t=2):
        time.sleep(t)
        self.read_a_bit(0.2)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def apply_cisco(port, name, log):
    print(f"\n=== {name} (cisco, port {port}) ===")
    c = Console(port, name, log)
    try:
        c.sendline("")
        c.drain(1)
        c.sendline("")
        i = c.expect([rb"#\s*$", rb">\s*$", rb"Press RETURN", rb"Username:"], timeout=8)
        if i == 2:  # Press RETURN
            c.sendline("")
            c.drain(2)
            i = c.expect([rb"#\s*$", rb">\s*$"], timeout=8)
        if i == 1:  # user mode
            c.sendline("enable")
            c.expect([rb"Password:", rb"#\s*$"], timeout=5)
            if b"Password:" in c.buf[-200:]:
                c.sendline("lab")
                c.expect([rb"#\s*$"], timeout=5)
        elif i == 3:
            print(f"  {name}: at Username prompt — not handled")
            return False
        elif i == -1:
            print(f"  {name}: no prompt found, last buf tail: {c.buf[-200:]!r}")
            return False
        # Now at # prompt
        c.sendline("terminal length 0")
        c.drain(1)
        c.sendline("configure terminal")
        c.expect([rb"\(config\)#"], timeout=5)
        c.sendline("cdp run")
        c.drain(0.5)
        c.sendline("lldp run")
        c.drain(0.5)
        c.sendline("end")
        c.expect([rb"#\s*$"], timeout=5)
        c.sendline("write memory")
        # wait for [OK] or '#' again
        i = c.expect([rb"\[OK\]", rb"Building configuration"], timeout=20)
        c.expect([rb"#\s*$"], timeout=15)
        # quick verify
        c.sendline("show running-config | include ^(cdp|lldp) run")
        c.drain(2)
        tail = c.buf[-400:].decode(errors="replace")
        ok = ("cdp run" in tail) and ("lldp run" in tail)
        print(f"  {name}: cdp+lldp running = {ok}")
        return ok
    finally:
        c.close()


def apply_mikrotik(port, name, log):
    print(f"\n=== {name} (mikrotik, port {port}) ===")
    c = Console(port, name, log)
    try:
        c.sendline("")
        c.drain(1)
        i = c.expect([rb"Login:", rb"login:", rb">\s*$"], timeout=10)
        if i in (0, 1):
            c.sendline("admin")
            c.expect([rb"Password:", rb"password:"], timeout=5)
            c.sendline("lab123")
            i2 = c.expect([rb">\s*$", rb"\] >", rb"banner", rb"login:"], timeout=15)
            if i2 == 3:
                print(f"  {name}: login failed")
                return False
        elif i == -1:
            print(f"  {name}: no login or prompt; tail: {c.buf[-200:]!r}")
            return False
        # Skip any banner / wizard
        c.sendline("")
        c.drain(1)
        c.sendline("/ip neighbor discovery-settings set protocol=cdp,lldp,mndp")
        c.drain(2)
        c.sendline("/ip neighbor discovery-settings print")
        c.drain(2)
        tail = c.buf[-600:].decode(errors="replace")
        ok = ("cdp" in tail) and ("lldp" in tail) and ("mndp" in tail)
        print(f"  {name}: discovery has cdp+lldp+mndp = {ok}")
        # quit
        c.sendline("/quit")
        c.drain(0.5)
        return ok
    finally:
        c.close()


def apply_junos(port, name, log):
    print(f"\n=== {name} (junos, port {port}) ===")
    c = Console(port, name, log)
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
                print(f"  {name}: login failed")
                return False
            i = i2
        elif i == -1:
            print(f"  {name}: no prompt; tail: {c.buf[-200:]!r}")
            return False
        if i == 1:  # at shell %, enter cli
            c.sendline("cli")
            c.expect([rb">\s*$"], timeout=10)
        # at CLI operational mode '>'
        c.sendline("configure")
        c.expect([rb"#\s*$"], timeout=10)
        c.sendline("set protocols lldp interface all")
        c.drain(0.5)
        c.sendline("set security zones security-zone trust host-inbound-traffic protocols lldp")
        c.drain(0.5)
        c.sendline("commit and-quit")
        i3 = c.expect([rb"commit complete", rb"error", rb"failed"], timeout=60)
        c.expect([rb">\s*$"], timeout=15)
        ok = (i3 == 0)
        # verify
        c.sendline("show configuration protocols lldp")
        c.drain(2)
        tail = c.buf[-600:].decode(errors="replace")
        ok = ok and ("interface all" in tail)
        print(f"  {name}: lldp committed = {ok}")
        c.sendline("exit")
        c.drain(0.5)
        return ok
    finally:
        c.close()


def main():
    results = {}
    log = open("/tmp/live_apply.transcript.bin", "wb")
    for nid, name in CISCO_NODES:
        try:
            results[name] = apply_cisco(BASE_PORT + nid, name, log)
        except Exception as e:
            print(f"  {name}: EXCEPTION {e}")
            results[name] = False
    for nid, name in MIKROTIK_NODES:
        try:
            results[name] = apply_mikrotik(BASE_PORT + nid, name, log)
        except Exception as e:
            print(f"  {name}: EXCEPTION {e}")
            results[name] = False
    for nid, name in JUNOS_NODES:
        try:
            results[name] = apply_junos(BASE_PORT + nid, name, log)
        except Exception as e:
            print(f"  {name}: EXCEPTION {e}")
            results[name] = False
    log.close()
    print("\n=== SUMMARY ===")
    for n, ok in results.items():
        print(f"  {'OK ' if ok else 'FAIL'}  {n}")
    print(f"\nTranscript: /tmp/live_apply.transcript.bin")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
