#!/bin/bash
# Print a table of running qemu/dynamips nodes and their direct console ports.
# These are the wrapper-level ports (not the 32768+N EVE-NG proxy ports).
# Usage: bash console_ports.sh [node_id ...]

echo "NODE  PORT    TYPE"
echo "----  ------  --------"

# QEMU nodes: qemu_wrapper -C <port> -D <nid>
ps aux | grep 'qemu_wrapper' | grep -v grep | while read -r line; do
    nid=$(echo "$line" | grep -oP '\-D \K[0-9]+')
    port=$(echo "$line" | grep -oP '\-C \K[0-9]+')
    [ -z "$nid" ] || [ -z "$port" ] && continue
    if [ $# -gt 0 ]; then
        match=0; for arg in "$@"; do [ "$arg" = "$nid" ] && match=1; done
        [ $match -eq 0 ] && continue
    fi
    printf "%-5s %-7s %s\n" "$nid" "$port" "qemu"
done | sort -n | uniq

# Dynamips nodes: dynamips_wrapper -C <port> -D <nid>
ps aux | grep 'dynamips_wrapper' | grep -v grep | while read -r line; do
    nid=$(echo "$line" | grep -oP '\-D \K[0-9]+')
    port=$(echo "$line" | grep -oP '\-C \K[0-9]+')
    [ -z "$nid" ] || [ -z "$port" ] && continue
    if [ $# -gt 0 ]; then
        match=0; for arg in "$@"; do [ "$arg" = "$nid" ] && match=1; done
        [ $match -eq 0 ] && continue
    fi
    printf "%-5s %-7s %s\n" "$nid" "$port" "dynamips"
done | sort -n | uniq
