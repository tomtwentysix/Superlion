#!/bin/bash
# Run as root by Superlion through pkexec.
#   edid-helper.sh enable <connector> <edid file>   use the EDID for the connector, now and after reboots
#   edid-helper.sh disable <connector>              go back to the connector's own EDID
# <connector> is the kernel's name, such as HDMI-A-1. Each override is kept as
# /usr/lib/firmware/edid/superlion-<connector>.bin, and the drm.edid_firmware
# boot option is rebuilt from those files, so it lists every override Superlion made.
set -euo pipefail

FIRMWARE=/usr/lib/firmware/edid
DRACUT_CONF=/etc/dracut.conf.d/superlion-edid.conf

action=${1:-}
connector=${2:-}
[[ $connector =~ ^[A-Za-z]+(-[A-Za-z])?-[0-9]+$ ]] || { echo "Not a connector name: $connector" >&2; exit 2; }
file="$FIRMWARE/superlion-$connector.bin"

sysfs=$(ls -d /sys/class/drm/card*-"$connector" 2>/dev/null | head -n1)
[[ -n $sysfs ]] || { echo "No such connector: $connector" >&2; exit 2; }

debugfs_dir() {
    mountpoint -q /sys/kernel/debug || mount -t debugfs debugfs /sys/kernel/debug
    ls -d /sys/kernel/debug/dri/*/"$connector" 2>/dev/null | head -n1
}

# Re-reading the EDID alone sends no hotplug event, so the desktop would not
# notice; turning the connector off and back on does.
reprobe() {
    echo off > "$sysfs/status"
    sleep 1
    echo detect > "$sysfs/status"
}

case $action in
enable)
    edid=${3:-}
    size=$(stat -c %s "$edid")
    if (( size == 0 || size % 128 )) || [[ $(head -c 8 "$edid" | od -An -tx1 | tr -d ' \n') != 00ffffffffffff00 ]]; then
        echo "Not an EDID: $edid" >&2
        exit 2
    fi
    install -Dm644 "$edid" "$file"
    dir=$(debugfs_dir)
    if [[ -n $dir ]]; then
        cat "$file" > "$dir/edid_override"
        reprobe
    fi
    ;;
disable)
    rm -f "$file"
    dir=$(debugfs_dir)
    if [[ -n $dir ]]; then
        echo reset > "$dir/edid_override"
        reprobe
    fi
    ;;
*)
    echo "Usage: $0 enable <connector> <edid file> | disable <connector>" >&2
    exit 2
    ;;
esac

entries=()
for f in "$FIRMWARE"/superlion-*.bin; do
    [[ -e $f ]] || continue
    name=$(basename "$f" .bin)
    entries+=("${name#superlion-}:edid/$name.bin")
done
grubby --update-kernel=ALL --remove-args=drm.edid_firmware
if (( ${#entries[@]} )); then
    grubby --update-kernel=ALL --args="drm.edid_firmware=$(IFS=,; echo "${entries[*]}")"
fi

# Drivers loaded from the initramfs read EDID files before the root file system is mounted.
if (( ${#entries[@]} )); then
    printf 'install_items+=" %s "\n' "$FIRMWARE"/superlion-*.bin > "$DRACUT_CONF"
else
    rm -f "$DRACUT_CONF"
fi
driver=$(basename "$(readlink -f "$sysfs/device/driver")")
if [[ -n $driver ]] && lsinitrd 2>/dev/null | grep -q "/$driver.ko"; then
    dracut -f
fi
