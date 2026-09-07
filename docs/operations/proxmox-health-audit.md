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
host      drive                        serial            % used   TB written   POH
ankh      Crucial CT1000P3SSD8         240646E767DB        143%     158 TB     18,210
morpork   Crucial CT1000P3SSD8         240646E76700        150%     172 TB     18,385
stolat    Samsung 970 EVO Plus 250GB   S4EUNX0R715109T      36%     146 TB     18,267
```

Both Crucial drives are QLC with no DRAM cache; the Samsung is TLC with DRAM.

**Identify these by serial, never by device name.** NVMe enumeration is not
stable across reboots. Observed on 2026-09-07: before morpork's reboot the
Crucial was `/dev/nvme1n1` and the Samsung 990 PRO was `/dev/nvme0n1`;
afterwards they had swapped. Anything that pins a drive to `nvme0n1` will
eventually be pointing at the wrong disk.

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

LXC 700 (pihole) is backed up while 701 and 702 (pihole1, pihole2) are not,
which looked like an oversight. It is not: **701 and 702 are clones of 700**.
Backing up one of three identical clones is the correct call, and backing up
all three would triple the cost for nothing. No action needed.

Backing up the rook-ceph OSD volumes is deliberately *not* wanted, and that is
correct. A vzdump of one OSD is a fragment of a striped, replicated store; it
cannot be safely restored, and the recovery path for a lost OSD is to remove
it and let Ceph backfill. The `backup=0` flags on those disks are right, even
though they are currently inert because none of those VMs are in the job.

## Finding 5: corosync runs one link, over the VM bridge

The cluster heartbeat has no redundancy, and two of three nodes carry it on
the bridge that also carries all guest traffic.

```text
ankh     ring5_addr 192.168.5.10  ->  vmbr0    (VM bridge, ~11 guests)
morpork  ring5_addr 192.168.5.11  ->  vmbr0    (VM bridge, ~19 guests)
stolat   ring5_addr 192.168.6.12  ->  enp7s0   (dedicated NIC, no guests)
```

`totem` declares two `interface` blocks, linknumber 5 and 0. Under knet those
are corosync-2 legacy and are ignored: link addresses come from the nodelist's
`ringX_addr` entries, and no node has a `ring0_addr`. So link 0 does not
exist. `corosync-cfgtool -s` and `-n` both report LINK 5 only. The giveaway
that those blocks are dead is that link 5's `bindnetaddr` is `192.168.6.0`
while ankh and morpork use `192.168.5.x`.

This matters because HA is live with fencing armed:

```text
fencing armed (CRM watchdog active), softdog
lrm morpork  watchdog active    vm:501, vm:503
lrm stolat   watchdog active    vm:502
```

A traffic burst on `vmbr0` that delays heartbeats past the token timeout costs
quorum, and the watchdog hard-resets the node. On morpork that takes roughly
nineteen guests with it, including a Kubernetes control plane node and a Ceph
OSD.

The second path already exists and is idle. Every host has a dedicated NIC on
`192.168.6.x` carrying no guest traffic, and it is clean: 0.21-0.23ms between
all three. Moving corosync onto it and keeping `192.168.5.x` as a second link
gives a quiet primary plus a fallback.

## Finding 6: no hypervisor has working UPS shutdown protection

All three run `upsmon` as a netclient, and none of them can talk to a UPS.

```text
ankh     /etc/nut/upsmon.conf MISSING (only .dpkg-dist)   service failed
morpork  config present, service running                  connect fails every 8s
stolat   config present                                   service not running
```

All three pointed at `pr1000elcd@192.168.2.143`, which is unreachable from the
hypervisor networks - routed via the gateway and returning `No route to host`.
morpork's `upsmon` had been logging connect failures continuously.

The UPS is reachable, just at a different address. `192.168.5.50`
(`nut.albatrossflavour.com`) has port 3493 open and serves the same device:

```text
pr1000elcd   model PR1000ELCD   status OL   battery 100%   load 52%
```

That is the host feeding the `network_ups_tools_ups_status` metric behind the
`UPSOnBattery` alert, so UPS *monitoring* works. What does not work is UPS
*shutdown*, which is a separate mechanism and the one that matters during a
power cut.

Repointing morpork at `192.168.5.50` got past the routing problem and hit the
real cause:

```text
Login on UPS [pr1000elcd@192.168.5.50] failed - got [ERR ACCESS-DENIED]
```

`upsd.users` on the NUT server defined `[upsmon_local]` with a password,
`actions` and `instcmds`, but **no `upsmon` directive at all**. upsd only
accepts a `LOGIN` from a user carrying that role, so every upsmon login was
rejected - including the NUT server's own, which had been failing since at
least 15 July:

```text
Jul 15 08:57:06 nut nut-monitor: Login on UPS [pr1000elcd@nut...] failed
                                 - got [ERR ACCESS-DENIED]
