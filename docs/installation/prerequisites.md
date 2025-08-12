# 📋 Prerequisites

Complete requirements and planning guide before deploying your Kubernetes homelab.

## 🧠 Knowledge Requirements

### Essential Knowledge

- **Kubernetes basics**: Pods, services, deployments, ingress
- **Command line comfort**: Bash/shell, YAML editing
- **Git fundamentals**: Clone, commit, push, pull requests
- **Basic networking**: IP addressing, DNS, HTTP/HTTPS

### Helpful but Not Required

- Helm charts and package management
- GitOps and Flux concepts
- Container orchestration experience
- Infrastructure as Code (IaC) principles

## 🏠 Hardware Requirements

### Minimum Setup (Learning/Testing)

| Component | Requirement |
|-----------|-------------|
| **Nodes** | 1 node (all-in-one) |
| **CPU** | 4 cores |
| **Memory** | 8GB RAM |
| **Storage** | 120GB SSD |
| **Network** | Gigabit Ethernet |

### Recommended Setup (Home Production)

| Component | Requirement |
|-----------|-------------|
| **Nodes** | 3 nodes (HA control plane) |
| **CPU** | 6 cores per node |
| **Memory** | 16GB RAM per node |
| **Storage** | 500GB NVMe per node |
| **Network** | Gigabit+ with static IPs |

### Enterprise/Heavy Workload Setup

| Component | Requirement |
|-----------|-------------|
| **Nodes** | 3+ controllers + workers |
| **CPU** | 8+ cores per node |
| **Memory** | 32GB+ RAM per node |
| **Storage** | 1TB+ NVMe + additional data drives |
| **Network** | 2.5G/10G with VLAN support |

### Hardware Considerations

**CPU Requirements:**

- x86_64 (AMD64) architecture preferred
- ARM64 supported but may require different container images
- Hardware virtualization support (VT-x/AMD-V)
- Multiple cores recommended for parallel workloads

**Memory Planning:**

- Kubernetes overhead: ~2GB per control plane node
- Container runtime: ~1GB per node
- Application workloads: Plan based on your services
- Monitoring stack: ~2-4GB total

**Storage Considerations:**

- **System disk**: Fast SSD/NVMe for OS and container images
- **Data storage**: Separate volumes for persistent data
- **Backup storage**: External or network storage for backups
- **Performance**: IOPS matter more than capacity for many workloads

## 🌐 Network Requirements

### IP Address Planning

```yaml
# Example network layout
Home Network: 192.168.1.0/24
Cluster Network: 192.168.8.0/24

# Required IP addresses
Gateway: 192.168.8.1
DNS Server: 192.168.8.1 (or dedicated Pi-hole)

# Cluster VIPs (Virtual IPs)
Controller VIP: 192.168.8.20
Ingress VIP: 192.168.8.21
Gateway VIP: 192.168.8.22
Tunnel VIP: 192.168.8.23

# Node IPs (static required)
Node 1: 192.168.8.10
Node 2: 192.168.8.11
Node 3: 192.168.8.12
```

### Network Infrastructure

- **Router/Firewall**: Supports static IP assignment
- **Switch**: Gigabit+ with sufficient ports
- **Internet**: Stable connection for downloads and external access
- **DNS**: Control over internal DNS resolution (optional but recommended)

### VLAN Configuration (Optional)

```yaml
# Recommended VLAN setup
VLAN 1: 192.168.1.0/24   # Main home network
VLAN 8: 192.168.8.0/24   # Kubernetes cluster
VLAN 10: 192.168.10.0/24 # IoT devices
VLAN 99: 192.168.99.0/24 # Management/IPMI
```

## ☁️ External Service Requirements

### Domain and DNS

#### Required: Domain with Cloudflare Management

- Domain registered and transferred to Cloudflare
- Or domain with nameservers pointed to Cloudflare
- Cloudflare account with API access

**DNS Planning:**

```yaml
# Domain structure example
Root: example.com
Cluster: k8s.example.com
Services: *.k8s.example.com

# Service examples
grafana.k8s.example.com
homeassistant.k8s.example.com
sonarr.k8s.example.com
```

### Cloudflare Account Setup

