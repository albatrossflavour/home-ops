# ☁️ Cloudflare Setup Guide

Complete guide for configuring Cloudflare domain management, DNS automation, and secure tunnel access for your Kubernetes homelab.

## 📋 Prerequisites

### Required Accounts

- **Cloudflare account** (free tier sufficient)
- **Domain** managed by or transferred to Cloudflare
- **Kubernetes cluster** deployed and accessible

### Before You Begin

- [ ] Domain transferred to Cloudflare or nameservers updated
- [ ] Cloudflare dashboard access verified
- [ ] Basic understanding of DNS concepts

## 🌐 Domain Setup

### 1. Add Domain to Cloudflare

**If domain is registered elsewhere:**

1. **Login to Cloudflare Dashboard**
2. **Add a Site** → Enter your domain
3. **Select plan** (Free is sufficient for homelab)
4. **Update nameservers** at your domain registrar:

   ```text
   NS1: ava.ns.cloudflare.com
   NS2: ryan.ns.cloudflare.com
   ```

5. **Wait for DNS propagation** (up to 24 hours)

**Verify DNS propagation:**

```bash
# Check nameserver delegation
dig NS your-domain.com

# Should show Cloudflare nameservers
# ava.ns.cloudflare.com
# ryan.ns.cloudflare.com
```

### 2. SSL/TLS Configuration

**Recommended Settings:**

1. **Navigate to**: SSL/TLS → Overview
2. **Set encryption mode**: `Full (strict)`
3. **Enable**: Always Use HTTPS
4. **Navigate to**: SSL/TLS → Edge Certificates
5. **Configure settings**:

   ```yaml
   Always Use HTTPS: On
   HTTP Strict Transport Security (HSTS): Enabled
   Minimum TLS Version: 1.2
   TLS 1.3: Enabled
   Automatic HTTPS Rewrites: On
   Certificate Transparency Monitoring: On
   ```

### 3. Security Settings

**Navigate to**: Security → Settings

```yaml
Security Level: Medium
Challenge Passage: 30 minutes
Browser Integrity Check: On
Privacy Pass Support: On
```

**Bot Fight Mode** (optional but recommended):

```yaml
Bot Fight Mode: On
Super Bot Fight Mode: Off (unless you have a paid plan)
```

## 🔑 API Token Creation

### 1. Create DNS Management Token

**Navigate to**: My Profile → API Tokens → Create Token

**Token Configuration:**

```yaml
Token name: k8s-external-dns
Permissions:
  - Zone:Zone:Read (All zones)
  - Zone:DNS:Edit (Specific zone: your-domain.com)
Zone Resources:
  - Include: Specific zone → your-domain.com
Client IP Address Filtering:
  - Include: Your home IP range (optional)
TTL: No expiration (or set based on security policy)
```

**Save the token securely** - you'll need it for external-dns configuration.

### 2. Verify Token Permissions

**Test the token:**

```bash
# Replace YOUR_TOKEN and YOUR_DOMAIN
curl -X GET "https://api.cloudflare.com/client/v4/zones" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json"

# Should return your zone information
```

## 🚇 Cloudflare Tunnel Setup

### 1. Create Tunnel via Dashboard

**Navigate to**: Zero Trust → Access → Tunnels

**Create tunnel:**

1. **Click**: Create a tunnel
2. **Select**: Cloudflared
3. **Name**: `homelab-tunnel` (or your preferred name)
4. **Copy the tunnel token** - save this securely

**Tunnel token format:**

```text
eyJhIjoiYWNjb3VudF9pZCIsInQiOiJ0dW5uZWxfaWQiLCJzIjoic2VjcmV0In0=
```

### 2. Extract Tunnel Credentials

**Decode the tunnel token to extract values:**

```bash
# Decode base64 token (example)
echo "eyJhIjoiYWNjb3VudF9pZCIsInQiOiJ0dW5uZWxfaWQiLCJzIjoic2VjcmV0In0=" | base64 -d  # pragma: allowlist secret

# Output example:
# {"a":"your_account_id","t":"your_tunnel_id","s":"your_tunnel_secret"}
```

**Extract these values for config.yaml:**

- `account_id`: Cloudflare account ID
- `tunnel_id`: Tunnel identifier
- `secret`: Tunnel authentication secret

### 3. Configure Tunnel Routes

**In Cloudflare Dashboard:**

1. **Navigate to**: Zero Trust → Access → Tunnels
2. **Click** your tunnel → Configure
3. **Add public hostnames**:

```yaml
# Example routes
Public hostname: *.k8s.your-domain.com
Service: http://192.168.8.21:80
Additional application settings:
  - No TLS Verify: Off
  - HTTP Host Header: Leave blank
```

**Add specific application routes:**

```yaml
# Grafana
Public hostname: grafana.your-domain.com
Service: http://192.168.8.21:80

# Home Assistant  
Public hostname: homeassistant.your-domain.com
Service: http://192.168.8.21:80

# Overseerr
Public hostname: overseerr.your-domain.com
Service: http://192.168.8.21:80
```

### 4. Update config.yaml

**Add tunnel configuration to your config.yaml:**

