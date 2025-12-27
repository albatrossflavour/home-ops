#!/usr/bin/env bash

# Volsync Change Validator
# Validates that Volsync configuration changes are safe before commit
#
# Exit codes:
#   0 - All checks passed (safe to commit)
#   1 - Validation failed (DANGEROUS - do not commit)
#   2 - Script error

set -euo pipefail

# Colors
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

ISSUES_FOUND=0

log_error() {
    echo -e "${RED}✗ DANGER: $1${NC}" >&2
    ISSUES_FOUND=$((ISSUES_FOUND + 1))
}

log_warning() {
    echo -e "${YELLOW}⚠ WARNING: $1${NC}"
}

log_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

log_info() {
    echo "ℹ $1"
}

# Check if PVC names are being renamed in Volsync-enabled apps
check_pvc_rename() {
    log_info "Checking for PVC renames in Volsync configurations..."

    # Get list of modified Volsync-related files
    local modified_files
    modified_files=$(git diff --cached --name-only | grep -E "volsync.*\.yaml$" || true)

    if [ -z "$modified_files" ]; then
        log_success "No Volsync files modified"
        return
    fi

    for file in $modified_files; do
        # Check if file exists (could be deleted)
        if [ ! -f "$file" ]; then
            continue
        fi

        # Check for PVC name changes
        local old_pvc
        local new_pvc
        old_pvc=$(git show "HEAD:$file" 2>/dev/null | grep -A 5 "persistentVolumeClaim:" | grep "claimName:" | awk '{print $2}' || true)
        new_pvc=$(grep -A 5 "persistentVolumeClaim:" "$file" | grep "claimName:" | awk '{print $2}' || true)

        if [ -n "$old_pvc" ] && [ -n "$new_pvc" ] && [ "$old_pvc" != "$new_pvc" ]; then
            log_error "PVC rename detected in $file: $old_pvc → $new_pvc"
            echo "  ❌ CRITICAL: PVC renames trigger Volsync repository reinitialization!"
            echo "  ❌ This will ORPHAN all existing backups (PERMANENT DATA LOSS)"
            echo "  ❌ See: ~/.claude/skills/recovery/volsync-restore.md"
            echo ""
            echo "  If you MUST rename (extremely rare):"
            echo "    1. Read the safe procedure in CLAUDE.md (Volsync PVC Immutability)"
            echo "    2. Backup restic repository metadata from Minio"
            echo "    3. Get explicit user approval"
            echo "    4. Document the repository ID before proceeding"
            echo ""
        fi
    done
}

# Check for ReplicationDestination trigger modifications
check_replication_destination_trigger() {
    log_info "Checking for ReplicationDestination trigger modifications..."

    local modified_files
    modified_files=$(git diff --cached --name-only | grep -E "volsync.*\.yaml$" || true)

    if [ -z "$modified_files" ]; then
        return
    fi

    for file in $modified_files; do
        if [ ! -f "$file" ]; then
            continue
        fi

        # Check if file contains ReplicationDestination
        if ! grep -q "kind: ReplicationDestination" "$file" 2>/dev/null; then
            continue
        fi

        # Check for trigger value changes
        local old_trigger
        local new_trigger
        old_trigger=$(git show "HEAD:$file" 2>/dev/null | grep -A 10 "kind: ReplicationDestination" | grep "manual:" | awk '{print $2}' || true)
        new_trigger=$(grep -A 10 "kind: ReplicationDestination" "$file" | grep "manual:" | awk '{print $2}' || true)

        if [ -n "$old_trigger" ] && [ -n "$new_trigger" ] && [ "$old_trigger" != "$new_trigger" ]; then
            log_error "ReplicationDestination trigger change detected in $file"
            echo "  ❌ CRITICAL: Trigger modifications reinitialize restic repository!"
            echo "  ❌ This will WIPE all existing backups (PERMANENT DATA LOSS)"
            echo "  ❌ Dec 27, 2024: Cluster Minio hourly backups lost to this exact mistake"
            echo ""
            echo "  For recovery operations:"
            echo "    1. Use manual restore jobs (NOT trigger-based)"
            echo "    2. See: ~/.claude/skills/recovery/volsync-restore.md"
            echo "    3. NEVER modify ReplicationDestination triggers"
            echo ""
        fi
    done
}

# Check for new Volsync resources without backup verification
check_new_volsync_resources() {
    log_info "Checking for new Volsync resources..."

    local new_files
    new_files=$(git diff --cached --name-only --diff-filter=A | grep -E "volsync.*\.yaml$" || true)

    if [ -z "$new_files" ]; then
        log_success "No new Volsync resources"
        return
    fi

    for file in $new_files; do
        log_warning "New Volsync resource: $file"
        echo "  ⚠️  Ensure PVC name matches existing PVC exactly (if adding to existing app)"
        echo "  ⚠️  Verify secret references are correct"
        echo "  ⚠️  Check schedule doesn't conflict with existing backups"
        echo ""
    done
}

main() {
    echo "==================================================="
    echo "Volsync Change Validator"
    echo "==================================================="
    echo ""

    check_pvc_rename
    check_replication_destination_trigger
    check_new_volsync_resources

    echo ""
    echo "==================================================="

    if [ $ISSUES_FOUND -eq 0 ]; then
        log_success "All Volsync validation checks passed"
        echo ""
        echo "Safe to commit. Remember:"
        echo "  - PVC names are IMMUTABLE once backups start"
        echo "  - Never modify ReplicationDestination triggers"
        echo "  - Use manual restore jobs for recovery operations"
        exit 0
    else
        log_error "Found $ISSUES_FOUND CRITICAL issue(s) - COMMIT BLOCKED"
        echo ""
        echo "DO NOT PROCEED unless you:"
        echo "  1. Understand the risks (permanent data loss possible)"
        echo "  2. Have explicit user approval"
        echo "  3. Have documented the safe procedure"
        echo "  4. Have verified backups exist"
        echo ""
        echo "To bypass (DANGEROUS): git commit --no-verify"
        exit 1
    fi
}

main "$@"
