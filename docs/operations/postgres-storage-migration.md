# PostgreSQL Storage Migration - openebs-hostpath to ceph-block

**Status:** Planned but not executed
**Created:** 2025-10-31
**Author:** System analysis (Claude Code)
**Priority:** High (enables proper high availability)

## Executive Summary

This document outlines the procedure to migrate the PostgreSQL cluster (`postgres16`) from local node storage (`openebs-hostpath`) to replicated storage (`ceph-block`). This migration is **critical for high availability** as the current configuration prevents PostgreSQL pods from failing over to different nodes during node failures.

### Key Facts

- **Current Issue:** PostgreSQL pods locked to specific nodes, cannot survive node failures
- **Data Size:** 1.14 GB across 10+ databases
- **Affected Apps:** 10 applications (Immich, Authentik, Sonarr, Radarr, Prowlarr, Gatus, N8N, Shlink, NocoDB, Resume)
- **Downtime:** 15-30 minutes estimated
- **Safety:** Very safe (9/10) - S3 backups verified, multiple rollback options
- **Storage Available:** 270 GiB free on Ceph after migration (82% free)

### Current State (As of 2025-10-31)

```bash
# Current PostgreSQL instances
postgres16-5: magrat node (openebs-hostpath) - 20Gi
postgres16-6: aching node (openebs-hostpath) - 20Gi
postgres16-9: ogg node (openebs-hostpath) - 20Gi

# Last verified backup
postgres-20251030000000: completed (22h ago)

# Active connections: 31
# Total database size: 1.14 GB
# Physical disk usage: 1.8 GB
```

## Prerequisites

### Before Starting

- [ ] Verify S3 backups are recent and successful
- [ ] Check Ceph cluster health (should be HEALTH_OK or HEALTH_WARN with known issues)
- [ ] Confirm available Ceph capacity (need 60 GiB for 3x20Gi PVCs)
- [ ] Schedule maintenance window (30-45 minutes)
- [ ] Notify users of affected applications
- [ ] Have rollback plan reviewed and ready

### Verification Commands

```bash
# Check latest backup
kubectl get backup -n database --sort-by=.metadata.creationTimestamp | tail -1

# Check Ceph health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status

# Check Ceph capacity
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph df

# List current PVCs
kubectl get pvc -n database | grep postgres16
```

## Migration Procedure

### Phase 1: Pre-Migration Preparation (10 minutes)

#### 1.1 Take Fresh Backup

```bash
# Create immediate backup
kubectl create -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: postgres-pre-migration-$(date +%Y%m%d-%H%M%S)
  namespace: database
spec:
  method: barmanObjectStore
  cluster:
    name: postgres16
EOF

# Wait for completion
kubectl wait --for=jsonpath='{.status.phase}'=completed \
  backup/postgres-pre-migration-* -n database --timeout=10m
```

#### 1.2 Verify Backup Success

```bash
# Check backup status
kubectl get backup -n database --sort-by=.metadata.creationTimestamp | tail -1

# Verify phase is "completed"
kubectl get backup postgres-pre-migration-* -n database \
  -o jsonpath='{.status.phase}'
```

#### 1.3 Document Current State

```bash
# Save current configuration
kubectl get cluster postgres16 -n database -o yaml > \
  /tmp/postgres16-before-migration-$(date +%Y%m%d-%H%M%S).yaml

# Save PVC list
kubectl get pvc -n database | grep postgres16 > \
  /tmp/postgres16-pvcs-before.txt

# Save database list and sizes
kubectl exec -n database postgres16-5 -- psql -U postgres -c "\l+" > \
  /tmp/postgres16-databases-before.txt
```

### Phase 2: Update Configuration (5 minutes)

#### 2.1 Edit Cluster Configuration

**File:** `kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml`

**Change line 13:**

```yaml
# BEFORE:
storage:
  size: 20Gi
  storageClass: openebs-hostpath

# AFTER:
storage:
  size: 20Gi
  storageClass: ceph-block
```

#### 2.2 Commit and Push

