# 🚀 Adding New Applications

Step-by-step guide for deploying new applications to the Kubernetes cluster following GitOps best practices.

## 📋 Prerequisites

Before adding a new application, ensure you have:

- **Kubectl access** to the cluster
- **Git repository access** for committing changes
- **Application requirements** documented (ports, storage, secrets)
- **Domain planning** (internal vs external access)

## 🏗️ Application Structure

Each application follows a standardized directory structure:

```text
kubernetes/apps/<namespace>/<app-name>/
├── app/
│   ├── externalsecret.yaml         # Secrets from 1Password
│   ├── helmrelease.yaml            # Helm chart deployment
│   └── kustomization.yaml          # Includes volsync + gatus templates
├── ks.yaml                         # Flux Kustomization
└── README.md                       # Application documentation (optional)
```

**Note:** No separate PVC files needed - persistence is handled via volsync templates.

## 🎯 Quick Start Example

Let's walk through adding a new application. First, decide on your application and namespace details:

**Example Variables:**

- `NAMESPACE`: `media` (or `documents`, `monitoring`, etc.)
- `APP_NAME`: `sonarr` (or `paperless-ngx`, `grafana`, etc.)

### Step 1: Create Directory Structure

```bash
# Set your variables (adjust these for your application)
NAMESPACE="media"
APP_NAME="sonarr"

# Navigate to the repository root
cd /path/to/your/home-ops

# Create namespace directory if it doesn't exist
mkdir -p kubernetes/apps/${NAMESPACE}/${APP_NAME}/app

# Create the application structure (no PVC needed - handled by volsync)
touch kubernetes/apps/${NAMESPACE}/${APP_NAME}/ks.yaml
touch kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/externalsecret.yaml
touch kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/helmrelease.yaml
touch kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/kustomization.yaml
```

### Step 2: Configure Flux Kustomization

**File**: `kubernetes/apps/${NAMESPACE}/${APP_NAME}/ks.yaml`

```yaml
---
# yaml-language-server: $schema=https://kubernetes-schemas.pages.dev/kustomize.toolkit.fluxcd.io/kustomization_v1.json
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: &app ${APP_NAME}
  namespace: flux-system
spec:
  targetNamespace: ${NAMESPACE}
  commonMetadata:
    labels:
      app.kubernetes.io/name: *app
  dependsOn:
    - name: external-secrets-stores
    # Add cloudnative-pg-cluster only if app needs database
  path: ./kubernetes/apps/${NAMESPACE}/${APP_NAME}/app
  prune: true
  sourceRef:
    kind: GitRepository
    name: home-kubernetes
  wait: false
  interval: 30m
  retryInterval: 1m
  timeout: 5m
  postBuild:
    substitute:
      APP: *app
      GATUS_SUBDOMAIN: ${APP_NAME}
      VOLSYNC_CAPACITY: 15Gi
```

### Step 3: Configure External Secrets

**File**: `kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/externalsecret.yaml`

```yaml
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: ${APP_NAME}-secret
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: onepassword-connect
  target:
    name: ${APP_NAME}-secret
    creationPolicy: Owner
    template:
      engineVersion: v2
      data:
        # Database configuration
        DB_USER: "{{ .DB_USER }}"
        DB_PASS: "{{ .DB_PASS }}"
        DB_HOST: "${APP_NAME}-postgresql"
        DB_NAME: "${APP_NAME}"

        # Admin user
        ADMIN_USER: "{{ .ADMIN_USER }}"
        ADMIN_PASSWORD: "{{ .ADMIN_PASSWORD }}"

        # Security
        SECRET_KEY: "{{ .SECRET_KEY }}"

        # Additional app-specific secrets
        API_KEY: "{{ .API_KEY }}"
  dataFrom:
    - extract:
        key: ${APP_NAME}
```

**Note**: Since we're using 1Password integration, this file doesn't need SOPS encryption - External Secrets will fetch the values directly from 1Password.

### Step 4: Create Persistent Volume Claim

**File**: `kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/pvc.yaml`

```yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${APP_NAME}-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 15Gi
  storageClassName: ceph-block
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: ${APP_NAME}-config
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
  storageClassName: ceph-block
```

