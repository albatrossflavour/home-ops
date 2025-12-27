# 🛡️ Cilium Network Policy Management

Comprehensive guide for managing Cilium network policies for threat detection and blocking.

## 📋 Overview

The cluster uses Cilium network policies to:

- Allow all trusted sources (private networks, Cloudflare)
- Monitor traffic from known threat sources (Tor, VPNs, botnets)
- Block malicious traffic (when enforcement mode enabled)
- Provide visibility into attack patterns

## 🏗️ Architecture

### Policy Types

**CiliumClusterwideNetworkPolicy**: Applies to all pods cluster-wide

- `allow-trusted-sources.yaml` - Whitelist for private networks and Cloudflare
- `audit-threat-intel.yaml` - Audit mode monitoring (logs only)
- `block-threat-intel.yaml` - Enforcement mode blocking (created after validation)

### Current Deployment State

**Phase 1: Audit Mode** (Current)

- ✅ Whitelist policies active (private networks always allowed)
- ✅ Audit policies logging threat intel traffic
- ❌ No blocking enabled (observation only)

## 📊 Monitoring Traffic

### View Cilium Logs

```bash
# Watch for traffic from threat intel IPs
kubectl --kubeconfig kubeconfig logs -n kube-system -l k8s-app=cilium --tail=100 -f | grep "Policy verdict"

# Check specific IP range
kubectl --kubeconfig kubeconfig logs -n kube-system -l k8s-app=cilium --tail=100 | grep "185.220"

# View all policy denials (when enforcement enabled)
kubectl --kubeconfig kubeconfig logs -n kube-system -l k8s-app=cilium | grep "DENIED"
```

### Hubble Observability (If Installed)

```bash
# Install Hubble CLI
# brew install hubble

# Port-forward to Hubble relay
kubectl --kubeconfig kubeconfig port-forward -n kube-system svc/hubble-relay 4245:80

# Observe dropped traffic
hubble observe --verdict DROPPED

# Watch traffic from specific CIDR
hubble observe --from-cidr 185.220.100.0/22

# See traffic to ingress-nginx
hubble observe --to-label app.kubernetes.io/name=ingress-nginx
```

### Prometheus Metrics

```promql
# Policy drops over time
sum(rate(cilium_policy_verdict_total{verdict="DENIED"}[5m])) by (source, destination)

# Top blocked source IPs
topk(10, sum by (source_ip) (rate(cilium_drop_count_total{reason="Policy denied"}[5m])))

# Policy enforcement errors
rate(cilium_policy_l3_l4_error_total[5m])
```

## 🔧 Managing Policies

### List Active Policies

```bash
# List all cluster-wide policies
kubectl --kubeconfig kubeconfig get ciliumclusterwideNetworkpolicies

# List namespace-specific policies
kubectl --kubeconfig kubeconfig get ciliumnetworkpolicies -A

# View policy details
kubectl --kubeconfig kubeconfig describe cnp <policy-name> -n <namespace>
```

### Update Whitelist (Add Trusted Sources)

**File**: `kubernetes/apps/kube-system/cilium/policies/allow-trusted-sources.yaml`

```yaml
# Add new trusted CIDR ranges
- fromCIDR:
    - 203.0.113.0/24  # Example: new office network
  toPorts:
    - ports:
        - port: "1"
          endPort: "65535"
          protocol: TCP
```

**Apply changes**:

```bash
git add kubernetes/apps/kube-system/cilium/policies/allow-trusted-sources.yaml
git commit -m "feat(cilium): add trusted network 203.0.113.0/24"
git push

# Force reconciliation
flux reconcile kustomization cilium-policies --with-source
```

### Update Threat Intelligence

**File**: `kubernetes/apps/kube-system/cilium/policies/audit-threat-intel.yaml`

**Add new threat IP ranges**:

```yaml
# Add to ingress section
- fromCIDRSet:
    # New botnet range discovered
    - cidr: 198.51.100.0/24
  toPorts:
    - ports:
        - port: "80"
          protocol: TCP
        - port: "443"
          protocol: TCP
```

**Sources for threat intelligence**:

- Spamhaus DROP/EDROP lists: <https://www.spamhaus.org/drop/>
- Tor exit nodes: <https://check.torproject.org/torbulkexitlist>
- Feodo Tracker: <https://feodotracker.abuse.ch/blocklist/>
- AbuseCH IP Blocklist: <https://sslbl.abuse.ch/blacklist/>

