#!/bin/bash
# Idempotent EVE-NG host bootstrap for LAB-2.
# Run on the EVE-NG host. Applies these modifications:
#   1. Add PA-2FE-TX to the c7200 dynamips template (intel + amd variants)
#   2. Patch __node.php to handle PA-2FE-TX in the c7200 slot dispatcher
#   3. Restore /boot/vmlinuz-* readability (libguestfs needs it)
# These are needed because PE4 in LAB-2 uses two PA-2FE-TX cards in slots 4/5
# to land all four new Cisco CEs on dedicated physical ports.
set -u

# 1. Templates
for f in /opt/unetlab/html/templates/intel/c7200.yml \
         /opt/unetlab/html/templates/amd/c7200.yml; do
    if grep -q "PA-2FE-TX:" "$f"; then
        echo "    template $f: already has PA-2FE-TX"
    else
        cp "$f" "$f.bak.$(date +%s)"
        sed -i 's|^  PA-FE-TX: PA-FE-TX|&\n  PA-2FE-TX: PA-2FE-TX|' "$f"
        echo " +  template $f: added PA-2FE-TX"
    fi
done

# 2. PHP dispatcher
PHPF=/opt/unetlab/html/includes/__node.php
if grep -q "case 'PA-2FE-TX':" "$PHPF"; then
    echo "    $PHPF: already patched"
else
    cp "$PHPF" "$PHPF.bak.$(date +%s)"
    python3 - <<'PYEOF'
import re, sys
PATH = "/opt/unetlab/html/includes/__node.php"
with open(PATH) as f: src = f.read()
m = re.search(r"(\n[\t ]+)case 'PA-4E':", src)
if not m:
    print("ERROR: PA-4E case marker not found"); sys.exit(2)
indent = m.group(1).rstrip("\n")
inner = indent + "\t"
patch_lines = [
    f"{indent}case 'PA-2FE-TX':",
    f"{inner}$this -> slots[$i] = $s;",
    f"{inner}$this -> flags_eth .= ' -p '.$i.':'.$s;",
    f"{inner}for ($p = 0; $p <= 1; $p++) {{",
    f"{inner}\tif (isset($old_ethernets[16 * $i + $p])) {{",
    f"{inner}\t\t$this -> ethernets[16 * $i + $p] = $old_ethernets[16 * $i + $p];",
    f"{inner}\t}} else {{",
    f"{inner}\t\ttry {{",
    f"{inner}\t\t\t$this -> ethernets[16 * $i + $p] = new Interfc(Array('name' => 'fa'.$i.'/'.$p, 'type' => 'ethernet'), 16 * $i + $p);",
    f"{inner}\t\t}} catch (Exception $e) {{",
    f"{inner}\t\t\terror_log(date('M d H:i:s ').'ERROR: '.$GLOBALS['messages'][40020]);",
    f"{inner}\t\t\terror_log(date('M d H:i:s ').(string) $e);",
    f"{inner}\t\t\treturn 40020;",
    f"{inner}\t\t}}",
    f"{inner}\t}}",
    f"{inner}\t$this -> flags_eth .= ' -s '.$i.':'.$p.':tap:vunl'.$this -> tenant.'_'.$this -> id.'_'.(16 * $i + $p);",
    f"{inner}}}",
    f"{inner}break;",
]
patch = "\n".join(patch_lines) + "\n"
out = src[:m.start()] + "\n" + patch + src[m.start()+1:]
with open(PATH, "w") as f: f.write(out)
print("OK: __node.php patched")
PYEOF
    echo " +  $PHPF: PA-2FE-TX case added"
fi

# 3. /boot kernel readability for libguestfs (FreeBSD inject helper).
chmod 0644 /boot/vmlinuz-* 2>/dev/null && echo "    /boot/vmlinuz-* readable"

echo
echo "EVE-NG host LAB-2 patches applied. PE4 can now use PA-2FE-TX in any slot 1-6."
