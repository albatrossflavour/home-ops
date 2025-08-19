#!/bin/bash
# Home-Ops Infrastructure Restore Script
# Restores critical files from 1Password using op CLI to a safe location

set -euo pipefail

VAULT="discworld"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RESTORE_DIR="$REPO_ROOT/restored-$(date +%Y%m%d-%H%M%S)"

echo "🔓 Starting Home-Ops infrastructure restore from 1Password..."
echo "📁 Files will be restored to: $RESTORE_DIR"

mkdir -p "$RESTORE_DIR"
cd "$RESTORE_DIR"

# Function to restore document
restore_document() {
    local title="$1"
    local output_file="$2"

    if op item get "$title" --vault="$VAULT" >/dev/null 2>&1; then
        echo "📥 Restoring $title to $output_file..."
        op document get "$title" --vault="$VAULT" --output="$output_file"
        echo "✅ $output_file restored"
    else
        echo "❌ $title not found in 1Password vault"
        return 1
    fi
}

restore_age_key() {
    local title="homeops-age-key-backup"

    if op item get "$title" --vault="$VAULT" >/dev/null 2>&1; then
        echo "📥 Restoring age.key from secure note..."
        op item get "$title" --vault="$VAULT" --field="notesPlain" > age.key
        chmod 600 age.key
        echo "✅ age.key restored with proper permissions"
    else
        echo "❌ $title not found in 1Password vault"
        return 1
    fi
}

restore_bootstrap_directory() {
    local title="homeops-bootstrap-templates"
    local archive="bootstrap-restore.tar.gz"

    if op item get "$title" --vault="$VAULT" >/dev/null 2>&1; then
        echo "📥 Restoring bootstrap/ directory..."
        op document get "$title" --vault="$VAULT" --output="$archive"
        tar -xzf "$archive"
        rm -f "$archive"
        echo "✅ bootstrap/ directory restored"
    else
        echo "❌ $title not found in 1Password vault"
        return 1
    fi
}

# Check if op CLI is available and authenticated
if ! command -v op >/dev/null 2>&1; then
    echo "❌ 1Password CLI (op) not found. Please install it first."
    echo "   https://developer.1password.com/docs/cli/get-started/"
    exit 1
fi

if ! op vault list >/dev/null 2>&1; then
    echo "❌ Not authenticated with 1Password CLI. Run: op signin"
    exit 1
fi

if ! op vault list | grep -q "$VAULT"; then
    echo "❌ Vault '$VAULT' not found or not accessible"
    exit 1
fi

echo "🔍 Checking available backups in vault: $VAULT"
echo ""

# Check what's available
available_items=()
for item in "homeops-age-key-backup" "homeops-cluster-config" "homeops-bootstrap-templates" "homeops-kubeconfig" "homeops-talosconfig"; do
    if op item get "$item" --vault="$VAULT" >/dev/null 2>&1; then
        available_items+=("$item")
        echo "✅ $item available"
    else
        echo "❌ $item not found"
    fi
done

if [ ${#available_items[@]} -eq 0 ]; then
    echo "❌ No backup items found in 1Password vault"
    exit 1
fi

echo ""
echo "📁 Files will be restored to: $RESTORE_DIR"
read -p "🤔 Continue with restore? [y/N]: " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Restore cancelled"
    rmdir "$RESTORE_DIR" 2>/dev/null || true
    exit 0
fi

echo ""
echo "🔄 Starting restore process..."

# Restore items
for item in "${available_items[@]}"; do
    case "$item" in
        "homeops-age-key-backup")
            restore_age_key
            ;;
        "homeops-cluster-config")
            restore_document "$item" "config.yaml"
            ;;
        "homeops-bootstrap-templates")
            restore_bootstrap_directory
            ;;
        "homeops-kubeconfig")
            restore_document "$item" "kubeconfig"
            chmod 600 kubeconfig
            ;;
        "homeops-talosconfig")
            restore_document "$item" "talosconfig"
            chmod 644 talosconfig
            ;;
    esac
done

echo ""
echo "🎉 Restore complete!"
echo "📁 All files restored to: $RESTORE_DIR"
echo ""
echo "📝 Next steps:"
echo "   1. Review restored files in $RESTORE_DIR"
echo "   2. Copy needed files to proper locations manually"
echo "   3. Test age.key: sops -d kubernetes/flux/vars/cluster-secrets.sops.yaml"
echo "   4. Test cluster access: kubectl --kubeconfig $RESTORE_DIR/kubeconfig get nodes"
echo ""
echo "💡 Manual copy commands (review before running):"
echo "   cp $RESTORE_DIR/age.key ./age.key"
echo "   cp $RESTORE_DIR/config.yaml ./config.yaml"
echo "   cp $RESTORE_DIR/kubeconfig ./kubeconfig"
echo "   cp $RESTORE_DIR/talosconfig ./talosconfig"
echo "   cp -r $RESTORE_DIR/bootstrap ./bootstrap"
echo ""
echo "⚠️  Note: restore directory is gitignored and safe from accidental commits"
