# 🔧 Common Issues & Troubleshooting

Comprehensive troubleshooting guide for common problems in the Kubernetes homelab cluster.

## 🚨 Application Issues

### Application Not Starting

**Symptoms:** Pod stuck in `Pending`, `CrashLoopBackOff`, or `ImagePullBackOff` state

**Diagnosis:**

```bash
# Check pod status
kubectl -n <namespace> get pods

# Describe problematic pod
kubectl -n <namespace> describe pod <pod-name>

# Check events
kubectl -n <namespace> get events --sort-by='.metadata.creationTimestamp'

# Check logs
kubectl -n <namespace> logs <pod-name> --previous
```

**Common Causes & Solutions:**

- **Resource constraints:** Check node resources with `kubectl top nodes`
- **Image pull issues:** Verify image name and registry access
- **Configuration errors:** Check configmaps and secrets
- **Storage issues:** Verify PVC status and availability

### Configuration Problems

**Symptoms:** Application starts but behaves incorrectly

**Diagnosis:**

```bash
# Check configmaps and secrets
kubectl -n <namespace> get configmap,secret

# Verify External Secrets
kubectl -n <namespace> describe externalsecret <app>-secret

# Check environment variables
kubectl -n <namespace> describe deployment <app>
```

## 🔄 GitOps & Flux Issues

### Flux Sync Issues

**Symptoms:** Changes not appearing in cluster, Flux showing errors

**Diagnosis:**

```bash
# Check Flux status
flux get all -A

# Check specific kustomization
flux get kustomizations -A

# Check source status
flux get sources git -A
```

**Solutions:**

```bash
# Force reconciliation
flux reconcile source git flux-system

# Reconcile specific kustomization
flux reconcile kustomization cluster

# Check Flux logs
kubectl -n flux-system logs -f deployment/source-controller
kubectl -n flux-system logs -f deployment/kustomize-controller
```

### Git Repository Issues

**Symptoms:** Flux can't fetch from repository

**Common Solutions:**

- Verify repository URL and branch
- Check deploy key permissions
- Ensure repository is accessible from cluster

## 🔒 Certificate Issues

### TLS Certificate Problems

**Symptoms:** HTTPS not working, certificate warnings in browser

**Diagnosis:**

```bash
# Check certificate status
kubectl get certificates -A

# Check certificate details
kubectl -n <namespace> describe certificate <cert-name>

# Check cert-manager logs
kubectl -n cert-manager logs -f deployment/cert-manager
```

**Solutions:**

```bash
# Delete certificate to force recreation
kubectl -n <namespace> delete certificate <cert-name>

# Check Let's Encrypt rate limits
kubectl -n cert-manager logs deployment/cert-manager | grep "rate limit"

# Verify DNS challenge
kubectl -n cert-manager describe challenge
```

## 💾 Storage Issues

### Persistent Volume Problems

**Symptoms:** Pods stuck in `Pending` with PVC mount issues

**Diagnosis:**

```bash
# Check persistent volumes and claims
kubectl get pv,pvc -A

# Check OpenEBS status
kubectl -n openebs-system get pods

# Check storage class
kubectl get storageclass
```

**Solutions:**

```bash
# Check PVC details
kubectl -n <namespace> describe pvc <pvc-name>

# Verify node storage capacity
kubectl describe nodes | grep -A5 "Allocated resources"

# Check OpenEBS logs
kubectl -n openebs-system logs -f deployment/openebs-localpv-provisioner
```

### Disk Space Issues

**Diagnosis:**

```bash
# Check node disk usage
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.status.allocatable.ephemeral-storage}{"\n"}{end}'

# Check application storage usage
kubectl -n <namespace> exec deployment/<app> -- df -h
```

## 🌐 DNS and Networking Issues

### Internal DNS Resolution

**Symptoms:** Services can't reach each other, DNS lookup failures

**Diagnosis:**

