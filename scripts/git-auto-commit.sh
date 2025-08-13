#!/bin/bash
# git-auto-commit.sh - Auto-fix and retry git commits

auto_commit() {
    local max_retries=3
    local retry_count=0
    local commit_message="$*"

    echo "🚀 Auto-commit with pre-commit retry..."

    while [ $retry_count -lt $max_retries ]; do
        echo "📝 Attempt $((retry_count + 1))/$max_retries"

        if git commit -m "$commit_message"; then
            echo "✅ Commit successful!"
            return 0
        else
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $max_retries ]; then
                echo "🔧 Pre-commit failed, auto-fixing and retrying..."
                # Add any files that were auto-fixed by pre-commit
                git add -A
                sleep 1
            else
                echo "❌ Max retries reached. Remaining issues:"
                echo "  1. Check pre-commit output above"
                echo "  2. Fix remaining issues manually"
                echo "  3. Run: git add -A && git commit -m '$commit_message'"
                return 1
            fi
        fi
    done
}

# Usage examples:
# auto_commit "fix: update configuration"
# auto_commit "feat: add new feature"

# If called directly (not sourced)
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    if [ $# -eq 0 ]; then
        echo "Usage: $0 'commit message'"
        echo "Example: $0 'fix: update helm values'"
        exit 1
    fi
    auto_commit "$*"
fi
