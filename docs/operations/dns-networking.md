# 🌐 DNS & Networking

Comprehensive guide to DNS resolution, networking architecture, and external access configuration.

## 🏗️ DNS Architecture

The cluster uses a multi-layer DNS setup providing both internal and external access:

1. **External DNS (external-dns)**: Automatically creates DNS records in Cloudflare for ingresses with `external` class
2. **Internal DNS (k8s-gateway)**: Provides DNS resolution for internal services to home network clients  
3. **Cloudflare Tunnel (cloudflared)**: Secure tunnel for external access without exposing ports

## 🔄 DNS Resolution Flow

### For External Access

1. Public DNS queries for `*.albatrossflavour.com` resolve to Cloudflare
2. Cloudflare routes traffic through the tunnel to the cluster
3. Traffic hits the external ingress controller (192.168.8.21)
4. Ingress routes to appropriate services

### For Internal/Home Network Access

1. Home DNS server forwards `*.albatrossflavour.com` queries to k8s-gateway (192.168.8.22)
2. k8s-gateway resolves to internal ingress controller (192.168.8.21)
3. Ingress routes to appropriate services

## 🚪 Ingress Configuration

The cluster runs two ingress controllers for different traffic types:

### External Ingress (`ingress-nginx-external`)

- **Purpose**: Handles traffic from Cloudflare tunnel
- **IP**: 192.168.8.21
- **Ingress Class**: `external`
- **Usage**: For applications accessible from internet

**Example Configuration:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-external
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

### Internal Ingress (`ingress-nginx-internal`)

- **Purpose**: Handles internal home network traffic
- **IP**: 192.168.8.21 (same as external, different ports)
- **Ingress Class**: `internal`
- **Usage**: For home-only applications

**Example Configuration:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: myapp-internal
  annotations:
    kubernetes.io/ingress.class: internal
spec:
  rules:
    - host: myapp.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: myapp
                port: {number: 80}
```

## 🔧 Network Components

### External-DNS

**Purpose**: Automatically manages DNS records in Cloudflare

**Operation:**

- Watches Ingress resources with external-dns annotations
- Creates/updates DNS records in Cloudflare
- Removes records when ingresses are deleted

**Monitoring:**

```bash
# Check external-dns logs
kubectl -n network logs -f deployment/external-dns

# Verify DNS record creation
kubectl -n network logs deployment/external-dns | grep "CREATE\|UPDATE\|DELETE"
```

### K8s-Gateway

**Purpose**: Provides internal DNS resolution for home network

**Operation:**

- Exposes cluster services to home network DNS
- Resolves `*.albatrossflavour.com` to ingress IP
- Enables split-brain DNS for internal/external access

**Monitoring:**

```bash
# Check k8s-gateway status
kubectl -n network logs -f deployment/k8s-gateway

# Test internal DNS resolution
dig @192.168.8.22 grafana.albatrossflavour.com
```

### Cloudflared Tunnel

**Purpose**: Secure external access without port forwarding

**Operation:**

- Establishes secure tunnel to Cloudflare
- Routes external traffic to ingress controller
- Automatically manages certificates

**Monitoring:**

```bash
# Check tunnel connectivity
kubectl -n network logs -f deployment/cloudflared

# Verify tunnel status
kubectl -n network describe deployment cloudflared
```

## 🔄 Managing DNS and Access

### Adding External Access to an Application

1. **Create ingress with external class**
2. **Add external-dns annotation**
3. **Ensure Cloudflare tunnel includes the domain**
4. **Configure TLS certificate**

**Complete Example:**

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: newapp
  namespace: default
  annotations:
    kubernetes.io/ingress.class: external
    external-dns.alpha.kubernetes.io/target: "external.albatrossflavour.com"
    cert-manager.io/cluster-issuer: letsencrypt-production
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  tls:
    - hosts: [newapp.albatrossflavour.com]
      secretName: newapp-tls
  rules:
    - host: newapp.albatrossflavour.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: newapp
                port: {number: 8080}
```

### Adding Internal-Only Access

For applications that should only be accessible from the home network:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: internalapp
  namespace: default
  annotations:
    kubernetes.io/ingress.class: internal
spec:
  rules:
    - host: internalapp.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: internalapp
                port: {number: 3000}