```bash
# Test internal DNS resolution
kubectl run debug --image=busybox -it --rm -- nslookup kubernetes.default.svc.cluster.local

# Check CoreDNS status
kubectl -n kube-system get pods -l k8s-app=kube-dns

# Check CoreDNS logs
kubectl -n kube-system logs -f deployment/coredns
```

### External DNS Issues

**Symptoms:** External domains not resolving, DNS records not created

**Diagnosis:**

```bash
# Check external-dns status
kubectl -n network logs -f deployment/external-dns

# Check k8s-gateway status
kubectl -n network logs -f deployment/k8s-gateway

# Verify DNS records
dig @8.8.8.8 <app>.<domain>.com
```

**Solutions:**

```bash
# Check external-dns configuration
kubectl -n network describe deployment external-dns

# Verify Cloudflare API token
kubectl -n network get secret external-dns-secret -o yaml

# Force DNS record refresh
kubectl -n network rollout restart deployment/external-dns
```

### Ingress Controller Issues

**Symptoms:** Applications not accessible via HTTP/HTTPS

**Diagnosis:**

```bash
# Check ingress controllers
kubectl -n network get pods -l app.kubernetes.io/name=ingress-nginx

# Check ingress resources
kubectl get ingress -A

# Check ingress controller logs
kubectl -n network logs -f deployment/ingress-nginx-external
```

## ☁️ Cloudflare Tunnel Issues

### Tunnel Connectivity Problems

**Symptoms:** External access not working, tunnel disconnected

**Diagnosis:**

```bash
# Check tunnel connectivity
kubectl -n network logs -f deployment/cloudflared

# Verify tunnel configuration
kubectl -n network get secret cloudflared-secret -o yaml

# Test external connectivity
curl -I https://<app>.<domain>.com
```

**Solutions:**

```bash
# Restart cloudflared
kubectl -n network rollout restart deployment/cloudflared

# Check tunnel status in Cloudflare dashboard
# Verify tunnel credentials and routes

# Test internal connectivity
kubectl -n network exec deployment/cloudflared -- wget -qO- http://ingress-nginx-external-controller
```

## 🛡️ Security and Secrets

### External Secrets Issues

**Symptoms:** Secrets not syncing from 1Password

**Diagnosis:**

```bash
# Check External Secrets status
kubectl -n <namespace> get externalsecrets

# Check External Secrets logs
kubectl -n external-secrets logs -f deployment/external-secrets

# Check 1Password Connect status
kubectl -n external-secrets get pods -l app.kubernetes.io/name=onepassword-connect
```

### SOPS Decryption Issues

**Symptoms:** Can't decrypt SOPS files, age key issues

**Diagnosis:**

```bash
# Test SOPS decryption
sops --decrypt kubernetes/flux/vars/cluster-secrets.sops.yaml

# Check age key
echo $SOPS_AGE_KEY_FILE
age --version
```

## 📊 Monitoring Issues

### Prometheus Scraping Problems

**Symptoms:** Missing metrics, scrape failures

**Diagnosis:**

```bash
# Check Prometheus targets
kubectl -n observability port-forward svc/prometheus-operated 9090:9090
# Visit http://localhost:9090/targets

# Check service monitors
kubectl -n observability get servicemonitor
```

### Grafana Dashboard Issues

**Symptoms:** No data in dashboards, login problems

**Diagnosis:**

```bash
# Check Grafana logs
kubectl -n observability logs -f deployment/grafana

# Verify data sources
# Login to Grafana and check Settings > Data Sources
```

## 🚑 Emergency Procedures

### Node Maintenance

```bash
# Drain node for maintenance
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Uncordon after maintenance
kubectl uncordon <node-name>

# Check node status
kubectl get nodes -o wide
```

### Cluster Recovery

#### ⚠️ WARNING: DESTRUCTIVE OPERATIONS

```bash
# Emergency cluster reset (LAST RESORT)
task talos:nuke --force

# Re-bootstrap cluster
task talos:bootstrap
task flux:bootstrap

# Verify cluster health
kubectl get nodes
flux get all -A
```

### Application Recovery

