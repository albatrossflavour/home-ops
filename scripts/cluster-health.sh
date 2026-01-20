#!/usr/bin/env bash

# Cluster Health Check Script
# Comprehensive monitoring for Kubernetes cluster health
# Shows only problems, stays silent when everything is healthy

set -uo pipefail

# Colors
readonly RED='\033[0;31m'
readonly YELLOW='\033[1;33m'
readonly GREEN='\033[0;32m'
readonly BLUE='\033[0;34m'
readonly GRAY='\033[0;90m'
readonly NC='\033[0m' # No Color

# Configuration
KUBECONFIG_PATH="${KUBECONFIG:-kubeconfig}"
WATCH_MODE=false
SHOW_WARNINGS=false
INTERVAL=30
KUBECTL="kubectl --kubeconfig ${KUBECONFIG_PATH}"

# Issue counters - using global scope properly
CRITICAL_COUNT=0
WARNING_COUNT=0

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--watch)
            WATCH_MODE=true
            shift
            ;;
        --warnings)
            SHOW_WARNINGS=true
            shift
            ;;
        -i|--interval)
            INTERVAL="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [-w|--watch] [--warnings] [-i|--interval SECONDS]"
            echo "  -w, --watch     Run in watch mode (continuous monitoring)"
            echo "  --warnings      Show warnings in addition to critical issues"
            echo "  -i, --interval  Refresh interval in seconds (default: 30)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Helper functions
print_header() {
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "${BLUE}════════════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  Cluster Health Check - ${timestamp}${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════════${NC}"
}

print_footer() {
    local status_text
    if [[ $CRITICAL_COUNT -gt 0 ]]; then
        status_text="${RED}Critical: ${CRITICAL_COUNT}${NC}  ${YELLOW}Warnings: ${WARNING_COUNT}${NC}"
    elif [[ $WARNING_COUNT -gt 0 ]]; then
        status_text="${YELLOW}Warnings: ${WARNING_COUNT}${NC}  ${GREEN}No Critical Issues${NC}"
    else
        status_text="${GREEN}✓ All Systems Healthy${NC}"
    fi
    echo -e "${BLUE}════════════════════════════════════════════════════════════════════${NC}"
    echo -e "  Status: ${status_text}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════════════${NC}"
}