### Step 5: Configure Helm Release

**File**: `kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/helmrelease.yaml`

```yaml
---
apiVersion: helm.toolkit.fluxcd.io/v2beta1
kind: HelmRelease
metadata:
  name: paperless-ngx
spec:
  interval: 30m
  chart:
    spec:
      chart: app-template
      version: 1.5.1
      sourceRef:
        kind: HelmRepository
        name: bjw-s
        namespace: flux-system
  maxHistory: 2
  install:
    remediation:
      retries: 3
  upgrade:
    cleanupOnFail: true
    remediation:
      retries: 3
  uninstall:
    keepHistory: false
  values:
    controller:
      type: statefulset
      annotations:
        reloader.stakater.com/auto: "true"

    image:
      repository: ghcr.io/paperless-ngx/paperless-ngx
      tag: 1.17.4

    env:
      # Basic configuration
      PAPERLESS_PORT: &port 8000
      PAPERLESS_URL: "https://paperless.albatrossflavour.com"
      PAPERLESS_TIME_ZONE: "America/New_York"

      # Features
      PAPERLESS_OCR_LANGUAGE: "eng"
      PAPERLESS_CONSUMER_POLLING: 60
      PAPERLESS_CONSUMER_RECURSIVE: true
      PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS: true

    envFrom:
      - secretRef:
          name: paperless-ngx-secret

    service:
      main:
        ports:
          http:
            port: *port

    ingress:
      main:
        enabled: true
        ingressClassName: external
        annotations:
          external-dns.alpha.kubernetes.io/target: "external.albatrossflavour.com"
          cert-manager.io/cluster-issuer: "letsencrypt-production"
          nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
          nginx.ingress.kubernetes.io/proxy-body-size: "100m"
        hosts:
          - host: &host "paperless.albatrossflavour.com"
            paths:
              - path: /
                pathType: Prefix
        tls:
          - hosts:
              - *host
            secretName: paperless-tls

    persistence:
      data:
        enabled: true
        existingClaim: paperless-data
        mountPath: /usr/src/paperless/data
      media:
        enabled: true
        existingClaim: paperless-media
        mountPath: /usr/src/paperless/media
      consume:
        enabled: true
        type: nfs
        server: 192.168.8.100
        path: /mnt/user/paperless/consume
        mountPath: /usr/src/paperless/consume

    resources:
      requests:
        cpu: 100m
        memory: 256Mi
      limits:
        memory: 512Mi

    # PostgreSQL database
    postgresql:
      enabled: true
      auth:
        existingSecret: paperless-ngx-secret
        secretKeys:
          adminPasswordKey: PAPERLESS_DBPASS
          userPasswordKey: PAPERLESS_DBPASS
        username: paperless
        database: paperless
      primary:
        persistence:
          enabled: true
          size: 8Gi
          storageClass: openebs-hostpath

    # Redis cache
    redis:
      enabled: true
      auth:
        enabled: false
      master:
        persistence:
          enabled: false
```

### Step 6: Configure Kustomization

**File**: `kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/kustomization.yaml`

```yaml
---
# yaml-language-server: $schema=https://json.schemastore.org/kustomization
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: documents
resources:
  - ./pvc.yaml
  - ./helmrelease.yaml
  - ./externalsecret.yaml
  - ../../../../templates/gatus/guarded    # Health monitoring with authentication
  - ../../../../templates/volsync         # Backup and replication
generatorOptions:
  disableNameSuffixHash: true
```

**Template Explanations:**

- **`gatus/guarded`**: Adds health monitoring with authentication requirements
- **`volsync`**: Provides backup and replication using the `VOLSYNC_CLAIM` specified in ks.yaml

### Step 7: Add Secrets to 1Password

Create a new item in 1Password with the key `${APP_NAME}`:

```text
DB_USER=${APP_NAME}
DB_PASS=<secure-password>
ADMIN_USER=admin
ADMIN_PASSWORD=<admin-password>
SECRET_KEY=<50-character-random-string>
API_KEY=<application-specific-api-key>
```

### Step 8: Update Namespace Kustomization

**File**: `kubernetes/apps/${NAMESPACE}/kustomization.yaml`

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ./namespace.yaml
  - ./${APP_NAME}/ks.yaml
