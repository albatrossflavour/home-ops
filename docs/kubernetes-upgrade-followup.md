# Kubernetes v1.33.7 Upgrade Follow-up Tasks

**Upgrade Path**: v1.30.3 → v1.31.14 → v1.32.11 → v1.33.7
**Date Completed**: December 27, 2025 ✅
**Current Status**: All 6 nodes running Kubernetes v1.33.7

## 🎯 Immediate Verification Tasks

### 1. Verify Upgrade Completion

```bash
# Check all nodes running v1.33.7
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion

# Full cluster health check
task talos:maintenance:verify

# Check for any stuck pods
kubectl get pods -A | grep -v Running | grep -v Completed
```

### 2. Check Ceph Cluster Health

```bash
kubectl exec -n rook-ceph deployment/rook-ceph-tools -- ceph status
kubectl exec -n rook-ceph deployment/rook-ceph-tools -- ceph osd tree
kubectl exec -n rook-ceph deployment/rook-ceph-tools -- ceph pg stat
```

### 3. Verify Flux Reconciliation

```bash
flux get kustomizations | grep -v "True.*True"
```

## 🆕 New Features to Consider (v1.31-v1.33)

### HIGH PRIORITY

#### 1. Native Sidecar Containers (v1.33 Stable) ⭐

**Impact**: Home Assistant Matter server, code-server sidecars
**Benefit**: Proper lifecycle management, probes support, better ordering

**Current setup** (multi-container pattern):

```yaml
# kubernetes/apps/default/home-assistant/app/helmrelease.yaml
controllers:
  home-assistant:
    containers:
      app: # main HA
      matter-server: # sidecar
      code-server: # sidecar
```

**New sidecar pattern**:

```yaml
controllers:
  home-assistant:
    initContainers:
      matter-server:
        image: ghcr.io/home-assistant-libs/python-matter-server:stable
        restartPolicy: Always  # Makes it a sidecar
        ports:
          - name: websocket
            containerPort: 5580
        readinessProbe:
          tcpSocket:
            port: 5580
          initialDelaySeconds: 5
      code-server:
        image: ghcr.io/coder/code-server:latest
        restartPolicy: Always
        ports:
          - name: http
            containerPort: 8080
    containers:
      app:
        image: ghcr.io/home-assistant/home-assistant:latest
```

**Files to update**:

- `kubernetes/apps/default/home-assistant/app/helmrelease.yaml`

**Advantages**:

- Probes work properly (readiness/liveness)
- Better startup ordering (sidecars start before main app)
- Cleaner termination (sidecars automatically stop after main container)

---

#### 2. nftables kube-proxy Backend (v1.33 Stable) 🚀

**Impact**: Cluster-wide networking performance
**Benefit**: Better performance and scalability than iptables

**How to enable**: Update Talos configuration

**File to check**: `kubernetes/bootstrap/talos/talconfig.yaml`

**Add to cluster config**:

```yaml
cluster:
  proxy:
    mode: nftables  # Instead of iptables (default)
```

**Steps**:

1. Update `talconfig.yaml` with nftables mode
2. Regenerate Talos configs: `talhelper genconfig`
3. Apply to nodes one at a time: `task talos:maintenance:apply-config node=weatherwax ip=192.168.8.10`
4. Monitor for any service connectivity issues

**Prerequisites**: ✅ Kernel 5.13+ (you have 6.6+ via Talos v1.10.6)

---

#### 3. StatefulSet PVC Auto-Deletion (v1.32 Stable)

**Impact**: PostgreSQL, Immich, Paperless, Redis, EMQX
**Benefit**: Automatic PVC cleanup when StatefulSets scale down or are deleted

**Current behavior**: PVCs remain after StatefulSet deletion (manual cleanup needed)
**New behavior**: PVCs auto-delete based on retention policy

**Example for PostgreSQL**:

```yaml
# kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
spec:
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain  # Keep data when cluster deleted (safe default)
    whenScaled: Delete   # Clean up PVCs when scaling down
```

**Files to review**:

- `kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml`
- Any StatefulSet-based applications

**Recommendation**: Use `Retain` for production databases, `Delete` for ephemeral workloads

