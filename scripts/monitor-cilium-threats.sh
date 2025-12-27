#!/usr/bin/env bash

# Cilium Network Policy Threat Monitor
# Quick check for suspicious traffic and policy activity

set -euo pipefail

KUBECONFIG="${KUBECONFIG:-./kubeconfig}"
TAIL_LINES="${1:-1000}"  # Default to last 1000 log lines, override with argument

echo "🔍 Cilium Threat Monitor - Checking last ${TAIL_LINES} log lines..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check for any denied/dropped traffic
echo "🚫 Policy Denials (blocked traffic):"
DENIALS=$(kubectl --kubeconfig "$KUBECONFIG" logs -n kube-system -l k8s-app=cilium --tail="$TAIL_LINES" 2>/dev/null | grep -iE "(verdict.*DENIED|action.*DROP|policy.*denied)" | grep -v "hubble-drop-events\|bpf-events-drop\|Configured metrics plugin.*drop" || true)
if [ -z "$DENIALS" ]; then
    echo "   ✅ No denied traffic found"
else
    echo "$DENIALS" | head -20
    DENIAL_COUNT=$(echo "$DENIALS" | wc -l | tr -d ' ')
    echo "   ⚠️  Found $DENIAL_COUNT denial events (showing first 20)"
fi
echo ""

# Check for Tor exit node traffic
echo "🧅 Tor Exit Node Traffic (185.220.100.0/22):"
TOR_TRAFFIC=$(kubectl --kubeconfig "$KUBECONFIG" logs -n kube-system -l k8s-app=cilium --tail="$TAIL_LINES" 2>/dev/null | grep "185\.220\." || true)
if [ -z "$TOR_TRAFFIC" ]; then
    echo "   ✅ No Tor traffic detected"
else
    echo "$TOR_TRAFFIC" | head -10
    TOR_COUNT=$(echo "$TOR_TRAFFIC" | wc -l | tr -d ' ')
    echo "   ⚠️  Found $TOR_COUNT Tor-related events (showing first 10)"
fi
echo ""

# Check for any suspicious source IPs (common VPN/proxy ranges)
echo "🔎 Suspicious Source IPs (VPN/Proxy ranges):"
SUSPICIOUS=$(kubectl --kubeconfig "$KUBECONFIG" logs -n kube-system -l k8s-app=cilium --tail="$TAIL_LINES" 2>/dev/null | grep -E "45\.142\.|185\.220\.|103\.21\." || true)
if [ -z "$SUSPICIOUS" ]; then
    echo "   ✅ No suspicious IP activity"
else
    echo "$SUSPICIOUS" | head -10
    SUSP_COUNT=$(echo "$SUSPICIOUS" | wc -l | tr -d ' ')
    echo "   ⚠️  Found $SUSP_COUNT suspicious IP events (showing first 10)"
fi
echo ""

# Recent policy updates
echo "📋 Recent Policy Activity:"
POLICY_ACTIVITY=$(kubectl --kubeconfig "$KUBECONFIG" logs -n kube-system -l k8s-app=cilium --tail=50 2>/dev/null | grep -i "policy" | tail -5 || true)
if [ -z "$POLICY_ACTIVITY" ]; then
    echo "   ℹ️  No recent policy activity"
else
    echo "$POLICY_ACTIVITY"
fi
echo ""

# Active policies summary
echo "📊 Active Network Policies:"
kubectl --kubeconfig "$KUBECONFIG" get ciliumclusterwideNetworkpolicies 2>/dev/null | tail -n +2 | while read -r name rest; do
    STATUS=$(kubectl --kubeconfig "$KUBECONFIG" get ccnp "$name" -o jsonpath='{.status.state}' 2>/dev/null || echo "unknown")
    printf "   %-30s %s\n" "$name" "$STATUS"
done
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Scan complete - $(date)"
echo ""
echo "💡 Tips:"
echo "   - Run with custom line count: $0 5000"
echo "   - Watch in real-time: watch -n 30 $0"
echo "   - Check full logs: kubectl --kubeconfig kubeconfig logs -n kube-system -l k8s-app=cilium -f"