```yaml
bootstrap_cloudflare:
  enabled: true
  domain: "your-domain.com"
  token: "your-api-token-here"  # pragma: allowlist secret
  acme:
    email: "your-email@your-domain.com"
    production: false  # Start with staging certificates
  ingress_vip: "192.168.8.21"
  gateway_vip: "192.168.8.22"
  tunnel:
    id: "tunnel-id-from-decode"
    account_id: "account-id-from-decode"
    secret: "secret-from-decode"  # pragma: allowlist secret
    ingress_vip: "192.168.8.23"
```

## 🏠 Split DNS Configuration

Split DNS allows internal clients to access services directly while external clients use the tunnel.

### 1. Router Configuration

**Most Home Routers:**

1. **Navigate to**: DHCP/DNS Settings
2. **Add custom DNS entry**:

   ```yaml
   Domain: your-domain.com
   DNS Server: 192.168.8.22
   ```

### 2. Pi-hole Configuration

**Add to `/etc/dnsmasq.d/99-k8s-gateway.conf`:**

```bash
# Forward cluster domain to k8s-gateway
server=/your-domain.com/192.168.8.22
```

**Restart Pi-hole:**

```bash
sudo systemctl restart pihole-FTL
```

### 3. UniFi Configuration

**UniFi Dream Machine/Controller:**

1. **Navigate to**: Settings → Networks → LAN
2. **DHCP Name Server**: Manual
3. **DNS Server 1**: 192.168.8.22
4. **DNS Server 2**: 1.1.1.1 (fallback)

**Or create DNS record:**

1. **Navigate to**: Settings → Profiles → Domain
2. **Add domain**: `your-domain.com` → `192.168.8.22`

### 4. Verify Split DNS

**Test internal resolution:**

```bash
# From internal network
nslookup grafana.your-domain.com 192.168.8.22
# Should return: 192.168.8.21

# Test external resolution
nslookup grafana.your-domain.com 8.8.8.8
# Should return: Cloudflare IP addresses
```

## 🚀 Deploy Configuration

### 1. Generate and Apply Templates

```bash
# Generate Kubernetes manifests
task configure

# Verify external-dns configuration
cat kubernetes/apps/network/external-dns/app/secret.sops.yaml

# Verify cloudflared configuration  
cat kubernetes/apps/network/cloudflared/app/secret.sops.yaml
```

### 2. Deploy to Cluster

```bash
# Apply via Flux
git add .
git commit -m "Add Cloudflare configuration"
git push

# Force Flux reconciliation
flux reconcile source git flux-system
flux reconcile kustomization cluster
```

### 3. Verify Deployment

**Check external-dns:**

```bash
# Verify pod status
kubectl get pods -n network | grep external-dns

# Check logs for DNS record creation
kubectl logs -n network deployment/external-dns --tail=50

# Look for messages like:
# INFO Desired change: CREATE grafana.your-domain.com A [target IP]
```

**Check cloudflared tunnel:**

```bash
# Verify tunnel pod
kubectl get pods -n network | grep cloudflared

# Check tunnel connectivity
kubectl logs -n network deployment/cloudflared --tail=50

# Look for:
# INF Connection established connIndex=0
# INF Registered tunnel connection
```

## 🔒 Certificate Management

### 1. Start with Staging Certificates

**Verify Let's Encrypt staging setup:**

```bash
# Check cert-manager issuer
kubectl get clusterissuer

# Check initial certificate requests
kubectl get certificates -A
kubectl get certificaterequests -A
```

**Monitor certificate creation:**

```bash
# Watch certificate status
kubectl get certificates -A --watch

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=100
```

### 2. Transition to Production Certificates

**Once staging certificates work properly:**

1. **Update config.yaml:**

   ```yaml
   bootstrap_cloudflare:
     acme:
       production: true  # Change from false
   ```

2. **Regenerate and apply:**

   ```bash
   task configure
   git add .
   git commit -m "Switch to Let's Encrypt production certificates"
   git push
   ```

3. **Delete existing certificates to force renewal:**

   ```bash
   # Delete staging certificates
   kubectl delete certificates -A --all

   # Let cert-manager recreate with production issuer
   flux reconcile kustomization cluster
   ```

4. **Verify production certificates:**

   ```bash
   # Check certificate status
   kubectl get certificates -A

   # Verify in browser - should show valid Let's Encrypt certificate
   curl -I https://grafana.your-domain.com
   ```

## 🧪 Testing External Access

### 1. DNS Resolution Test

**External DNS test:**

```bash
# Test from external network (use mobile data or VPN)
dig grafana.your-domain.com
# Should resolve to Cloudflare IP addresses

# Test specific DNS servers
dig @8.8.8.8 grafana.your-domain.com
dig @1.1.1.1 grafana.your-domain.com
```

### 2. Application Access Test

**Test applications through tunnel:**

```bash
# Basic connectivity test
curl -I https://grafana.your-domain.com

# Full application test
curl -L https://grafana.your-domain.com/login

# Test from external network
# Use mobile data or external VPS for testing
```

### 3. Internal vs External Verification

**Create test script:**

