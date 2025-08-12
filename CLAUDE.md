# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a Kubernetes home operations repository based on the onedr0p cluster template. It uses Talos Linux as the operating system and Flux for GitOps-based cluster management. The repository contains Infrastructure as Code (IaC) configurations for a complete Kubernetes homelab setup with Cloudflare integration.

## Architecture

### Core Components

- **Talos Linux**: Immutable Kubernetes-focused operating system
- **Flux**: GitOps tool for continuous deployment from Git
- **SOPS**: Encrypted secrets management using Age encryption
- **Kustomize**: Kubernetes native configuration management
- **Helm**: Package manager for Kubernetes applications

### Directory Structure

- `bootstrap/`: Jinja2 templates for initial cluster configuration
- `kubernetes/apps/`: Application manifests organized by namespace
- `kubernetes/bootstrap/`: Core cluster bootstrapping configs (Talos, Flux)
- `kubernetes/flux/`: Flux system configuration and repositories
- `kubernetes/templates/`: Reusable Kustomize templates
- `.taskfiles/`: Task definitions for various operations

### Secret Management

- Uses SOPS with Age encryption for all sensitive data
- Age key stored in `age.key` file
- SOPS configuration in `.sops.yaml`
- All `.sops.yaml` files contain encrypted secrets

## Common Commands

### Development Environment Setup

```bash
# Initialize configuration from template
task init

# Setup Python virtual environment and dependencies
task workstation:venv

# Configure repository (renders templates, encrypts secrets)
task configure
```

### Cluster Operations

```bash
# Bootstrap Talos cluster
task talos:bootstrap

# Install Flux into cluster
task flux:bootstrap

# Force Flux reconciliation
task flux:reconcile

# Validate Kubernetes manifests
task kubernetes:kubeconform

# Get cluster resource overview
task kubernetes:resources
```

### Application Management

```bash
# Apply specific Flux Kustomization
task flux:apply path=<app-path>

# Example: Apply homepage app
task flux:apply path=default/homepage
```

### Talos Management

```bash
# Upgrade Talos node
task talos:upgrade node=<ip> image=<factory-image>

# Upgrade Kubernetes
task talos:upgrade-k8s controller=<ip> to=<version>

# Destroy cluster (resets to maintenance mode)
task talos:nuke
```

### Pre-commit and Validation

```bash
# Run pre-commit hooks manually
pre-commit run --all-files

# Validate YAML with yamllint
yamllint kubernetes/

# Check SOPS encryption
detect-secrets scan --baseline .secrets.baseline
```

## Development Workflow

### Configuration Changes

1. Update `config.yaml` with your changes
2. Run `task configure` to render templates
3. Commit encrypted secrets and rendered manifests
4. Push to trigger Flux reconciliation

### Adding New Applications

1. Create application directory under `kubernetes/apps/<namespace>/`
2. Add HelmRelease or Kustomization manifests
3. Create corresponding `ks.yaml` (Kustomization) file
4. Update namespace kustomization to include new app
5. Test with `task flux:apply path=<namespace>/<app>`

### Secret Management Workflow

1. Create/edit `.sops.yaml` files with sensitive data
2. Encrypt with `sops --encrypt --in-place <file>.sops.yaml`
3. Never commit unencrypted sensitive data
4. Use ExternalSecrets or direct SOPS decryption in manifests

## Key Configuration Files

### Bootstrap Configuration (`config.yaml`)

Contains cluster-wide settings including:

- Node inventory and network configuration
- Cloudflare domain and API tokens
- GitHub repository settings
- Talos-specific configurations

### Flux Configuration

- `kubernetes/flux/config/`: Core Flux system setup
- `kubernetes/flux/repositories/`: Helm and Git repository definitions
- `kubernetes/flux/vars/`: Cluster variables and secrets

### Application Organization

Applications are organized by namespace:

- `cert-manager/`: Certificate management
- `database/`: PostgreSQL, Redis, EMQX
- `default/`: Core applications (Homepage, Home Assistant)
- `media/`: Media server stack (Sonarr, Radarr, etc.)
- `network/`: Ingress, DNS, tunneling
- `observability/`: Monitoring and alerting
- `security/`: Authentication and security tools

## Templating System

Uses makejinja for Jinja2 templating:

- Template files end with `.j2` extension
- Configuration from `config.yaml` available as variables
- Custom delimiters: `#{variable}#`, `#%block%#`, `#|comment|#`
- Templates in `bootstrap/templates/` render to `kubernetes/`

## Important Notes

- All SOPS files must be encrypted before committing
- Use `kubectl --kubeconfig kubeconfig` for cluster access
- Talos configuration stored in `kubernetes/bootstrap/talos/clusterconfig/talosconfig`
- Pre-commit hooks enforce code quality and security scanning
- Renovate handles automated dependency updates via GitHub PRs
