#!/bin/bash
# Print a table of running qemu nodes and their console ports.
# Usage: bash console_ports.sh [node_id ...]
#   No args: list all running nodes.
#   With args: print only those node IDs.

echo "NODE  PORT    PID(qemu-system)"
echo "----  ------  ----------------"

ps aux | grep 'qemu_wrapper' | grep -v grep | while read -r line; do
    pid=$(echo "$line" | awk '{print $2}')
    nid=$(echo "$line" | grep -oP '\-D \K[0-9]+')
    [ -z "$nid" ] && continue

    # filter if specific node IDs requested
    if [ $# -gt 0 ]; then
        match=0
        for arg in "$@"; do [ "$arg" = "$nid" ] && match=1; done
        [ $match -eq 0 ] && continue
    fi

    port=$(ss -tlnp 2>/dev/null | grep "pid=$pid," | grep -oP ':\K[0-9]+' | head -1)
    qpid=$(ss -tlnp 2>/dev/null | grep "pid=$pid," | grep -oP '"qemu-system[^"]*",pid=\K[0-9]+' | head -1)
    printf "%-5s %-7s %s\n" "$nid" "${port:--}" "${qpid:--}"
done | sort -n
