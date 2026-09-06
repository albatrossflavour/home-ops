# etcd disk cache mode on the Proxmox control plane

The three control plane nodes are Proxmox VMs, and etcd's write latency is
governed by how QEMU is told to cache their system disk. Two of the three were
configured in a way that puts the host page cache directly in etcd's fsync
path. This records what was found, why it matters, and what to change.

## What triggered the investigation

`etcdHighCommitDurations` fired on weatherwax on 2026-09-06 at 21:10 UTC,
reporting a 99th percentile commit duration of 923ms against a 250ms
threshold, alongside `etcdHighFsyncDurations` at 515ms. At 2-minute resolution
the burst peaked near 1.9 seconds:

```text
time     .8.10   .8.11   .8.12
21:07       15      18      76 ms
21:09      152    1456      26 ms
21:13     1757     908     150 ms
21:15     1836     913     168 ms
21:17     1889     984     208 ms
21:21      923      94      16 ms
```

Baseline is 8-20ms, so these are bursts rather than a sick disk. They are also
not new. Over the seven days to 2026-09-06 all three members breached the
250ms threshold between 7 and 27 times per day, worst case 4058ms.

## Why it matters

etcd is unusually sensitive to fsync latency, and the cost shows up as raft
instability rather than as a slow graph. Over that same week:

| Metric | weatherwax | ogg | magrat |
| ------ | ---------- | --- | ------ |
| leader changes | 67 | 67 | 69 |
| failed proposals | 752 | 1459 | 471 |
| slow applies | 85,935 | 97,656 | 65,640 |

Roughly ten leader elections a day. A healthy etcd sits near zero. Each
election is a window where the API server cannot commit writes, which is the
mechanism behind the intermittent kube-state-metrics `/livez` failures and the
`KustomizationNotReady` bursts seen in the same period.

## What was found

`/var` is `/dev/sda6` (48GB) on all three nodes, which is `scsi0`. That is the
disk etcd writes to. Read from the running QEMU processes rather than inferred
from `qm config`:

| Node | Host | VM | `cache.direct` | `aio` |
| ---- | ---- | -- | -------------- | ----- |
| weatherwax | ankh | 300 | **false** | threads |
| ogg | morpork | 301 | true | native |
| magrat | stolat | 302 | **false** | threads |

`direct: false` means O_DIRECT is not used, so writes land in the host page
cache first and a guest fsync must push whatever has accumulated there. The
hosts allow a lot to accumulate:

```text
ankh      125G RAM, 14G available, dirty ceiling 25.1 GiB
morpork   125G RAM, 24G available, dirty ceiling 25.1 GiB
stolat     62G RAM,  2G available, dirty ceiling 12.5 GiB
```

The hardware is not the problem. `local-lvm` is local NVMe
(`/dev/nvme1n1p3`), and the guest disks sit at 7-11% busy while fsync p99
reaches 1.9 seconds. Low utilisation with a very long tail is the signature of
a caching problem, not a slow device.

All three `scsi1` disks, the 500G Ceph OSD volumes, are already correctly set
to `cache=none,aio=native`. Only the system disk kept the default.

**This is not a durability risk.** QEMU reports `no-flush: false`, so a guest
fsync does reach the physical disk. The cost is latency, not correctness.

## What the evidence does not show

Cache mode is a real contributor but not a proven sole cause. The per-node
breach counts do not separate cleanly:

```text
           .10 weatherwax   .11 ogg    .12 magrat
           (writeback)      (direct)   (writeback)
04 Sep         16              7           0
05 Sep         20              8           0
06 Sep         26             21           4
```

weatherwax has the misconfiguration and is consistently worst, which fits. But
magrat has the same misconfiguration and is currently the best, and ogg has the
correct configuration and still spikes. Host IO contention is clearly a second
factor: morpork carries roughly twenty VMs, stolat far fewer.

Treat this as removing a known-wrong setting from the path, not as a
guaranteed fix for every spike.

## The change

Align `scsi0` on VMs 300 and 302 with what VM 301 already runs, and with what
all three `scsi1` disks already run. Note the two commands differ: VM 300
carries `replicate=0` and VM 302 does not, and that must be preserved.

```bash
# on ankh
qm set 300 -scsi0 local-lvm:vm-300-disk-0,aio=native,cache=none,discard=on,iothread=1,replicate=0,size=50G,ssd=1

# on stolat
qm set 302 -scsi0 local-lvm:vm-302-disk-0,aio=native,cache=none,discard=on,iothread=1,size=50G,ssd=1
```

