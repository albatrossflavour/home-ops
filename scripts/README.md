# Git Auto-Commit Setup

Enhanced git workflow with pre-commit auto-fix and retry functionality.

## Setup

Add this line to your shell profile (`~/.zshrc`, `~/.bashrc`, or `~/.profile`):

```bash
source ~/dev/home-ops/.shell-aliases
```

Then reload your shell:

```bash
source ~/.zshrc  # or ~/.bashrc
```

## Usage

### Enhanced `gg` Function (Recommended)

Your existing `gg` workflow now includes automatic pre-commit fixing and retry:

```bash
# Interactive commit with message
gg "fix: update helm values"

# Interactive commit (will open editor for message)
gg

# What it does:
# 1. Shows git status
# 2. Waits for your review (press Enter)
# 3. Stages all files (git add -A)
# 4. Commits with auto-retry (up to 3 attempts)
# 5. Auto-fixes common issues (whitespace, formatting)
# 6. Pushes to remote
```

### Alternative Options

```bash
# Original gg behavior (no auto-retry)
gg_orig "commit message"

# Quick commit without review pause
gg_fast "commit message"

# Direct auto-commit function
auto_commit "commit message"

# Task-based approach
task commit -- "commit message"
task commit-and-push -- "commit message"
```

## What Gets Auto-Fixed

The system automatically fixes these common issues:

- ✅ **Trailing whitespace** - Removes extra spaces at line ends
- ✅ **Missing newlines** - Adds final newline to files  
- ✅ **Line endings** - Normalizes to LF
- ✅ **Python formatting** - Ruff code formatting
- ✅ **Import sorting** - Organizes Python imports
- ✅ **Markdown formatting** - Fixes markdown syntax
- ✅ **YAML formatting** - Basic YAML structure fixes

## Troubleshooting

If commits still fail after 3 retries:

1. **Check the pre-commit output** - Look for specific errors
2. **Fix manually** - Address any remaining issues
3. **Continue workflow** - Run `git add -A && git commit -m "message" && git push`

Common issues that need manual fixing:

- YAML syntax errors (unquoted special characters)
- Kubernetes manifest validation failures  
- Security scan findings
- Complex linting violations

## Examples

```bash
# Your normal workflow - now with auto-retry
gg "feat: add nocodb deployment"

# Quick update without review
gg_fast "chore: update dependencies"  

# Original behavior if needed
gg_orig "fix: manual formatting required"
```

The enhanced `gg` function maintains your existing workflow while adding resilience against common formatting issues!
