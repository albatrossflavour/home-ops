#!/bin/bash
# Test script to demonstrate the function loading

echo "🔍 Testing git function availability:"
echo

# Test if functions are available
if type gg &>/dev/null; then
    echo "✅ gg function: Available"
    echo "   $(type gg | head -1)"
else
    echo "❌ gg function: Not available"
fi

if type gg_original &>/dev/null; then
    echo "✅ gg_original function: Available"
    echo "   $(type gg_original | head -1)"
else
    echo "❌ gg_original function: Not available"
fi

if type gg_quick &>/dev/null; then
    echo "✅ gg_quick function: Available"
    echo "   $(type gg_quick | head -1)"
else
    echo "❌ gg_quick function: Not available"
fi

if type auto_commit &>/dev/null; then
    echo "✅ auto_commit function: Available"
    echo "   $(type auto_commit | head -1)"
else
    echo "❌ auto_commit function: Not available"
fi

echo
echo "💡 If functions are not available:"
echo "   1. Make sure direnv is set up: direnv allow"
echo "   2. Or source manually: source scripts/enhanced-gg.sh"
echo "   3. Or cd out and back into the home-ops directory"
