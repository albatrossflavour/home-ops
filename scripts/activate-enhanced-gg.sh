#!/bin/bash
# activate-enhanced-gg.sh - Quick activation script for enhanced gg functions
# Usage: source ./activate-enhanced-gg.sh

echo "🚀 Loading enhanced git functions for home-ops..."

# Source the enhanced functions
if [[ -f "scripts/enhanced-gg.sh" ]]; then
    # shellcheck source=scripts/enhanced-gg.sh
    source scripts/enhanced-gg.sh
    echo "✅ Enhanced gg functions loaded:"
    echo "   gg -> auto-retry with pre-commit fixing"
    echo "   gg_original -> your original gg behavior"
    echo "   gg_quick -> quick commit without pause"
    echo ""
    echo "💡 Test with: type gg"
    echo "📝 Use normally: gg 'your commit message'"
else
    echo "❌ scripts/enhanced-gg.sh not found"
    echo "   Make sure you're in the home-ops directory"
fi

# Also load the auto-commit function
if [[ -f "scripts/git-auto-commit.sh" ]]; then
    # shellcheck source=scripts/git-auto-commit.sh
    source scripts/git-auto-commit.sh
    echo "✅ auto_commit function also available"
else
    echo "⚠️  auto_commit function not found"
fi