```

Nothing in the estate had working UPS shutdown. `upsc` needs no auth, which is
why status reads, the Prometheus metric and the `UPSOnBattery` alert all
looked healthy while the shutdown path was dead. That is the same trap as the
pushgateway and the QEMU cache mode: the visible signal was fine and the
mechanism behind it was not.

### Resolution, 2026-09-07

One line on the NUT server:

```text
[upsmon_local]
        upsmon primary      <- added
        password = ...
        actions = SET
        instcmds = ALL
```

Then on the hypervisors: all three repointed from the unreachable
`192.168.2.143` to `192.168.5.50`, `upsmon.conf` recreated on ankh from
morpork's working copy, and `systemctl enable --now nut-monitor` on all three.
The `enable` matters as much as the start: the unit was `disabled` at boot on
every host, so even morpork's running instance would not have survived a
reboot.

```text
ankh     enabled/active  denied=0  ups=OL
morpork  enabled/active  denied=0  ups=OL
stolat   enabled/active  denied=0  ups=OL
nut      enabled/active  denied=0
```

Verified over a sustained window rather than at the moment of restart, since
the old failure recurred every 8 seconds and would have shown up.

This reframes the unsafe shutdown counts, 69 on ankh and 39 on morpork's
Crucial. Those were not bad luck.

## Finding 7: patch debt

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

## Alerting and mail (done 2026-09-07)

`NvmeAvailableSpareLow` (warning, below 90%) and `NvmeAvailableSpareCritical`
(critical, at or below the drive's own published threshold) now exist in
`custom-alerts`. Endurance is deliberately not alerted on: it is a warranty
counter that only climbs, and two drives are already past 100%, so a rule on
it would fire permanently while saying nothing new. Available spare is the
metric that actually predicts failure, and every drive still reads 100%, so
any movement is genuinely new information.

Note the alerts label by `device`, which as above is not stable across
reboots. They still identify the correct host, and `smartctl` gives the serial.

Postfix on all three hypervisors now relays through the cluster's
`smtp-relay` LoadBalancer at `192.168.8.24:25`, and `root` is aliased to a
real address. smartd sends to `root`, so without the alias its warnings landed
in a local mailbox nobody reads. Direct-to-MX delivery had been working but
slowly, at 462s of queue delay against 0.06s through the relay.

## Roadmap: the 192.168.6.0/24 subnet collision

Two VLANs share one subnet. From the network diagram:

```text
VLAN 3   192.168.6.0/24   Cameras Network
VLAN 6   192.168.6.0/24   CEPH Network
```

**Benign today, verified rather than assumed.** The Ceph network is isolated
on the Proxmox nodes: no gateway on any of the three interfaces, and the only
reachable neighbours are the other two hypervisors.

```text
ankh     enp8s0  no gateway  neighbours 6.11, 6.12   REACHABLE
morpork  enp8s0  no gateway  neighbours 6.10, 6.12   REACHABLE
stolat   enp7s0  no gateway  neighbours 6.10, 6.11   REACHABLE
```

No route exists between the two VLANs, so nothing has broken and nothing is
expected to. One wrinkle: stolat also carries STALE ARP entries for
`192.168.5.10` and `192.168.5.11` on its Ceph NIC. Those are management
addresses, and they are there because stolat's corosync link is the only one
using the Ceph network, so it talks to peers on management from that NIC. It
resolves itself once corosync is made symmetric.

### Which side to renumber

By the estate's own convention, VLAN *n* maps to `192.168.n.0/24`. On that
reading Ceph on VLAN 6 with `192.168.6.0/24` is the correct one, and Cameras
on VLAN 3 with `192.168.6.0/24` is the anomaly that should be
`192.168.3.0/24`.

The practical argument runs the other way. Renumbering Ceph touches three
addresses on three hypervisors; renumbering cameras touches every camera. That
is the preferred direction, at the cost of Ceph no longer matching the
VLAN-to-subnet convention. Worth deciding deliberately rather than by
whichever is easiest on the day.

### Scope, if Ceph moves

Smaller than it first appears. `192.168.6.0/24` is used **only** as the Ceph
`cluster_network`, which is OSD-to-OSD replication. Monitors and client
traffic are elsewhere:

```text
cluster_network = 192.168.6.12/24
public_network  = 192.168.9.12/24
mon_host        = 192.168.9.10 192.168.9.11 192.168.9.12
```

So the work is three interface addresses in `/etc/network/interfaces`, one
line in `/etc/pve/ceph.conf`, and an OSD restart per node. No monitor
reconfiguration, which is the part that would normally make this risky.

### Sequencing: three phases, Ceph before corosync

The obvious order is corosync first, then Ceph. That is wrong, because the
planned second corosync link is *on* the Ceph network: configure corosync
first and it has to be redone once Ceph moves.

Doing Ceph first has its own snag, since stolat's current corosync link is
`192.168.6.12`, so readdressing Ceph pulls the address out from under it.

Three phases resolve both:

1. ~~**Minimal corosync fix.**~~ Done 2026-09-07 at `config_version: 14`.
   stolat's `ring5_addr` moved from `192.168.6.12` to `192.168.5.12`, and both
   stale `interface` blocks removed. All three links now run on
   `192.168.5.x`, so corosync no longer touches the Ceph network. It cost an
   unplanned loss of quorum on the way; see the two subsections above for what
   went wrong and why the recovery is straightforward.
2. **Ceph readdress.** Now purely a Ceph and migration operation with nothing
   depending on it.
3. **Add the second corosync link** on the final Ceph addresses, configured
   once rather than twice.

### Full scope of the readdress

Four touchpoints, not two. The migration network is easy to miss:

```text
/etc/network/interfaces   three interface addresses, one per host
/etc/pve/ceph.conf        cluster_network = 192.168.6.12/24
/etc/pve/datacenter.cfg   migration: network=192.168.6.10/24,type=secure
/etc/pve/corosync.conf    stolat ring5_addr (removed by phase 1 above)
```

Plus a rolling restart of three OSDs, one per node, with `noout` set. Roughly
an hour. No monitor reconfiguration, because mons and `public_network` are on
`192.168.9.x`, which is the part that would normally make this risky.

### Editing corosync safely

Fencing is armed with `softdog`, so any corosync edit needs HA stopped first
or a node that fails to rejoin will hard-reset itself. Verified procedure:

```bash
# on every node, in this order
systemctl stop pve-ha-lrm     # wait for all three
systemctl stop pve-ha-crm