1. **Free Cloudflare account** (paid features optional)
2. **Domain management** active in Cloudflare
3. **API token** with DNS edit permissions
4. **Tunnel creation** capability (free feature)

### 1Password Account

**Personal/Family Account Sufficient:**

- 1Password personal or family subscription
- API access enabled
- Vault organization for secrets

**Business Account (Optional):**

- Required only for 1Password Connect server
- Self-hosted secret management
- Enhanced audit and compliance features

### GitHub Repository

- **GitHub account** (free or paid)
- **Repository** created from this template
- **Personal access token** for Flux (optional, improves rate limits)

## 🛠 Local Development Environment

### Required Tools

| Tool | Purpose | Installation |
|------|---------|--------------|
| **git** | Version control | `brew install git` |
| **task** | Task automation | `brew install go-task` |
| **kubectl** | Kubernetes CLI | `brew install kubectl` |
| **flux** | GitOps toolkit | `brew install fluxcd/tap/flux` |

### Development Environment Options

#### Option 1: DevContainer (Recommended)

- Requirements: Docker Desktop + VS Code
- All tools pre-installed in container
- Consistent environment across platforms
- No local tool conflicts

#### Option 2: Local Installation

```bash
# macOS with Homebrew
brew install go-task direnv age sops kubectl flux

# Linux (various package managers)
# See detailed installation guide

# Windows with WSL2
# Use Linux installation in WSL2 environment
```

#### Option 3: GitHub Codespaces

- Cloud-based development environment
- All tools pre-configured
- No local setup required
- Requires GitHub account with Codespaces access

### Editor Setup

**VS Code (Recommended):**

- Kubernetes extension
- YAML extension
- SOPS extension
- Wakatime extension (optional)

**Other Editors:**

- Vim/Neovim with appropriate plugins
- JetBrains IDEs with Kubernetes plugin
- Any editor with YAML and Git support

## 🔒 Security Considerations

### Age Key Management

```bash
# Generate Age key pair for SOPS encryption
age-keygen -o age.key

# Public key goes in config.yaml
# Private key stays local (never commit!)
```

### Access Control Planning

- **SSH keys** for server access
- **API tokens** with minimal required permissions
- **Backup authentication** methods
- **Recovery procedures** documented

### Network Security

- **Firewall rules** for cluster access
- **VPN access** for remote management (recommended)
- **Intrusion detection** consideration
- **Network monitoring** setup

## 📊 Capacity Planning

### Workload Assessment

**Media Services:**

- CPU: Low to moderate (transcoding spikes)
- Memory: Moderate (2-4GB per service)
- Storage: High (media files)
- Network: High bandwidth for streaming

**Home Automation:**

- CPU: Low
- Memory: Low to moderate
- Storage: Low (time series data)
- Network: Low to moderate

**Monitoring Stack:**

- CPU: Moderate (metrics processing)
- Memory: High (time series storage)
- Storage: Moderate (retention policies)
- Network: Moderate (metrics collection)

### Growth Planning

- **Start smaller**: Can always add nodes and storage
- **Monitor usage**: Use Grafana to track resource consumption
- **Scale gradually**: Add resources based on actual needs
- **Plan maintenance**: Consider rolling updates and maintenance windows

## ✅ Pre-Installation Checklist

### Hardware Ready

- [ ] Nodes configured with static IP addresses
- [ ] Network connectivity verified between all nodes
- [ ] Talos ISO created and flashed to installation media
- [ ] All nodes booted from Talos ISO (maintenance mode)

### External Services Configured

- [ ] Domain transferred to or managed by Cloudflare
- [ ] Cloudflare API token created with DNS permissions
- [ ] 1Password account accessible with API capabilities
- [ ] GitHub repository created from template

### Local Environment Ready

- [ ] Development tools installed (`task`, `kubectl`, `flux`)
- [ ] Age key pair generated
- [ ] SSH access to nodes verified (if applicable)
- [ ] Network connectivity to cluster from workstation

### Planning Complete

- [ ] IP address allocation documented
- [ ] Domain structure planned
- [ ] Application workload requirements assessed
- [ ] Backup and recovery strategy outlined

---

**Next Step**: Once all prerequisites are met, proceed to **[Network Planning](./network-planning.md)** for detailed network configuration.
