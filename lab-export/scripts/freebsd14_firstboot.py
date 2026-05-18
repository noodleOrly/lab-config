#!/usr/bin/env python3
"""Type first-boot config into freebsd14 (node 24) via the QEMU monitor.

Connects to the EVE-NG telnet console and switches to QEMU monitor mode
via Ctrl+A C, then injects sendkey commands into the VM's VGA console.

Run on the EVE-NG host AFTER node 24 has started. The system should already
be booted (DHCP on management interface) before running this script.

Usage:
  python3 freebsd14_firstboot.py                   # use default port 32792
  python3 freebsd14_firstboot.py --port 36167      # qemu_wrapper direct port
  python3 freebsd14_firstboot.py --wait            # wait 150s for FreeBSD to boot

Note: on some EVE-NG versions the console is on port 32768+node_id (32792)
accessible via the external IP; on others qemu_wrapper opens a random high
port (find it with: ss -tlnp | grep qemu-system).
"""
import socket, time, sys

CONSOLE_PORT = 32792  # default; override with --port <N>

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
    def __init__(self, port):
        self.s = socket.create_connection(('127.0.0.1', port), timeout=10)
        self.s.settimeout(0.1)  # short timeout so drain loops don't stall 1s per recv
        self.buf = b''
        # Drain telnet IAC negotiation bytes from EVE-NG console
        self._drain(3)
        # Switch from serial mux to QEMU monitor: Ctrl+A then C
        self.s.sendall(b'\x01c')
        time.sleep(0.5)
        self._drain(1.0)
        print(f'  connected to QEMU monitor via console mux :{port}')

    def _drain(self, t=1.0):
        end = time.time() + t
        while time.time() < end:
            try:
                d = self.s.recv(4096)
                if d: self.buf += d
            except socket.timeout:
                pass

    def cmd(self, command):
        self.s.sendall((command + '\n').encode())
        time.sleep(0.02)
        self._drain(0.15)

    def sendkey(self, key):
        self.cmd(f'sendkey {key}')

    def type_char(self, ch):
        k = _KEYMAP.get(ch)
        if k is None:
            print(f'  WARNING: no keymap for {ch!r}, skipping')
            return
        self.sendkey(k)

    def type_string(self, s, delay=0.03):
        for ch in s:
            self.type_char(ch)
            time.sleep(delay)

    def type_line(self, line, post_delay=1.0):
        print(f'  > {line[:70]}{"..." if len(line) > 70 else ""}')
        self.type_string(line)
        self.sendkey('ret')
        time.sleep(post_delay)

    def close(self):
        try: self.s.close()
        except Exception: pass


def main():
    port = CONSOLE_PORT
    if '--port' in sys.argv:
        port = int(sys.argv[sys.argv.index('--port') + 1])
    print(f'  connecting to console port {port}...')
    m = Monitor(port)

    if '--wait' in sys.argv:
        print('  waiting 150s for FreeBSD to boot...')
        for i in range(150, 0, -10):
            print(f'  {i}s...')
            time.sleep(10)

    # Wake the VGA console — send several Enters to clear any stale prompt
    print('  waking VGA console (sending Enter x5)...')
    for _ in range(5):
        m.sendkey('ret')
        time.sleep(0.5)
    time.sleep(2)

    print('  logging in as root (no password on base image)...')
    m.type_line('root', post_delay=4)

    # /boot/loader.conf
    print('\n  writing /boot/loader.conf ...')
    m.type_line("echo 'net.fibs=\"6\"' > /boot/loader.conf")
    m.type_line("echo 'boot_multicons=\"YES\"' >> /boot/loader.conf")
    m.type_line("echo 'boot_serial=\"YES\"' >> /boot/loader.conf")
    m.type_line("echo 'comconsole_speed=\"9600\"' >> /boot/loader.conf")
    m.type_line("echo 'console=\"comconsole,vidconsole\"' >> /boot/loader.conf")

    # /etc/rc.conf — simple values via sysrc
    print('\n  writing /etc/rc.conf ...')
    m.type_line('sysrc hostname=freebsd14')
    m.type_line('sysrc ifconfig_em0=DHCP')
    m.type_line('sysrc ifconfig_em1=up')
    m.type_line("sysrc 'cloned_interfaces=vlan1803 vlan1804 vlan1805 vlan1806'")
    m.type_line("sysrc 'static_routes=vlan1803 vlan1803default vlan1804 vlan1804default vlan1805 vlan1805default vlan1806 vlan1806default'")

    # VLAN interfaces and per-FIB routes — complex values, write directly
    for vlan, fib, gw_last, host_last, net_last in [
        (1803, 2, 1, 2, 0),
        (1804, 3, 5, 6, 4),
        (1805, 4, 9, 10, 8),
        (1806, 5, 13, 14, 12),
    ]:
        gw   = f'100.112.2.{gw_last}'
        host = f'100.112.2.{host_last}'
        net  = f'100.112.2.{net_last}'
        m.type_line(f"echo 'ifconfig_vlan{vlan}=\"{host}/30 vlan {vlan} vlandev em1\"' >> /etc/rc.conf", post_delay=0.6)
        m.type_line(f"echo 'route_vlan{vlan}=\"{net}/30 -iface vlan{vlan} -fib {fib}\"' >> /etc/rc.conf", post_delay=0.6)
        m.type_line(f"echo 'route_vlan{vlan}default=\"default {gw} -fib {fib}\"' >> /etc/rc.conf", post_delay=0.6)

    m.type_line('sysrc sshd_enable=YES')
    m.type_line('sysrc syslogd_flags=-s')
    m.type_line('sysrc syslogd_enable=YES')

    # SSH config
    print('\n  configuring sshd ...')
    m.type_line('mkdir -p /etc/ssh/sshd_config.d')
    m.type_line("printf 'PermitRootLogin yes\\nPasswordAuthentication yes\\n' > /etc/ssh/sshd_config.d/lab.conf")

    # Serial getty in /etc/ttys
    print('\n  adding serial getty ...')
    m.type_line("sed -i '' '/^ttyu0/d' /etc/ttys")
    m.type_line("printf 'ttyu0\\t\"/usr/libexec/getty 3wire\"\\tvt100\\tonifconsole secure\\n' >> /etc/ttys")

    # Remote syslog
    print('\n  configuring remote syslog ...')
    m.type_line("printf '*.notice\\t@10.2.0.114\\n' >> /etc/syslog.conf")

    # Root password — use passwd interactive (two prompts) for reliability
    print('\n  setting root password via passwd ...')
    m.type_line('passwd root', post_delay=2)
    m.type_line('lab123', post_delay=1)
    m.type_line('lab123', post_delay=1)

    # Verify files landed
    print('\n  verifying ...')
    m.type_line('cat /boot/loader.conf', post_delay=1)
    m.type_line('grep vlan1803 /etc/rc.conf', post_delay=1)
    m.type_line('cat /etc/ssh/sshd_config.d/lab.conf', post_delay=1)

    print('\n  rebooting ...')
    m.type_line('reboot', post_delay=5)
    m.close()

    print('\nDone. freebsd14 rebooting.')
    print('After ~90s, serial console at port 32792 will carry the login prompt.')
    print('SSH to 10.2.0.140 (root / lab123) once it comes up.')


if __name__ == '__main__':
    main()
