# 💾 Backup & Recovery

Comprehensive guide for data protection, backup strategies, and disaster recovery procedures.

## 🏗️ Backup Architecture

The cluster implements multiple backup strategies to ensure data protection:

### Automated Backups

- **Volsync**: Handles PVC snapshots and replication to external storage
- **External backup**: Configured for critical application data
- **1Password**: Secrets backup via external secrets integration
- **GitOps**: Configuration backup through git repository

### Backup Components

1. **Volume Snapshots**: Point-in-time copies of persistent volumes
2. **Replication**: Sync data to external storage locations
3. **Secret Management**: Automated secret backup and rotation
4. **Configuration**: Infrastructure as Code in git

## 📋 Automated Backup Systems

### Volsync Configuration

Volsync provides automated backup and replication for persistent volumes:

**Check Volsync Status:**

```bash
# Check Volsync pods
kubectl -n volsync-system get pods

# List replication sources
kubectl get replicationsources -A

# List replication destinations  
kubectl get replicationdestinations -A

# Check backup schedules
kubectl get cronjobs -A | grep backup
```

### Volume Snapshots

**List Current Snapshots:**

```bash
# List all volume snapshots
kubectl get volumesnapshots -A

# Check snapshot details
kubectl -n <namespace> describe volumesnapshot <snapshot-name>

# List snapshot classes
kubectl get volumesnapshotclasses
```

**Create Manual Snapshot:**

```bash
kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: manual-backup-$(date +%Y%m%d-%H%M%S)
  namespace: <namespace>
spec:
  source:
    persistentVolumeClaimName: <pvc-name>
EOF
```

## 🔧 Manual Backup Procedures

### Full Cluster Configuration Backup

```bash
# Export all cluster resources
kubectl get all --all-namespaces -o yaml > cluster-backup-$(date +%Y%m%d).yaml

# Export custom resources
kubectl get crd -o name | xargs -I {} kubectl get {} --all-namespaces -o yaml > custom-resources-$(date +%Y%m%d).yaml

# Export secrets (encrypted)
kubectl get secrets --all-namespaces -o yaml > secrets-backup-$(date +%Y%m%d).yaml
```

### Application Data Backup

**Database Backups:**

```bash
# PostgreSQL backup
kubectl -n <namespace> exec deployment/postgresql -- pg_dump -U postgres <database> > postgres-backup-$(date +%Y%m%d).sql

# MySQL backup
kubectl -n <namespace> exec deployment/mysql -- mysqldump -u root -p<password> <database> > mysql-backup-$(date +%Y%m%d).sql
```

**File System Backups:**

```bash
# Backup application data
kubectl -n <namespace> exec deployment/<app> -- tar czf - /data > app-data-backup-$(date +%Y%m%d).tar.gz

# Backup configuration files
kubectl -n <namespace> exec deployment/<app> -- tar czf - /config > app-config-backup-$(date +%Y%m%d).tar.gz
```

### SOPS Encrypted Secrets Backup

```bash
# Backup all SOPS encrypted files
find kubernetes -name "*.sops.yaml" -exec cp {} backups/secrets/ \;

# Verify SOPS files can be decrypted
find backups/secrets -name "*.sops.yaml" -exec sops --decrypt {} \; > /dev/null
```

## 🔄 Recovery Procedures

### Application Data Recovery

**Restore from Volume Snapshot:**

```bash
# Create PVC from snapshot
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: restored-pvc
  namespace: <namespace>
spec:
  dataSource:
    name: <snapshot-name>
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: <size>
EOF
```

**Restore Database:**

```bash
# PostgreSQL restore
kubectl -n <namespace> exec -i deployment/postgresql -- psql -U postgres <database> < postgres-backup.sql

# MySQL restore  
kubectl -n <namespace> exec -i deployment/mysql -- mysql -u root -p<password> <database> < mysql-backup.sql
```

**Restore File System Data:**

```bash
# Restore application data
kubectl -n <namespace> exec -i deployment/<app> -- tar xzf - -C /data < app-data-backup.tar.gz

# Restart application after restore
kubectl -n <namespace> rollout restart deployment/<app>
```

### Cluster Configuration Recovery

**Restore Resources:**

```bash
# Restore from backup file
kubectl apply -f cluster-backup.yaml

# Apply custom resources
kubectl apply -f custom-resources.yaml

# Restore secrets (be careful with this)
kubectl apply -f secrets-backup.yaml
```

## 🚨 Disaster Recovery

### Complete Cluster Recovery

#### Step 1: Rebuild Infrastructure

