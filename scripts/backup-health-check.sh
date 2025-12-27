#!/usr/bin/env bash

# Backup Health Check Script
# Verifies Volsync backup systems are functional and recent backups completed
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed (backup issues found)
#   2 - Script error (missing dependencies, etc.)

set -euo pipefail

# Configuration
KUBECONFIG="${KUBECONFIG:-./kubeconfig}"
ALERT_AGE_HOURS=48  # Alert if backup older than this
CRITICAL_APPS=("home-assistant" "paperless" "immich" "postgres16")
NAMESPACES=("default" "media" "database")

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Counters
ISSUES_FOUND=0
CHECKS_PASSED=0
CHECKS_TOTAL=0

log_error() {
    echo -e "${RED}✗ $1${NC}" >&2
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
    CHECKS_PASSED=$((CHECKS_PASSED + 1))
}

log_info() {
    echo "ℹ $1"
}

check_dependencies() {
    local missing=0
    for cmd in kubectl jq; do
        if ! command -v "$cmd" &> /dev/null; then
            log_error "Required command not found: $cmd"
            missing=1
        fi
    done
    if [ $missing -eq 1 ]; then
        exit 2
    fi
}

check_cluster_minio() {
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    log_info "Checking cluster Minio health..."

    # Check Minio pod is running
    if kubectl --kubeconfig "$KUBECONFIG" get pod -n default -l app.kubernetes.io/name=minio -o jsonpath='{.items[0].status.phase}' 2>/dev/null | grep -q "Running"; then
        log_success "Cluster Minio pod is Running"
    else
        log_error "Cluster Minio pod is not Running"
        return
    fi

    # Check Minio service is accessible
    if kubectl --kubeconfig "$KUBECONFIG" get svc -n default minio -o jsonpath='{.spec.clusterIP}' &>/dev/null; then
        local MINIO_IP
        MINIO_IP=$(kubectl --kubeconfig "$KUBECONFIG" get svc -n default minio -o jsonpath='{.spec.clusterIP}')
        log_success "Cluster Minio service accessible at $MINIO_IP:9000"
    else
        log_error "Cluster Minio service not found"
    fi
}

check_nas_minio() {
    CHECKS_TOTAL=$((CHECKS_TOTAL + 1))
    log_info "Checking NAS Minio connectivity..."

    # Try to create a test pod to check NAS Minio access
    # We'll use a secret from an app that has NAS backup configured
    local TEST_APP="overseerr"
    local TEST_NS="media"
    local SECRET="${TEST_APP}-volsync-r2-secret"

    if ! kubectl --kubeconfig "$KUBECONFIG" get secret -n "$TEST_NS" "$SECRET" &>/dev/null; then
        log_warning "Cannot verify NAS Minio (test secret $SECRET not found)"
        return
    fi

    # Run quick connectivity test using restic
    local JOB_NAME
    JOB_NAME="nas-minio-health-check-$(date +%s)"
    cat <<EOF | kubectl --kubeconfig "$KUBECONFIG" apply -f - >/dev/null 2>&1
apiVersion: batch/v1
kind: Job
metadata:
  name: $JOB_NAME
  namespace: $TEST_NS
spec:
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: restic-check
        image: quay.io/backube/volsync:0.14.0
        command: ["/bin/bash", "-c"]
        args: ["restic snapshots --last 2>/dev/null && echo 'NAS_MINIO_OK' || echo 'NAS_MINIO_FAIL'"]
        env:
        - name: RESTIC_REPOSITORY
          valueFrom:
            secretKeyRef:
              name: $SECRET
              key: RESTIC_REPOSITORY
        - name: RESTIC_PASSWORD
          valueFrom:
            secretKeyRef:
              name: $SECRET
              key: RESTIC_PASSWORD
        - name: AWS_ACCESS_KEY_ID
          valueFrom:
            secretKeyRef:
              name: $SECRET
              key: AWS_ACCESS_KEY_ID
        - name: AWS_SECRET_ACCESS_KEY
          valueFrom:
            secretKeyRef:
              name: $SECRET
              key: AWS_SECRET_ACCESS_KEY
EOF

    # Wait for job to complete (max 60 seconds)
    local TIMEOUT=60
    local ELAPSED=0
    while [ $ELAPSED -lt $TIMEOUT ]; do
        if kubectl --kubeconfig "$KUBECONFIG" wait --for=condition=complete "job/$JOB_NAME" -n "$TEST_NS" --timeout=5s >/dev/null 2>&1; then
            # Check job output
            local OUTPUT
            OUTPUT=$(kubectl --kubeconfig "$KUBECONFIG" logs "job/$JOB_NAME" -n "$TEST_NS" 2>/dev/null | tail -1)
            if echo "$OUTPUT" | grep -q "NAS_MINIO_OK"; then
                log_success "NAS Minio (192.168.1.22:9000) is accessible"
            else
                log_error "NAS Minio connectivity test failed"
            fi
            kubectl --kubeconfig "$KUBECONFIG" delete job "$JOB_NAME" -n "$TEST_NS" >/dev/null 2>&1
            return
        fi
        sleep 5
        ELAPSED=$((ELAPSED + 5))
    done

    log_warning "NAS Minio connectivity test timed out"
    kubectl --kubeconfig "$KUBECONFIG" delete job "$JOB_NAME" -n "$TEST_NS" --force --grace-period=0 >/dev/null 2>&1 || true
}

