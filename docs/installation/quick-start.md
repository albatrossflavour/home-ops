# 🚀 Quick Start Guide

Get your Kubernetes homelab up and running in the fastest way possible. This guide assumes you have basic Kubernetes knowledge and want to deploy quickly.

## ⚡ Prerequisites Checklist

Before starting, ensure you have:

- [ ] 3 nodes with static IP addresses
- [ ] Talos ISO flashed and nodes booted
- [ ] Domain registered with Cloudflare
- [ ] 1Password account (personal/family is fine)
- [ ] GitHub repository created from this template

## 🎯 30-Minute Deployment

### Step 1: Environment Setup (5 minutes)

```bash
# Clone your repository
git clone https://github.com/yourusername/your-homelab.git
cd your-homelab

# Setup development environment
task workstation:venv
```

### Step 2: Configuration (10 minutes)

```bash
# Initialize configuration
task init

# Edit config.yaml with your details:
# - Node IPs and MAC addresses
# - Domain name
# - Cloudflare API token
# - Cluster name
```

**Minimal config.yaml example:**

```yaml
bootstrap_cluster_name: "homelab"
bootstrap_node_network: "192.168.1.0/24"
bootstrap_node_inventory:
  - name: "node1"
    address: "192.168.1.10"
    controller: true
    disk: "/dev/sda"
bootstrap_cloudflare:
  enabled: true
  domain: "your-domain.com"
  token: "your-cloudflare-token"
```

### Step 3: Generate Templates (2 minutes)

```bash
# Generate all configuration files
task configure

# Commit initial configuration
git add .
git commit -m "Initial cluster configuration"
git push
```

### Step 4: Deploy Cluster (10 minutes)

```bash
# Bootstrap Talos cluster
task talos:bootstrap

# This will:
# - Apply node configurations
# - Bootstrap Kubernetes
# - Install core components
# - Fetch kubeconfig
```

### Step 5: Install Flux (3 minutes)

```bash
# Bootstrap GitOps
task flux:bootstrap

# Verify deployment
kubectl get pods -A
flux get all -A
```

## ✅ Verification

### Check Cluster Health

```bash
# Nodes should be Ready
kubectl get nodes

# Core pods should be Running
kubectl get pods -n kube-system

# Flux should be synced
flux get kustomizations -A
```

### Test Application Access

```bash
# Check ingress controllers
kubectl get pods -n network

# Test DNS resolution
nslookup grafana.your-domain.com

# Access applications (may take 10-15 minutes for certificates)
curl -I https://grafana.your-domain.com
```

## 🔧 Common Quick Fixes

### Nodes Not Joining

```bash
# Check node status
kubectl get nodes
talosctl --nodes 192.168.1.10 get machineconfig
```

### Flux Not Syncing

```bash
# Force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster
```

### DNS Issues

```bash
# Check external-dns
kubectl logs -n network deployment/external-dns

# Verify Cloudflare records
dig grafana.your-domain.com
```

## 📚 Next Steps

Once your quick deployment is working:

1. **[Production Readiness](./production-readiness.md)** - Security and certificates
2. **[Application Management](../operations/application-management.md)** - Deploy additional services
3. **[Monitoring Setup](../operations/monitoring.md)** - Configure dashboards and alerts

## 🆘 Need Help?

If the quick start doesn't work:

1. **[Prerequisites](./prerequisites.md)** - Detailed requirements
2. **[Common Issues](../troubleshooting/common-issues.md)** - Solutions to frequent problems
3. **[Full Installation Guide](./cluster-deployment.md)** - Step-by-step detailed process

---

**⏱ Expected Timeline**: 30 minutes for basic deployment, 1-2 hours for full production setup including certificates and applications.