# confirm nothing can fence: this must be inactive on EVERY node
systemctl is-active pve-ha-lrm

# ... edit corosync, bump config_version ...

systemctl start pve-ha-crm    # reverse order
systemctl start pve-ha-lrm
```

Two checks that do **not** work, both learned the hard way:

`ha-manager status` keeps reporting "fencing armed" from a stale status file
after the services stop.

`ls /run/watchdog-mux.active/ | wc -l` reads 0 whether HA is armed or not, so
it cannot distinguish the two states. It was used as the safety gate on
2026-09-07 and proved nothing. `watchdog-mux` holds `/dev/watchdog` open
permanently regardless of HA state; it is the LRM that arms fencing, so
`systemctl is-active pve-ha-lrm` is the check that means something.

### Corosync will not change a link address on reload

Editing `ring5_addr` and bumping `config_version` distributes the file and
corosync accepts it, but refuses to apply it:

```text
[TOTEM] new config has different address for link 5
        (addr changed from 192.168.6.12 to 192.168.5.12).
        Internal value was NOT changed.
[CFG  ] Cannot configure new interface definitions: To reconfigure an
        interface it must be deleted and recreated. A working interface
        needs to be available to corosync at all times
```

So the config and the running state silently diverge until corosync restarts.
Plan on restarting it, and check `corosync-cfgtool -n` for the addresses
actually in use rather than trusting the file.

### The `interface` blocks are NOT ignored

An earlier version of this document claimed the `totem` `interface` blocks
were corosync-2 legacy that knet ignores. That is wrong, and it caused an
outage on 2026-09-07.

Corosync uses `bindnetaddr` to match a node's ring address to a link at
**startup validation only**, which is why a running cluster never complains.
The config carried two blocks, `linknumber: 5` on `192.168.6.0` and
`linknumber: 0` on `192.168.5.0`. Moving stolat's `ring5_addr` from
`192.168.6.12` to `192.168.5.12` made it match the `linknumber: 0` block while
the other two still matched `linknumber: 5`, so corosync refused to start:

```text
[MAIN] parse error in config: Not all nodes have the same number of links
```

With knet and explicit `ringX_addr` entries the blocks serve no purpose. Both
were removed at `config_version: 14`, and the cluster is healthier for it.

### Recovering a cluster that has lost quorum

Once quorum is gone `/etc/pve` is read-only, so corosync cannot be fixed
there. Corosync reads `/etc/corosync/corosync.conf`, a real local file on each
node, which stays writable. Fix that copy on every node, restart corosync,
and once quorum returns copy it back to `/etc/pve/corosync.conf` so the two do
not diverge.

Guests are unaffected throughout. During the 2026-09-07 outage every VM and
container kept running, including the whole Kubernetes cluster; it is a
control-plane outage only.

### Adjacent observation

`public_network` and `mon_host` sit on `192.168.9.0/24`, the VM Network, which
carries every guest on the estate. Ceph client and monitor traffic sharing the
busiest network is a larger performance question than the subnet collision,
and is worth its own look rather than being folded into this change.

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
5. Reduce overcommit on stolat. LXC 701/702 need no backup change, they are
   clones of 700.
6. ~~Fix UPS shutdown~~. Done 2026-09-07, see Finding 6.
7. Corosync and Ceph networking, in the three-phase order set out above:
   stolat's ring address onto management first, then the Ceph readdress, then
   the second corosync link. Higher risk than the rest of this list, since a
   botched corosync change splits a cluster. Stop HA first, bump
   `config_version`, and verify with `corosync-cfgtool -n` that every link
   shows connected before trusting it.

Parked: replacing the two Crucial P3s. They are past rated endurance but
`Available Spare` is still 100% with zero media errors on both, and the
`NvmeAvailableSpareLow` alert now watches the metric that actually predicts
failure. Revisit if that fires.
