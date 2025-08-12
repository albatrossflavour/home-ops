# 📊 Monitoring & Observability

Comprehensive guide for monitoring cluster health, application performance, and system observability.

## 🏗️ Monitoring Architecture

The cluster implements a comprehensive observability stack:

### Core Components

- **Prometheus**: Metrics collection and storage
- **Grafana**: Dashboards and visualization
- **AlertManager**: Alert routing and management
- **Gatus**: Uptime monitoring and status pages
- **Various Exporters**: Application and system metrics

### Access Points

- **Grafana**: https://grafana.albatrossflavour.com
- **Prometheus**: https://prometheus.albatrossflavour.com  
- **AlertManager**: https://alertmanager.albatrossflavour.com
- **Gatus**: https://status.albatrossflavour.com

## 📈 Key Metrics to Monitor

### Cluster Health

**Node Metrics:**

- CPU utilization
- Memory usage
- Disk space
- Network I/O
- Pod capacity

**Control Plane:**

- API server response times
- etcd performance
- Controller manager health
- Scheduler performance

### Application Performance

**Resource Utilization:**

- CPU and memory per application
- Storage usage and I/O
- Network bandwidth
- Request rates and latency

**Availability:**

- Pod restart rates
- Service uptime
- Error rates
- Response times

### Infrastructure Services

**Storage:**

- Persistent volume usage
- Backup success rates
- I/O performance
- Snapshot creation

**Networking:**

- DNS resolution times
- Ingress controller performance
- Certificate expiration
- Tunnel connectivity

## 🔧 Monitoring Operations

### Prometheus Management

**Check Prometheus Status:**

```bash
# Check Prometheus pods
kubectl -n observability get pods -l app.kubernetes.io/name=prometheus

# Access Prometheus web UI
kubectl -n observability port-forward svc/prometheus-operated 9090:9090
# Visit: http://localhost:9090

# Check Prometheus configuration
kubectl -n observability get prometheus -o yaml
```

**Monitor Scrape Targets:**

```bash
# Check targets in Prometheus UI: Status > Targets
# Or use API:
curl http://localhost:9090/api/v1/targets
```

### Grafana Administration

**Access Grafana:**

```bash
# Port-forward for local access
kubectl -n observability port-forward svc/grafana 3000:80
# Visit: http://localhost:3000

# Get admin password
kubectl -n observability get secret grafana-admin-credentials -o jsonpath='{.data.password}' | base64 -d
```

**Dashboard Management:**

```bash
# List available dashboards
kubectl -n observability get configmaps -l grafana_dashboard=1

# Import new dashboard via ConfigMap
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: custom-dashboard
  namespace: observability
  labels:
    grafana_dashboard: "1"
data:
  dashboard.json: |
    {
      "dashboard": {
        // Dashboard JSON here
      }
    }
EOF
```

### AlertManager Configuration

**Check AlertManager Status:**

```bash
# Check AlertManager pods
kubectl -n observability get pods -l app.kubernetes.io/name=alertmanager

# Access AlertManager UI
kubectl -n observability port-forward svc/alertmanager-operated 9093:9093
# Visit: http://localhost:9093

# Check current alerts
curl http://localhost:9093/api/v1/alerts
```

**Alert Rules:**

```bash
# List Prometheus rules
kubectl -n observability get prometheusrules

# Check rule status
kubectl -n observability describe prometheusrule <rule-name>

# Validate rules
promtool check rules /path/to/rules.yaml
```

## 🚨 Alert Configuration

### Common Alert Rules

**Cluster Health Alerts:**

```yaml
groups:
- name: cluster.rules
  rules:
  - alert: NodeDown
    expr: up{job="node-exporter"} == 0
    for: 5m
    labels:
      severity: critical
    annotations:
      summary: "Node {{ $labels.instance }} is down"

  - alert: HighCPUUsage
    expr: 100 - (avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100) > 80
    for: 10m
    labels:
      severity: warning
    annotations:
      summary: "High CPU usage on {{ $labels.instance }}"

  - alert: HighMemoryUsage
    expr: (node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes) / node_memory_MemTotal_bytes * 100 > 90
    for: 5m
    labels:
      severity: warning
    annotations:
      summary: "High memory usage on {{ $labels.instance }}"
```

**Application Alerts:**

```yaml
- alert: PodCrashLooping
  expr: rate(kube_pod_container_status_restarts_total[15m]) > 0
  for: 0m
  labels:
    severity: critical
  annotations:
    summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} is crash looping"

- alert: PodNotReady
  expr: kube_pod_status_ready{condition="false"} == 1
  for: 15m
  labels:
    severity: warning
  annotations:
    summary: "Pod {{ $labels.namespace }}/{{ $labels.pod }} is not ready"
```

**Certificate Alerts:**

```yaml
- alert: CertificateExpiringSoon
  expr: (x509_cert_not_after - time()) / 86400 < 7
  for: 0m
  labels:
    severity: warning
  annotations:
    summary: "Certificate {{ $labels.job }} expires in less than 7 days"
```

### Alert Routing

**AlertManager Configuration:**

