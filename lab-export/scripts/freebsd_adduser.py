#!/usr/bin/env python3
"""Add a user to a FreeBSD lab node via QEMU monitor sendkey injection.

Connects to the node's console port, switches to the QEMU monitor via
Ctrl+A C, logs in as root, and runs pw useradd.

Usage:
  python3 freebsd_adduser.py --port 34441          # freebsd13 (node 18)
  python3 freebsd_adduser.py --port 36167          # freebsd14 (node 24)
  python3 freebsd_adduser.py --node 18             # auto-detect port from ps
  python3 freebsd_adduser.py --node 24 --user admin --password secret
"""
import socket, time, sys, re, subprocess

DEFAULT_USER     = "iris"
DEFAULT_PASSWORD = "1r15"
BASE_PORT        = 32768

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


class Monitor:
    def __init__(self, port):
        self.s = socket.create_connection(('127.0.0.1', port), timeout=10)
        self.s.settimeout(0.1)
        self.buf = b''
        self._drain(3)
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


def parse_args():
    args = sys.argv[1:]
    port = None
    node = None
    user = DEFAULT_USER
    password = DEFAULT_PASSWORD

    def get(flag):
        if flag in args:
            idx = args.index(flag)
            return args[idx + 1]
        return None

    if get('--port'):  port     = int(get('--port'))
    if get('--node'):  node     = int(get('--node'))
    if get('--user'):  user     = get('--user')
    if get('--password'): password = get('--password')

    if port is None and node is None:
        print("ERROR: specify --port <N> or --node <NID>")
        sys.exit(1)

    if port is None:
        port = node_console_port(node)
        print(f'  node {node} → console port {port}')

    return port, user, password


def main():
    port, user, password = parse_args()
    m = Monitor(port)

    print('  waking VGA console...')
    for _ in range(5):
        m.sendkey('ret')
        time.sleep(0.5)
    time.sleep(2)

    print('  logging in as root...')
    m.type_line('root', post_delay=4)

    print(f'\n  adding user {user} to wheel group...')
    m.type_line(f"echo '{password}' | pw useradd {user} -m -G wheel -h 0", post_delay=2)

    print('  verifying...')
    m.type_line(f'id {user}', post_delay=1)

    print('  logging out...')
    m.type_line('exit', post_delay=1)
    m.close()

    print(f'\nDone. User {user} created on the node.')


if __name__ == '__main__':
    main()
