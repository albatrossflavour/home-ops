#!/usr/bin/env bash
# Enable memory ballooning on guests that currently have it disabled.
#
# WHY
#
# Two separate problems on this estate, both of which stop the hypervisor
# reclaiming guest memory when it runs short:
#
#   balloon: 0    The balloon DEVICE is omitted entirely at QEMU launch.
#                 `qm monitor <id> <<< "info balloon"` returns
#                 "No balloon device has been activated". The host can never
#                 reclaim from these guests. Fixing it requires a VM restart,
#                 because the device is added at launch.
#
#   balloon unset Proxmox treats the floor as equal to `memory`, so the device
#                 exists but has no range to shrink into. Measured 2026-09-07:
#                 every enabled guest reported actual == max_mem. Nothing on
#                 the estate was reclaimable. Setting a floor below `memory`
#                 is what actually enables reclaim, and needs no restart.
#
# Proxmox auto-balloons when host memory passes 80%, shrinking guests toward
# their floor. Above that threshold this is the difference between reclaiming
# and swapping.
#
# WHAT IT DOES
#
# For each running guest on THIS node with ballooning disabled, sets a floor
# at FLOOR_PCT of allocated memory and restarts it if required. Kubernetes
# nodes are excluded: the kubelet sizes itself from the memory it sees at
# start, and shrinking a node underneath it gets pods OOM-killed rather than
# rescheduled.
#
# Run it on each Proxmox node in turn. Dry run unless --apply is given.
#
# Usage:
#   ./enable-vm-ballooning.sh                 # show the plan, change nothing
#   ./enable-vm-ballooning.sh --apply         # do it, prompting per guest
#   ./enable-vm-ballooning.sh --apply --yes   # do it without prompting
#   FLOOR_PCT=60 ./enable-vm-ballooning.sh    # more aggressive floor

set -euo pipefail

FLOOR_PCT="${FLOOR_PCT:-75}"
SHUTDOWN_TIMEOUT="${SHUTDOWN_TIMEOUT:-300}"
APPLY=0
ASSUME_YES=0

# Kubernetes nodes. Ballooning a k8s node gets pods OOM-killed: the kubelet
# advertises capacity from what it saw at start and does not renegotiate.
EXCLUDE_VMIDS="${EXCLUDE_VMIDS:-300 301 302 304 305 306}"

for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --help|-h) sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

command -v qm >/dev/null || { echo "ERROR: qm not found, run this on a Proxmox node" >&2; exit 1; }
NODE="$(hostname)"

if ! pvecm status >/dev/null 2>&1; then
  echo "ERROR: cluster status unavailable" >&2; exit 1
fi
if ! pvecm status 2>/dev/null | grep -qE '^Quorate:\s+Yes'; then
  echo "ERROR: cluster is not quorate, refusing to change guest config" >&2; exit 1
fi

is_excluded() { for x in $EXCLUDE_VMIDS; do [ "$x" = "$1" ] && return 0; done; return 1; }
ha_managed()  { ha-manager status 2>/dev/null | grep -qE "^service vm:$1 "; }

