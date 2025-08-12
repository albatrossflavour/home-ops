# 🔄 Daily Operations

Common tasks and workflows for managing your Kubernetes homelab on a day-to-day basis.

## 🌅 Daily Checks (5 minutes)

### Quick Health Assessment

```bash
# Check node status
kubectl get nodes -o wide

# Verify all pods are running
kubectl get pods -A | grep -v Running | grep -v Completed

# Check Flux synchronization
flux get all -A | grep -v "True"

# Monitor resource usage
kubectl top nodes 2>/dev/null || echo "Metrics server starting..."
```

### Dashboard Quick Check

Access these dashboards for visual health check:

- **[Grafana](https://grafana.your-domain.com)** - Overall system health
- **[Gatus](https://status.your-domain.com)** - Service availability  
- **[Home Assistant](https://homeassistant.your-domain.com)** - Home automation status

## 📱 Application Management

### Media Stack Operations

```bash
# Check media services status
kubectl get pods -n media

# Restart a problematic service
kubectl rollout restart deployment/sonarr -n media

# Check download progress
kubectl logs -f deployment/qbittorrent -n media --tail=50

# Monitor storage usage
kubectl exec -n media deployment/sonarr -- df -h /data
```

### Monitoring and Alerts

```bash
# Check for fired alerts
kubectl get prometheusrules -A
kubectl logs -n observability deployment/alertmanager --tail=20

# Verify certificate status
kubectl get certificates -A | grep -v True

# Check backup status
kubectl get volumesnapshots -A
```

### Home Automation

```bash
# Home Assistant operations
kubectl logs -n default deployment/home-assistant --tail=50

# Check configuration
kubectl get configmaps -n default | grep home-assistant

# Restart if needed
kubectl rollout restart deployment/home-assistant -n default
```

## 🔧 Common Maintenance Tasks

### Application Updates

```bash
# Check for available updates (Renovate PRs)
gh pr list --repo yourusername/homelab

# Apply specific application update
task flux:apply path=media/sonarr

# Monitor deployment
kubectl rollout status deployment/sonarr -n media
```

### Log Management

```bash
# Check application logs
kubectl logs -n <namespace> deployment/<app> --tail=100

# Follow logs in real-time
kubectl logs -n <namespace> deployment/<app> -f

# Check system logs
kubectl logs -n kube-system daemonset/cilium --tail=50
```

### Resource Cleanup

```bash
# Clean up completed jobs
kubectl delete jobs --field-selector status.successful=1 -A

# Remove unused secrets (be careful!)
kubectl get secrets -A | grep default-token

# Check for orphaned PVCs
kubectl get pvc -A | grep -v Bound
```

## 🚨 Troubleshooting Workflows

### Pod Not Starting

```bash
# 1. Check pod status
kubectl get pods -n <namespace> | grep <app>

# 2. Describe the problematic pod
kubectl describe pod -n <namespace> <pod-name>

# 3. Check events
kubectl get events -n <namespace> --sort-by='.metadata.creationTimestamp' | tail -20

# 4. Check logs
kubectl logs -n <namespace> <pod-name> --previous
```

### Service Not Accessible

```bash
# 1. Check service and endpoints
kubectl get svc,endpoints -n <namespace>

# 2. Verify ingress configuration
kubectl get ingress -n <namespace>
kubectl describe ingress -n <namespace> <ingress-name>

# 3. Test internal connectivity
kubectl run debug --image=busybox -it --rm -- wget -qO- http://<service>.<namespace>:port
```

### DNS Issues

```bash
# 1. Test internal DNS
kubectl run debug --image=busybox -it --rm -- nslookup kubernetes.default.svc.cluster.local

# 2. Check external DNS
kubectl logs -n network deployment/external-dns --tail=50

# 3. Test external resolution
dig @8.8.8.8 your-service.your-domain.com
```

### Storage Problems

```bash
# 1. Check PVC status
kubectl get pvc -A

# 2. Verify storage class
kubectl get storageclass

# 3. Check OpenEBS status
kubectl get pods -n openebs-system

# 4. Monitor disk usage on nodes
kubectl exec -n kube-system ds/node-exporter -- df -h
```

## 📊 Performance Monitoring

### Resource Usage Tracking

```bash
# Node resource consumption
kubectl top nodes

# Pod resource usage by namespace
kubectl top pods -A --sort-by=memory
kubectl top pods -A --sort-by=cpu

# Check resource requests vs limits
kubectl describe nodes | grep -A5 "Allocated resources"
```

### Network Performance

```bash
# Check ingress controller status
kubectl get pods -n network -l app.kubernetes.io/name=ingress-nginx

# Monitor connection metrics
kubectl logs -n network deployment/ingress-nginx-external --tail=20

# Test network connectivity
kubectl run netshoot --image=nicolaka/netshoot -it --rm -- ping google.com
```

## 🔄 Routine Workflows

### Weekly Review (30 minutes)

1. **Review Renovate PRs** - Check for dependency updates
2. **Check resource trends** - Look at Grafana dashboards for usage patterns
3. **Verify backups** - Ensure Volsync snapshots are current
4. **Security scan** - Review any CVE alerts
5. **Clean up resources** - Remove old snapshots, unused secrets

### Monthly Maintenance (1-2 hours)

1. **Update cluster components** - Talos, Kubernetes versions
2. **Review capacity** - Plan for scaling needs
3. **Security audit** - Check access logs, rotate secrets
4. **Documentation update** - Keep procedures current
5. **Disaster recovery test** - Verify backup restoration

### Quarterly Planning (2-4 hours)

1. **Architecture review** - Assess current design
2. **Performance optimization** - Tune resource allocations
3. **Capacity planning** - Plan hardware upgrades
4. **Security hardening** - Implement new security measures
5. **Technology evaluation** - Research new tools and approaches

## 🎯 Quick Commands Reference

### Essential Aliases

```bash
# Add to your shell profile
alias k="kubectl"
alias kgp="kubectl get pods"
alias kgs="kubectl get services"
alias kgi="kubectl get ingress"
alias kgn="kubectl get nodes"
alias kdp="kubectl describe pod"
alias kl="kubectl logs"

# Flux shortcuts
alias fga="flux get all -A"
alias fgk="flux get kustomizations -A"
alias fr="flux reconcile"
```

### One-Liner Health Checks

```bash
# All-in-one health check
kubectl get nodes && kubectl get pods -A | grep -v Running | grep -v Completed && flux get kustomizations -A | grep -v True

# Quick resource summary
kubectl get pods -A --no-headers | awk '{print $1}' | sort | uniq -c

# Certificate expiration check
kubectl get certificates -A -o custom-columns="NAMESPACE:.metadata.namespace,NAME:.metadata.name,READY:.status.conditions[0].status,SECRET:.spec.secretName"
```

## 📱 Mobile Access

### Emergency Access Setup

For when you're away from your workstation:

1. **Mobile SSH client** - Termius, ConnectBot
2. **VPN access** - WireGuard, Tailscale
3. **Dashboard bookmarks** - Grafana, Gatus mobile views
4. **Notification setup** - Slack, Discord, email alerts

### Mobile-Friendly Commands

```bash
# Compact status views
k get pods -A --no-headers | grep -v Running
k top nodes --no-headers
flux get ks -A --no-headers | grep -v True
```

---

**💡 Pro Tip**: Set up shell aliases and functions to make these daily operations faster. Consider creating a "morning check" script that runs all your daily health checks automatically.
