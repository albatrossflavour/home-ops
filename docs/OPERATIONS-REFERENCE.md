# 📋 Operations Reference Manual

> **Note**: This is the comprehensive operations reference. For current structured operations guides, see the [Operations Documentation](./operations/) and [Documentation Index](./README.md).

This document provides complete operational guidance for managing the "witches" Kubernetes cluster running on Talos Linux.

## Cluster Information

- **Cluster Name**: witches
- **Network**: 192.168.8.0/24
- **Controller VIP**: 192.168.8.20
- **Ingress VIP**: 192.168.8.21
- **Gateway VIP**: 192.168.8.22
- **Domain**: albatrossflavour.com

### Node Inventory

- **weatherwax** (192.168.8.10) - Controller
- **ogg** (192.168.8.11) - Controller  
- **magrat** (192.168.8.12) - Controller

## Quick Start for Development

### Prerequisites

Ensure you have the required tools installed:

```bash
# Install via Homebrew
task workstation:brew

# Or setup Python environment
task workstation:venv
```

### Daily Development Commands

```bash
# Check cluster status
kubectl get nodes -o wide

# Monitor Flux reconciliation
flux get all -A

# View application status
task kubernetes:resources

# Force reconciliation after git changes
task flux:reconcile
```

## Application Management

### Deployed Applications

#### Core Infrastructure

- **cert-manager**: TLS certificate management with Let's Encrypt
- **external-secrets**: Secret management via 1Password
- **ingress-nginx**: HTTP/HTTPS ingress (internal and external)
- **cloudflared**: Cloudflare tunnel for external access
- **external-dns**: Automatic DNS record management
- **k8s-gateway**: Internal DNS resolution for cluster services

#### Media Stack

- **sonarr/radarr**: Media acquisition
- **bazarr**: Subtitle management
- **overseerr**: Media requests
- **qbittorrent**: Torrent client
- **sabnzbd**: Usenet client

#### Monitoring

- **kube-prometheus-stack**: Prometheus, Grafana, AlertManager
- **gatus**: Uptime monitoring
- Various exporters for application metrics

#### Other Services

- **home-assistant**: Home automation
- **paperless**: Document management
- **authentik**: Authentication provider

### Managing Applications

```bash
# Deploy/update specific application
task flux:apply path=media/sonarr

# Check application logs
kubectl -n media logs -f deployment/sonarr

# Restart an application
kubectl -n media rollout restart deployment/sonarr

# Check ingress status
kubectl get ingress -A
```

## Troubleshooting

### Common Issues

#### Application Not Starting

```bash
# Check pod status
kubectl -n <namespace> get pods

# Describe problematic pod
kubectl -n <namespace> describe pod <pod-name>

# Check events
kubectl -n <namespace> get events --sort-by='.metadata.creationTimestamp'
```

#### Flux Sync Issues

```bash
# Check Flux status
flux get all -A

# Force reconciliation
flux reconcile source git flux-system

# Check Flux logs
kubectl -n flux-system logs -f deployment/source-controller
```

#### Certificate Issues

```bash
# Check certificate status
kubectl get certificates -A

# Check cert-manager logs
kubectl -n cert-manager logs -f deployment/cert-manager
```

#### Storage Issues

```bash
# Check persistent volumes
kubectl get pv,pvc -A

# Check OpenEBS status
kubectl -n openebs-system get pods
```

#### DNS and Networking Issues

```bash
# Check external-dns status
kubectl -n network logs -f deployment/external-dns

# Check k8s-gateway status
kubectl -n network logs -f deployment/k8s-gateway

# Check cloudflared tunnel status
kubectl -n network logs -f deployment/cloudflared

# Test internal DNS resolution
kubectl run -it --rm debug --image=busybox --restart=Never -- nslookup homepage.default.svc.cluster.local

# Check ingress controllers
kubectl -n network get pods -l app.kubernetes.io/name=ingress-nginx
```

#### Cloudflare Tunnel Issues

```bash
# Check tunnel connectivity
kubectl -n network logs -f deployment/cloudflared

# Verify tunnel configuration
kubectl -n network get secret cloudflared-secret -o yaml

# Test external connectivity through tunnel
curl -I https://your-app.albatrossflavour.com
```

### Emergency Procedures

#### Node Maintenance

```bash
# Drain node for maintenance
kubectl drain <node-name> --ignore-daemonsets --delete-emptydir-data

# Uncordon after maintenance
kubectl uncordon <node-name>
```

#### Cluster Recovery

```bash
# Emergency cluster reset (DESTRUCTIVE)
task talos:nuke --force

# Re-bootstrap cluster
task talos:bootstrap
task flux:bootstrap
```

## Maintenance Tasks

### Regular Maintenance

#### Weekly

- Review Renovate PRs for dependency updates
- Check Grafana dashboards for anomalies
- Verify backup integrity via Volsync

#### Monthly

- Review resource usage and scaling needs
- Update Talos if new versions available
- Clean up unused container images

### Updates and Upgrades

#### Application Updates

Renovate automatically creates PRs for:

- Container image updates
- Helm chart updates
- Flux component updates

Review and merge PRs after testing.

#### Talos Updates

```bash
# Check current Talos version
talosctl version

# Upgrade single node
task talos:upgrade node=192.168.8.10 image=factory.talos.dev/installer/<schematic>:v1.x.x

# Upgrade all nodes sequentially
for node in 192.168.8.10 192.168.8.11 192.168.8.12; do
  task talos:upgrade node=$node image=factory.talos.dev/installer/<schematic>:v1.x.x
done
```

#### Kubernetes Updates