```bash
# Re-bootstrap Talos cluster
task talos:bootstrap

# Re-install Flux
task flux:bootstrap

# Verify cluster basic functionality
kubectl get nodes
flux get all -A
```

#### Step 2: Restore Secrets

```bash
# Restore SOPS age key
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt

# Verify secret decryption works
sops --decrypt kubernetes/flux/vars/cluster-secrets.sops.yaml

# Let Flux restore all encrypted secrets
flux reconcile source git flux-system
```

#### Step 3: Restore Applications

```bash
# Force Flux reconciliation
flux reconcile kustomization cluster

# Monitor application deployment
kubectl get pods -A -w

# Restore data from backups as needed
```

### Node Recovery

**Replace Failed Node:**

```bash
# Remove failed node
kubectl delete node <failed-node>

# Bootstrap replacement node
talosctl apply-config --nodes <new-node-ip> --file <config-file>

# Verify node joins cluster
kubectl get nodes -w
```

### Data Center Recovery

**Cross-Site Recovery:**

```bash
# Deploy cluster at new location
task talos:bootstrap

# Restore configuration from git
task flux:bootstrap

# Restore data from external backups
# (Follow Volsync replication procedures)

# Update DNS records for new location
# Update Cloudflare tunnel configuration
```

## 📊 Backup Monitoring

### Backup Health Checks

```bash
# Check backup job status
kubectl get jobs -A | grep backup

# Check backup pod logs
kubectl -n <namespace> logs job/<backup-job>

# Verify recent snapshots
kubectl get volumesnapshots -A --sort-by=.metadata.creationTimestamp
```

### Monitoring Backup Success

**Prometheus Queries:**

```promql
# Backup job success rate
rate(kube_job_status_succeeded[1d])

# Volume snapshot creation rate
increase(volume_snapshot_created_total[1d])

# Backup storage usage
volsync_backup_size_bytes
```

**Grafana Dashboards:**

- Backup success rates
- Storage usage trends
- Recovery time objectives
- Snapshot retention policies

## 🔐 Security Considerations

### Backup Encryption

- All backups should be encrypted at rest
- Use SOPS for sensitive configuration
- Rotate backup encryption keys regularly
- Secure backup storage locations

### Access Control

```bash
# Limit backup access with RBAC
kubectl get rolebindings -A | grep backup

# Check service account permissions
kubectl describe serviceaccount backup-operator -n volsync-system

# Audit backup access
kubectl get events -A | grep backup
```

## 📅 Backup Schedules

### Recommended Frequencies

**Critical Data (Daily):**

- Database backups
- Application configuration
- User data

**System Configuration (Weekly):**

- Cluster manifests
- Network policies
- RBAC configuration

**Full System (Monthly):**

- Complete cluster backup
- Disaster recovery test
- Backup validation

### Retention Policies

```bash
# Configure snapshot retention
kubectl patch volumesnapshotclass <class-name> --type merge -p '{"deletionPolicy":"Retain"}'

# Set backup retention in Volsync
kubectl patch replicationsource <source-name> -n <namespace> --type merge -p '{"spec":{"sourcePVC":"<pvc>","retain":{"daily":7,"weekly":4,"monthly":12}}}'
```

## 🧪 Testing Recovery Procedures

### Regular Testing

**Monthly Recovery Tests:**

1. Restore application from backup
2. Verify data integrity
3. Test application functionality
4. Document any issues

**Quarterly Disaster Recovery:**

1. Deploy test cluster
2. Restore from production backups
3. Validate complete system functionality
4. Update recovery procedures

### Validation Scripts

```bash
#!/bin/bash
# backup-validation.sh

# Test backup integrity
echo "Testing backup integrity..."
kubectl get volumesnapshots -A --no-headers | while read ns name rest; do
    echo "Validating snapshot $name in namespace $ns"
    # Add validation logic here
done

# Test SOPS decryption
echo "Testing SOPS decryption..."
find kubernetes -name "*.sops.yaml" -exec sops --decrypt {} \; > /dev/null
echo "SOPS test completed"

# Test database connectivity
echo "Testing database connectivity..."
kubectl get pods -A -l app=postgresql --no-headers | while read ns name rest; do
    kubectl -n $ns exec $name -- pg_isready
done
```

## 📚 Related Documentation

- [Daily Operations](./daily-operations.md) - Routine backup monitoring
- [Application Management](./application-management.md) - Application-specific backup procedures
- [Common Issues](../troubleshooting/common-issues.md) - Backup troubleshooting
- [Security](../architecture/security.md) - Backup security considerations