```bash
cd /Users/tgreen/dev/home-ops

git add kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml

git commit -m "feat(postgres): migrate from openebs-hostpath to ceph-block storage

Migrate PostgreSQL cluster from node-local storage (openebs-hostpath)
to replicated storage (ceph-block) to enable proper high availability
and node failover capability.

Changes:
- Update storageClass from openebs-hostpath to ceph-block
- Enables pods to failover between nodes during failures
- Data preserved via S3 backup recovery mechanism
- Pre-migration backup: postgres-pre-migration-*

Migration will:
1. Delete existing cluster pods
2. Create new PVCs using ceph-block
3. Auto-recover data from S3 (postgres16-v6)

Rollback: Revert this commit and restore from S3 or old PVCs

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>"

git push
```

### Phase 3: Notify Users (2 minutes)

```bash
# Send notification via your preferred method
# Example notification text:

echo "⚠️ MAINTENANCE WINDOW STARTING
PostgreSQL database maintenance in progress
Expected downtime: 15-30 minutes
Affected services: Immich, Authentik, Sonarr, Radarr, Prowlarr,
Gatus, N8N, Shlink, NocoDB, Resume
Start time: $(date)
Expected completion: $(date -v+30M)"
```

### Phase 4: Delete Old Cluster (2 minutes)

#### ⚠️ DOWNTIME BEGINS HERE

```bash
# Delete cluster (data preserved in S3)
kubectl delete cluster postgres16 -n database

# Monitor pod termination
kubectl get pods -n database -w
# Press Ctrl+C when all postgres16-* pods are gone
```

**Checkpoint:** Old cluster deleted, S3 backups safe, old PVCs preserved

### Phase 5: Trigger Flux Reconciliation (1 minute)

```bash
# Force Flux to apply new configuration
flux reconcile kustomization cloudnative-pg --with-source

# Watch for new cluster creation
kubectl get cluster postgres16 -n database -w
```

### Phase 6: Wait for Recovery (10-20 minutes)

#### 6.1 Monitor Recovery Progress

```bash
# Watch cluster status
watch -n 5 'kubectl get cluster postgres16 -n database'

# Monitor recovery in logs
kubectl logs -n database -l cnpg.io/cluster=postgres16 -f | \
  grep -i "recovery\|restore\|backup"
```

#### 6.2 Verify New PVCs Created

```bash
# Check new PVCs with ceph-block
kubectl get pvc -n database | grep postgres16

# Expected: postgres16-1, postgres16-2, postgres16-3 (ceph-block)
# OLD PVCs still exist: postgres16-5, postgres16-6, postgres16-9 (openebs-hostpath)
```

#### 6.3 Wait for Cluster Ready

```bash
# Wait for cluster to be ready
kubectl wait --for=condition=Ready cluster/postgres16 -n database --timeout=30m
```

**Checkpoint:** New cluster running on ceph-block

### Phase 7: Validation (10-15 minutes)

#### 🎉 DOWNTIME ENDS HERE (if validation passes)

#### 7.1 Check Cluster Health

```bash
# Verify cluster healthy
kubectl get cluster postgres16 -n database

# Expected output:
# NAME         AGE   INSTANCES   READY   STATUS                     PRIMARY
# postgres16   5m    3           3       Cluster in healthy state   postgres16-1
```

#### 7.2 Verify All Databases Restored

```bash
# Get current primary
PRIMARY=$(kubectl get cluster postgres16 -n database \
  -o jsonpath='{.status.currentPrimary}')

# List databases
kubectl exec -n database $PRIMARY -- psql -U postgres -c "\l+"

# Verify all databases present:
# app, atuin, authentik, awx, firefly, gatus, immich,
# kapowarr_main, n8n, nextcloud, etc.
```

#### 7.3 Check Database Sizes

```bash
# Verify data integrity
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SELECT pg_size_pretty(sum(pg_database_size(datname))) as total_size
   FROM pg_database;"

# Expected: ~1143 MB (should match pre-migration size)
```

#### 7.4 Test Application Connectivity

```bash
# Check connections restored
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SELECT count(*) FROM pg_stat_activity WHERE datname IS NOT NULL;"

# Expected: 30+ connections (may take a few minutes)

# Check critical app logs
kubectl logs -n security deployment/authentik-server --tail=20 | grep -i database
kubectl logs -n default deployment/immich-server --tail=20 | grep -i postgres
kubectl logs -n observability deployment/gatus --tail=20 | grep -i database
```

#### 7.5 Verify Ceph Storage