```bash
# Scale down problematic application
kubectl -n <namespace> scale deployment <app> --replicas=0

# Clear problematic resources
kubectl -n <namespace> delete pod --all

# Scale back up
kubectl -n <namespace> scale deployment <app> --replicas=1

# Check status
kubectl -n <namespace> get pods -w
```

## 🔍 Diagnostic Commands

### Quick Health Check

```bash
# Cluster overview
kubectl get nodes -o wide
kubectl get pods -A | grep -v Running | grep -v Completed

# Flux status
flux get all -A | grep -v "True"

# Resource usage
kubectl top nodes
kubectl top pods -A --sort-by=memory
```

### Detailed Investigation

```bash
# System events
kubectl get events -A --sort-by='.metadata.creationTimestamp' | tail -20

# Resource constraints
kubectl describe nodes | grep -A10 "Allocated resources"

# Network policies
kubectl get networkpolicies -A

# Certificate status
kubectl get certificates -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[0].status"
```

## 🔄 Application Deployment Issues

### PVC Multi-Attach Errors

**Symptoms:** `Multi-Attach error for volume`, pods stuck in `ContainerCreating`

**Cause:** Multiple containers trying to use the same ReadWriteOnce PVC

**Diagnosis:**

```bash
# Check pod events
kubectl describe pod <pod-name>

# Check PVC usage
kubectl get pods -o wide | grep <pvc-name>
```

**Solution:**

```bash
# 1. Force delete conflicting pods
kubectl delete pods -l app=<appname> --force --grace-period=0

# 2. Fix HelmRelease to use advancedMounts instead of globalMounts
# In helmrelease.yaml:
persistence:
  data:
    advancedMounts:
      main-controller:  # Only mount to specific controller
        app:
          - path: /app/data
    # Remove: globalMounts

# 3. Apply changes
flux reconcile kustomization <appname>
```

### Helm Upgrade Timeouts

**Symptoms:** `context deadline exceeded`, HelmRelease stuck in "Running 'upgrade'"

**Diagnosis:**

```bash
# Check HelmRelease status
kubectl get helmrelease <appname>

# Check Helm controller logs
kubectl -n flux-system logs -f deployment/helm-controller
```

**Solution:**

```bash
# Force reconciliation with fresh source
flux reconcile kustomization <appname> --with-source

# If still stuck, suspend and resume
flux suspend helmrelease <appname>
flux resume helmrelease <appname>
```

### ExternalSecret Sync Issues

**Symptoms:** Environment variables are empty, "SecretSyncError"

**Diagnosis:**

```bash
# Check ExternalSecret status
kubectl get externalsecret <appname>
kubectl describe externalsecret <appname>

# Check secret contents
kubectl get secret <appname>-secret -o yaml

# Test 1Password connectivity
kubectl -n external-secrets-system logs deployment/external-secrets
```

**Solution:**

```bash
# Force resync
kubectl annotate externalsecret <appname> force-sync=$(date +%s)

# Check 1Password item exists
op item get <appname> --vault=discworld

# Verify ClusterSecretStore
kubectl get clustersecretstore onepassword-connect
```

### Database Connection Issues

**Symptoms:** "Authentication failed", "database does not exist"

**Diagnosis:**

```bash
# Check init container ran
kubectl logs <pod-name> -c init-db

# Verify database user was created
kubectl exec -n database deployment/postgres16 -- psql -U postgres -c "\du"

# Test database connection
kubectl exec -n database deployment/postgres16 -- psql -U postgres -d <dbname> -c "SELECT 1"
```

**Solution:**

```bash
# Delete pod to re-run init container
kubectl delete pod <pod-name>

# Check postgres-init image is available
kubectl run test-init --image=ghcr.io/home-operations/postgres-init:17 --rm -it -- /bin/sh

# Verify DATABASE_URL format
kubectl exec deployment/<appname> -- env | grep DATABASE_URL
```

### Minio Storage Access Issues

**Symptoms:** "Valid and authorized credentials required", S3Error AccessDenied

**Diagnosis:**