**Automated updates** (future enhancement):

```bash
# CronJob to fetch and update threat feeds daily
# See templates/cilium/threat-intel-updater.yaml
```

## 🚀 Enabling Enforcement Mode

**IMPORTANT**: Only enable after 48+ hours of audit mode with no false positives.

### Step 1: Review Audit Logs

```bash
# Check for any legitimate traffic that might be blocked
kubectl logs -n kube-system -l k8s-app=cilium --since=48h | grep "185.220" > audit-review.txt

# Review the file for any known-good traffic
less audit-review.txt
```

### Step 2: Create Enforcement Policy

**File**: `kubernetes/apps/kube-system/cilium/policies/block-threat-intel.yaml`

```yaml
---
# yaml-language-server: $schema=https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/cilium.io/ciliumclusterwideNetworkpolicy_v2.json
apiVersion: "cilium.io/v2"
kind: CiliumClusterwideNetworkPolicy
metadata:
  name: block-threat-intel
  annotations:
    policy.cilium.io/description: "ENFORCEMENT: Block known threat sources"
spec:
  description: "Block traffic from known malicious sources"
  endpointSelector: {}
  ingressDeny:
    # Block Tor exit nodes
    - fromCIDR:
        - 185.220.100.0/22
      toPorts:
        - ports:
            - port: "80"
              protocol: TCP
            - port: "443"
              protocol: TCP

    # Block other threat ranges
    - fromCIDR:
        - 45.142.120.0/22  # Example VPN/proxy abuse
      toPorts:
        - ports:
            - port: "80"
              protocol: TCP
            - port: "443"
              protocol: TCP
```

### Step 3: Add to Kustomization

**File**: `kubernetes/apps/kube-system/cilium/policies/kustomization.yaml`

```yaml
resources:
  - ./allow-trusted-sources.yaml
  - ./audit-threat-intel.yaml
  - ./block-threat-intel.yaml  # Add this line
```

### Step 4: Deploy with Monitoring

```bash
# Commit changes
git add kubernetes/apps/kube-system/cilium/policies/
git commit -m "feat(cilium): enable enforcement mode for threat intel blocking"
git push

# Apply and watch
flux reconcile kustomization cilium-policies --with-source

# Monitor for issues
kubectl logs -n kube-system -l k8s-app=cilium -f | grep "DENIED"
```

### Step 5: Validation

```bash
# Test from VPN/Tor (should be blocked)
# curl -I https://status.${SECRET_DOMAIN}
# Expected: Connection timeout or refused

# Test from home network (should work)
curl -I https://status.${SECRET_DOMAIN}
# Expected: HTTP 200 OK

# Check Prometheus metrics for blocks
# Visit Grafana → Explore → Prometheus
# Query: sum(rate(cilium_policy_verdict_total{verdict="DENIED"}[5m]))
```

## 🆘 Emergency Procedures

### Quick Disable All Policies

```bash
# Suspend Flux kustomization (stops policy enforcement)
flux --kubeconfig kubeconfig suspend kustomization cilium-policies

# Verify suspension
flux get kustomizations | grep cilium-policies
# Should show: False    True
```

### Delete Specific Policy

```bash
# Delete blocking policy only (keeps whitelists)
kubectl --kubeconfig kubeconfig delete ciliumclusterwideNetworkpolicy block-threat-intel

# Verify deletion
kubectl get ccnp
```

### Delete All Policies (Nuclear Option)

```bash
# Delete all cluster-wide policies
kubectl --kubeconfig kubeconfig delete ciliumclusterwideNetworkpolicy --all

# WARNING: This removes whitelists too!
# Traffic may be disrupted until policies are reapplied
```

### Resume from Suspension

```bash
# Resume Flux kustomization
flux --kubeconfig kubeconfig resume kustomization cilium-policies

# Force immediate reconciliation
flux reconcile kustomization cilium-policies --with-source
```

### Node-Level Emergency Access

**If you're completely locked out:**

```bash
# SSH to any control plane node
ssh tgreen@192.168.8.10  # weatherwax

# Use local kubectl
sudo kubectl --kubeconfig /var/etc/kubernetes/admin.conf get nodes

# Delete policies from node
sudo kubectl --kubeconfig /var/etc/kubernetes/admin.conf delete ccnp --all

# Restart Cilium agents (clears runtime state)
sudo kubectl --kubeconfig /var/etc/kubernetes/admin.conf rollout restart daemonset/cilium -n kube-system
```

