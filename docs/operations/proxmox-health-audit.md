# Proxmox health audit

Estate-wide audit of the three Proxmox hosts, 2026-09-07. Recorded because
several findings need action over weeks rather than minutes, and one of them
reframes the etcd latency investigation in
[etcd disk cache mode](./etcd-disk-cache-mode.md).

All three hosts run pve-manager 9.0.4 on kernel 6.14.8-2-pve, clustered and
quorate with 3 votes.

## Hardware

| Host | Cores | RAM | NVMe | Other |
| ---- | ----- | --- | ---- | ----- |
| ankh | 28 | 125 GiB | Samsung 990 PRO 2TB (Ceph), Crucial CT1000P3SSD8 1TB (`pve`) | WD Ultrastar 16TB HDD (ZFS) |
| morpork | 28 | 125 GiB | Samsung 990 PRO 2TB (Ceph), Crucial CT1000P3SSD8 1TB (`pve`) | none |
| stolat | 12 | 62 GiB | Samsung 990 PRO 2TB (Ceph), Samsung 970 EVO Plus 250GB (`pve`) | 16TB HDD |

The `pve` volume group is what matters here. It carries the Proxmox host root
and swap, every VM system disk on that host, and on ankh and morpork it also
carries the Kubernetes rook-ceph OSD volumes.

So the Kubernetes storage layer sits on the cheaper drive while the Samsung
990 PRO serves the separate *Proxmox* Ceph cluster. That is where the bulk of
the write volume below comes from.

## Finding 1: two NVMe drives are past rated endurance

```text
host      drive                        type            % used   TB written   POH
ankh      Crucial CT1000P3SSD8         QLC, no DRAM      143%     158 TB     18,210
morpork   Crucial CT1000P3SSD8         QLC, no DRAM      150%     172 TB     18,385
stolat    Samsung 970 EVO Plus 250GB   TLC, DRAM          36%     146 TB     18,267
```

Similar power-on hours and similar total writes across all three, so the
difference is drive class rather than workload. Roughly 80 TB/year each.

**They are not failing.** `Percentage Used` is a warranty counter, not a
failure predictor, and every actual health indicator is clean on both:

```text
Available Spare:                  100%   (threshold 5%)
Media and Data Integrity Errors:  0
Error Information Log Entries:    0
Critical Warning:                 0x00
```

Budget for replacement; do not treat it as urgent. If replacing, note the
requirement is about 500 GB usable, not 2 TB: ankh's thin pool is 794 GB at
43% and morpork's is 810 GB at 44%. A DRAM-less QLC drive is the wrong class
for sync-heavy work, so the replacement wants TLC with DRAM, or secondhand
enterprise M.2 with power-loss protection.

## Finding 2: a year-old snapshot on ankh (resolved)

ankh was the only host in the estate carrying any snapshot: a `pre-upgrade`
snapshot of VM 300 (weatherwax) taken **2025-09-06**, covering both disks.

```text
snap_vm-300-disk-0_pre-upgrade    50.00g   <- etcd system disk
snap_vm-300-disk-2_pre-upgrade   500.00g   <- rook-ceph OSD disk
```

LVM thin snapshots force copy-on-write: every write to the origin preserves
the old block first. Both volumes see constant writes, etcd on one and a Ceph
OSD on the other, so this had been roughly doubling the write load on an
already-worn QLC drive for twelve months.

It also explains a result that drive class could not. Comparing etcd commit
latency over ten days:

| Host | Snapshot | `pve` drive | commit p99 | windows >250ms |
| ---- | -------- | ----------- | ---------- | -------------- |
| ankh | **yes** | Crucial P3 (143%) | 985 ms | 7.5% |
| morpork | no | Crucial P3 (150%) | 836 ms | 4.1% |
| stolat | no | Samsung 970 EVO (36%) | 505 ms | 2.2% |

morpork's drive is *more* worn than ankh's and performs better. The snapshot
is the variable that separates them.

Rolling it back would have restored a year-old etcd member into a live raft
cluster, so it carried no recovery value. Removed 2026-09-07:

```text
thin pool data:      54.40%  ->  43.03%   (~90 GB reclaimed)
thin pool metadata:   2.24%  ->   1.89%
```

Worth re-measuring weatherwax's commit p99 over the following week. It is the
cheapest of the three mitigations and may be the largest.

## Finding 3: memory overcommit on every host

```text
host      running guests   physical   overcommit
ankh          206 GiB       125 GiB      165%
morpork       131 GiB       125 GiB      105%
stolat         95 GiB        62 GiB      153%
```

Swap is 100% full on all three (8 GiB of 8 GiB), and swap lives on the `pve`
VG, which on ankh and morpork means the worn Crucial drives.

It is not currently thrashing. Live `si`/`so` is approximately zero and memory
PSI avg60 reads 0.00 to 0.14, so those are pages parked during a past event
and never touched since. KSM is carrying a lot of the load: 9.1 GB
deduplicated on ankh, 13 GB on morpork.

There is no headroom though. stolat has 2.3 GiB available of 62 GiB, which is
what `NodeMemoryHighUtilization` has been reporting since 2026-09-02. That
alert is true.

## Finding 4: backup coverage

The vzdump job covers eight guests: `102, 500, 501, 502, 503, 700, 851,
91001`, to the PBS datastore at 62% of 1 TB.

Excluding roughly 35 templates, about 25 real guests are uncovered. Most are
defensible: the Talos nodes are cattle rebuilt from `talconfig.yaml`, the
puppet lab VMs are disposable, and VM 201 is the PBS server itself.

One is not. **LXC 700 (pihole) is backed up while 701 and 702 (pihole1,
pihole2) are not.** Same role, same importance, no apparent reason.

Backing up the rook-ceph OSD volumes is deliberately *not* wanted, and that is
correct. A vzdump of one OSD is a fragment of a striped, replicated store; it
cannot be safely restored, and the recovery path for a lost OSD is to remove
it and let Ceph backfill. The `backup=0` flags on those disks are right, even
though they are currently inert because none of those VMs are in the job.

## Finding 5: patch debt

```text
ankh     332 pending updates    uptime 37 weeks
morpork  313 pending updates    uptime 37 weeks
stolat   285 pending updates    uptime  7 weeks
```

No `reboot-required` flag is set, but nine months of uptime with 300+ pending
packages means no kernel security fixes have landed either.

Convenient timing: the `scsi0` cache mode changes staged on VMs 300 and 302
need a full VM power cycle to take effect, so a rolling host update and reboot
applies both in one window.

## Healthy

- ZFS pool on ankh `ONLINE`, 10.1T of 14.5T used, 5% fragmentation.
- Proxmox Ceph `HEALTH_OK` on all three.
- Corosync quorate, 3 votes.
- Zero failed systemd units on any host.
- No SMART errors, no media errors, `Available Spare` 100% everywhere.
- Storage pools between 13% and 70% used.

## Suggested order

1. **Delete the stale snapshot.** Done 2026-09-07. Re-measure before spending
   anything.
2. **Apply the etcd `election-timeout` change** from
   [etcd disk cache mode](./etcd-disk-cache-mode.md). Removes 84% of the
   stalls that can trigger a leader election and costs nothing.
3. **Roll host updates with reboots**, one node at a time, which also applies
   the staged `cache=none` change.
4. **Re-measure.** If commit p99 has come down, no hardware purchase is
   needed.
5. Reduce overcommit on stolat, and add LXC 701/702 to the backup job or
   record why they differ from 700.
