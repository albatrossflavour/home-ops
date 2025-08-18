# Container Architecture Override Template

This template provides standardised ways to override container images in Helm charts to ensure AMD64 architecture compatibility.

## Usage

When adding new applications, include architecture-specific overrides for common problematic containers:

### Init Containers
```yaml
# For charts using curl/wget init containers
downloadDashboards:
  image:
    repository: curlimages/curl
    tag: "8.9.1@sha256:8addc281f0ea517409209f76832b6ddc2cabc3264feb1ebbec2a2521ffad24e4"

# For charts using busybox init containers  
initContainers:
  image:
    repository: busybox
    tag: "1.36.1@sha256:650fd573e056b679a5110a70aabeb01e26b76e545ec4b9c70a9523f2dfaf18c6"
```

### Sidecar Containers
```yaml
sidecar:
  image:
    repository: quay.io/kiwigrid/k8s-sidecar
    tag: "1.30.3@sha256:49dcce269568b1645b0050f296da787c99119647965229919a136614123f0627"
```

### Common Problematic Images

These images frequently have architecture issues:
- `curlimages/curl` - Use SHA256 digest
- `busybox` - Use SHA256 digest  
- `alpine` - Use SHA256 digest
- `k8s-sidecar` - Use SHA256 digest
- `postgres-init` scripts - Ensure AMD64 build

## Automated Checks

Renovate will automatically:
1. Pin digests for security
2. Update to new versions while maintaining architecture
3. Create separate PRs for digest updates vs version updates