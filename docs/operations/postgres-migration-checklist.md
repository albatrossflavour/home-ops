# PostgreSQL Storage Migration - Quick Checklist

**Purpose:** Migrate postgres16 from openebs-hostpath to ceph-block
**Estimated Time:** 30-45 minutes
**Downtime:** 15-30 minutes

---

## Pre-Flight Checklist

- [ ] Read full documentation: `docs/operations/postgres-storage-migration.md`
- [ ] Schedule maintenance window (notify users)
- [ ] Verify latest backup successful: `kubectl get backup -n database | tail -1`
- [ ] Check Ceph health: `kubectl exec -n rook-ceph deploy/rook-ceph-tools -- ceph status`
- [ ] Confirm 270+ GiB free on Ceph
- [ ] Have terminal ready with `kubectl get pods -n database -w` running

---

## Execution Checklist

### Phase 1: Preparation (10 min)

- [ ] **1.1** Take fresh backup
- [ ] **1.2** Verify backup completed
- [ ] **1.3** Save current state to /tmp

### Phase 2: Configuration (5 min)

- [ ] **2.1** Edit `cluster16.yaml` line 13: `openebs-hostpath` → `ceph-block`
- [ ] **2.2** Commit and push to Git

### Phase 3: Notification (2 min)

- [ ] **3.1** Notify users of maintenance window

### Phase 4: Delete (2 min) ⚠️ DOWNTIME STARTS

- [ ] **4.1** `kubectl delete cluster postgres16 -n database`
- [ ] **4.2** Verify all pods terminated

### Phase 5: Reconcile (1 min)

- [ ] **5.1** `flux reconcile kustomization cloudnative-pg --with-source`
- [ ] **5.2** Verify new cluster creating

### Phase 6: Recovery (10-20 min)

- [ ] **6.1** Monitor recovery: `kubectl get cluster postgres16 -n database -w`
- [ ] **6.2** Verify new PVCs created (ceph-block)
- [ ] **6.3** Wait for Ready: True

### Phase 7: Validation (10-15 min) 🎉 DOWNTIME ENDS

- [ ] **7.1** Check cluster healthy
- [ ] **7.2** Verify all databases present (`\l+`)
- [ ] **7.3** Check database size (~1.14 GB)
- [ ] **7.4** Test app connectivity (check logs)
- [ ] **7.5** Verify Ceph storage (no node affinity)
- [ ] **7.6** Optional: Test failover

### Phase 8: Cleanup (24+ hours later)

- [ ] **8.1** Monitor performance for 24 hours
- [ ] **8.2** Delete old PVCs (postgres16-5, -6, -9) ⚠️ ONLY AFTER 24H

---

## Quick Abort / Rollback

**Before Step 4.1:** Just don't push the Git commit

**After Step 4.1:**

```bash
# Option A: Git revert (fastest)
git revert HEAD && git push
kubectl delete cluster postgres16 -n database
flux reconcile kustomization cloudnative-pg --with-source

# Option B: Restore from S3
# See full docs: postgres-storage-migration.md section "Rollback Option C"
```

---

## Success Verification

```bash
# Quick validation script
PRIMARY=$(kubectl get cluster postgres16 -n database -o jsonpath='{.status.currentPrimary}')

echo "=== Cluster Status ==="
kubectl get cluster postgres16 -n database

echo -e "\n=== Database Count ==="
kubectl exec -n database $PRIMARY -- psql -U postgres -c "\l+" | grep -c "MB\|GB"

echo -e "\n=== Total Size ==="
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SELECT pg_size_pretty(sum(pg_database_size(datname))) FROM pg_database;"

echo -e "\n=== Active Connections ==="
kubectl exec -n database $PRIMARY -- psql -U postgres -c \
  "SELECT count(*) FROM pg_stat_activity WHERE datname IS NOT NULL;"

echo -e "\n=== Storage Class ==="
kubectl get pvc -n database | grep postgres16 | grep ceph-block | wc -l
echo "Expected: 3"
```

**Expected Results:**

- ✅ Cluster: "Cluster in healthy state"
- ✅ Database count: 10+
- ✅ Total size: ~1143 MB
- ✅ Connections: 30+
- ✅ Ceph-block PVCs: 3

---

## Emergency Contacts / Resources

- **Full Docs:** `docs/operations/postgres-storage-migration.md`
- **CloudNative-PG:** https://cloudnative-pg.io/documentation/current/recovery/
- **S3 Backup Location:** Minio bucket `cloudnative-pg` server `postgres16-v6`
- **Old PVCs:** postgres16-5 (magrat), postgres16-6 (aching), postgres16-9 (ogg)

---

**Last Updated:** 2025-10-31
**Related:** postgres-storage-migration.md