check_backup_freshness() {
    log_info "Checking backup freshness across namespaces..."

    for ns in "${NAMESPACES[@]}"; do
        local sources
        sources=$(kubectl --kubeconfig "$KUBECONFIG" get replicationsource -n "$ns" -o json 2>/dev/null | jq -r '.items[]')

        if [ -z "$sources" ] || [ "$sources" = "null" ]; then
            continue
        fi

        kubectl --kubeconfig "$KUBECONFIG" get replicationsource -n "$ns" -o json 2>/dev/null | jq -r '.items[] | "\(.metadata.name)|\(.status.lastSyncTime // "never")|\(.status.latestMoverStatus.result // "unknown")"' | while IFS='|' read -r name time status; do
            CHECKS_TOTAL=$((CHECKS_TOTAL + 1))

            # Check if it's a critical app
            local IS_CRITICAL=0
            for critical_app in "${CRITICAL_APPS[@]}"; do
                if [[ "$name" == "$critical_app"* ]]; then
                    IS_CRITICAL=1
                    break
                fi
            done

            if [ "$time" = "never" ]; then
                if [ $IS_CRITICAL -eq 1 ]; then
                    log_error "$ns/$name: CRITICAL APP - No backups ever completed"
                else
                    log_warning "$ns/$name: No backups completed yet"
                fi
                continue
            fi

            if [ "$status" != "Successful" ]; then
                if [ $IS_CRITICAL -eq 1 ]; then
                    log_error "$ns/$name: CRITICAL APP - Last backup status: $status"
                else
                    log_warning "$ns/$name: Last backup status: $status"
                fi
                continue
            fi

            # Check backup age (macOS compatible date parsing)
            local LAST_BACKUP
            if command -v gdate &> /dev/null; then
                LAST_BACKUP=$(gdate -d "$time" +%s 2>/dev/null || echo "0")
            else
                LAST_BACKUP=$(date -j -f "%Y-%m-%dT%H:%M:%SZ" "$time" +%s 2>/dev/null || echo "0")
            fi
            local NOW
            NOW=$(date +%s)
            local AGE_HOURS=$(( (NOW - LAST_BACKUP) / 3600 ))

            if [ "$AGE_HOURS" -gt "$ALERT_AGE_HOURS" ]; then
                if [ $IS_CRITICAL -eq 1 ]; then
                    log_error "$ns/$name: CRITICAL APP - Last backup ${AGE_HOURS}h ago (threshold: ${ALERT_AGE_HOURS}h)"
                else
                    log_warning "$ns/$name: Last backup ${AGE_HOURS}h ago (threshold: ${ALERT_AGE_HOURS}h)"
                fi
            else
                log_success "$ns/$name: Last backup ${AGE_HOURS}h ago"
            fi
        done
    done
}

main() {
    echo "==================================================="
    echo "Volsync Backup Health Check"
    echo "==================================================="
    echo ""

    check_dependencies

    echo "Configuration:"
    echo "  Alert threshold: ${ALERT_AGE_HOURS}h"
    echo "  Critical apps: ${CRITICAL_APPS[*]}"
    echo "  Namespaces: ${NAMESPACES[*]}"
    echo ""

    check_cluster_minio
    echo ""

    check_nas_minio
    echo ""

    check_backup_freshness
    echo ""

    echo "==================================================="
    echo "Summary"
    echo "==================================================="
    echo "Checks passed: $CHECKS_PASSED"
    echo "Issues found: $ISSUES_FOUND"
    echo ""

    if [ $ISSUES_FOUND -eq 0 ]; then
        log_success "All backup health checks passed!"
        exit 0
    else
        log_error "Backup health check found $ISSUES_FOUND issue(s)"
        exit 1
    fi
}

main "$@"