---

### MEDIUM PRIORITY

#### 4. Topology-Aware Routing (v1.33 Stable)

**Impact**: Multi-zone services
**Benefit**: Lower latency, reduced cross-zone traffic costs

Your cluster has 3 control plane nodes - this feature can route traffic to the nearest endpoint.

**Add to services**:

```yaml
apiVersion: v1
kind: Service
spec:
  trafficDistribution: PreferClose  # Routes to nearest endpoint based on topology
```

**Use cases**:

- Internal services with multiple replicas across nodes
- Reduce latency for database queries
- Minimize cross-zone bandwidth

**Files to consider**:

- Services with multiple replicas across nodes
- Database services (PostgreSQL, Redis, EMQX)

---

#### 5. In-Place Pod Resource Resize (v1.33 Beta, enabled by default)

**Impact**: All deployments
**Benefit**: Resize CPU/memory without pod restart

**How to use**:

```bash
# Resize deployment without downtime
kubectl set resources deployment/paperless -n default --limits=cpu=2,memory=4Gi

# Pod resizes in-place (no restart!)
```

**Use cases**:

- Scale up database memory during high load
- Scale down idle services to save resources
- Dynamic resource adjustment based on metrics

**Best candidates in your cluster**:

- `paperless` - varies with document processing load
- `immich` - varies with photo processing
- `n8n` - varies with workflow execution
- Media apps (sonarr, radarr) - peak during downloads

---

#### 6. Memory Manager (v1.32 Stable)

**Impact**: Databases, Ceph OSDs
**Benefit**: Guaranteed memory allocation at NUMA node level

**When to use**: Critical workloads needing guaranteed memory (databases, caches)

**Enable via guaranteed QoS** (requests = limits):

```yaml
resources:
  requests:
    memory: "8Gi"
  limits:
    memory: "8Gi"  # Must match for guaranteed QoS
```

**Best candidates**:

- PostgreSQL cluster (guaranteed memory for buffer pool)
- Redis/Dragonfly (guaranteed memory for cache)
- Ceph OSDs (guaranteed memory for caching)

---

### LOW PRIORITY (Optional Exploration)

#### 7. AppArmor Field-Based Configuration (v1.31 Stable)

**Impact**: Security-conscious workloads
**Benefit**: More structured security policy management

**Migration from annotations to fields**:

```yaml
# Old (annotation-based)
metadata:
  annotations:
    container.apparmor.security.beta.kubernetes.io/app: runtime/default

# New (field-based)
spec:
  securityContext:
    appArmorProfile:
      type: RuntimeDefault  # or Localhost, Unconfined
```

**Files to check**: Any pods with AppArmor annotations

---

#### 8. Multiple Service CIDRs (v1.33 Stable)

**Impact**: Future cluster scaling
**Benefit**: Add more ClusterIP ranges without downtime

**When needed**: If you run out of ClusterIP addresses (unlikely for homelab)

**How to check current usage**:

```bash
kubectl get services -A | wc -l
```

**Currently using**: ~100 services (plenty of headroom with default /16 or /12 CIDR)

---

#### 9. Volume Populators (v1.33 Stable)

**Impact**: Storage workflows
**Benefit**: Pre-populate volumes from external sources

**Use cases**:

- Restore from backup to new PVC
- Clone data from another PVC
- Import data from S3/MinIO to PVC

**Future opportunity**: Could integrate with Volsync for advanced backup/restore workflows

---

## 🗑️ Deprecation Cleanup

### 1. Check for Deprecated Endpoints API Usage

**Status**: Deprecated in v1.33 (still functional, removal in future version)

```bash
# Check if any custom scripts/tools use Endpoints
kubectl get endpoints -A

# Migrate to EndpointSlices
kubectl get endpointslices -A
```

**Action**: If you have any custom tooling/scripts using `endpoints`, migrate to `endpointslices`

---

### 2. Remove gitRepo Volume References (if any)

**Status**: Removed in v1.33 (security concerns)

```bash
# Search for gitRepo volumes
grep -r "gitRepo" kubernetes/apps/
```

