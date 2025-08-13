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
- **Storage**: Multi-tier approach with OpenEBS (temporary/stateless), Rook-Ceph (persistent/replicated), and NFS (large shared data)

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

## Storage Architecture

### Storage Strategy: EBS + Ceph + NFS

This cluster uses a multi-tier storage approach optimized for different workload types:

#### OpenEBS (EBS)

- **Use case**: Temporary and stateless workloads, high-performance local storage
- **Benefits**: High performance local storage, low overhead, fast I/O
- **Storage class**: `openebs-hostpath`
- **Examples**: Cache data, temporary processing, application logs

#### Rook-Ceph

- **Use case**: Persistent data requiring replication and backups
- **Benefits**: Distributed storage, data redundancy, snapshot capabilities
- **Storage class**: `ceph-block`, `ceph-filesystem`
- **Examples**: Application databases, user data, configuration files

#### NFS

- **Use case**: Large shared storage, bulk data, media files
- **Benefits**: High capacity, shared across multiple pods, cost-effective
- **Configuration**: `192.168.1.22:/volume2/apps/<appname>`
- **Examples**: Media files, backups, shared application assets

## Database Provisioning Pattern

### Standard PostgreSQL Setup with CloudNative-PG

For apps requiring PostgreSQL databases, use this standard pattern:

#### ExternalSecret Configuration

```yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: appname
spec:
  target:
    name: appname-secret
    template:
      engineVersion: v2
      data:
        # App-specific variables
        APPNAME_DB_PASSWORD: &dbPass "{{ .APPNAME_DB_PASSWORD }}"

        # Postgres Init variables
        INIT_POSTGRES_DBNAME: &dbName appname
        INIT_POSTGRES_HOST: &dbHost postgres16-rw.database.svc.cluster.local
        INIT_POSTGRES_USER: &dbUser appname
        INIT_POSTGRES_PASS: *dbPass
        INIT_POSTGRES_SUPER_PASS: "{{ .POSTGRES_SUPER_PASS }}"
  dataFrom:
    - extract:
        key: appname
    - extract:
        key: cloudnative-pg
```

#### HelmRelease Init Container

```yaml
controllers:
  appname:
    initContainers:
      init-db:
        image:
          repository: ghcr.io/home-operations/postgres-init
          tag: "17"
        envFrom:
          - secretRef:
              name: appname-secret
```

#### Dependencies

```yaml
# In ks.yaml
dependsOn:
  - name: external-secrets-stores
  - name: cloudnative-pg-cluster
```

## Multi-Container Application Patterns

### Avoiding PVC Conflicts

When deploying applications with multiple containers (main app + sidecar services), use `advancedMounts` instead of `globalMounts` to prevent ReadWriteOnce PVC conflicts:

#### Correct Pattern

```yaml
persistence:
  data:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 1Gi
    storageClass: ceph-block
    advancedMounts:
      main-controller:  # Only mount to specific controller
        app:
          - path: /app/data

controllers:
  main-controller:
    containers:
      app:
        # Main application container
  sidecar-controller:
    containers:
      app:
        # Sidecar container (no storage mount)
```

#### Incorrect Pattern (Causes Conflicts)

```yaml
persistence:
  data:
    type: persistentVolumeClaim
    globalMounts:  # ❌ Mounts to ALL containers
      - path: /app/data
```

## Minio Integration Best Practices

### Standard Configuration

- **Always reuse existing credentials**: Use `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD` from existing minio 1Password item
- **Standard endpoint**: `minio.default.svc.cluster.local:9000`
- **Skip bucket validation**: Set `STORAGE_SKIP_BUCKET_CHECK: "true"` for apps that validate buckets on startup
- **Create buckets manually**: Use Minio web UI to create required buckets before app deployment

### Environment Variables Pattern

```yaml
# In HelmRelease
env:
  STORAGE_ENDPOINT: "minio.default.svc.cluster.local"
  STORAGE_PORT: "9000"
  STORAGE_REGION: "us-east-1"
  STORAGE_BUCKET: "appname"
  STORAGE_USE_SSL: "false"
  STORAGE_SKIP_BUCKET_CHECK: "true"

# In ExternalSecret
data:
  STORAGE_ACCESS_KEY: "{{ .MINIO_ROOT_USER }}"
  STORAGE_SECRET_KEY: "{{ .MINIO_ROOT_PASSWORD }}"
```

## Troubleshooting Workflow

### Common Issues and Resolution Steps

1. **Check init containers completed successfully**

   ```bash
   kubectl logs <pod-name> -c init-db
   ```

2. **Verify ExternalSecret synchronization**

   ```bash
   kubectl get externalsecret <appname>
   kubectl describe externalsecret <appname>
   ```