```bash
# Upgrade Kubernetes
task talos:upgrade-k8s controller=192.168.8.10 to=1.30.x
```

## Security and Secrets

### SOPS Management

```bash
# Decrypt secret for viewing
sops kubernetes/apps/media/sonarr/app/externalsecret.yaml

# Edit encrypted secret
sops kubernetes/apps/media/sonarr/app/externalsecret.yaml

# Encrypt new secret
sops --encrypt --in-place new-secret.sops.yaml
```

### 1Password Integration

External secrets are automatically synced from 1Password Connect:

- Credentials stored in 1Password vaults
- ExternalSecret resources fetch and create Kubernetes secrets
- Rotation handled automatically

## Monitoring and Alerting

### Access Points

- **Grafana**: https://grafana.albatrossflavour.com
- **Prometheus**: https://prometheus.albatrossflavour.com  
- **AlertManager**: https://alertmanager.albatrossflavour.com
- **Gatus**: https://status.albatrossflavour.com

### Key Metrics to Monitor

- Node resource utilization
- Pod restart rates
- Certificate expiration
- Backup success rates
- Application response times

## Backup and Recovery

### Automated Backups

- **Volsync**: Handles PVC snapshots and replication
- **External backup**: Configured for critical data
- **1Password**: Secrets backup via external secrets

### Manual Backup

```bash
# Export cluster configuration
kubectl get all --all-namespaces -o yaml > cluster-backup.yaml

# Backup persistent volumes (application-specific)
kubectl exec -n <namespace> <pod> -- tar czf - /data | gzip > backup.tar.gz
```

## DNS and External Access

### DNS Architecture

The cluster uses a multi-layer DNS setup:

1. **External DNS (external-dns)**: Automatically creates DNS records in Cloudflare for ingresses with `external` class
2. **Internal DNS (k8s-gateway)**: Provides DNS resolution for internal services to home network clients
3. **Cloudflare Tunnel (cloudflared)**: Secure tunnel for external access without exposing ports

### DNS Resolution Flow

#### For External Access

1. Public DNS queries for `*.albatrossflavour.com` resolve to Cloudflare
2. Cloudflare routes traffic through the tunnel to the cluster
3. Traffic hits the external ingress controller (192.168.8.21)
4. Ingress routes to appropriate services

#### For Internal/Home Network Access

1. Home DNS server forwards `*.albatrossflavour.com` queries to k8s-gateway (192.168.8.22)
2. k8s-gateway resolves to internal ingress controller (192.168.8.21)
3. Ingress routes to appropriate services

### Ingress Configuration

The cluster runs two ingress controllers:

#### External Ingress (`ingress-nginx-external`)

- **Purpose**: Handles traffic from Cloudflare tunnel
- **IP**: 192.168.8.21
- **Ingress Class**: `external`
- **Usage**: For applications accessible from internet

```yaml
annotations:
  kubernetes.io/ingress.class: external
  external-dns.alpha.kubernetes.io/target: "external.albatrossflavour.com"
```

#### Internal Ingress (`ingress-nginx-internal`)

- **Purpose**: Handles internal home network traffic
- **IP**: 192.168.8.21 (same as external, different ports)
- **Ingress Class**: `internal`
- **Usage**: For home-only applications

```yaml
annotations:
  kubernetes.io/ingress.class: internal
```

### Reverse Proxy Configuration

Some applications use nginx reverse proxy for:

- Legacy applications not in Kubernetes
- External services that need cluster integration
- Load balancing across multiple backends

#### nginx-reverse-proxy Application

Located in `kubernetes/apps/default/nginx-reverse-proxy/`:

- Custom nginx configuration via ConfigMap
- Ingress integration for DNS/certificates
- Useful for bridging non-k8s services

Example configuration:

```nginx
server {
    listen 80;
    server_name legacy-app.albatrossflavour.com;

    location / {
        proxy_pass http://192.168.8.100:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Managing DNS and Access

#### Adding External Access to an Application

1. Create ingress with `external` class
2. Add external-dns annotation
3. Ensure Cloudflare tunnel includes the domain

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp
  annotations:
    kubernetes.io/ingress.class: external
    external-dns.alpha.kubernetes.io/target: "external.albatrossflavour.com"
    cert-manager.io/cluster-issuer: letsencrypt-production
spec:
  tls:
    - hosts: [myapp.albatrossflavour.com]
      secretName: myapp-tls
  rules:
    - host: myapp.albatrossflavour.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port: {number: 80}
```

#### DNS Troubleshooting Commands

```bash
# Check external-dns logs for record creation
kubectl -n network logs -f deployment/external-dns

# Verify Cloudflare DNS records
dig myapp.albatrossflavour.com

# Test internal DNS resolution from home network
nslookup myapp.albatrossflavour.com 192.168.8.22

# Check tunnel routing
kubectl -n network get configmap cloudflared-config -o yaml
```

## Configuration Changes

### Making Changes

1. Update relevant files in the repository
2. For secrets, ensure SOPS encryption: `sops --encrypt --in-place file.sops.yaml`
3. Commit and push changes
4. Monitor Flux reconciliation: `flux get all -A`

### Template Updates

If modifying bootstrap templates:

```bash
# Update config.yaml as needed
# Regenerate templates
task configure

# Review changes before committing
git diff
```

## Support and Documentation

- **Flux Documentation**: https://fluxcd.io/docs/
- **Talos Documentation**: https://www.talos.dev/docs/
- **Template Source**: https://github.com/onedr0p/cluster-template
- **Home Operations Discord**: https://discord.gg/home-operations