```bash
# Check storage environment variables
kubectl exec deployment/<appname> -- env | grep STORAGE

# Test Minio connectivity
kubectl run minio-test --image=minio/mc --rm -it -- mc ls minio.default.svc.cluster.local:9000

# Check bucket exists
# Access Minio UI at https://minio.<domain>
```

**Solution:**

```bash
# Add bucket check bypass
# In helmrelease.yaml:
env:
  STORAGE_SKIP_BUCKET_CHECK: "true"

# Create missing bucket in Minio UI
# Verify credentials match minio secret
kubectl get secret minio-secret -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d
```

## 🤖 Renovate Automation Issues

### Branch Protection Requirements

**Symptoms:** "Your main branch isn't protected" error in Renovate logs

**Cause:** Renovate requires branch protection to create pull requests

**Solution:**

| Issue | Symptom | Solution |
|-------|---------|----------|
| Branch not protected | "Error updating branch" in Renovate | Enable branch protection in GitHub Settings → Branches |
| Missing status checks | PRs created but no automation | Add required status checks in branch protection |
| Admin bypass disabled | Manual pushes bypass checks | Enable "Include administrators" in protection rules |
| Outdated fileMatch patterns | No PRs for containers | Update Renovate config with correct `fileMatch` patterns |

### SHA256 Digest Issues

**Symptoms:** YAML lint failures, unquoted digest strings

**Diagnosis:**

```bash
# Check for unquoted @ symbols
yamllint kubernetes/ --format=parsable | grep "@"

# Find missing digests
grep -r "tag:" kubernetes/apps/ | grep -v "@sha256"
```

**Solutions:**

```bash
# Get digest for any image
docker pull repository/image:tag
docker inspect repository/image:tag --format='{{index .RepoDigests 0}}'

# Ensure tags with @ are quoted
# ❌ Wrong: tag: 1.0.0@sha256:abcd...
# ✅ Correct: tag: "1.0.0@sha256:abcd..."
```

### Renovate Configuration Problems

**Common Issues:**

- **Excess registryUrls warning**: Remove deprecated `managerFilePatterns` in favor of `fileMatch`
- **No updates detected**: Verify `docker:pinDigests` preset is enabled
- **Wrong file patterns**: Ensure `fileMatch` covers all YAML files

```json5
// Correct Renovate configuration
{
  extends: [
    "docker:pinDigests",  // Auto-add SHA256 digests
  ],
  flux: {
    fileMatch: ["(^|/)kubernetes/.+\\.ya?ml(?:\\.j2)?$"]
  },
  kubernetes: {
    fileMatch: ["(^|/)kubernetes/.+\\.ya?ml(?:\\.j2)?$"]
  }
}
```

## 🔍 Advanced Debugging Workflow

### Systematic Troubleshooting Steps

1. **Check Resource Status**

   ```bash
   kubectl get helmrelease,externalsecret,pvc -n <namespace>
   ```

2. **Review Pod Events**

   ```bash
   kubectl describe pod <pod-name>
   ```

3. **Check Init Containers**

   ```bash
   kubectl logs <pod-name> -c init-db
   ```

4. **Verify Environment Variables**

   ```bash
   kubectl exec deployment/<appname> -- env | grep -E "DB|STORAGE|SECRET"
   ```

5. **Test Dependencies**

   ```bash
   # Database connectivity
   kubectl exec -n database deployment/postgres16 -- pg_isready

   # Minio connectivity  
   kubectl run test --image=busybox --rm -it -- wget -qO- http://minio.default.svc.cluster.local:9000
   ```

6. **Force Reconciliation**

   ```bash
   flux reconcile kustomization <appname> --with-source
   ```

## 📚 Related Documentation

- [Daily Operations](../operations/daily-operations.md) - Routine maintenance tasks
- [Application Management](../operations/application-management.md) - Managing deployed services
- [DNS & Networking](../operations/dns-networking.md) - Network configuration
- [Backup & Recovery](../operations/backup-recovery.md) - Disaster recovery procedures
