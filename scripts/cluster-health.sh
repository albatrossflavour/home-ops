#!/usr/bin/env bash

# Cluster Health Check Script
# Comprehensive monitoring for Kubernetes cluster health
# Shows only problems, stays silent when everything is healthy

set -euo pipefail

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

# Issue counters
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
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║${NC}           Cluster Health Check - ${timestamp}            ${BLUE}║${NC}"
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
    echo -e "${BLUE}║${NC}  Status: ${status_text}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════╝${NC}"
}

increment_critical() {
    ((CRITICAL_COUNT++)) || true
}

increment_warning() {
    ((WARNING_COUNT++)) || true
}

# Check Flux HelmReleases
check_helm_releases() {
    local issues
    issues=$($KUBECTL get helmreleases -A -o json | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: HelmReleases Not Ready${NC}"
        echo "$issues" | while IFS= read -r line; do
            echo -e "  ${RED}└─${NC} $line"
            increment_critical
        done
    fi
}

# Check Flux Kustomizations
check_kustomizations() {
    local issues
    issues=$($KUBECTL get kustomizations -A -o json | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Kustomizations Not Ready${NC}"
        echo "$issues" | while IFS= read -r line; do
            echo -e "  ${RED}└─${NC} $line"
            increment_critical
        done
    fi
}

# Check Flux Source Repositories
check_flux_sources() {
    local git_issues oci_issues helm_issues

    # GitRepositories
    git_issues=$($KUBECTL get gitrepositories -A -o json | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    # OCIRepositories
    oci_issues=$($KUBECTL get ocirepositories -A -o json | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    # HelmRepositories
    helm_issues=$($KUBECTL get helmrepositories -A -o json | \
        jq -r '.items[] | select(.status.conditions[]? | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$git_issues" ]] || [[ -n "$oci_issues" ]] || [[ -n "$helm_issues" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Flux Source Repositories Not Ready${NC}"
        [[ -n "$git_issues" ]] && echo "$git_issues" | while IFS= read -r line; do
            echo -e "  ${RED}└─ [Git]${NC} $line"
            increment_critical
        done
        [[ -n "$oci_issues" ]] && echo "$oci_issues" | while IFS= read -r line; do
            echo -e "  ${RED}└─ [OCI]${NC} $line"
            increment_critical
        done
        [[ -n "$helm_issues" ]] && echo "$helm_issues" | while IFS= read -r line; do
            echo -e "  ${RED}└─ [Helm]${NC} $line"
            increment_critical
        done
    fi
}

# Check Pod Status
check_pods() {
    local problem_pods recent_restarts

    # Pods in bad states (not Running, not Completed, not Succeeded)
    problem_pods=$($KUBECTL get pods -A -o json | \
        jq -r '.items[] | select(.status.phase != "Running" and .status.phase != "Succeeded") |
        select(.status.phase != "Completed") |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.phase) - \(.status.conditions[]? | select(.type=="Ready") | .message // "No message")"' 2>/dev/null)

    if [[ -n "$problem_pods" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Pods Not Running${NC}"
        echo "$problem_pods" | while IFS= read -r line; do
            echo -e "  ${RED}└─${NC} $line"
            increment_critical
        done
    fi

    # Pods with recent restarts (within last 10 minutes)
    recent_restarts=$($KUBECTL get pods -A -o json | \
        jq -r --arg now "$(date -u +%s)" '.items[] |
        select(.status.containerStatuses[]? |
        (.restartCount > 0) and
        (.lastState.terminated.finishedAt != null) and
        ((($now | tonumber) - (.lastState.terminated.finishedAt | fromdateiso8601)) < 600)) |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.containerStatuses[0].restartCount) restarts (last: \(.status.containerStatuses[0].lastState.terminated.reason // "Unknown"))"' 2>/dev/null)

    if [[ -n "$recent_restarts" ]] && [[ "$SHOW_WARNINGS" == true ]]; then
        echo -e "\n${YELLOW}⚠ WARNING: Pods with Recent Restarts (< 10 minutes)${NC}"
        echo "$recent_restarts" | while IFS= read -r line; do
            echo -e "  ${YELLOW}└─${NC} $line"
            increment_warning
        done
    elif [[ -n "$recent_restarts" ]]; then
        # Still count warnings even if not displayed
        echo "$recent_restarts" | while IFS= read -r line; do
            increment_warning
        done
    fi
}

# Check PVCs
check_pvcs() {
    local unbound_pvcs
    unbound_pvcs=$($KUBECTL get pvc -A -o json | \
        jq -r '.items[] | select(.status.phase != "Bound") |
        "\(.metadata.namespace)/\(.metadata.name): \(.status.phase)"' 2>/dev/null)

    if [[ -n "$unbound_pvcs" ]]; then
        echo -e "\n${RED}❌ CRITICAL: PVCs Not Bound${NC}"
        echo "$unbound_pvcs" | while IFS= read -r line; do
            echo -e "  ${RED}└─${NC} $line"
            increment_critical
        done
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
            echo "$ceph_status" | while IFS= read -r line; do
                echo -e "  ${RED}└─${NC} $line"
                increment_critical
            done
        elif [[ "$SHOW_WARNINGS" == true ]]; then
            echo -e "\n${YELLOW}⚠ WARNING: Ceph Cluster Health Warning${NC}"
            echo "$ceph_status" | while IFS= read -r line; do
                echo -e "  ${YELLOW}└─${NC} $line"
                increment_warning
            done
        else
            # Still count warnings even if not displayed
            echo "$ceph_status" | while IFS= read -r line; do
                increment_warning
            done
        fi
    fi
}

# Check Node Status
check_nodes() {
    local not_ready nodes_pressure

    # Nodes not ready
    not_ready=$($KUBECTL get nodes -o json | \
        jq -r '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status!="True")) |
        "\(.metadata.name): NotReady - \(.status.conditions[] | select(.type=="Ready") | .message)"' 2>/dev/null)

    if [[ -n "$not_ready" ]]; then
        echo -e "\n${RED}❌ CRITICAL: Nodes Not Ready${NC}"
        echo "$not_ready" | while IFS= read -r line; do
            echo -e "  ${RED}└─${NC} $line"
            increment_critical
        done
    fi

    # Nodes with pressure conditions
    nodes_pressure=$($KUBECTL get nodes -o json | \
        jq -r '.items[] |
        .status.conditions[] | select(.type == "DiskPressure" or .type == "MemoryPressure" or .type == "PIDPressure") |
        select(.status == "True") |
        "\(.type) on node"' 2>/dev/null)

    if [[ -n "$nodes_pressure" ]] && [[ "$SHOW_WARNINGS" == true ]]; then
        echo -e "\n${YELLOW}⚠ WARNING: Node Pressure Conditions${NC}"
        echo "$nodes_pressure" | while IFS= read -r line; do
            echo -e "  ${YELLOW}└─${NC} $line"
            increment_warning
        done
    elif [[ -n "$nodes_pressure" ]]; then
        # Still count warnings even if not displayed
        echo "$nodes_pressure" | while IFS= read -r line; do
            increment_warning
        done
    fi
}

# Check Certificates
check_certificates() {
    local expiring_certs
    local seven_days_future
    seven_days_future=$(date -u -v+7d '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '+7 days' '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)

    expiring_certs=$($KUBECTL get certificates -A -o json | \
        jq -r --arg threshold "$seven_days_future" '.items[] |
        select(.status.notAfter != null) |
        select(.status.notAfter < $threshold) |
        "\(.metadata.namespace)/\(.metadata.name): expires \(.status.notAfter)"' 2>/dev/null)

    if [[ -n "$expiring_certs" ]] && [[ "$SHOW_WARNINGS" == true ]]; then
        echo -e "\n${YELLOW}⚠ WARNING: Certificates Expiring Soon (< 7 days)${NC}"
        echo "$expiring_certs" | while IFS= read -r line; do
            echo -e "  ${YELLOW}└─${NC} $line"
            increment_warning
        done
    elif [[ -n "$expiring_certs" ]]; then
        # Still count warnings even if not displayed
        echo "$expiring_certs" | while IFS= read -r line; do
            increment_warning
        done
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

    if [[ -n "$failed_replications" ]] && [[ "$SHOW_WARNINGS" == true ]]; then
        echo -e "\n${YELLOW}⚠ WARNING: Volsync Replication Issues${NC}"
        echo "$failed_replications" | while IFS= read -r line; do
            echo -e "  ${YELLOW}└─${NC} $line"
            increment_warning
        done
    elif [[ -n "$failed_replications" ]]; then
        # Still count warnings even if not displayed
        echo "$failed_replications" | while IFS= read -r line; do
            increment_warning
        done
    fi
}

# Check Recent Events
check_events() {
    local warning_events

    # Get events from last 10 minutes with Warning type
    warning_events=$($KUBECTL get events -A --field-selector type=Warning -o json | \
        jq -r --arg cutoff "$(date -u -v-10M '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || date -u -d '10 minutes ago' '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null)" \
        '.items[] | select(.lastTimestamp > $cutoff) |
        "\(.involvedObject.namespace // "cluster")/\(.involvedObject.name): \(.message)"' 2>/dev/null | \
        head -10)

    if [[ -n "$warning_events" ]] && [[ "$SHOW_WARNINGS" == true ]]; then
        echo -e "\n${YELLOW}⚠ Recent Warning Events (last 10 minutes)${NC}"
        echo "$warning_events" | while IFS= read -r line; do
            echo -e "  ${YELLOW}└─${NC} $line"
            increment_warning
        done
    elif [[ -n "$warning_events" ]]; then
        # Still count warnings even if not displayed
        echo "$warning_events" | while IFS= read -r line; do
            increment_warning
        done
    fi
}

# Main health check function
run_health_check() {
    # Reset counters
    CRITICAL_COUNT=0
    WARNING_COUNT=0

    # Run all checks
    check_helm_releases
    check_kustomizations
    check_flux_sources
    check_pods
    check_pvcs
    check_ceph
    check_nodes
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
        print_header
        run_health_check
        print_footer

        # Exit with proper code
        if [[ $CRITICAL_COUNT -gt 0 ]]; then
            exit 1
        fi
        exit 0
    fi
}

main
