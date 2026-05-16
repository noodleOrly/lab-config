#!/usr/bin/env python3
"""Type first-boot config into ACDC_HOST (node 23) via the QEMU monitor.

Connects to the QEMU monitor at localhost:4423 and sends sendkey commands
to type the configuration into the FreeBSD console — no VNC needed.

Run on the EVE-NG host AFTER node 23 has been started and has had time
to reach the login prompt (allow ~120 seconds from node start).
"""
import socket, time, sys, re

MONITOR_HOST = "127.0.0.1"
MONITOR_PORT = 4423

# US keyboard mapping for QEMU sendkey
_KEYMAP = {
    **{c: c for c in 'abcdefghijklmnopqrstuvwxyz0123456789'},
    **{c.upper(): f'shift-{c}' for c in 'abcdefghijklmnopqrstuvwxyz'},
    ' ': 'spc', '\n': 'ret', '\t': 'tab',
    '!': 'shift-1', '@': 'shift-2', '#': 'shift-3', '$': 'shift-4',
    '%': 'shift-5', '^': 'shift-6', '&': 'shift-7', '*': 'shift-8',
    '(': 'shift-9', ')': 'shift-0',
    '-': 'minus', '_': 'shift-minus', '=': 'equal', '+': 'shift-equal',
    '[': 'bracket_left', ']': 'bracket_right',
    '{': 'shift-bracket_left', '}': 'shift-bracket_right',
    '\\': 'backslash', '|': 'shift-backslash',
    ';': 'semicolon', ':': 'shift-semicolon',
    "'": 'apostrophe', '"': 'shift-apostrophe',
    ',': 'comma', '.': 'dot', '/': 'slash',
    '<': 'shift-comma', '>': 'shift-dot', '?': 'shift-slash',
    '`': 'grave_accent', '~': 'shift-grave_accent',
}


class Monitor:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=10)
        self.s.settimeout(1.0)
        self.buf = b""
        self._drain(3)
        print(f"  connected to QEMU monitor at {host}:{port}")

    def _drain(self, t=1.0):
        end = time.time() + t
        while time.time() < end:
            try:
                d = self.s.recv(4096)
                if d:
                    self.buf += d
            except socket.timeout:
                pass

    def cmd(self, command):
        self.s.sendall((command + "\n").encode())
        time.sleep(0.05)
        self._drain(0.3)

    def sendkey(self, key):
        self.cmd(f"sendkey {key}")

    def type_char(self, ch):
        k = _KEYMAP.get(ch)
        if k is None:
            print(f"  WARNING: no keymap for {ch!r}, skipping")
            return
        self.sendkey(k)

    def type_string(self, s, delay=0.04):
        for ch in s:
            self.type_char(ch)
            time.sleep(delay)

    def type_line(self, line, post_delay=0.8):
        print(f"  typing: {line[:60]}{'...' if len(line) > 60 else ''}")
        self.type_string(line)
        self.sendkey('ret')
        time.sleep(post_delay)

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def main():
    m = Monitor(MONITOR_HOST, MONITOR_PORT)

    # If node just started and is still booting, wait.
    # FreeBSD bootloader has a 10s countdown, boot takes ~90s total.
    # If you know the node is already at a prompt, run with --nowait.
    if '--nowait' not in sys.argv:
        print("  waiting 120s for FreeBSD to boot (pass --nowait to skip)...")
        for i in range(120, 0, -10):
            print(f"  {i}s remaining...")
            time.sleep(10)

    print("  sending Enter to wake console...")
    m.sendkey('ret')
    time.sleep(2)

    # Log in as root (no password on base image)
    print("  logging in as root...")
    m.type_line('root', post_delay=3)

    # --- /boot/loader.conf (serial console for future telnet sessions) ---
    print("\n  writing /boot/loader.conf ...")
    m.type_line('echo boot_multicons=YES > /boot/loader.conf')
    m.type_line('echo boot_serial=YES >> /boot/loader.conf')
    m.type_line('echo comconsole_speed=9600 >> /boot/loader.conf')
    m.type_line("echo 'console=comconsole,vidconsole' >> /boot/loader.conf")

    # --- /etc/rc.conf via sysrc ---
    print("\n  writing rc.conf via sysrc ...")
    m.type_line('sysrc hostname=acdc-host')
    m.type_line('sysrc ifconfig_em0=192.168.101.100/24')
    m.type_line('sysrc defaultrouter=192.168.101.1')
    m.type_line('sysrc sshd_enable=YES')
    m.type_line('sysrc syslogd_enable=YES')

    # --- SSH allow root login ---
    print("\n  configuring sshd ...")
    m.type_line('mkdir -p /etc/ssh/sshd_config.d')
    m.type_line("printf 'PermitRootLogin yes\\nPasswordAuthentication yes\\n' > /etc/ssh/sshd_config.d/lab.conf")

    # --- serial getty ---
    print("\n  adding serial getty to /etc/ttys ...")
    m.type_line("sed -i '' '/^ttyu0/d' /etc/ttys")
    m.type_line("printf 'ttyu0\\t\"/usr/libexec/getty 3wire\"\\tvt100\\tonifconsole secure\\n' >> /etc/ttys")

    # --- syslog remote ---
    print("\n  configuring remote syslog ...")
    m.type_line("printf '*.notice\\t@10.2.0.114\\n' >> /etc/syslog.conf")

    # --- root password ---
    print("\n  setting root password ...")
    m.type_line('echo lab123 | pw usermod root -h 0')

    # --- verify and reboot ---
    print("\n  verifying loader.conf ...")
    m.type_line('cat /boot/loader.conf')
    time.sleep(1)

    print("\n  rebooting ...")
    m.type_line('reboot', post_delay=5)

    m.close()
    print("\nDone. FreeBSD will reboot with serial console enabled.")
    print("After ~90s, telnet console at port 32791 will be live.")
    print("Test from freebsd13: setfib 2 ping 192.168.101.100")


if __name__ == "__main__":
    main()