3. **Check environment variables are populated**

   ```bash
   kubectl exec deployment/<appname> -- env | grep <VARIABLE>
   ```

4. **Resolve PVC conflicts**
   - Use `advancedMounts` instead of `globalMounts`
   - Force delete conflicting pods: `kubectl delete pods -l app=<name> --force --grace-period=0`

5. **Handle Helm upgrade timeouts**

   ```bash
   flux reconcile kustomization <appname> --with-source
   ```

6. **Database connection issues**
   - Verify init container ran successfully
   - Check database user was created: `kubectl exec -n database deployment/postgres16 -- psql -U postgres -c "\du"`
   - Verify connection string format and credentials

## Templating System

Uses makejinja for Jinja2 templating:

- Template files end with `.j2` extension
- Configuration from `config.yaml` available as variables
- Custom delimiters: `#{variable}#`, `#%block%#`, `#|comment|#`
- Templates in `bootstrap/templates/` render to `kubernetes/`

## Development Tools Integration

### Wakatime Time Tracking

- Project configured as "home-ops" for consistent tracking
- VS Code integration with recommended extensions
- Tracks time across YAML, Jinja2, scripts, and documentation
- See `docs/WAKATIME.md` for full setup and analytics guide

### VS Code Configuration

- Enhanced YAML schemas for Kubernetes and Flux manifests
- SOPS integration for encrypted secrets editing
- Kubernetes tools integration with local kubeconfig
- File associations for homelab-specific file types

## Application Deployment Patterns

### Standard Application Structure

When deploying new applications, follow these exact patterns to avoid common issues:

#### ExternalSecret Configuration pragma: allowlist secret

Always use the correct API version and structure:

```yaml
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/external-secrets.io/externalsecret_v1.json
apiVersion: external-secrets.io/v1  # Always v1, never v1beta1
kind: ExternalSecret
metadata:
  name: appname
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: appname-secret
    template:
      engineVersion: v2
```

#### Kustomization.yaml Structure

Use templates instead of hardcoded configurations:

```yaml
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./externalsecret.yaml
  - ./helmrelease.yaml
  - ../../../../templates/gatus/external    # For monitoring
  - ../../../../templates/volsync           # For backups
```

#### ks.yaml Dependencies and Variables

**CRITICAL**: Most apps only need `external-secrets-stores` dependency. Only add others if specifically needed:

```yaml
dependsOn:
  - name: external-secrets-stores   # Standard for ALL apps
  - name: cloudnative-pg-cluster    # Only if app needs database
  - name: rook-ceph-cluster         # Only if app needs ceph storage
postBuild:
  substitute:
    APP: *app                       # Application name
    GATUS_SUBDOMAIN: app-name      # Monitoring subdomain
    VOLSYNC_CAPACITY: 20Gi         # Storage size
```

#### Standard Persistence Pattern

**CRITICAL**: Never create PVCs directly in HelmRelease. Always use volsync template pattern:

1. **HelmRelease persistence**: Use `existingClaim: appname` (NOT size/storageClass)
2. **Kustomization**: Include `../../../../templates/volsync`
3. **ks.yaml**: Set `VOLSYNC_CAPACITY` in postBuild.substitute
4. **Volsync template** automatically creates PVC with backup/restore capabilities

```yaml
# In HelmRelease
persistence:
  data:
    existingClaim: node-red  # Uses APP variable from ks.yaml
    globalMounts:
      - path: /data

# In app/kustomization.yaml  
resources:
  - ./externalsecret.yaml
  - ./helmrelease.yaml
  - ../../../../templates/gatus/external
  - ../../../../templates/volsync

# In ks.yaml
postBuild:
  substitute:
    VOLSYNC_CAPACITY: 10Gi  # This creates the PVC
```

#### Namespace Organization

- `utilities`: Workflow/automation tools (n8n, cyberchef, it-tools)
- `default`: Core home services (Home Assistant, Minio)
- `database`: Data services (PostgreSQL, Redis, EMQX)
- `media`: Media server stack (Sonarr, Radarr, etc.)
- `observability`: Monitoring and alerting
- `security`: Authentication and security tools

#### 1Password Integration

- Vault name: `discworld`
- Use `op cli` for creating items: `op item create --vault="discworld"`
- Generate secure secrets: `openssl rand -base64 32` # pragma: allowlist secret

### Standard App Deployment Workflow

When deploying any new application, follow this exact sequence:

1. **Create directory structure**: `mkdir -p kubernetes/apps/NAMESPACE/APPNAME/app`
2. **Create externalsecret.yaml**: Always use `apiVersion: external-secrets.io/v1`
3. **Create helmrelease.yaml**: Use `existingClaim: APPNAME` for persistence
4. **Create app/kustomization.yaml**: Include volsync and gatus templates
5. **Create ks.yaml**: Use only `external-secrets-stores` dependency unless database needed
6. **Update namespace kustomization.yaml**: Add `- ./APPNAME/ks.yaml`
7. **Create 1Password item**: `op item create --vault="discworld" --title="APPNAME" --category="Server" FIELD="$(openssl rand -base64 32)"`
8. **Ensure branch protection**: Main branch must be protected for Renovate to work
9. **Test with**: `task flux:apply path=NAMESPACE/APPNAME`

**Key patterns**:

- Dependencies: `external-secrets-stores` (standard), `cloudnative-pg-cluster` (if database)
- Persistence: `existingClaim: APPNAME` + volsync template + `VOLSYNC_CAPACITY`
- Monitoring: Include gatus template in kustomization
- Secrets: Always use 1Password via ExternalSecret, create item with secure random values
- 1Password fields: Use descriptive names (e.g. `APPNAME_PASSWORD`, `APPNAME_API_KEY`)
- **Images: Always use `tag: version@sha256:digest` format for Renovate compatibility and security**

### Renovate Image Management

**CRITICAL**: All container images MUST use SHA256 digest pinning for security and Renovate automation.

**Getting digests for new images:**

```bash
# Pull and get digest in one command
docker pull repository/image:tag && docker inspect repository/image:tag --format='{{index .RepoDigests 0}}'

# Example output: repository/image@sha256:abc123...
# Use as: tag: "version@sha256:abc123..." (MUST be quoted due to @ character)
```

**Configuration:**

- Renovate config includes `docker:pinDigests` preset for automatic digest pinning
- New images without digests will be automatically updated with digests by Renovate
- Digest updates create separate PRs with `chore(container)` commits
- Version updates include both new version and new digest

**No special annotations required** - Renovate automatically detects and manages:

- Container images in HelmReleases
- Version updates with digest updates
- Security-first pinning approach

### Renovate Branch Protection Requirements

**CRITICAL**: Main branch MUST be protected for Renovate to function properly.

**Required GitHub branch protection settings**:

1. Go to repo **Settings → Branches**
2. Add protection rule for `main` branch
3. **Minimum required settings**:
   - ✅ **Require status checks to pass before merging**
   - ✅ **Require branches to be up to date before merging**
   - ✅ Add status checks: `pre-commit` (if using pre-commit hooks)
   - ❌ **Do NOT** enforce on administrators (allows emergency fixes)

**Alternative: GitHub CLI setup**:

```bash
gh api repos/:owner/:repo/branches/main/protection \
  --method PUT \
  --field required_status_checks='{"strict":true,"contexts":["pre-commit"]}' \
  --field enforce_admins=false \
  --field required_pull_request_reviews='{"required_approving_review_count":0}' \
  --field restrictions=null
```

### Renovate Troubleshooting

**Common issues and solutions**:

| Issue | Cause | Solution |
|-------|-------|----------|
| "Error updating branch" | Unprotected main branch | Enable branch protection |
| "Excess registryUrls found" | Conflicting Helm repo configs | Check fileMatch patterns in renovate.json5 |
| No PRs created | Schedule restrictions | Check `schedule: ["every weekend"]` in config |
| YAML syntax errors | Unquoted @sha256 digests | Always quote: `tag: "version@sha256:digest"` |

**Manual trigger Renovate**:

- Comment `@renovatebot rebase` on any issue/PR
- Push empty commit: `git commit --allow-empty -m "trigger renovate"`
- GitHub Actions → Run "Renovate" workflow manually

## Repository Setup Requirements

### GitHub Branch Protection (MANDATORY)

**Branch protection is required for Renovate to function**:

- Main branch must have protection rules enabled
- Required status checks should include pre-commit hooks
- Allows automated PR creation and merging
- Prevents accidental force pushes or deletions

### Pre-commit Hooks

- Enforce YAML syntax validation (prevents @sha256 quote issues)  
- Run security scanning with detect-secrets
- Validate Kubernetes manifests with kubeval/kubeconform
- Format code consistently across the repository

### Renovate Configuration

- Configured for weekend runs to minimize disruption
- Automatic digest pinning for all container images
- Grouped updates for related components (Flux, Talos)
- Auto-merge enabled for minor/patch updates and digests

## Important Notes

- All SOPS files must be encrypted before committing
- Use `kubectl --kubeconfig kubeconfig` for cluster access
- Talos configuration stored in `kubernetes/bootstrap/talos/clusterconfig/talosconfig`
- Pre-commit hooks enforce code quality and security scanning
- Renovate handles automated dependency updates via GitHub PRs
- 1Password integration supports both personal/family and business accounts
