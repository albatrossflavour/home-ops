# 📱 Application Management

Comprehensive guide for managing applications deployed in the Kubernetes homelab cluster.

## 📋 Deployed Applications

### Core Infrastructure

- **cert-manager**: TLS certificate management with Let's Encrypt
- **external-secrets**: Secret management via 1Password
- **ingress-nginx**: HTTP/HTTPS ingress (internal and external)
- **cloudflared**: Cloudflare tunnel for external access
- **external-dns**: Automatic DNS record management
- **k8s-gateway**: Internal DNS resolution for cluster services

### Media Stack

- **sonarr/radarr**: Media acquisition
- **bazarr**: Subtitle management
- **overseerr**: Media requests
- **qbittorrent**: Torrent client
- **sabnzbd**: Usenet client

### Monitoring

- **kube-prometheus-stack**: Prometheus, Grafana, AlertManager
- **gatus**: Uptime monitoring
- Various exporters for application metrics

### Utilities & Automation

- **n8n**: Workflow automation platform
- **node-red**: Visual programming for IoT and automation
- **nocodb**: No-code database and API platform

### Other Services

- **home-assistant**: Home automation
- **paperless**: Document management
- **authentik**: Authentication provider

## 🔧 Application Operations

### Deploy/Update Applications

```bash
# Deploy/update specific application
task flux:apply path=media/sonarr
task flux:apply path=utilities/node-red
task flux:apply path=database/nocodb

# Apply changes to entire namespace
task flux:apply path=media
task flux:apply path=utilities

# Force immediate reconciliation
flux reconcile kustomization cluster
```

### Monitor Application Status

```bash
# Check application logs
kubectl -n media logs -f deployment/sonarr
kubectl -n utilities logs -f deployment/node-red
kubectl -n database logs -f deployment/nocodb

# View application pods
kubectl -n media get pods -l app.kubernetes.io/name=sonarr
kubectl -n utilities get pods -l app.kubernetes.io/name=node-red

# Check resource usage
kubectl -n media top pods
kubectl -n utilities top pods
```

### Restart Applications

```bash
# Restart an application
kubectl -n media rollout restart deployment/sonarr

# Restart all applications in namespace
kubectl -n media rollout restart deployment

# Check rollout status
kubectl -n media rollout status deployment/sonarr
```

### Application Configuration

```bash
# View application configuration
kubectl -n media get configmap sonarr-config -o yaml

# Edit configuration (avoid this, use GitOps instead)
kubectl -n media edit configmap sonarr-config

# Check environment variables
kubectl -n media describe deployment sonarr
```

## 🌐 Ingress and Access

### Check Ingress Status

```bash
# List all ingress resources
kubectl get ingress -A

# Check specific ingress
kubectl -n media describe ingress sonarr

# Test internal connectivity
kubectl run debug --image=busybox -it --rm -- wget -O- http://sonarr.media:8989
```

### External Access

```bash
# Check Cloudflare tunnel status
kubectl -n network logs -f deployment/cloudflared

# Verify external DNS records
kubectl -n network logs -f deployment/external-dns

# Test external access
curl -I https://sonarr.yourdomain.com
```

## 💾 Storage Management

### Persistent Volumes

```bash
# Check application storage
kubectl get pvc -A

# View storage usage
kubectl -n media exec deployment/sonarr -- df -h /data

# Check OpenEBS status
kubectl -n openebs-system get pods
```

### Volume Snapshots

```bash
# List snapshots
kubectl get volumesnapshots -A

# Create manual snapshot
kubectl -n media apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: sonarr-manual-snapshot
spec:
  source:
    persistentVolumeClaimName: sonarr-config
EOF
```

## 🔒 Secrets and Configuration

### View Secrets

```bash
# List secrets (values hidden)
kubectl -n media get secrets

# Check External Secrets status
kubectl -n media get externalsecrets

# Verify 1Password integration
kubectl -n external-secrets logs -f deployment/external-secrets
```

### Configuration Updates

```bash
# Update application via GitOps
# 1. Edit files in kubernetes/apps/media/sonarr/
# 2. Commit and push changes
git add kubernetes/apps/media/sonarr/
git commit -m "Update Sonarr configuration"
git push

# Force Flux to pick up changes
flux reconcile source git flux-system
flux reconcile kustomization cluster
```

## 📊 Monitoring Applications

### Application Metrics

```bash
# Port-forward to application metrics
kubectl -n media port-forward svc/sonarr 8989:8989

# Check application in Grafana
# Visit: https://grafana.yourdomain.com
```

### Log Analysis

```bash
# Stream logs in real-time
kubectl -n media logs -f deployment/sonarr

# Get recent logs with timestamps
kubectl -n media logs deployment/sonarr --since=1h --timestamps

# Search logs for errors
kubectl -n media logs deployment/sonarr | grep -i error
```

### Health Checks

```bash
# Check application readiness
kubectl -n media get pods -l app.kubernetes.io/name=sonarr

# Test application endpoints
kubectl -n media exec deployment/sonarr -- wget -q --spider http://localhost:8989

# Check service endpoints
kubectl -n media get endpoints sonarr
```

## 🚀 Scaling Applications

### Manual Scaling

```bash
# Scale application replicas
kubectl -n media scale deployment sonarr --replicas=2

# Check scaling status
kubectl -n media get deployment sonarr

# View horizontal pod autoscaler (if configured)
kubectl -n media get hpa
```

### Resource Adjustments

```bash
# Check current resource requests/limits
kubectl -n media describe deployment sonarr | grep -A5 -B5 "Requests\|Limits"

# Update resources via GitOps (edit kubernetes manifests)
# Then apply changes through git commit/push cycle
```

## 🔄 Application Lifecycle

### Adding New Applications

1. **Create application manifests** in `kubernetes/apps/<namespace>/<app>/`
2. **Configure secrets** via External Secrets
3. **Set up ingress** for web access
4. **Add monitoring** and health checks
5. **Document configuration** and operational notes

### Removing Applications

```bash
# Scale down gracefully
kubectl -n media scale deployment old-app --replicas=0

# Remove from Flux manifests
# Delete files in kubernetes/apps/media/old-app/

# Clean up resources
kubectl -n media delete pvc old-app-data
kubectl -n media delete secret old-app-secret
```

## 🆘 Troubleshooting

### Common Issues

**Application not starting:**

```bash
# Check pod status and events
kubectl -n media describe pod <pod-name>
kubectl -n media get events --sort-by='.metadata.creationTimestamp'
```

**Configuration issues:**

```bash
# Verify configmaps and secrets
kubectl -n media get configmap,secret
kubectl -n media describe externalsecret <app>-secret
```

**Storage problems:**

```bash
# Check PVC status
kubectl -n media get pvc
kubectl -n media describe pvc <app>-config
```

**Network connectivity:**

```bash
# Test internal connectivity
kubectl -n media exec deployment/<app> -- nslookup kubernetes.default
kubectl run debug --image=busybox -it --rm -- ping <service>.<namespace>
```

For more detailed troubleshooting, see [Troubleshooting Guide](../troubleshooting/common-issues.md).

## 📚 Related Documentation

- [Daily Operations](./daily-operations.md) - Common daily tasks
- [DNS & Networking](./dns-networking.md) - Network configuration
- [Backup & Recovery](./backup-recovery.md) - Data protection
- [Monitoring](./monitoring.md) - Observability setup
