# 🏠 Kubernetes Homelab

[![wakatime](https://wakatime.com/badge/user/97c75e0e-3119-41db-b612-8c629b4e97f4/project/ef519725-9fe1-48f5-83e1-57bf5545021e.svg)](https://wakatime.com/badge/user/97c75e0e-3119-41db-b612-8c629b4e97f4/project/ef519725-9fe1-48f5-83e1-57bf5545021e)

A production-ready Kubernetes homelab built on **Talos Linux** with **Flux GitOps**, featuring automated certificate management, secure external access via **Cloudflare tunnels**, and comprehensive monitoring.

## ✨ What's Included

### 🏗 Core Infrastructure

- **[Talos Linux](https://www.talos.dev/)** - Immutable Kubernetes OS
- **[Flux](https://fluxcd.io/)** - GitOps continuous delivery
- **[Cilium](https://cilium.io/)** - eBPF-based networking and security
- **[cert-manager](https://cert-manager.io/)** - Automated TLS certificate management
- **[External Secrets](https://external-secrets.io/)** - Secret management with 1Password integration

### 🌐 Networking & Access

- **[Cloudflare Tunnel](https://www.cloudflare.com/products/tunnel/)** - Secure external access
- **[external-dns](https://github.com/kubernetes-sigs/external-dns)** - Automated DNS management
- **[ingress-nginx](https://kubernetes.github.io/ingress-nginx/)** - Internal and external traffic routing
- **[k8s-gateway](https://github.com/ori-edge/k8s_gateway)** - Internal DNS for home network

### 📊 Observability

- **[Prometheus](https://prometheus.io/)** - Metrics collection
- **[Grafana](https://grafana.com/)** - Dashboards and visualization
- **[AlertManager](https://prometheus.io/docs/alerting/latest/alertmanager/)** - Alert routing and management
- **[Gatus](https://gatus.io/)** - Uptime monitoring

### 🎬 Applications

- **Media Stack**: Sonarr, Radarr, Bazarr, Overseerr, qBittorrent, SABnzbd
- **Home Automation**: Home Assistant with comprehensive IoT integration
- **Productivity**: Paperless document management, IT tools
- **Authentication**: Authentik SSO provider

## 🚀 Quick Start

**Want to deploy immediately?** Follow the **[Quick Start Guide](./docs/installation/quick-start.md)** for a 30-minute deployment.

**First time with this setup?** Start with the **[Prerequisites](./docs/installation/prerequisites.md)** and **[Architecture Overview](./docs/architecture/overview.md)**.

### Essential Commands

```bash
# Initialize and configure
task init
task configure

# Deploy cluster
task talos:bootstrap
task flux:bootstrap

# Check status
kubectl get nodes
flux get all -A
```

## 📚 Documentation

### 🚀 Essential Guides

| Guide | Description |
|-------|-------------|
| **[Quick Start](./docs/installation/quick-start.md)** | 30-minute deployment guide |
| **[Architecture Overview](./docs/architecture/overview.md)** | High-level system design |
| **[SSO Setup](./docs/installation/sso-setup.md)** | Complete Authentik SSO configuration |
| **[Daily Operations](./docs/operations/daily-operations.md)** | Common tasks and workflows |

**📖 [Complete Documentation Index](./docs/README.md)** - Browse all installation, operations, and troubleshooting guides

## 🎯 Cluster Information

### Node Configuration

- **Control Plane**: 3 nodes (weatherwax, ogg, magrat)
- **Worker Nodes**: 3 nodes (aching, greebo, wuffles)
- **Network**: 192.168.8.0/24
- **VIPs**: Controller (192.168.8.20), Ingress (192.168.8.21), Gateway (192.168.8.22)
- **Domain**: albatrossflavour.com

*Node names follow [Discworld naming conventions](./docs/about/naming-conventions.md) - because why shouldn't infrastructure have personality?*

### Key Features

- **High Availability**: 3-node control plane
- **Automated Updates**: Renovate dependency management
- **Security**: SOPS encryption, network policies, RBAC
- **Backup**: Volsync snapshots and external storage
- **Monitoring**: Comprehensive metrics and alerting

## 🛠 Development

### Development Environment

This repository includes VS Code devcontainer support and comprehensive tooling:

```bash
# Setup local environment
task workstation:venv

# Or use devcontainer with VS Code
# All tools and extensions pre-configured
```

### Key Tools

- **[Task](https://taskfile.dev/)** - Task automation
- **[SOPS](https://github.com/getsops/sops)** - Secret encryption
- **[Age](https://github.com/FiloSottile/age)** - Modern encryption
- **[Flux CLI](https://fluxcd.io/flux/cmd/)** - GitOps management
- **[kubectl](https://kubernetes.io/docs/reference/kubectl/)** - Kubernetes CLI

### Adding Applications

See **[Adding Applications](./docs/development/adding-applications.md)** for deploying new services to the cluster.

## 📊 Monitoring & Access

### Dashboards

- **Grafana**: https://grafana.albatrossflavour.com
- **Prometheus**: https://prometheus.albatrossflavour.com
- **Gatus**: https://status.albatrossflavour.com

### Applications

- **Home Assistant**: https://homeassistant.albatrossflavour.com
- **Overseerr**: https://overseerr.albatrossflavour.com
- **Paperless**: https://paperless.albatrossflavour.com

## 🤝 Community & Support

### Getting Help

- **[Home Operations Discord](https://discord.gg/home-operations)** - Community support and discussion
- **[GitHub Discussions](https://github.com/onedr0p/cluster-template/discussions)** - Template-specific questions
- **[Documentation](./docs/)** - Comprehensive guides and troubleshooting

### Contributing

This repository is based on the [onedr0p cluster template](https://github.com/onedr0p/cluster-template). Contributions to documentation and improvements are welcome.

### Related Projects

- **[onedr0p/cluster-template](https://github.com/onedr0p/cluster-template)** - The base template
- **[k8s-at-home](https://github.com/k8s-at-home)** - Community charts and tools
- **[awesome-home-kubernetes](https://github.com/k8s-at-home/awesome-home-kubernetes)** - Curated list of resources

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](./LICENSE) file for details.

---

**🚀 Ready to get started?** Check out the **[Quick Start Guide](./docs/installation/quick-start.md)** or browse the **[full documentation](./docs/README.md)**.