```

### Step 9: Create Namespace (if needed)

**File**: `kubernetes/apps/${NAMESPACE}/namespace.yaml`

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: ${NAMESPACE}
  labels:
    name: ${NAMESPACE}
    kustomize.toolkit.fluxcd.io/prune: disabled
```

### Step 10: Update Cluster Kustomization

**File**: `kubernetes/flux/apps.yaml`

```yaml
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: cluster-apps
  namespace: flux-system
spec:
  # ... existing config ...
  dependsOn:
    - name: cluster-apps-external-secrets-stores
    - name: cluster-apps-${NAMESPACE}  # Add this line
```

**File**: `kubernetes/flux/kustomization.yaml`

```yaml
---
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  # ... existing resources ...
  - ./apps.yaml
  - ./config.yaml
```

### Step 11: Create Application Documentation

**File**: `documents/paperless-ngx/README.md`

```markdown
# Paperless-ngx

Document management system for scanning, indexing, and archiving documents.

## Application Details

- **Namespace**: documents
- **Chart**: bjw-s/app-template
- **Version**: 1.17.4
- **External URL**: https://paperless.albatrossflavour.com

## Configuration

### Storage

- **Data**: 5Gi persistent volume for application data
- **Media**: 10Gi persistent volume for processed documents
- **Consume**: NFS mount for document intake
- **Database**: 8Gi PostgreSQL database

### Secrets

Managed via External Secrets from 1Password:

- Database credentials
- Admin user credentials
- Secret key for sessions

### Networking

- **Internal Port**: 8000
- **External Access**: Via Cloudflare tunnel
- **Ingress Class**: external
- **TLS**: Let's Encrypt certificate

## Operations

### Common Tasks

```bash
# Check application status
kubectl -n documents get pods -l app.kubernetes.io/name=paperless-ngx

# View logs
kubectl -n documents logs -f deployment/paperless-ngx

# Restart application
kubectl -n documents rollout restart deployment/paperless-ngx

# Access database
kubectl -n documents exec -it deployment/paperless-ngx-postgresql -- psql -U paperless
```

### Troubleshooting

- Check External Secrets sync status
- Verify NFS mount accessibility
- Monitor database connectivity
- Check ingress certificate status

## 📋 Deployment Checklist

Before committing your changes, verify:

### ✅ Pre-Deployment

- [ ] **Directory structure** follows standard layout
- [ ] **Namespace** exists or is created
- [ ] **Dependencies** are properly configured
- [ ] **Secrets** are added to 1Password
- [ ] **Storage requirements** are specified
- [ ] **Resource limits** are set appropriately
- [ ] **Ingress configuration** is correct
- [ ] **External Secrets** reference correct 1Password items

### ✅ Validation

```bash
# Validate Kubernetes manifests
kubectl apply --dry-run=client -f kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/

# Check Flux Kustomization syntax
flux create kustomization test --source=flux-system --path="./kubernetes/apps/${NAMESPACE}/${APP_NAME}/app" --dry-run

# Validate External Secrets configuration
kubectl apply --dry-run=client -f kubernetes/apps/${NAMESPACE}/${APP_NAME}/app/externalsecret.yaml
```

## 🚀 Deployment Process

### Step 1: Commit and Push

```bash
# Add all new files
git add kubernetes/apps/${NAMESPACE}/${APP_NAME}/

# Commit changes
git commit -m "Add ${APP_NAME} to ${NAMESPACE} namespace

- Configure Helm release with app-template
- Set up External Secrets integration
- Add Ceph persistent storage
- Configure external ingress with TLS
- Include Volsync backup and Gatus monitoring"

# Push to repository
git push
```

### Step 2: Monitor Deployment

```bash
# Watch Flux reconciliation
flux get kustomizations -A -w

# Monitor namespace creation
kubectl get namespaces -w

# Check application deployment
kubectl -n ${NAMESPACE} get pods -w

# Verify secrets creation
kubectl -n ${NAMESPACE} get secrets
```

### Step 3: Verify Application

```bash
# Check ingress status
kubectl -n ${NAMESPACE} get ingress

