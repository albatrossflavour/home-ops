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

# node_exporter textfile collector. ankh already writes smartmon.prom and
# nvme.prom here and Prometheus already scrapes this node, so metrics land
# without any new plumbing. Written atomically (temp file + mv) because
# node_exporter will happily read a half-written file and report garbage.
TEXTFILE_DIR="/var/lib/prometheus/node-exporter"
METRICS="${TEXTFILE_DIR}/nas_sync.prom"
STATE_DIR="/var/lib/nas-sync"
LAST_SUCCESS_FILE="${STATE_DIR}/last_success"

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

# WHY EXIT 23 IS NOT A FAILURE
#
# rsync exit 23 is "some files/attrs were not transferred". On this NAS that is
# a permanent condition: 48 files under Media and PlexMediaServer are owned in a
# way the tgreen account cannot read, so every run will skip them and every run
# will exit 23. Treating that as a failure means the script cries wolf nightly,
# which is how the original script's real failure went unnoticed for eight
# months. Treating it as success would hide a genuine partial transfer.
#
# So it is its own state. Exit 23 and 24 (source files vanished mid-transfer,
# normal on live data) are PARTIAL. The count of unreadable files is exported as
# a metric, so the alert fires when that number GROWS rather than when it exists.
#
#   status  0 = ok        rsync exit 0
#           1 = partial   rsync exit 23 or 24
#           2 = failed    anything else
STATUS_OK=0
STATUS_PARTIAL=1
STATUS_FAILED=2

declare -A SRC_STATUS SRC_DURATION SRC_UNREADABLE
hard_failures=0
partials=0

# Metrics are written on every exit path, including the die() calls above and a
# mid-run crash. A sync that dies without leaving metrics is indistinguishable
# from one that never ran, and "never ran" is the failure this script exists to
# make visible.
write_metrics() {
  local now; now=$(date +%s)
  local last_success; last_success=$(cat "$LAST_SUCCESS_FILE" 2>/dev/null || echo 0)

  mkdir -p "$TEXTFILE_DIR"
  local tmp; tmp=$(mktemp "${METRICS}.XXXXXX")
  {
    echo "# HELP nas_sync_last_run_timestamp_seconds Unix time the last run finished."
    echo "# TYPE nas_sync_last_run_timestamp_seconds gauge"
    echo "nas_sync_last_run_timestamp_seconds ${now}"
    echo "# HELP nas_sync_last_success_timestamp_seconds Unix time of the last run with no hard failures. This is the metric that matters - a stale value means the backup is not happening, which is the failure that went unnoticed for eight months."
    echo "# TYPE nas_sync_last_success_timestamp_seconds gauge"
    echo "nas_sync_last_success_timestamp_seconds ${last_success}"
    echo "# HELP nas_sync_hard_failures Sources that failed for a reason other than unreadable files."
    echo "# TYPE nas_sync_hard_failures gauge"
    echo "nas_sync_hard_failures ${hard_failures}"
    echo "# HELP nas_sync_partial_sources Sources that completed but skipped files."
    echo "# TYPE nas_sync_partial_sources gauge"
    echo "nas_sync_partial_sources ${partials}"
    echo "# HELP nas_sync_source_status Per-source outcome. 0 ok, 1 partial, 2 failed."
    echo "# TYPE nas_sync_source_status gauge"
    for k in "${!SRC_STATUS[@]}"; do
      echo "nas_sync_source_status{source=\"${k}\"} ${SRC_STATUS[$k]}"
    done
    echo "# HELP nas_sync_source_duration_seconds Wall clock time for the source."
    echo "# TYPE nas_sync_source_duration_seconds gauge"
    for k in "${!SRC_DURATION[@]}"; do
      echo "nas_sync_source_duration_seconds{source=\"${k}\"} ${SRC_DURATION[$k]}"
    done
    echo "# HELP nas_sync_source_unreadable_files Files the NAS refused to read. A steady number is the known permission problem; a rising one is new."
    echo "# TYPE nas_sync_source_unreadable_files gauge"
    for k in "${!SRC_UNREADABLE[@]}"; do
      echo "nas_sync_source_unreadable_files{source=\"${k}\"} ${SRC_UNREADABLE[$k]}"
    done
    if mountpoint -q "$DEST" 2>/dev/null; then
      echo "# HELP nas_sync_destination_bytes Destination filesystem size."
      echo "# TYPE nas_sync_destination_bytes gauge"
      echo "nas_sync_destination_bytes $(df -B1 --output=size "$DEST" | tail -1 | tr -dc '0-9')"
      echo "# HELP nas_sync_destination_used_bytes Destination filesystem usage."
      echo "# TYPE nas_sync_destination_used_bytes gauge"
      echo "nas_sync_destination_used_bytes $(df -B1 --output=used "$DEST" | tail -1 | tr -dc '0-9')"
    fi
  } > "$tmp"
  chmod 0644 "$tmp"
  mv -f "$tmp" "$METRICS"
}
trap write_metrics EXIT

for entry in "${SOURCES[@]}"; do
  src="${entry%%|*}"
  extra="${entry#*|}"
  name="$(basename "$src")"
  [ -n "$ONLY" ] && [ "$ONLY" != "$name" ] && continue

  log "--- $name ---"
  start=$(date +%s)
  # NOT `$(grep -c ... || echo 0)`. grep -c prints "0" AND exits 1 when it
  # matches nothing, so that form yields the two-line string "0\n0" and every
  # later $(( )) dies with "syntax error in expression". Caught on 2026-09-09
  # by testing it rather than reading it.
  before=$(grep -c "Permission denied" "$LOG" 2>/dev/null) || before=0

  rc=0
  # shellcheck disable=SC2086
  rsync -a --delete --stats --human-readable $DRY $extra \
        -e ssh --rsync-path="$RSYNC_PATH" \
        "${NAS}:${src}" "${DEST}/" >>"$LOG" 2>&1 || rc=$?

  duration=$(( $(date +%s) - start ))
  after=$(grep -c "Permission denied" "$LOG" 2>/dev/null) || after=0
  unreadable=$(( after - before ))

  SRC_DURATION[$name]=$duration
  SRC_UNREADABLE[$name]=$unreadable

  case "$rc" in
    0)
      SRC_STATUS[$name]=$STATUS_OK
      log "$name ok in $(( duration / 60 ))m"
      ;;
    23|24)
      SRC_STATUS[$name]=$STATUS_PARTIAL
      partials=$(( partials + 1 ))
      log "$name PARTIAL in $(( duration / 60 ))m (rsync exit $rc, ${unreadable} unreadable file(s)) - not treated as a failure, see the note above"
      ;;
    *)
      SRC_STATUS[$name]=$STATUS_FAILED
      hard_failures=$(( hard_failures + 1 ))
      log "$name FAILED (rsync exit $rc), see $LOG"
      ;;
  esac
done

log "destination now: $(df -h "$DEST" | tail -1 | awk '{print $3" used, "$4" free, "$5}')"
log "inodes: $(df -i "$DEST" | tail -1 | awk '{print $3" used, "$5}')"

if [ "$hard_failures" -gt 0 ]; then
  log "=== sync finished with $hard_failures hard failure(s), $partials partial ==="
  exit 1
fi

# Only a run with no hard failures advances last_success. A partial still counts:
# the data moved, some files were skipped, and the unreadable-file metric is what
# reports that.
mkdir -p "$STATE_DIR"
date +%s > "$LAST_SUCCESS_FILE"
if [ "$partials" -gt 0 ]; then
  log "=== sync finished, $partials source(s) partial ==="
else
  log "=== sync finished cleanly ==="
fi