Cache mode only changes on a full VM power cycle, not a guest reboot, so the
setting can be staged and takes effect whenever those nodes next cycle. Talos
upgrades do that regularly.

Do one control plane node at a time, verifying etcd raft index and term stay in
sync between each, following the same procedure as the machine config applies
described in commit `e99c2822`.

To confirm afterwards, read it back from the running process rather than the
config file, since `qm config` shows the staged value whether or not it is in
effect:

```bash
ps -o args= -C kvm | tr ' ' '\n' | grep -A0 'vm-300-disk-0'
# want "cache":{"direct":true ...} and "aio":"native"
```

## A correction, and what came after

An earlier version of this document said Talos upgrades would apply the cache
mode change "naturally". They do not. A Talos upgrade reboots the guest OS;
the QEMU process on the host keeps running and holds the disk backend it
opened at launch. Proof: on 2026-09-07 the QEMU processes for VMs 300 and 301
had been running since **29 December 2025**, while the guests inside them last
booted on 31 August 2026, having been through several Talos upgrades in
between.

Applying it needs the QEMU process restarted, which means `qm shutdown` then
`qm start`, or `qm reboot` at the Proxmox level. Nothing initiated from inside
Talos will do it. The hypervisor itself never needs to go down.

The [Proxmox health audit](./proxmox-health-audit.md) later found two things
that bear on the latency more than cache mode does: the `pve` volume groups on
ankh and morpork are worn QLC DRAM-less drives at 143% and 150% of rated
endurance, and ankh was carrying a year-old LVM snapshot of the control plane
VM that was doubling its write load through copy-on-write. The snapshot was
removed on 2026-09-07.

## Related

This configuration lives on the Proxmox hosts, not in this repository, so
nothing here enforces it. If a control plane VM is ever rebuilt, check
`scsi0` again.

Host memory pressure is a separate and genuine problem. stolat sitting at 2G
available of 62G is what `NodeMemoryHighUtilization` has been reporting since
2026-09-02. It is a true alert, and low available memory makes host page cache
behaviour worse, so the two interact.

## etcd snapshots

`task talos:maintenance:etcd-snapshot` takes a verified snapshot and writes it
to the NAS.

This cluster is GitOps-managed, so a snapshot is not what makes it
recoverable. Everything under `kubernetes/` is rebuilt by Flux and PVC data is
covered by Volsync. What a snapshot buys is speed, plus the things git does
not hold: resource UIDs, cert-manager state, and Volsync replication state. It
is also the only way back from etcd corruption that raft cannot repair, which
is not hypothetical given the leader-election rate above.

```bash
task talos:maintenance:etcd-snapshot                       # default node, NAS
task talos:maintenance:etcd-snapshot node=192.168.8.11     # from a follower
task talos:maintenance:etcd-snapshot keep=30               # deeper retention
```

Measured 2026-09-06: 425MB, about 6 seconds, 16705 keys. A snapshot is a local
read of one member's bbolt file, so it does not need the leader and does not
disturb raft, but it does read the whole database.

### Where it writes, and the guard that matters

`/mnt/nas-backups/etcd`, which is `192.168.1.22:/volume2/Backups` on the
Synology, the same share family backups already use. The `/etc/fstab` entry
carries `nofail` and `_netdev` so a NAS outage cannot block boot:

```text
192.168.1.22:/volume2/Backups  /mnt/nas-backups  nfs  vers=3,soft,timeo=100,retrans=3,_netdev,nofail  0  0
```

The task refuses to run if that path is not a mount point. Without the guard,
writing to an unmounted `/mnt/nas-backups/etcd` silently creates a local
directory, reports success, and fills the workstation disk while looking
exactly like a working backup. Verified by pointing the task at a plain
directory: it fails the precondition and writes nothing.

Not in `task backup:create`, which pushes to the 1Password `discworld` vault.
That suits `age.key` and `config.yaml`; a 425MB snapshot does not belong
there.

Retention keeps the newest 14, roughly 6GB against 3.5TB free.

### Still manual

This is a task, not a schedule. Automating it in-cluster would mean putting
`talosconfig` into a Kubernetes Secret, and that credential is node-level root
across the whole control plane, so it is a security decision rather than a
plumbing one. A timer on a trusted host is the lower-risk option if scheduling
is wanted.