```bash
# Check PVCs on Ceph
kubectl get pvc -n database -o wide | grep ceph-block

# Verify no node affinity (can move between nodes)
for pvc in postgres16-1 postgres16-2 postgres16-3; do
  echo "=== $pvc ==="
  PV=$(kubectl get pvc $pvc -n database -o jsonpath='{.spec.volumeName}')
  kubectl get pv $PV -o jsonpath='{.spec.nodeAffinity}' || echo "No node affinity ✅"
done
```

#### 7.6 Optional: Test Failover Capability

```bash
# OPTIONAL: Test pod can move between nodes
# Only do this if you want to verify failover works

# Cordon a node
kubectl cordon magrat

# Delete primary pod to force failover
kubectl delete pod $PRIMARY -n database

# Watch failover (new primary should be elected)
kubectl get cluster postgres16 -n database -w

# Uncordon node
kubectl uncordon magrat
```

### Phase 8: Monitoring & Cleanup (24+ hours later)

#### 8.1 Monitor Performance (First 24 Hours)

```bash
# Check Ceph performance
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd perf

# Monitor application performance
# Watch for latency issues, connection errors, slow queries

# Check PostgreSQL metrics in Grafana
# Monitor active connections, query duration, cache hit ratio
```

#### 8.2 Clean Up Old PVCs (After 24-48 Hours Validation)

##### ⚠️ POINT OF NO RETURN - DO NOT RUSH THIS STEP

```bash
# ONLY after 24-48 hours of successful operation
# This permanently removes the rollback option via old PVCs

# Verify new cluster is stable first
kubectl get cluster postgres16 -n database
# Must show "Cluster in healthy state" and all apps working

# Delete old PVCs
kubectl delete pvc postgres16-5 postgres16-6 postgres16-9 -n database

# Verify cleanup
kubectl get pvc -n database | grep postgres16
# Should only show: postgres16-1, postgres16-2, postgres16-3
```

## Rollback Procedures

### Option A: Git Revert (Fastest - 5 minutes)

**Use when:** Migration fails before deleting old PVCs

```bash
# Revert the commit
git revert HEAD
git push

# Delete failed cluster
kubectl delete cluster postgres16 -n database

# Reconcile Flux (recreates with old storage)
flux reconcile kustomization cloudnative-pg --with-source

# Old PVCs automatically reattach
# Zero data loss
```

### Option B: Manual Configuration Revert

**Use when:** Need to manually control rollback

```bash
# Edit cluster16.yaml back to openebs-hostpath
# Change: storageClass: ceph-block → storageClass: openebs-hostpath

git add kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml
git commit -m "rollback: revert postgres to openebs-hostpath"
git push

# Delete cluster
kubectl delete cluster postgres16 -n database

# Reconcile
flux reconcile kustomization cloudnative-pg --with-source
```

### Option C: Restore from S3 (Nuclear Option)

**Use when:** Everything is broken, need to restore from backup

Edit `cluster16.yaml` and uncomment the bootstrap section:

```yaml
bootstrap:
  recovery:
    source: postgres16-v6

externalClusters:
  - name: postgres16-v6
    barmanObjectStore:
      destinationPath: s3://cloudnative-pg/
      endpointURL: http://minio.default.svc.cluster.local:9000
      serverName: postgres16-v6
      s3Credentials:
        accessKeyId:
          name: cloudnative-pg-secret
          key: aws-access-key-id
        secretAccessKey:
          name: cloudnative-pg-secret
          key: aws-secret-access-key
```

Then apply:

```bash
git add kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml
git commit -m "fix: restore postgres from S3 backup"
git push

flux reconcile kustomization cloudnative-pg --with-source
```

## Success Criteria

### Migration Successful When

- ✅ All postgres16-* pods show Running (3/3)
- ✅ Cluster status: "Cluster in healthy state"
- ✅ All 10+ databases present with correct sizes (~1.14 GB total)
- ✅ Applications reconnecting successfully
- ✅ Active connections count ~30+
- ✅ No errors in application logs
- ✅ Ceph performance good (<10ms latency)
- ✅ PVCs using ceph-block storage class
- ✅ No node affinity on new PVs

### Rollback Required When

- ❌ Cluster stuck in "Initializing" for >30 minutes
- ❌ Databases missing or corrupted
- ❌ Applications can't connect after 10 minutes
- ❌ Significant performance degradation (>100ms queries)
- ❌ Ceph health degraded to HEALTH_ERR
- ❌ Data size mismatch (not ~1.14 GB)

## Troubleshooting

