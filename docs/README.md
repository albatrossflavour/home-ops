# 📚 Documentation Index

Welcome to the comprehensive documentation for this Kubernetes homelab setup. This documentation is organized into focused guides to help you deploy, operate, and maintain your cluster.

## 🚀 Getting Started

### New to this setup?

1. **[Quick Start Guide](./installation/quick-start.md)** - Get up and running fast
2. **[Architecture Overview](./architecture/overview.md)** - Understand the system design
3. **[Prerequisites](./installation/prerequisites.md)** - What you need before starting

### Ready to deploy?

4. **[Installation Guide](./installation/)** - Complete deployment process
5. **[First Steps](./operations/first-steps.md)** - Post-installation configuration

## 📖 Documentation Sections

### 🏗 Installation & Setup

- **[Prerequisites](./installation/prerequisites.md)** - Hardware, accounts, and planning
- **[Network Planning](./installation/network-planning.md)** - IP addressing and DNS setup
- **[Cloudflare Setup](./installation/cloudflare.md)** - Domain, tunnels, and DNS integration
- **[SSO Setup](./installation/sso-setup.md)** - Complete Authentik SSO configuration
- **[Secrets Management](./installation/secrets.md)** - SOPS and 1Password configuration
- **[Cluster Deployment](./installation/cluster-deployment.md)** - Talos and Kubernetes setup
- **[Application Deployment](./installation/application-deployment.md)** - Core services and apps
- **[Production Readiness](./installation/production-readiness.md)** - Security and monitoring

### ⚙️ Operations & Maintenance

- **[Daily Operations](./operations/daily-operations.md)** - Common tasks and workflows
- **[Adding Applications](./operations/adding-applications.md)** - Step-by-step guide for new apps
- **[Application Management](./operations/application-management.md)** - Managing services
- **[DNS & Networking](./operations/dns-networking.md)** - Traffic flow and troubleshooting
- **[Backup & Recovery](./operations/backup-recovery.md)** - Data protection
- **[Monitoring](./operations/monitoring.md)** - Observability and alerting
- **[Updates & Upgrades](./operations/updates.md)** - Keeping the system current

### 🏛 Architecture & Design

- **[System Overview](./architecture/overview.md)** - High-level architecture ✅
- **[Network Architecture](./architecture/networking.md)** - Traffic flow and DNS
- **[Security Model](./architecture/security.md)** - Authentication and authorization
- **[Storage Design](./architecture/storage.md)** - Persistent volumes and backup
- **[Application Stack](./architecture/applications.md)** - Deployed services

### 🔧 Troubleshooting & Maintenance

- **[Common Issues](./troubleshooting/common-issues.md)** - Frequent problems and solutions
- **[Diagnostic Commands](./troubleshooting/diagnostics.md)** - Health checks and debugging
- **[Recovery Procedures](./troubleshooting/recovery.md)** - Disaster recovery
- **[Performance Tuning](./troubleshooting/performance.md)** - Optimization guides

### 🛠 Development & Customization

- **[Adding Applications](./operations/adding-applications.md)** - Deploy new services
- **[Template Customization](./development/templates.md)** - Modifying configurations
- **[Development Workflow](./development/workflow.md)** - Local development setup
- **[Testing](./development/testing.md)** - Validation and quality assurance

### 📊 Tools & Integrations

- **[Wakatime Integration](./WAKATIME.md)** - Time tracking and analytics
- **[VS Code Setup](./development/vscode.md)** - IDE configuration
- **[CLI Tools](./development/cli-tools.md)** - Command-line utilities

### 📖 Reference Documentation

- **[Original Template README](./ORIGINAL-README.md)** - Complete installation guide from template
- **[Operations Reference](./OPERATIONS-REFERENCE.md)** - Comprehensive operations manual

### 📚 About This Project

- **[Naming Conventions](./about/naming-conventions.md)** - Why everything has Discworld names

## 🎯 Quick Reference

### Essential Commands

```bash
# Cluster status
kubectl get nodes -o wide
flux get all -A

# Application management  
task flux:apply path=media/sonarr
kubectl -n media logs -f deployment/sonarr

# Maintenance
task talos:upgrade node=192.168.8.10 image=factory.talos.dev/installer/...
task kubernetes:kubeconform
```

### Important Files

- **[config.yaml](../config.yaml)** - Main cluster configuration
- **[CLAUDE.md](../CLAUDE.md)** - AI assistant guidance
- **[Taskfile.yaml](../Taskfile.yaml)** - Automation commands

### Key Endpoints

- **Grafana**: https://grafana.your-domain.com
- **Home Assistant**: https://homeassistant.your-domain.com
- **Gatus**: https://status.your-domain.com

## 🆘 Need Help?

### Immediate Issues

1. Check **[Common Issues](./troubleshooting/common-issues.md)** first
2. Run **[Diagnostic Commands](./troubleshooting/diagnostics.md)**
3. Review logs: `kubectl logs -n <namespace> <pod>`

### Emergency Procedures

- **[Recovery Procedures](./troubleshooting/recovery.md)** - When things go wrong
- **[Emergency Contacts](./troubleshooting/emergency.md)** - Support channels

### Community Support

- **[Home Operations Discord](https://discord.gg/home-operations)** - Community help
- **[GitHub Discussions](https://github.com/onedr0p/cluster-template/discussions)** - Template support

## 📝 Contributing

This documentation is living and should be updated as the system evolves:

1. **Update docs** when making significant changes
2. **Test procedures** before documenting them
3. **Link related docs** to improve navigation
4. **Keep examples current** with actual configuration

### Documentation Standards

- Use clear, step-by-step instructions
- Include validation commands
- Provide troubleshooting notes
- Link to relevant files and external docs

---

**💡 Tip**: Bookmark this page and use it as your navigation hub for all homelab documentation!