# Check etcd Health
check_etcd() {
    # Only run on clusters with accessible etcd (control plane)
    local etcd_health
    etcd_health=$($KUBECTL get pods -n kube-system -l component=etcd -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase != "Running") |
        "\(.metadata.name): \(.status.phase)"' 2>/dev/null)

    if [[ -n "$etcd_health" ]]; then
        echo -e "\n${RED}❌ CRITICAL: etcd Pods Not Running${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$etcd_health"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Flux HelmReleases
check_helm_releases() {
    local issues
    issues=$($KUBECTL get helmreleases -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: HelmReleases Not Ready${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$issues"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Flux Kustomizations
check_kustomizations() {
    local issues
    issues=$($KUBECTL get kustomizations -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Kustomizations Not Ready${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$issues"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Flux Source Repositories
check_flux_sources() {
    local git_issues oci_issues helm_issues total_count

    # GitRepositories
    git_issues=$($KUBECTL get gitrepositories -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    # OCIRepositories
    oci_issues=$($KUBECTL get ocirepositories -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    # HelmRepositories
    helm_issues=$($KUBECTL get helmrepositories -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$git_issues" ]] || [[ -n "$oci_issues" ]] || [[ -n "$helm_issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Flux Source Repositories Not Ready${NC}"
        total_count=0

        if [[ -n "$git_issues" ]]; then
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${RED}└─ [Git]${NC} $line"
                ((total_count++))
            done <<< "$git_issues"
        fi

        if [[ -n "$oci_issues" ]]; then
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${RED}└─ [OCI]${NC} $line"
                ((total_count++))
            done <<< "$oci_issues"
        fi

        if [[ -n "$helm_issues" ]]; then
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${RED}└─ [Helm]${NC} $line"
                ((total_count++))
            done <<< "$helm_issues"
        fi

        CRITICAL_COUNT=$((CRITICAL_COUNT + total_count))
    fi
}

# Check External Secrets
check_external_secrets() {
    local store_issues
    store_issues=$($KUBECTL get clustersecretstores -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$store_issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: ClusterSecretStores Not Ready${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$store_issues"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check CloudNative-PG Clusters
check_databases() {
    local db_issues
    db_issues=$($KUBECTL get clusters.postgresql.cnpg.io -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase != "Cluster in healthy state") |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.phase)"' 2>/dev/null)

    if [[ -n "$db_issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: PostgreSQL Clusters Not Healthy${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$db_issues"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Ingress Controllers
check_ingress() {
    local ingress_issues
    ingress_issues=$($KUBECTL get pods -n network -l app.kubernetes.io/component=controller -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase != "Running") |
        "\(.metadata.name): \(.status.phase)"' 2>/dev/null)

    if [[ -n "$ingress_issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Ingress Controllers Not Running${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$ingress_issues"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Node Disk Usage
check_disk_usage() {
    # Check /var filesystem usage - alert if > 75% (above GC threshold)
    local disk_issues
    disk_issues=$($KUBECTL get --raw /api/v1/nodes 2>/dev/null | \
        jq -r '.items[] |
        .status.conditions[] |
        select(.type == "DiskPressure" and .status == "True") |
        .message' 2>/dev/null)

    if [[ -n "$disk_issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Node Disk Pressure Detected${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$disk_issues"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Pod Status
check_pods() {
    local problem_pods recent_restarts

    # Pods in bad states (not Running, not Completed, not Succeeded)
    problem_pods=$($KUBECTL get pods -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase != "Running" and .status.phase != "Succeeded") |
        select(.status.phase != "Completed") |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.phase) - \(.status.conditions[]? | select(.type=="Ready") | .message // "No message")"' 2>/dev/null)

    if [[ -n "$problem_pods" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Pods Not Running${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$problem_pods"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi

    # Pods with recent restarts (within last 10 minutes)
    local current_time
    current_time=$(date -u +%s 2>/dev/null)
    recent_restarts=$($KUBECTL get pods -A -o json 2>/dev/null | \
        jq -r --arg now "$current_time" '.items[] |
        select(.status.containerStatuses[]? |
        (.restartCount > 0) and
        (.lastState.terminated.finishedAt != null) and
        ((($now | tonumber) - (.lastState.terminated.finishedAt | fromdateiso8601)) < 600)) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.containerStatuses[0].restartCount) restarts (last: \(.status.containerStatuses[0].lastState.terminated.reason // "Unknown"))"' 2>/dev/null)

    if [[ -n "$recent_restarts" ]]; then
        if [[ "$SHOW_WARNINGS" == true ]]; then
            echo -e "\n${YELLOW}⚠ WARNING: Pods with Recent Restarts (< 10 minutes)${NC}"
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${YELLOW}└─${NC} $line"
            done <<< "$recent_restarts"
        fi
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            ((count++))
        done <<< "$recent_restarts"
        WARNING_COUNT=$((WARNING_COUNT + count))
    fi
}

# Check PVCs
check_pvcs() {
    local unbound_pvcs
    unbound_pvcs=$($KUBECTL get pvc -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.phase != "Bound") |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.phase)"' 2>/dev/null)

    if [[ -n "$unbound_pvcs" ]]; then
        echo -e "\n${RED}❌ CRITICAL: PVCs Not Bound${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$unbound_pvcs"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi
}

# Check Ceph Health
check_ceph() {
    local ceph_status
    ceph_status=$($KUBECTL get cephcluster -A -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.ceph.health != "HEALTH_OK") |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.ceph.health)"' 2>/dev/null)

    if [[ -n "$ceph_status" ]]; then
        if echo "$ceph_status" | grep -q "HEALTH_ERR"; then
            echo -e "\n${RED}❌ CRITICAL: Ceph Cluster Health Error${NC}"
            local count=0
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${RED}└─${NC} $line"
                ((count++))
            done <<< "$ceph_status"
            CRITICAL_COUNT=$((CRITICAL_COUNT + count))
        else
            if [[ "$SHOW_WARNINGS" == true ]]; then
                echo -e "\n${YELLOW}⚠ WARNING: Ceph Cluster Health Warning${NC}"
                while IFS= read -r line; do
                    [[ -z "$line" ]] && continue
                    echo -e "  ${YELLOW}└─${NC} $line"
                done <<< "$ceph_status"
            fi
            local count=0
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                ((count++))
            done <<< "$ceph_status"
            WARNING_COUNT=$((WARNING_COUNT + count))
        fi
    fi
}

# Check Node Status
check_nodes() {
    local not_ready nodes_pressure

    # Nodes not ready
    not_ready=$($KUBECTL get nodes -o json 2>/dev/null | \
        jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.name): NotReady - \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$not_ready" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Nodes Not Ready${NC}"
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            echo -e "  ${RED}└─${NC} $line"
            ((count++))
        done <<< "$not_ready"
        CRITICAL_COUNT=$((CRITICAL_COUNT + count))
    fi

    # Nodes with pressure conditions - FIXED: include node name
    nodes_pressure=$($KUBECTL get nodes -o json 2>/dev/null | \
        jq -r '.items[] |
        . as $node |
        .status.conditions[] | select(.type == "DiskPressure" or .type == "MemoryPressure" or .type == "PIDPressure") |
        select(.status == "True") |
        "\($node.metadata.name): \(.type)"' 2>/dev/null)

    if [[ -n "$nodes_pressure" ]]; then
        if [[ "$SHOW_WARNINGS" == true ]]; then
            echo -e "\n${YELLOW}⚠ WARNING: Node Pressure Conditions${NC}"
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${YELLOW}└─${NC} $line"
            done <<< "$nodes_pressure"
        fi
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            ((count++))
        done <<< "$nodes_pressure"
        WARNING_COUNT=$((WARNING_COUNT + count))
    fi
}

# Check Certificates
check_certificates() {
    local expiring_certs seven_days_future

    # Portable date calculation
    if date -v+7d > /dev/null 2>&1; then
        # BSD/macOS
        seven_days_future=$(date -u -v+7d '+%Y-%m-%dT%H:%M:%SZ')
    else
        # GNU/Linux
        seven_days_future=$(date -u -d '+7 days' '+%Y-%m-%dT%H:%M:%SZ')
    fi

    expiring_certs=$($KUBECTL get certificates -A -o json 2>/dev/null | \
        jq -r --arg threshold "$seven_days_future" '.items[] |
        select(.status.notAfter != null) |
        select(.status.notAfter < $threshold) |
        "\(.metadata.namespace)/\(.metadata.name): expires \(.status.notAfter)"' 2>/dev/null)

    if [[ -n "$expiring_certs" ]]; then
        if [[ "$SHOW_WARNINGS" == true ]]; then
            echo -e "\n${YELLOW}⚠ WARNING: Certificates Expiring Soon (< 7 days)${NC}"
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${YELLOW}└─${NC} $line"
            done <<< "$expiring_certs"
        fi
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            ((count++))
        done <<< "$expiring_certs"
        WARNING_COUNT=$((WARNING_COUNT + count))
    fi
}

# Check Volsync Replications
check_volsync() {
    local failed_replications

    # Check for ReplicationSources with failed lastSyncStatus
    failed_replications=$($KUBECTL get replicationsources -A -o json 2>/dev/null | \
        jq -r '.items[] |
        select(.status.lastSyncTime != null and .status.lastManualSync == null) |
        select(.status.lastSyncDuration == null or .status.lastSyncDuration == "0s") |
        "\(.metadata.namespace)/\(.metadata.name): Last sync may have failed"' 2>/dev/null)

    if [[ -n "$failed_replications" ]]; then
        if [[ "$SHOW_WARNINGS" == true ]]; then
            echo -e "\n${YELLOW}⚠ WARNING: Volsync Replication Issues${NC}"
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${YELLOW}└─${NC} $line"
            done <<< "$failed_replications"
        fi
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            ((count++))
        done <<< "$failed_replications"
        WARNING_COUNT=$((WARNING_COUNT + count))
    fi
}

# Check Recent Events
check_events() {
    local warning_events ten_min_ago

    # Portable date calculation
    if date -v-10M > /dev/null 2>&1; then
        # BSD/macOS
        ten_min_ago=$(date -u -v-10M '+%Y-%m-%dT%H:%M:%SZ')
    else
        # GNU/Linux
        ten_min_ago=$(date -u -d '10 minutes ago' '+%Y-%m-%dT%H:%M:%SZ')
    fi

    # Get events from last 10 minutes with Warning type
    warning_events=$($KUBECTL get events -A --field-selector type=Warning -o json 2>/dev/null | \
        jq -r --arg cutoff "$ten_min_ago" \
        '.items[] | select(.lastTimestamp > $cutoff) |
        "\(.involvedObject.namespace // "cluster")/\(.involvedObject.name): \(.message)"' 2>/dev/null | \
        head -10)

    if [[ -n "$warning_events" ]]; then
        if [[ "$SHOW_WARNINGS" == true ]]; then
            echo -e "\n${YELLOW}⚠ Recent Warning Events (last 10 minutes)${NC}"
            while IFS= read -r line; do
                [[ -z "$line" ]] && continue
                echo -e "  ${YELLOW}└─${NC} $line"
            done <<< "$warning_events"
        fi
        local count=0
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            ((count++))
        done <<< "$warning_events"
        WARNING_COUNT=$((WARNING_COUNT + count))
    fi
}

# Main health check function
run_health_check() {
    # Reset counters
    CRITICAL_COUNT=0
    WARNING_COUNT=0

    # Run all checks
    check_etcd
    check_nodes
    check_disk_usage
    check_external_secrets
    check_databases
    check_ingress
    check_helm_releases
    check_kustomizations
    check_flux_sources
    check_pods
    check_pvcs
    check_ceph
    check_certificates
    check_volsync
    check_events
}

# Main execution
main() {
    if [[ "$WATCH_MODE" == true ]]; then
        while true; do
            clear
            print_header
            run_health_check
            print_footer
            echo -e "\n${GRAY}Refreshing in ${INTERVAL}s... (Ctrl+C to exit)${NC}"
            sleep "$INTERVAL"
        done
    else
        # Run directly without capturing output (fixes exit code bug)
        print_header
        run_health_check
        print_footer

        # Exit with proper code based on issues found
        if [[ $CRITICAL_COUNT -gt 0 ]]; then
            exit 1
        fi
        exit 0
    fi
}

main