```yaml
route:
  group_by: ['alertname']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'default'
  routes:
  - match:
      severity: critical
    receiver: 'critical-alerts'

receivers:
- name: 'default'
  webhook_configs:
  - url: 'http://webhook-service/alerts'

- name: 'critical-alerts'
  slack_configs:
  - api_url: 'YOUR_SLACK_WEBHOOK_URL'
    channel: '#alerts'
    title: 'Critical Alert'
    text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
```

## 📊 Dashboard Management

### Essential Dashboards

**Cluster Overview:**

- Node resource utilization
- Pod distribution
- Network traffic
- Storage usage

**Application Performance:**

- Request rates and latency
- Error rates
- Resource consumption
- Dependency health

**Infrastructure Services:**

- DNS performance
- Certificate status
- Backup success
- Security events

### Custom Dashboard Creation

**Dashboard Development:**

```bash
# Export existing dashboard
curl -H "Authorization: Bearer $GRAFANA_TOKEN" \
  http://grafana.local/api/dashboards/uid/dashboard-uid

# Import dashboard
kubectl apply -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: custom-dashboard
  namespace: observability
  labels:
    grafana_dashboard: "1"
data:
  dashboard.json: |
    {
      // Dashboard JSON content
    }
EOF
```

## 🔍 Log Management

### Application Logs

**View Application Logs:**

```bash
# Stream logs in real-time
kubectl -n <namespace> logs -f deployment/<app>

# Get recent logs with timestamps
kubectl -n <namespace> logs deployment/<app> --since=1h --timestamps

# Search logs for errors
kubectl -n <namespace> logs deployment/<app> | grep -i error

# Multiple containers
kubectl -n <namespace> logs deployment/<app> -c <container>
```

### System Logs

**Cluster Component Logs:**

```bash
# Control plane logs
kubectl -n kube-system logs -l component=kube-apiserver
kubectl -n kube-system logs -l component=kube-controller-manager
kubectl -n kube-system logs -l component=kube-scheduler

# Network logs
kubectl -n kube-system logs -l k8s-app=kube-dns
kubectl -n network logs -l app.kubernetes.io/name=ingress-nginx
```

### Log Aggregation

**Centralized Logging Setup:**

```bash
# Check log collection
kubectl -n logging get pods

# View log pipeline
kubectl -n logging logs -f daemonset/fluent-bit

# Query logs in Grafana Loki
# Use LogQL queries in Grafana Explore
```

## 📱 Status Monitoring with Gatus

### Gatus Configuration

**Check Gatus Status:**

```bash
# Check Gatus pod
kubectl -n default get pods -l app.kubernetes.io/name=gatus

# View Gatus configuration
kubectl -n default get configmap gatus-config -o yaml

# Access status page
curl https://status.albatrossflavour.com
```

**Add New Service Monitoring:**

```yaml
endpoints:
  - name: "Application Name"
    url: "https://app.domain.com"
    interval: 1m
    conditions:
      - "[STATUS] == 200"
      - "[RESPONSE_TIME] < 500"
    alerts:
      - type: slack
        webhook-url: "YOUR_WEBHOOK_URL"
```

## 🔧 Performance Tuning

### Prometheus Optimization

**Storage Management:**

```bash
# Check Prometheus storage usage
kubectl -n observability exec prometheus-operator-prometheus-0 -- df -h /prometheus

# Configure retention
kubectl -n observability patch prometheus prometheus-operator-prometheus --type merge -p '{"spec":{"retention":"30d"}}'

# Monitor query performance
kubectl -n observability port-forward svc/prometheus-operated 9090:9090
# Check: Status > Runtime & Build Information
```

### Resource Allocation

**Monitoring Resource Usage:**

```bash
# Check monitoring stack resource usage
kubectl -n observability top pods

# Adjust resource limits
kubectl -n observability patch deployment grafana --type merge -p '{"spec":{"template":{"spec":{"containers":[{"name":"grafana","resources":{"limits":{"memory":"512Mi"}}}]}}}}'
```

## 🔐 Security Monitoring

### Security Metrics

**Monitor Security Events:**

- Failed authentication attempts
- Unauthorized API access
- Certificate validation failures
- Network policy violations

**Security Dashboards:**

```bash
# Create security-focused queries
kubectl auth can-i --list --as system:anonymous
kubectl get networkpolicies -A
kubectl get clusterroles | grep -E "(admin|edit|view)"
```

## 🧪 Monitoring Best Practices

### Metric Collection

- **Use appropriate cardinality** - Avoid high-cardinality labels
- **Set proper retention** - Balance storage with data needs
- **Monitor monitoring** - Track Prometheus health
- **Regular cleanup** - Remove unused metrics and dashboards

### Alert Management

- **Meaningful alerts** - Avoid alert fatigue
- **Proper escalation** - Route alerts appropriately
- **Alert documentation** - Include runbooks
- **Regular review** - Update alerts based on experience

### Dashboard Design

- **Clear purpose** - Each dashboard should have a specific use case
- **Consistent layout** - Use standard visualization patterns
- **Contextual information** - Include relevant metadata
- **Performance** - Optimize queries for dashboard load times

## 📚 Related Documentation

- [Daily Operations](./daily-operations.md) - Daily monitoring tasks
- [Application Management](./application-management.md) - Application-specific monitoring
- [Common Issues](../troubleshooting/common-issues.md) - Monitoring troubleshooting
- [Architecture Overview](../architecture/overview.md) - System design context
