#!/usr/bin/env bash
# Mirror selected NAS shares to the local backup disk on ankh.
#
# WHAT WENT WRONG WITH THE PREVIOUS VERSION
#
# It was five bare rsync lines with no error handling, invoked from cron as:
#
#     0 0 * * * /root/sync.sh 2>/dev/null 1>/dev/null
#
# When root's SSH key stopped authenticating to the NAS, every run failed with
# "Permission denied" straight into /dev/null. Nothing reported it. Discovered
# 2026-09-07, by which point the newest content was eight months stale and
# PlexMediaServer had not moved since 2021.
#
# This version fails loudly, refuses to run when it cannot do the job safely,
# and leaves a log worth reading.
#
# THE GUARD THAT MATTERS MOST
#
# Every rsync uses --delete. If /nas-backup is not mounted, those writes land
# on the root filesystem instead and --delete starts removing things from a
# directory that is not the backup. The mountpoint check below is not
# defensive tidiness; without it a failed mount turns this into a script that
# fills / and deletes as it goes.
#
# Usage:
#   ./sync.sh              sync everything enabled below
#   ./sync.sh --dry-run    show what would transfer, change nothing
#   ./sync.sh --only Media sync a single source

set -euo pipefail

NAS="tgreen@192.168.1.22"
DEST="/nas-backup"
RSYNC_PATH="/opt/bin/rsync"
LOG="/var/log/nas-sync.log"
LOCK="/var/lock/nas-sync.lock"

# source path on the NAS | extra rsync args
# proximages is disabled: it was commented out in the original script and the
# local copy was two years stale by 2026-09. Enable deliberately if wanted.
SOURCES=(
  "/volume1/Media|"
  "/volume1/PlexMediaServer|"
  "/volume2/photos|"
  "/volume2/Backups|--exclude edward --exclude software --exclude *teve* --exclude *odie*"
  # "/volume1/proximages|"
)

DRY=""
ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY="--dry-run"; shift ;;
    --only) ONLY="${2:-}"; shift 2 ;;
    --help|-h) sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG"; }
die() { log "ERROR: $*"; exit 1; }

exec 9>"$LOCK"
flock -n 9 || die "another run is already in progress"

log "=== sync starting ${DRY:+(dry run) }==="

# 1. Destination must be a real mountpoint. See the note above.
mountpoint -q "$DEST" || die "$DEST is not mounted, refusing to rsync --delete into the root filesystem"

# 2. Fail early on a dead credential rather than once per source.
ssh -o BatchMode=yes -o ConnectTimeout=10 "$NAS" true 2>/dev/null \
  || die "cannot ssh to $NAS. Check root's key is still in tgreen's authorized_keys."

# 3. Refuse to start a large transfer with no room for it.
avail=$(df -BG --output=avail "$DEST" | tail -1 | tr -dc '0-9')
[ "${avail:-0}" -ge 50 ] || die "only ${avail}G free on $DEST, refusing to start"
log "destination ok: ${avail}G free"

failed=0
for entry in "${SOURCES[@]}"; do
  src="${entry%%|*}"
  extra="${entry#*|}"
  name="$(basename "$src")"
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue

  log "--- $name ---"
  start=$(date +%s)

  # shellcheck disable=SC2086
  if rsync -a --delete --stats --human-readable $DRY $extra \
        -e ssh --rsync-path="$RSYNC_PATH" \
        "${NAS}:${src}" "${DEST}/" >>"$LOG" 2>&1; then
    log "$name ok in $(( ($(date +%s) - start) / 60 ))m"
  else
    rc=$?
    log "$name FAILED (rsync exit $rc), see $LOG"
    failed=$(( failed + 1 ))
  fi
done

log "destination now: $(df -h "$DEST" | tail -1 | awk '{print $3" used, "$4" free, "$5}')"
log "inodes: $(df -i "$DEST" | tail -1 | awk '{print $3" used, "$5}')"

if [ "$failed" -gt 0 ]; then
  log "=== sync finished with $failed failure(s) ==="
  exit 1
fi
log "=== sync finished cleanly ==="
