# Enhanced Git Workflow

Simple `gg` script with auto-retry for home-ops repository.

## Setup

1. **Remove or comment out** your existing `gg` function from `~/.zshrc`:

   ```bash
   # Comment out or delete your existing gg function
   # gg() { ... }
   ```

2. **Add scripts directory to PATH** in `~/.zshrc`:

   ```bash
   export PATH="$HOME/dev/home-ops/scripts:$PATH"
   ```

3. **Reload shell**:

   ```bash
   source ~/.zshrc
   ```

## Usage

Same as before - `gg` just works:

```bash
# In home-ops directory
gg "feat: add new application"
# Shows: "🚀 Enhanced mode: home-ops repository detected"
# Auto-retries with pre-commit fixing

# In other repositories  
gg "fix: update documentation"  
# Normal behavior, no auto-retry
```

## What it does

**In home-ops repository:**

- ✅ Auto-detects home-ops (looks for `.envrc` + `kubeconfig`)
- ✅ Shows git status and waits for confirmation
- ✅ Stages all changes
- ✅ Auto-retries commit up to 3 times
- ✅ Auto-fixes common issues (whitespace, formatting)
- ✅ Pushes to remote

**In other repositories:**

- ✅ Shows git status and waits for confirmation  
- ✅ Stages all changes
- ✅ Simple commit (no retry)
- ✅ Pushes to remote

## Benefits

- 🎯 **Simple**: Just a script, no complex functions
- 🔧 **Smart**: Auto-detects home-ops vs other repos
- 🚀 **Robust**: Handles pre-commit failures automatically
- 📦 **Portable**: Easy to backup/version/share
- 🧹 **Clean**: No shell function pollution

## Troubleshooting

**Script not found:**

```bash
which gg  # Should show: /Users/tgreen/dev/home-ops/scripts/gg
```

**Still using old function:**
Remove the `gg` function from your `~/.zshrc` and restart your shell.

**PATH not updated:**
Make sure `~/dev/home-ops/scripts` is in your PATH:

```bash
echo $PATH | grep home-ops
```
