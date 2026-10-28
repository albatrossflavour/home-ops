#!/bin/sh
# Install the pinned Claude Code CLI onto the PVC once per version, then run the checker.
set -eu
bin=/data/claude/node_modules/.bin/claude
case "$("$bin" --version 2>/dev/null || true)" in
  "$CLAUDE_CODE_VERSION"*) ;;
  *) npm install --silent --no-audit --no-fund --prefix /data/claude "@anthropic-ai/claude-code@$CLAUDE_CODE_VERSION" ;;
esac
mkdir -p "$HOME"
cd /app
exec python3 -m checker.main