## 🔍 Troubleshooting

### Policy Not Taking Effect

```bash
# Check policy status
kubectl describe ccnp <policy-name>

# Look for errors in status
kubectl get ccnp <policy-name> -o jsonpath='{.status}'

# Check Cilium operator logs
kubectl logs -n kube-system deployment/cilium-operator -f
```

### Legitimate Traffic Blocked (False Positive)

#### Step 1: Identify the source

```bash
# Check recent drops
kubectl logs -n kube-system -l k8s-app=cilium --tail=500 | grep "DENIED"
```

#### Step 2: Add exception to whitelist

```yaml
# In allow-trusted-sources.yaml
- fromCIDR:
    - 203.0.113.50/32  # Specific legitimate IP
  toPorts:
    - ports:
        - port: "443"
          protocol: TCP
```

#### Step 3: Apply and verify

```bash
git add kubernetes/apps/kube-system/cilium/policies/allow-trusted-sources.yaml
git commit -m "fix(cilium): whitelist legitimate source 203.0.113.50"
git push
flux reconcile kustomization cilium-policies --with-source
```

### Policy Conflicts

```bash
# Check for overlapping CIDRs
kubectl get ccnp -o yaml | grep -A 5 "fromCIDR"

# Cilium processes policies in order:
# 1. Explicit allow (whitelist)
# 2. Explicit deny (blocklist)
# 3. Default (depends on endpointSelector)

# Whitelists (allow-trusted-sources) always win
```

### Performance Impact

```bash
# Check policy computation overhead
kubectl top nodes

# Monitor Cilium memory usage
kubectl top pods -n kube-system | grep cilium

# If high resource usage:
# - Consolidate CIDR ranges (use larger blocks)
# - Remove unused policies
# - Consider using CiliumNetworkPolicy (namespace-scoped) instead of cluster-wide
```

## 📈 Grafana Dashboards

### Import Pre-built Dashboards

**Cilium Metrics Dashboard**:

- Dashboard ID: 16611
- Import: Grafana → Dashboards → Import → 16611

**Custom Queries for Threat Monitoring**:

```promql
# Blocked IPs per minute
sum(rate(cilium_policy_verdict_total{verdict="DENIED"}[1m])) by (source_ip)

# Top blocked destinations
topk(5, sum(rate(cilium_policy_verdict_total{verdict="DENIED"}[5m])) by (destination))

# Policy enforcement errors
sum(rate(cilium_policy_l3_l4_error_total[5m]))

# Audit mode traffic volume (before blocking)
sum(rate(cilium_policy_verdict_total{verdict="AUDIT"}[5m]))
```

## 🔄 Maintenance Tasks

### Weekly

- [ ] Review audit logs for new attack patterns
- [ ] Check Grafana metrics for blocked traffic trends
- [ ] Verify whitelisted IPs still valid

### Monthly

- [ ] Update threat intelligence feeds
- [ ] Review and consolidate CIDR ranges
- [ ] Check for Cilium policy updates/best practices
- [ ] Test emergency access procedures

### Quarterly

- [ ] Full policy audit (remove stale entries)
- [ ] Performance review (resource usage, latency)
- [ ] Update documentation with new learnings

## 📚 Related Documentation

- [Cilium Network Policy Documentation](https://docs.cilium.io/en/stable/security/policy/)
- [Application Management](./application-management.md) - General app operations
- [Daily Operations](./daily-operations.md) - Common tasks
- [Monitoring](./monitoring.md) - Observability setup

## 🔗 Useful Links

- [Cilium Policy Editor](https://editor.cilium.io/) - Visual policy builder
- [Cilium Hubble UI](https://docs.cilium.io/en/stable/gettingstarted/hubble/) - Network visibility
- [Spamhaus DROP Lists](https://www.spamhaus.org/drop/) - IP threat intelligence
- [Tor Exit Node List](https://check.torproject.org/torbulkexitlist) - Tor exit nodes

---

**Last Updated**: December 27, 2025
**Cluster**: witches (Cilium eBPF kube-proxy replacement)
**Current Mode**: Audit (non-blocking)