### Issue: Cluster Stuck Initializing

```bash
# Check cluster events
kubectl describe cluster postgres16 -n database

# Check pod logs
kubectl logs -n database -l cnpg.io/cluster=postgres16 --tail=100

# Check for S3 connectivity
kubectl exec -n database postgres16-1 -- \
  curl -I http://minio.default.svc.cluster.local:9000
```

### Issue: Databases Missing After Recovery

```bash
# Check backup was actually used
kubectl logs -n database postgres16-1 | grep -i "recovery\|backup"

# List available backups
kubectl get backup -n database | grep postgres

# Verify S3 backup exists (from another pod with mc client)
# Check Minio UI at http://minio.${SECRET_DOMAIN}
```

### Issue: Performance Degradation

```bash
# Check Ceph performance
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph osd perf

# Check for slow ops
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph health detail

# Monitor PostgreSQL query times
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SELECT calls, mean_exec_time, query
   FROM pg_stat_statements
   ORDER BY mean_exec_time DESC LIMIT 10;"
```

### Issue: Applications Can't Connect

```bash
# Check service endpoints
kubectl get endpoints -n database postgres16-rw postgres16-ro

# Test connectivity from an app pod
kubectl exec -n default deployment/immich-server -- \
  nc -zv postgres16-rw.database.svc.cluster.local 5432

# Check PostgreSQL is accepting connections
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SHOW listen_addresses;"
```

## Reference Information

### Affected Applications

| Application | Namespace | Database | Criticality |
|-------------|-----------|----------|-------------|
| Authentik | security | authentik | High (auth) |
| Immich | default | immich | Medium |
| Gatus | observability | gatus | Medium |
| Sonarr | media | sonarr | Low |
| Radarr | media | radarr | Low |
| Prowlarr | media | prowlarr | Low |
| N8N | utilities | n8n | Low |
| Shlink | utilities | shlink | Low |
| NocoDB | database | nocodb | Low |
| Resume | default | resume | Low |

### Storage Comparison

| Feature | openebs-hostpath | ceph-block |
|---------|------------------|------------|
| Replication | None | 3x |
| Node Failover | ❌ No | ✅ Yes |
| Performance | Fast (local) | Good (network) |
| Capacity | Node-limited | Cluster-wide |
| HA | ❌ No | ✅ Yes |
| Backup | External (S3) | External (S3) + Ceph snapshots |

### Ceph Cluster Status (As of 2025-10-31)

```text
Total capacity: 1.5 TiB
Used: 74 GiB (4.75%)
Available: 1.4 TiB
ceph-blockpool max available: 330 GiB
After migration: 270 GiB available (82% free)

Health: HEALTH_WARN (slow ops on OSD.2, OSD.3 - residual from node failure)
Performance: 3-7ms commit/apply latency (excellent)
Replication: 3x (can survive 2 OSD failures)
```

### Useful Commands Reference

```bash
# Check cluster status
kubectl get cluster postgres16 -n database

# Get current primary
kubectl get cluster postgres16 -n database -o jsonpath='{.status.currentPrimary}'

# List backups
kubectl get backup -n database --sort-by=.metadata.creationTimestamp

# Force new backup
kubectl create -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: postgres-manual-$(date +%Y%m%d-%H%M%S)
  namespace: database
spec:
  method: barmanObjectStore
  cluster:
    name: postgres16
EOF

# Check Ceph health
kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status

# Monitor PostgreSQL connections
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SELECT * FROM pg_stat_activity WHERE datname IS NOT NULL;"
```

## Related Documentation

- [CloudNative-PG Recovery](https://cloudnative-pg.io/documentation/current/recovery/)
- [Rook-Ceph Documentation](https://rook.io/docs/rook/latest/)
- [Home-Ops Backup Recovery](../operations/backup-recovery.md)
- [Home-Ops Storage Architecture](../../CLAUDE.md#storage-architecture)

## Changelog

### 2025-10-31 - Initial Documentation

- Created migration plan based on cluster analysis
- Verified S3 backups working (last 5 days successful)
- Confirmed Ceph capacity available (270 GiB free after migration)
- Documented rollback procedures
- Status: Ready for execution when maintenance window scheduled

---

**Last Updated:** 2025-10-31
**Document Version:** 1.0
**Reviewed By:** System Analysis (Claude Code)
**Next Review:** Before execution
