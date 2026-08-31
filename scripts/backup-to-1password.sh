#!/bin/bash
# Home-Ops Infrastructure Backup Script
# Backs up critical files to 1Password using op CLI

set -euo pipefail

VAULT="discworld"
ACCOUNT="thegreens.1password.com"
DATE=$(date +%Y%m%d)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 2026-08-31: run log lives outside the repo (not git-tracked, not the
# 1Password item itself) - a 1Password item's updated_at proves *a*
# backup happened at some point, but says nothing about who ran it,
# whether it completed cleanly, and would vanish entirely if the item
# were ever deleted and recreated. This is a separate, durable record.
RUN_LOG="${XDG_STATE_HOME:-$HOME/.local/state}/home-ops/backup-runs.log"
mkdir -p "$(dirname "$RUN_LOG")"

# Counters for validation
BACKUP_SUCCESS=0
BACKUP_TOTAL=0

echo "🔐 Starting Home-Ops infrastructure backup to 1Password..."

cd "$REPO_ROOT"

# Function to validate backup success
validate_backup() {
    local title="$1"
    local description="$2"

    if op item get "$title" --vault="$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
        echo "✅ $description backup verified"
        ((BACKUP_SUCCESS++))
        return 0
    else
        echo "❌ $description backup failed verification"
        return 1
    fi
}

# Function to check if item exists and update or create
backup_file_as_document() {
    local file="$1"
    local title="$2"

    ((BACKUP_TOTAL++))

    if [ ! -f "$file" ]; then
        echo "❌ File $file not found, skipping..."
        return 1
    fi

    # Check if item exists (suppress error output)
    if op item get "$title" --vault="$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
        echo "📝 Updating existing $title..."
        if cat "$file" | op document edit "$title" --vault="$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
            echo "✅ $file updated successfully"
        else
            echo "❌ Failed to update $file"
            return 1
        fi
    else
        echo "📝 Creating new $title..."
        if op document create "$file" --vault="$VAULT" --account="$ACCOUNT" --title="$title" >/dev/null 2>&1; then
            echo "✅ $file created successfully"
        else
            echo "❌ Failed to create $file"
            return 1
        fi
    fi

    # Validate the backup worked
    validate_backup "$title" "$file"
}

backup_age_key() {
    local title="homeops-age-key-backup"

    ((BACKUP_TOTAL++))

    if [ ! -f "age.key" ]; then
        echo "❌ age.key not found!"
        return 1
    fi

    # Check if item exists (suppress error output)
    if op item get "$title" --vault="$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
        echo "📝 Updating existing age key backup..."
        AGE_KEY_CONTENT=$(cat age.key)
        if op item edit "$title" --vault="$VAULT" --account="$ACCOUNT" notesPlain="$AGE_KEY_CONTENT" >/dev/null 2>&1; then
            echo "✅ age.key updated successfully"
        else
            echo "❌ Failed to update age.key"
            return 1
        fi
    else
        echo "📝 Creating new age key backup..."
        cat > /tmp/age_key_item.json << 'EOF'
{
  "title": "homeops-age-key-backup",
  "category": "SECURE_NOTE",
  "fields": [
    {
      "id": "notesPlain",
      "type": "STRING",
      "purpose": "NOTES",
      "label": "Age Key Content"
    }
  ]
}
EOF
        AGE_KEY_CONTENT=$(cat age.key)
        if command -v jq >/dev/null 2>&1; then
            jq --arg content "$AGE_KEY_CONTENT" '.fields[0].value = $content' /tmp/age_key_item.json > /tmp/age_key_final.json
            if op item create --vault="$VAULT" --account="$ACCOUNT" --template=/tmp/age_key_final.json >/dev/null 2>&1; then
                echo "✅ age.key created successfully"
            else
                echo "❌ Failed to create age.key"
                rm -f /tmp/age_key_item.json /tmp/age_key_final.json
                return 1
            fi
            rm -f /tmp/age_key_item.json /tmp/age_key_final.json
        else
            echo "❌ jq not found - cannot create age key backup"
            rm -f /tmp/age_key_item.json
            return 1
        fi
    fi

    # Validate the backup worked
    validate_backup "$title" "age.key"
}

backup_bootstrap_directory() {
    local title="homeops-bootstrap-templates"
    local archive="/tmp/bootstrap-backup-$DATE.tar.gz"

    ((BACKUP_TOTAL++))

    if [ ! -d "bootstrap" ]; then
        echo "❌ bootstrap/ directory not found!"
        return 1
    fi

    echo "📦 Creating bootstrap archive..."
    if ! tar -czf "$archive" bootstrap/ 2>/dev/null; then
        echo "❌ Failed to create bootstrap archive"
        return 1
    fi

    # Check if document exists (suppress error output)
    if op item get "$title" --vault="$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
        echo "📝 Updating existing bootstrap backup..."
        if cat "$archive" | op document edit "$title" --vault="$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
            echo "✅ bootstrap/ updated successfully"
        else
            echo "❌ Failed to update bootstrap/"
            rm -f "$archive"
            return 1
        fi
    else
        echo "📝 Creating new bootstrap backup..."
        if op document create "$archive" --vault="$VAULT" --account="$ACCOUNT" --title="$title" >/dev/null 2>&1; then
            echo "✅ bootstrap/ created successfully"
        else
            echo "❌ Failed to create bootstrap/"
            rm -f "$archive"
            return 1
        fi
    fi

    rm -f "$archive"

    # Validate the backup worked
    validate_backup "$title" "bootstrap/"
}

# Check prerequisites
echo "🔍 Checking prerequisites..."

if ! command -v op >/dev/null 2>&1; then
    echo "❌ 1Password CLI (op) not found. Please install it first."
    echo "   https://developer.1password.com/docs/cli/get-started/"
    exit 1
fi

if ! op vault list --account="$ACCOUNT" >/dev/null 2>&1; then
    echo "❌ Not authenticated with 1Password CLI. Run: op signin --account $ACCOUNT"
    exit 1
fi

if ! op vault get "$VAULT" --account="$ACCOUNT" >/dev/null 2>&1; then
    echo "❌ Vault '$VAULT' not found or not accessible"
    echo "Available vaults:"
    op vault list --account="$ACCOUNT"
    exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
    echo "⚠️  Warning: jq not found - age.key backup may fail"
fi

echo "✅ Prerequisites met"
echo ""

# Perform backups
echo "🔑 Backing up age.key..."
backup_age_key || true

echo ""
echo "⚙️  Backing up config.yaml..."
backup_file_as_document "config.yaml" "homeops-cluster-config" || true

echo ""
echo "🗂️  Backing up bootstrap templates..."
backup_bootstrap_directory || true

echo ""
echo "🔧 Backing up kubeconfig..."
backup_file_as_document "kubeconfig" "homeops-kubeconfig" || true

echo ""
echo "🔧 Backing up talosconfig..."
backup_file_as_document "talosconfig" "homeops-talosconfig" || true

echo ""
echo "📊 Backup Summary:"
echo "   ✅ Successful: $BACKUP_SUCCESS/$BACKUP_TOTAL"

if [ "$BACKUP_SUCCESS" -eq "$BACKUP_TOTAL" ]; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $(whoami)@$(hostname) SUCCESS ${BACKUP_SUCCESS}/${BACKUP_TOTAL}" >> "$RUN_LOG"
    echo "🎉 All backups completed successfully!"
    echo ""
    echo "📝 Backed up items in vault '$VAULT':"
    echo "   - homeops-age-key-backup (Secure Note)"
    echo "   - homeops-cluster-config (Document)"
    echo "   - homeops-bootstrap-templates (Document)"
    echo "   - homeops-kubeconfig (Document)"
    echo "   - homeops-talosconfig (Document)"
    echo ""
    echo "💡 To verify: task backup:list"
    echo "💡 To restore: task backup:restore"
    echo "💡 Run history: $RUN_LOG"
    exit 0
else
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $(whoami)@$(hostname) PARTIAL ${BACKUP_SUCCESS}/${BACKUP_TOTAL}" >> "$RUN_LOG"
    echo "⚠️  Some backups failed! Check the output above for details."
    echo ""
    echo "💡 To troubleshoot:"
    echo "   - Ensure you're signed into 1Password CLI: op signin"
    echo "   - Check vault access: op vault list"
    echo "   - Verify file permissions in the repository"
    exit 1
fi