**Expected**: No results (you're not using this deprecated feature)

---

## 📊 Performance Monitoring Post-Upgrade

### Week 1: Monitor for Issues

```bash
# Daily health checks
task talos:maintenance:verify

# Watch for pod restarts
kubectl get pods -A --sort-by='.status.containerStatuses[0].restartCount' | tail -20

# Check for evicted pods
kubectl get pods -A --field-selector=status.phase=Failed

# Monitor Ceph performance
kubectl exec -n rook-ceph deployment/rook-ceph-tools -- ceph status
kubectl exec -n rook-ceph deployment/rook-ceph-tools -- ceph osd perf
```

### Week 2-4: Performance Baseline

- Monitor Grafana dashboards for anomalies
- Check Loki logs for new error patterns
- Review Prometheus alerts for increased frequency
- Validate backup/restore workflows (Volsync)

---

## 🚀 Recommended Action Plan

### Immediate (Week 1)

1. ✅ Verify upgrade completion
2. ✅ Check Ceph health
3. ✅ Monitor for pod issues
4. ✅ Review Flux reconciliation

### Short Term (Week 2-4)

1. **Migrate Home Assistant to native sidecars** (highest value, low risk)
2. **Test in-place pod resize** on non-critical workload (e.g., echo-server)
3. **Review StatefulSet PVC retention policies** for databases

### Medium Term (Month 2-3)

1. **Enable nftables kube-proxy backend** (test on single node first)
2. **Add topology-aware routing** to high-traffic services
3. **Implement Memory Manager** for PostgreSQL/Redis

### Long Term (Optional)

1. Migrate AppArmor annotations to field-based config
2. Explore volume populators for backup workflows
3. Monitor Service CIDR usage for future scaling needs

---

## 📝 Files to Review/Update

### High Priority

- [ ] `kubernetes/apps/default/home-assistant/app/helmrelease.yaml` - Native sidecars
- [ ] `kubernetes/bootstrap/talos/talconfig.yaml` - nftables backend
- [ ] `kubernetes/apps/database/cloudnative-pg/cluster/cluster16.yaml` - PVC retention

### Medium Priority

- [ ] Service manifests with multiple replicas - Topology-aware routing
- [ ] High-resource deployments - Memory Manager (guaranteed QoS)

### Low Priority

- [ ] Any manifests with AppArmor annotations
- [ ] Custom scripts using Endpoints API

---

## 🔗 Reference Documentation

- [Kubernetes v1.31 Release Notes](https://kubernetes.io/blog/2024/08/13/kubernetes-v1-31-release/)
- [Kubernetes v1.32 Release Notes](https://kubernetes.io/blog/2024/12/11/kubernetes-v1-32-release/)
- [Kubernetes v1.33 Release Notes](https://kubernetes.io/blog/2025/04/23/kubernetes-v1-33-release/)
- [Native Sidecar Containers Guide](https://kubernetes.io/docs/concepts/workloads/pods/sidecar-containers/)
- [Talos kube-proxy Configuration](https://www.talos.dev/latest/reference/configuration/#clusterconfig)
- [StatefulSet PVC Retention](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/#persistentvolumeclaim-retention)

---

**Last Updated**: December 27, 2025
**Cluster**: witches (Talos v1.10.6, Kubernetes v1.33.7)

---

## 📌 Talos Upgrade Decision

**Current**: Talos v1.10.6
**Latest Available**: v1.12.0 (Dec 22, 2025), v1.11.6 (Dec 16, 2025)

**Decision**: **Stay on v1.10.6** for now

**Reasoning**:

- v1.12.0 is only 5 days old - too new for production
- v1.11.6 is 11 days old - still too fresh
- Features in v1.11/v1.12 don't address current needs (swap, raw volumes)
- v1.10.6 fully supports Kubernetes v1.33.7
- Avoid upgrade fatigue after major K8s upgrade

**Revisit Date**: Late January/Early February 2026

- v1.11.x will have ~10 patches (v1.11.10+)
- v1.12.x will have ~3-5 patches (v1.12.4+)
- Can evaluate which version has better stability/features
- Target upgrade: v1.11.x or v1.12.x (TBD based on maturity)

---