```bash
#!/bin/bash
# test-access.sh

DOMAIN="your-domain.com"
SERVICES=("grafana" "homeassistant" "overseerr")

echo "=== Internal Access Test ==="
for service in "${SERVICES[@]}"; do
    echo "Testing $service.$DOMAIN"
    curl -I -m 5 "https://$service.$DOMAIN" 2>/dev/null | head -1
done

echo "=== External DNS Resolution ==="
for service in "${SERVICES[@]}"; do
    echo "Testing $service.$DOMAIN"
    dig +short "$service.$DOMAIN" @8.8.8.8
done
```

## 🔧 Troubleshooting

### Common Issues

#### DNS Records Not Created

**Check external-dns logs:**

```bash
kubectl logs -n network deployment/external-dns --tail=100

# Common errors:
# - API token permissions insufficient
# - Rate limiting from Cloudflare
# - Zone not found
```

**Verify API token:**

```bash
# Test token manually
curl -X GET "https://api.cloudflare.com/client/v4/zones" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

#### Tunnel Connection Issues

**Check cloudflared logs:**

```bash
kubectl logs -n network deployment/cloudflared --tail=100

# Common errors:
# - Authentication failed (wrong credentials)
# - Network connectivity issues
# - Tunnel configuration mismatch
```

**Verify tunnel configuration:**

```bash
# Check tunnel secret
kubectl get secret -n network cloudflared-secret -o yaml

# Verify tunnel status in Cloudflare dashboard
```

#### Certificate Issues

**Check cert-manager:**

```bash
# Check certificate status
kubectl describe certificate -A

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager --tail=100

# Common issues:
# - DNS challenge failures
# - Rate limiting (use staging first)
# - Network connectivity to Let's Encrypt
```

#### Split DNS Not Working

**Test DNS resolution:**

```bash
# Test internal DNS server
nslookup grafana.your-domain.com 192.168.8.22

# Check k8s-gateway logs
kubectl logs -n network deployment/k8s-gateway --tail=50

# Verify router/Pi-hole configuration
```

### Debugging Commands

**External-DNS debugging:**

```bash
# Enable debug logging
kubectl patch deployment external-dns -n network -p '{"spec":{"template":{"spec":{"containers":[{"name":"external-dns","args":["--source=ingress","--domain-filter=your-domain.com","--provider=cloudflare","--cloudflare-proxied","--log-level=debug"]}]}}}}'

# Watch for DNS changes
kubectl logs -n network deployment/external-dns -f
```

**Tunnel debugging:**

```bash
# Check tunnel metrics
kubectl port-forward -n network deployment/cloudflared 8080:8080
curl http://localhost:8080/metrics

# Test tunnel connectivity
kubectl exec -n network deployment/cloudflared -- wget -qO- http://192.168.8.21
```

## 🔒 Security Considerations

### API Token Security

- **Least privilege**: Only DNS edit permissions for your zone
- **IP restrictions**: Limit to your home IP range if static
- **Regular rotation**: Rotate tokens periodically
- **Monitoring**: Monitor API usage in Cloudflare dashboard

### Tunnel Security

- **Tunnel credentials**: Store securely in SOPS-encrypted secrets
- **Access control**: Use Cloudflare Access for additional protection
- **Monitoring**: Monitor tunnel metrics and logs
- **Network policies**: Restrict pod-to-pod communication

### DNS Security

- **DNSSEC**: Enable in Cloudflare for your domain
- **CAA records**: Restrict certificate authorities
- **Monitoring**: Monitor DNS changes and certificate issuance

## 📊 Monitoring

### Cloudflare Analytics

**Dashboard metrics:**

- DNS query volume and patterns
- Tunnel traffic and performance
- Security threats blocked
- Certificate status and expiration

### Kubernetes Metrics

**Monitor these components:**

```bash
# external-dns metrics
kubectl port-forward -n network deployment/external-dns 7979:7979
curl http://localhost:7979/metrics

# cert-manager metrics  
kubectl port-forward -n cert-manager deployment/cert-manager 9402:9402
curl http://localhost:9402/metrics

# cloudflared metrics
kubectl port-forward -n network deployment/cloudflared 8080:8080
curl http://localhost:8080/metrics
```

### Alerting Rules

**Add to Prometheus:**

```yaml
# Certificate expiration
- alert: CertificateExpiringSoon
  expr: (x509_cert_not_after - time()) / 86400 < 7
  labels:
    severity: warning
  annotations:
    summary: Certificate expiring in less than 7 days

# DNS record drift
- alert: DNSRecordDrift
  expr: increase(external_dns_source_endpoints_total[1h]) > 10
  labels:
    severity: warning
  annotations:
    summary: High DNS record change rate detected
```

---

**Next Steps:**

- [Production Readiness](./production-readiness.md) - Security and monitoring setup
- [DNS & Networking](../operations/dns-networking.md) - Operational DNS management
- [SSO Setup](../operations/sso-setup.md) - Secure application access

**Related Documentation:**

- [Architecture Overview](../architecture/overview.md) - Understanding the networking design
- [Troubleshooting](../troubleshooting/common-issues.md) - Common DNS and networking issues