# ---------------------------------------------------------------- build plan
declare -a PLAN=()
for conf in /etc/pve/qemu-server/*.conf; do
  [ -f "$conf" ] || continue
  vmid="$(basename "$conf" .conf)"
  [ "$(qm status "$vmid" 2>/dev/null | awk '{print $2}')" = "running" ] || continue

  mem="$(awk '/^memory:/{print $2; exit}' "$conf")"
  [ -n "${mem:-}" ] || continue
  bal="$(awk '/^balloon:/{print $2; exit}' "$conf" || true)"
  name="$(awk -F': *' '/^name:/{print $2; exit}' "$conf")"

  # Already has a working floor below its allocation: nothing to do.
  if [ -n "${bal:-}" ] && [ "$bal" != "0" ] && [ "$bal" -lt "$mem" ]; then continue; fi

  floor=$(( mem * FLOOR_PCT / 100 ))
  [ "$floor" -lt 512 ] && floor=512
  [ "$floor" -ge "$mem" ] && continue

  if is_excluded "$vmid"; then
    printf '  SKIP    %-6s %-32s kubernetes node, excluded\n' "$vmid" "${name:-?}"
    continue
  fi

  if [ "${bal:-unset}" = "0" ]; then action="floor+restart"; else action="floor only"; fi
  PLAN+=("$vmid|$name|$mem|${bal:-unset}|$floor|$action")
done

echo
echo "Node: $NODE    floor: ${FLOOR_PCT}% of allocated"
echo
if [ "${#PLAN[@]}" -eq 0 ]; then echo "  Nothing to do on this node."; exit 0; fi

printf '  %-6s %-32s %8s %8s %8s  %s\n' ID NAME ALLOC BALLOON FLOOR ACTION
for row in "${PLAN[@]}"; do
  IFS='|' read -r vmid name mem bal floor action <<< "$row"
  printf '  %-6s %-32s %7sM %8s %7sM  %s\n' "$vmid" "${name:0:32}" "$mem" "$bal" "$floor" "$action"
done
echo
reclaim=0
for row in "${PLAN[@]}"; do IFS='|' read -r _ _ mem _ floor _ <<< "$row"; reclaim=$(( reclaim + mem - floor )); done
echo "  Reclaimable once applied: $(( reclaim / 1024 ))G across ${#PLAN[@]} guests on $NODE"
echo

if [ "$APPLY" -ne 1 ]; then
  echo "  Dry run. Re-run with --apply to make these changes."
  exit 0
fi

# ------------------------------------------------------------------- apply
mkdir -p /root/balloon-backup
FAILED=0
for row in "${PLAN[@]}"; do
  IFS='|' read -r vmid name mem bal floor action <<< "$row"
  echo "--- VM $vmid ($name): $action ---"

  if [ "$ASSUME_YES" -ne 1 ]; then
    read -r -p "    proceed? [y/N] " ans </dev/tty
    case "$ans" in y|Y) ;; *) echo "    skipped"; continue ;; esac
  fi

  cp "/etc/pve/qemu-server/$vmid.conf" "/root/balloon-backup/$vmid.conf.$(date +%Y%m%d-%H%M%S)"
  qm set "$vmid" --balloon "$floor" >/dev/null
  echo "    balloon floor set to ${floor}M"

  if [ "$action" = "floor only" ]; then
    echo "    no restart needed, device already present"
  else
    if ha_managed "$vmid"; then
      echo "    HA-managed, cycling via ha-manager"
      ha-manager set "vm:$vmid" --state stopped
      for _ in $(seq 1 60); do
        [ "$(qm status "$vmid" 2>/dev/null | awk '{print $2}')" = "stopped" ] && break; sleep 5
      done
      ha-manager set "vm:$vmid" --state started
    else
      qm shutdown "$vmid" --timeout "$SHUTDOWN_TIMEOUT" || {
        echo "    graceful shutdown failed, leaving VM running and floor set" >&2
        echo "    restart it manually to activate the balloon device" >&2
        FAILED=$(( FAILED + 1 )); continue
      }
      qm start "$vmid"
    fi

    printf '    waiting for guest'
    for _ in $(seq 1 60); do
      [ "$(qm status "$vmid" 2>/dev/null | awk '{print $2}')" = "running" ] && break
      printf '.'; sleep 5
    done
    echo
  fi

  # Verify the device is actually live. This is the whole point of the restart,
  # so a failure here matters more than the config having been written.
  #
  # Retry rather than checking once: `qm start` returns as soon as QEMU
  # launches, well before the guest has loaded its virtio-balloon driver, and
  # the monitor does not answer during that window. A single check five
  # seconds after start reports a false failure on a guest that is fine.
  # Verify against the QEMU command line, NOT `qm monitor`.
  #
  # `qm monitor` opens /dev/tty directly when a terminal exists, so it ignores
  # redirected stdin and sits at an interactive `qm>` prompt, blocking the
  # script. It only appears to work when run without a tty, which is how it
  # passed testing and then hung on first interactive use.
  #
  # The process check is definitive about whether the balloon device was
  # created, needs no monitor, and cannot block.
  printf '    verifying balloon'
  ok=0
  for _ in $(seq 1 12); do
    if ps -o args= -C kvm 2>/dev/null | grep -- "-id $vmid " | grep -q 'id=balloon0'; then ok=1; break; fi
    printf '.'; sleep 5
  done
  echo
  if [ "$ok" -eq 1 ]; then
    echo "    OK: balloon device present, floor ${floor}M of ${mem}M"
  else
    echo "    WARNING: no balloon device for $vmid after 60s" >&2
    FAILED=$(( FAILED + 1 ))
  fi
done

echo
if [ "$FAILED" -gt 0 ]; then
  echo "Finished with $FAILED problem(s). Configs backed up in /root/balloon-backup/"
  exit 1
fi
echo "Done on $NODE. Configs backed up in /root/balloon-backup/"
echo "Run this on the remaining nodes to complete the estate."