# Verify external DNS record creation
kubectl -n network logs deployment/external-dns --tail=20

# Test external access
curl -I https://${APP_NAME}.albatrossflavour.com

# Check certificate status
kubectl -n ${NAMESPACE} get certificates
```

## 💾 Storage Configuration

The cluster provides several storage options for different use cases:

### Storage Classes Available

#### Ceph Storage (Primary)

- **Use case**: Primary storage for all persistent data
- **Performance**: High (distributed block storage)
- **Availability**: Highly available across nodes
- **Best for**: Databases, application data, persistent volumes

```yaml
# pvc.yaml
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: paperless-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: ceph-block
```

#### Local Storage (openebs-hostpath)

- **Use case**: Application data, databases, configuration
- **Performance**: High (local SSD/NVMe)
- **Availability**: Node-local (not shared)
- **Best for**: Databases, application state, fast I/O

```yaml
volumeClaimTemplates:
  - name: data
    mountPath: /app/data
    accessMode: ReadWriteOnce
    size: 10Gi
    storageClass: openebs-hostpath
```

#### NFS Storage

- **Use case**: Media files, shared data, backup storage
- **Performance**: Good (network dependent)
- **Availability**: Shared across all nodes
- **Best for**: Media libraries, shared files, large datasets

```yaml
persistence:
  media:
    enabled: true
    type: nfs
    server: 192.168.8.100          # NAS IP address
    path: /mnt/user/media          # NFS export path
    mountPath: /app/media          # Mount point in container
```

#### Hostpath Storage

- **Use case**: Direct access to node filesystem
- **Performance**: Highest (direct disk access)
- **Availability**: Node-specific
- **Best for**: System containers, node-specific data

```yaml
persistence:
  config:
    enabled: true
    type: hostPath
    hostPath: /opt/app/config
    mountPath: /app/config
```

#### EmptyDir Storage

- **Use case**: Temporary data, cache, scratch space
- **Performance**: High (RAM or local disk)
- **Availability**: Pod lifecycle only
- **Best for**: Temporary files, cache, inter-container communication

```yaml
persistence:
  tmp:
    enabled: true
    type: emptyDir
    medium: Memory                 # Optional: use RAM
    sizeLimit: 1Gi
    mountPath: /tmp
```

### Storage Examples by Application Type

#### Database Application (Ceph Storage)

```yaml
# Create PVC first (pvc.yaml)
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: postgres-data
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 20Gi
  storageClassName: ceph-block

# PostgreSQL with Ceph storage
postgresql:
  enabled: true
  auth:
    existingSecret: app-secret
  primary:
    persistence:
      enabled: true
      existingClaim: postgres-data

# Redis with Ceph storage
redis:
  enabled: true
  auth:
    enabled: false
  master:
    persistence:
      enabled: true
      existingClaim: redis-data
```

#### Media Application

```yaml
# Sonarr with NFS for media library
persistence:
  media:
    enabled: true
    type: nfs
    server: 192.168.8.100
    path: /mnt/user/media/tv
    mountPath: /tv
  downloads:
    enabled: true
    type: nfs
    server: 192.168.8.100
    path: /mnt/user/downloads
    mountPath: /downloads

# Local storage for application configuration
volumeClaimTemplates:
  - name: config
    mountPath: /config
    accessMode: ReadWriteOnce
    size: 1Gi
    storageClass: openebs-hostpath
```

#### Backup Application

```yaml
# Backup application with both local and NFS storage
persistence:
  # Local high-speed cache
  cache:
    enabled: true
    type: emptyDir
    sizeLimit: 10Gi
    mountPath: /cache

  # NFS backup destination
  backup:
    enabled: true
    type: nfs
    server: 192.168.8.100
    path: /mnt/user/backups
    mountPath: /backups

# Local metadata storage
volumeClaimTemplates:
  - name: metadata
    mountPath: /metadata
    accessMode: ReadWriteOnce
    size: 5Gi
    storageClass: openebs-hostpath
