#!/bin/bash
# LAB-3 regression verification: confirm the four customer branch sites are
# reachable end-to-end through the MPLS L3VPN from the FreeBSD CE.
#
# Run from this Mac (or anywhere with the right SSH keys); the script
# uses the documented FreeBSD SSH path (iris@10.2.0.139, id_vpoller).
#
# Exit code 0 if everything passes, non-zero otherwise. Prints a per-target
# table.
set -u

FBSD="iris@10.2.0.139"
KEY="${HOME}/.ssh/id_vpoller"

# (fib, target_ip, label)
TARGETS=(
    "2:192.168.101.100:ACDC_HOST (FreeBSD behind ACDC_SITE_A)"
    "2:192.168.101.1:ACDC_SITE_A LAN (lo)"
    "2:192.168.102.1:ACDC_SITE_B LAN (lo)"
    "3:192.168.103.1:SWANS_SITE_A LAN (lo)"
    "3:192.168.104.1:SWANS_SITE_B LAN (lo)"
    # PE-CE link reachability (added by LAB-3 follow-up)
    "2:10.100.0.1:ACDC fa1/0"
    "2:10.100.0.2:ACDC_SITE_A ether1"
    "2:10.100.0.5:ACDC fa1/1"
    "2:10.100.0.6:ACDC_SITE_B ether1"
    "3:10.101.0.1:SWANS fa1/0"
    "3:10.101.0.2:SWANS_SITE_A ether1"
    "3:10.101.0.5:SWANS fa1/1"
    "3:10.101.0.6:SWANS_SITE_B ether1"
    # LAB-2 sanity (the four CE Lo100s) — should still work
    "2:192.168.100.1:ACDC Lo100"
    "3:192.168.100.1:SWANS Lo100"
    "4:192.168.100.1:SEPULTURA Lo100"
    "5:192.168.100.1:NIN Lo100"
)

fails=0
total=${#TARGETS[@]}
printf "%-3s  %-18s  %-30s  %s\n" "FIB" "TARGET" "LABEL" "RESULT"
printf "%-3s  %-18s  %-30s  %s\n" "---" "------------------" "------------------------------" "------"

for entry in "${TARGETS[@]}"; do
    fib=$(echo "$entry" | cut -d: -f1)
    ip=$(echo "$entry"  | cut -d: -f2)
    label=$(echo "$entry" | cut -d: -f3-)
    out=$(ssh -i "$KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=5 "$FBSD" \
              "setfib $fib ping -c 2 -W 3 -t 6 $ip 2>&1" 2>/dev/null \
            | grep -E "packets received" | head -1)
    rcvd=$(echo "$out" | grep -oE "[0-9]+ packets received" | grep -oE "^[0-9]+")
    if [ "${rcvd:-0}" = "0" ] || [ -z "$rcvd" ]; then
        printf "%-3s  %-18s  %-30s  \033[31mFAIL\033[0m\n" "$fib" "$ip" "$label"
        fails=$((fails + 1))
    else
        printf "%-3s  %-18s  %-30s  \033[32mOK\033[0m  ($rcvd/2)\n" "$fib" "$ip" "$label"
    fi
done

echo
if [ "$fails" -eq 0 ]; then
    echo "All $total targets reachable."
    exit 0
else
    echo "$fails / $total targets FAILED."
    exit 1
fi
