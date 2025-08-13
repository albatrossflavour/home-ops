#!/bin/bash
# Enhanced gg function with pre-commit auto-fix and retry

gg() {
    # Check if we're in a git repo
    if [ "$(git rev-parse 2>/dev/null 1>/dev/null; echo $?)" -eq 128 ]; then
        echo "Not in a git repo"
        return 1
    fi

    # Show current status
    echo "🔍 Current git status:"
    git status

    # Pause for review
    echo ""
    echo "Press Enter to continue with commit (Ctrl+C to cancel)..."
    read -r _

    # Stage all changes
    echo "📦 Staging all changes..."
    git add -A

    # Auto-commit with retry logic
    local max_retries=3
    local retry_count=0

    echo "🚀 Starting commit process with pre-commit auto-fix retry..."

    while [ $retry_count -lt $max_retries ]; do
        echo "📝 Commit attempt $((retry_count + 1))/$max_retries"

        # Attempt commit
        if [ -n "$1" ]; then
            # Use provided commit message
            if git commit -m "$*"; then
                echo "✅ Commit successful!"
                break
            fi
        else
            # Use interactive commit (will open editor)
            if git commit; then
                echo "✅ Commit successful!"
                break
            fi
        fi

        # If we get here, commit failed
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $max_retries ]; then
            echo "🔧 Pre-commit failed, auto-fixing and retrying..."
            echo "   (Files may have been automatically fixed)"
            # Re-add any files that were auto-fixed by pre-commit
            git add -A
            sleep 1
        else
            echo "❌ Max retries reached. Remaining issues need manual attention:"
            echo "   1. Check the pre-commit output above"
            echo "   2. Fix any remaining issues manually"
            echo "   3. Run 'git add -A && git commit' when ready"
            echo "   4. Then run 'git push' to complete"
            return 1
        fi
    done

    # Push to remote
    echo "🚀 Pushing to remote..."
    if git push; then
        echo "✅ Push successful!"
        echo "🎉 Complete! Changes are now live."
    else
        echo "❌ Push failed. You may need to pull first:"
        echo "   git pull --rebase && git push"
        return 1
    fi
}

# Backup function - original gg behavior
gg_original() {
    if [ "$(git rev-parse 2>/dev/null 1>/dev/null; echo $?)" -eq 128 ]; then
        echo "Not in a git repo"
    else
        git status
        read -r _
        git add -A
        if [ -n "$1" ]; then
            git commit -m "$*"
        else
            git commit
        fi
        git push
    fi
}

# Quick commit without review (for automation)
gg_quick() {
    if [ "$(git rev-parse 2>/dev/null 1>/dev/null; echo $?)" -eq 128 ]; then
        echo "Not in a git repo"
        return 1
    fi

    git add -A
    ./scripts/git-auto-commit.sh "${*:-chore: update configuration}"
    git push
}

# Export functions if sourced
if [ "${BASH_SOURCE[0]}" != "${0}" ]; then
    export -f gg gg_original gg_quick
fi
