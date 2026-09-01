# Ceph CSI cephx Key Rotation

Procedure for bumping the `csi.keyGeneration` in `kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml`. This is the credential every kernel RBD client (`krbd`) on every node presents to OSDs. The rotation itself is a one-line change; the step everything else in this doc exists to protect is the one that got skipped on 2026-08-28.

## Why the restart step exists

A rotation only issues a new key — it doesn't do anything to a pod's already-mapped RBD device. The kernel client keeps the session it had, presenting the *old* generation's ticket, and that keeps working right up until it actually needs to re-authenticate — which happens the next time an OSD it talks to restarts. At that point the OSD rejects the stale ticket (`libceph: auth protocol 'cephx' authorization to osd failed: -13`), and the pod's write path silently wedges.

That's exactly what happened 2026-08-29: `keyGeneration` was bumped on the 28th, nothing using RBD got restarted, and `postgres16-2` (on `ogg`, RBD-mapped since before the rotation) sat with a stale session for a day until `osd.3` came back from a routine reboot and rejected it. 8.5 hours of SSO outage followed — see the incident log in [[home-ops-cluster-audit-2026-08]] for the full cascade. Ten other pods across three other nodes were carrying the same stale mapping and would have failed the same way; they were restarted by hand once the pattern was understood, not because anything detected it.

There is still no automated alert for this condition — Ceph itself reports `HEALTH_OK` throughout, because the failure is entirely client-side. This runbook's restart step, and the check script below, are what stand in for that alert today.

## Procedure

### 1. Bump the generation

Edit `kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml`, under `cephClusterSpec.security.cephx.csi`:

```yaml
keyGeneration: 7 # was 6
```

`keyGeneration` must only ever increase — Ceph's CRD validation rejects a decrease, which puts `rook-ceph-cluster` into a failed-upgrade/rollback loop with no valid rollback target and blocks every dependent app via `dependsOn`. If that happens, the only way out is forward: bump again.

Commit and push.

### 2. Reconcile and confirm the rotation applied

```bash
flux reconcile helmrelease rook-ceph-cluster -n rook-ceph
kubectl -n rook-ceph exec deploy/rook-ceph-tools -- ceph auth get client.csi-rbd-node
```

Confirm the key material actually changed (compare against what you had before, or just confirm the command succeeds cleanly with no CRD validation error).

### 3. Capture a CSI restart-count baseline

`CephCluster` health (`ceph -s`) doesn't cover this — a rotation can also destabilize the CSI node-plugin pods themselves, not just leave client mappings stale. One crash observed during the 2026-08-28 incident was a fatal apiserver timeout in a cephfs node-plugin that the driver treated as unrecoverable, not the stale-mount failure mode the rest of this runbook is built around. There was no fresh `keyGeneration` bump to confirm the pattern against as of 2026-09-01 (the prior restart counts had already been reset to 0 by an unrelated CSI image-pin rollout), so this is unverified as a repeatable pattern — capture a baseline every time so the next rotation actually tests it:

```bash
kubectl get pods -n rook-ceph --no-headers | grep csi.*nodeplugin | awk '{print $1, $4}'
```

### 4. Find every pod carrying a stale mapping

```bash
./scripts/check-stale-cephx-mounts.sh
```

This compares every RBD-backed (`ceph-block` storage class) pod's start time against the git commit date of the `csi.keyGeneration` line just changed in step 1, and lists any pod that started before the rotation — i.e. every pod that has *not* remapped its RBD device since. Exits non-zero if any are found.

### 5. Restart every pod the script flags

This is the step that was missing on 2026-08-28. For each flagged pod, restart its owning workload so the RBD device remaps with the current key:

```bash
kubectl -n <namespace> rollout restart deployment/<name>   # or statefulset/<name>
```

For CloudNativePG-managed Postgres instances specifically, prefer a controlled switchover over a raw restart if the flagged pod is the current primary — check `kubectl -n database get cluster postgres16` for the current primary before touching it.

### 6. Re-run the check, and compare the restart-count baseline

```bash
./scripts/check-stale-cephx-mounts.sh
```

Confirm it reports no stale mounts before considering the rotation done. Don't skip this even if step 5 "looked like" it worked — a rollout that silently didn't trigger (unchanged pod spec, a stuck PDB, whatever) is exactly the kind of gap this whole procedure exists to catch.

Also re-run the same command from step 3 and diff against the baseline:

```bash
kubectl get pods -n rook-ceph --no-headers | grep csi.*nodeplugin | awk '{print $1, $4}'
```

Any node-plugin pod with a restart count higher than its step 3 baseline crashed during this rotation — check its logs for the apiserver-timeout crash pattern from 2026-08-28 before writing it off as unrelated. Feed the result back into [[home-ops-cluster-audit-2026-08]] (the "CSI restart/keyGeneration correlation" finding) either way, whether or not anything crashed — this is the data point that finding has been missing.

## Related

- [[home-ops-cluster-audit-2026-08]] — the 2026-08-29 incident this runbook exists because of.
- `kubernetes/apps/rook-ceph/rook-ceph/cluster/helmrelease.yaml` — the cephx block itself, including why `keyType` is pinned to `aes` (not `aes256k`) until Talos ships a Linux 7.0+ kernel.
