#!/usr/bin/env bash
# One-off: partition, format and mount the NAS backup disk on ankh.
#
# Replaces the single-disk ZFS pool that used to live here. ZFS bought
# checksumming it could never repair (single vdev, copies=1) and cost the host
# an unbounded ARC: zfs_arc_max was unset, so ARC could grow to 124.6G of
# ankh's 125G, which is the likely cause of the host sitting at 93-98% memory
# through late August.
#
# ext4 with the NAS as the source of truth. If a file is bad, re-sync it.
#
# Safe to re-run: refuses to touch a disk that already has a filesystem.

set -euo pipefail

DISK_ID="ata-WUH721816ALE6L4_2BJGTYTN"
DISK="/dev/disk/by-id/${DISK_ID}"
PART="${DISK}-part1"
MOUNT="/nas-backup"
LABEL="nas-backup"

die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "must run as root"
[ -b "$DISK" ] || die "$DISK not found"

echo "Target: $DISK"
lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINTS "$DISK"
echo

# Refuse if anything is already on it. This is the guard that stops a re-run
# eating a populated disk.
if lsblk -no FSTYPE "$DISK" | grep -q .; then
  die "$DISK already carries a filesystem. Refusing. Wipe it deliberately first."
fi
if mountpoint -q "$MOUNT" 2>/dev/null; then
  die "$MOUNT is already mounted. Refusing."
fi

read -r -p "Partition and format ${DISK}? Everything on it is destroyed. [type YES] " ans </dev/tty
[ "$ans" = "YES" ] || { echo "aborted"; exit 1; }

echo "==> partitioning"
sgdisk --zap-all "$DISK" >/dev/null
sgdisk --new=1:0:0 --typecode=1:8300 --change-name=1:"$LABEL" "$DISK" >/dev/null
partprobe "$DISK"
udevadm settle
[ -b "$PART" ] || die "$PART did not appear after partprobe"

echo "==> formatting ext4"
# -m 0          drop the 5% root reserve; on 14.6T that is ~730G back
# -T largefile  one inode per 1MB rather than per 16KB. ~15M inodes instead of
#               ~977M, so mkfs takes minutes not hours and the inode tables do
#               not cost hundreds of GB. Suits Media/photos/Plex; check
#               `df -i` after the first full sync, since Backups holds git and
#               icloud trees that skew small.
mkfs.ext4 -m 0 -T largefile -L "$LABEL" "$PART"

echo "==> mounting at $MOUNT"
mkdir -p "$MOUNT"
UUID="$(blkid -s UUID -o value "$PART")"
[ -n "$UUID" ] || die "could not read UUID from $PART"

# by UUID, not device path: device letters shuffle across reboots, which has
# already bitten this estate once when NVMe names swapped on morpork.
if ! grep -q "$UUID" /etc/fstab; then
  cp /etc/fstab "/etc/fstab.bak-$(date +%Y%m%d-%H%M%S)"
  echo "UUID=$UUID  $MOUNT  ext4  defaults,noatime,nofail  0  2" >> /etc/fstab
  echo "    fstab entry added"
fi
systemctl daemon-reload
mount "$MOUNT"

mountpoint -q "$MOUNT" || die "$MOUNT failed to mount"
echo
echo "Done."
df -h  "$MOUNT" | tail -1
df -i  "$MOUNT" | tail -1
echo
echo "Next: run /root/sync.sh to populate it."