```

## 🔍 DNS Troubleshooting

### Common DNS Issues

**External DNS not creating records:**

```bash
# Check external-dns logs for errors
kubectl -n network logs deployment/external-dns

# Verify Cloudflare API token
kubectl -n network get secret external-dns-secret -o yaml

# Check ingress annotations
kubectl -n <namespace> describe ingress <app>
```

**Internal DNS not resolving:**

```bash
# Test k8s-gateway directly
nslookup app.albatrossflavour.com 192.168.8.22

# Check k8s-gateway logs
kubectl -n network logs deployment/k8s-gateway

# Verify home router DNS forwarding
```

**Tunnel connectivity issues:**

```bash
# Check tunnel logs
kubectl -n network logs deployment/cloudflared

# Verify tunnel credentials
kubectl -n network get secret cloudflared-secret

# Test internal connectivity
kubectl -n network exec deployment/cloudflared -- wget -qO- http://ingress-nginx-external-controller
```

### Diagnostic Commands

**DNS Resolution Testing:**

```bash
# Test external resolution
dig @8.8.8.8 app.albatrossflavour.com

# Test internal resolution
dig @192.168.8.22 app.albatrossflavour.com

# Test from within cluster
kubectl run debug --image=busybox -it --rm -- nslookup app.albatrossflavour.com
```

**Network Connectivity Testing:**

```bash
# Test ingress controllers
kubectl -n network get pods -l app.kubernetes.io/name=ingress-nginx

# Test service endpoints
kubectl -n <namespace> get endpoints

# Test pod-to-pod connectivity
kubectl run debug --image=busybox -it --rm -- ping <service>.<namespace>.svc.cluster.local
```

**Certificate Status:**

```bash
# Check certificate status
kubectl get certificates -A

# Test HTTPS connectivity
curl -I https://app.albatrossflavour.com

# Check cert-manager logs
kubectl -n cert-manager logs deployment/cert-manager
```

## 🔧 Network Policies

The cluster uses Cilium for network security with policies controlling traffic flow:

### Viewing Network Policies

```bash
# List all network policies
kubectl get networkpolicies -A

# Check Cilium status
kubectl -n kube-system get pods -l k8s-app=cilium

# View Cilium connectivity
cilium connectivity test
```

### Common Network Policy Patterns

**Allow ingress traffic:**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress
spec:
  podSelector:
    matchLabels:
      app: myapp
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: network
    ports:
    - protocol: TCP
      port: 8080
```

## 🌉 Reverse Proxy Configuration

Some applications use nginx reverse proxy for:

- Legacy applications not in Kubernetes
- External services that need cluster integration
- Load balancing across multiple backends

### nginx-reverse-proxy Application

Located in `kubernetes/apps/default/nginx-reverse-proxy/`:

**Configuration Example:**

```nginx
server {
    listen 80;
    server_name legacy-app.albatrossflavour.com;

    location / {
        proxy_pass http://192.168.8.100:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

**Managing Reverse Proxy:**

```bash
# Update configuration
kubectl -n default edit configmap nginx-reverse-proxy-config

# Restart to apply changes
kubectl -n default rollout restart deployment/nginx-reverse-proxy

# Check logs
kubectl -n default logs -f deployment/nginx-reverse-proxy
```

## 📊 Monitoring Network Health

### Key Metrics

- DNS query success rates
- Ingress controller response times
- Certificate expiration dates
- Tunnel connectivity status

### Monitoring Commands

```bash
# Check ingress controller metrics
kubectl -n network port-forward svc/ingress-nginx-external-controller-metrics 10254:10254
curl http://localhost:10254/metrics

# Monitor DNS queries
kubectl -n network logs -f deployment/k8s-gateway | grep "query"

# Check tunnel metrics
kubectl -n network port-forward deployment/cloudflared 8080:8080
curl http://localhost:8080/metrics
```

## 📚 Related Documentation

- [Cloudflare Setup](../installation/cloudflare.md) - Initial DNS and tunnel configuration
- [Application Management](./application-management.md) - Managing ingress for applications
- [Common Issues](../troubleshooting/common-issues.md) - DNS and networking troubleshooting
- [Daily Operations](./daily-operations.md) - Routine networking checks