```

### Storage Best Practices

#### Performance Considerations

- **Databases**: Use `ceph-block` for high performance with high availability
- **Application data**: `ceph-block` provides best balance of performance and availability
- **Media streaming**: NFS is sufficient, provides shared access
- **Temporary data**: Use `emptyDir` with memory backing for speed
- **Configuration**: Ceph storage for persistent, backed-up configuration

#### Availability Considerations

- **Critical data**: Use `ceph-block` with automatic backup via Volsync
- **Shared data**: NFS for multi-node access (media libraries)
- **High availability**: Ceph provides redundancy across the cluster
- **Backup strategy**: Volsync templates handle automatic backup to external storage

#### Size Planning

```yaml
# Conservative sizing examples
config_storage: 100Mi - 1Gi      # Application configuration
database_storage: 5Gi - 50Gi     # Most databases
media_storage: 100Gi - 10Ti      # Media libraries (NFS)
backup_storage: 50Gi - 5Ti       # Backup destinations (NFS)
cache_storage: 1Gi - 10Gi        # Application cache
```

### Storage Troubleshooting

#### Check Storage Usage

```bash
# Check PVC status
kubectl get pvc -A

# Check storage classes
kubectl get storageclass

# Check node storage capacity
kubectl describe nodes | grep -A5 "Allocated resources"

# Check OpenEBS components
kubectl -n openebs-system get pods
```

#### Common Storage Issues

- **PVC Pending**: Check storage class and node capacity
- **Mount failures**: Verify NFS connectivity and permissions
- **Performance issues**: Consider moving to local storage
- **Out of space**: Monitor usage and plan expansion

## 🔧 Common Patterns

### Internal-Only Application

For applications that should only be accessible from the home network:

```yaml
ingress:
  main:
    enabled: true
    ingressClassName: internal  # Use internal instead of external
    hosts:
      - host: &host "app.local"  # Use .local domain
        paths:
          - path: /
            pathType: Prefix
    # No external-dns annotation
    # No TLS configuration needed
```

### Pattern: Database Application

For applications requiring a database:

```yaml
# In helmrelease.yaml
postgresql:
  enabled: true
  auth:
    existingSecret: app-secret
    secretKeys:
      adminPasswordKey: DB_PASSWORD
      userPasswordKey: DB_PASSWORD
    username: appuser
    database: appdb
  primary:
    persistence:
      enabled: true
      size: 8Gi
      storageClass: openebs-hostpath
```

### Pattern: Media Application

For media applications requiring large storage:

```yaml
persistence:
  media:
    enabled: true
    type: nfs
    server: 192.168.8.100
    path: /mnt/user/media
    mountPath: /media
  downloads:
    enabled: true
    type: nfs
    server: 192.168.8.100
    path: /mnt/user/downloads
    mountPath: /downloads
```

### High-Availability Application

For applications requiring multiple replicas:

```yaml
controller:
  type: deployment
  replicas: 3
  strategy: RollingUpdate

resources:
  requests:
    cpu: 100m
    memory: 128Mi
  limits:
    cpu: 500m
    memory: 512Mi

affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 100
        podAffinityTerm:
          labelSelector:
            matchExpressions:
              - key: app.kubernetes.io/name
                operator: In
                values: [app-name]
          topologyKey: kubernetes.io/hostname
```

## 🔍 Troubleshooting

### Flux Not Syncing

```bash
# Check Flux status
flux get all -A

# Force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster-apps

# Check for validation errors
kubectl -n flux-system logs deployment/kustomize-controller
```

### External Secrets Not Working

```bash
# Check External Secrets status
kubectl -n documents get externalsecrets

# Check 1Password Connect
kubectl -n external-secrets get pods -l app.kubernetes.io/name=onepassword-connect

# Verify secret store
kubectl get clustersecretstore onepassword-connect -o yaml
```

### Ingress Issues

```bash
# Check ingress creation
kubectl -n documents describe ingress app-name

# Check external-dns logs
kubectl -n network logs deployment/external-dns --tail=50

# Test DNS resolution
dig app.albatrossflavour.com
```

### Storage Problems

```bash
# Check PVC status
kubectl -n documents get pvc

# Check storage class
kubectl get storageclass

# Check OpenEBS
kubectl -n openebs-system get pods
```

## Advanced Patterns

### Multi-Container Applications

When deploying applications with multiple containers (main app + sidecar services), use `advancedMounts` instead of `globalMounts` to prevent ReadWriteOnce PVC conflicts:

#### Correct Pattern (Prevents PVC Conflicts)

```yaml
# In helmrelease.yaml
controllers:
  main-app:
    containers:
      app:
        image:
          repository: myapp/main
          tag: latest
        # Main application logic

  sidecar-service:
    containers:
      app:
        image:
          repository: myapp/sidecar
          tag: latest
        # Supporting service (e.g., browserless, redis)

persistence:
  data:
    type: persistentVolumeClaim
    accessMode: ReadWriteOnce
    size: 1Gi
    storageClass: ceph-block
    advancedMounts:
      main-app:  # Only mount to main controller
        app:
          - path: /app/data

service:
  main:
    controller: main-app
    ports:
      http:
        port: 3000
  sidecar:
    controller: sidecar-service
    ports:
      http:
        port: 8080
```

#### Incorrect Pattern (Causes PVC Conflicts)

```yaml
persistence:
  data:
    type: persistentVolumeClaim
    globalMounts:  # ❌ Mounts to ALL containers
      - path: /app/data
```

### Database Provisioning with CloudNative-PG

For applications requiring PostgreSQL databases, use this standard pattern:

#### 1. ExternalSecret Configuration

```yaml
# In externalsecret.yaml
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: myapp
spec:
  target:
    name: myapp-secret
    template:
      engineVersion: v2
      data:
        # App-specific variables
        MYAPP_DB_PASSWORD: &dbPass "{{ .MYAPP_DB_PASSWORD }}"

        # Database connection string
        DATABASE_URL: "postgresql://myapp:{{ .MYAPP_DB_PASSWORD }}@postgres16-rw.database.svc.cluster.local:5432/myapp"

        # Postgres Init variables (for database creation)
        INIT_POSTGRES_DBNAME: &dbName myapp
        INIT_POSTGRES_HOST: &dbHost postgres16-rw.database.svc.cluster.local
        INIT_POSTGRES_USER: &dbUser myapp
        INIT_POSTGRES_PASS: *dbPass
        INIT_POSTGRES_SUPER_PASS: "{{ .POSTGRES_SUPER_PASS }}"
  dataFrom:
    - extract:
        key: myapp
    - extract:
        key: cloudnative-pg  # For postgres superuser credentials
```

#### 2. HelmRelease with Init Container

```yaml
# In helmrelease.yaml
controllers:
  myapp:
    initContainers:
      init-db:
        image:
          repository: ghcr.io/home-operations/postgres-init
          tag: "17"
        envFrom:
          - secretRef:
              name: myapp-secret
    containers:
      app:
        image:
          repository: myapp/app
          tag: latest
        envFrom:
          - secretRef:
              name: myapp-secret
```

#### 3. Dependencies

```yaml
# In ks.yaml
dependsOn:
  - name: external-secrets-stores
  - name: cloudnative-pg-cluster
```

### Minio Storage Integration

For applications requiring object storage:

#### Environment Variables

```yaml
# In helmrelease.yaml
env:
  STORAGE_ENDPOINT: "minio.default.svc.cluster.local"
  STORAGE_PORT: "9000"
  STORAGE_REGION: "us-east-1"
  STORAGE_BUCKET: "myapp"
  STORAGE_USE_SSL: "false"
  STORAGE_SKIP_BUCKET_CHECK: "true"  # Skip validation on startup
```

#### ExternalSecret for Credentials

```yaml
# In externalsecret.yaml (template section)
data:
  STORAGE_ACCESS_KEY: "{{ .MINIO_ROOT_USER }}"
  STORAGE_SECRET_KEY: "{{ .MINIO_ROOT_PASSWORD }}"
dataFrom:
  - extract:
      key: myapp
  - extract:
      key: minio  # Reuse existing Minio credentials
```

**Important**: Create the bucket manually in Minio web UI before deploying the application.

## 📚 Related Documentation

- [Application Management](./application-management.md) - Managing deployed applications
- [DNS & Networking](./dns-networking.md) - Ingress and external access
- [Daily Operations](./daily-operations.md) - Monitoring and maintenance
- [Common Issues](../troubleshooting/common-issues.md) - Troubleshooting applications
