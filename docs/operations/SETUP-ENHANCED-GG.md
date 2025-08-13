# Enhanced `gg` Setup Guide

This guide sets up your `gg` function to automatically include pre-commit auto-fix and retry functionality when you're in the home-ops repository.

## Prerequisites

1. **direnv installed**: `brew install direnv`
2. **direnv hooked into shell**: Add to your `~/.zshrc`:

   ```bash
   eval "$(direnv hook zsh)"
   ```

## Setup Methods

### Method 1: Automatic (via direnv) - Recommended

**What it does**: Automatically loads enhanced `gg` when you `cd` into home-ops directory

1. **Hook direnv** (if not already done):

   ```bash
   echo 'eval "$(direnv hook zsh)"' >> ~/.zshrc
   source ~/.zshrc
   ```

2. **Allow the .envrc file**:

   ```bash
   cd ~/dev/home-ops
   direnv allow
   ```

3. **Test it works**:

   ```bash
   # Leave and re-enter the directory to trigger direnv
   cd .. && cd home-ops

   # Should see: "🚀 Enhanced git functions loaded for home-ops:"

   # Test the function
   type gg
   ```

### Method 2: Manual Loading

**What it does**: Manually source the functions when needed

```bash
# In the home-ops directory
source scripts/enhanced-gg.sh

# Now gg is enhanced with auto-retry
gg "test: enhanced function working"
```

### Method 3: Global Shell Setup

**What it does**: Always use enhanced functions (not repo-specific)

Add to your `~/.zshrc`:

```bash
# Load enhanced git functions globally
if [[ -f ~/dev/home-ops/scripts/enhanced-gg.sh ]]; then
    source ~/dev/home-ops/scripts/enhanced-gg.sh
fi
```

## Verification

Run this to test if setup worked:

```bash
cd ~/dev/home-ops
./scripts/test-functions.sh
```

Should show:

```bash
✅ gg function: Available
✅ gg_original function: Available
✅ gg_quick function: Available
✅ auto_commit function: Available
```

## Usage

### In home-ops directory (with direnv setup)

```bash
# Your normal workflow - now enhanced!
gg "feat: add new application"

# What happens:
# 1. Shows git status ✅
# 2. Waits for Enter ✅
# 3. Auto-fixes formatting ✅
# 4. Retries up to 3 times ✅
# 5. Pushes successfully ✅
```

### Alternative functions available

```bash
# Original behavior (no auto-retry)
gg_original "commit message"

# Quick commit (no pause for review)
gg_quick "commit message"

# Just the auto-commit part
auto_commit "commit message"
```

## Troubleshooting

### Functions not loading?

1. **Check direnv setup**:

   ```bash
   which direnv
   direnv version
   ```

2. **Check .envrc is allowed**:

   ```bash
   direnv status
   ```

3. **Manual trigger**:

   ```bash
   cd .. && cd home-ops  # Re-enter directory
   direnv reload         # Force reload
   ```

4. **Check function definitions**:

   ```bash
   type gg
   declare -f gg
   ```

### Still using old gg function?

Your existing `gg` function might be defined in your shell profile. The direnv version should override it when you're in the home-ops directory.

Check where your current `gg` is defined:

```bash
type gg
```

## Benefits

✅ **Same workflow** - `gg "message"` works exactly as before
✅ **Auto-fixes** - Handles whitespace, formatting, etc. automatically
✅ **Smart retry** - Up to 3 attempts with fixes between retries
✅ **Better feedback** - Clear status messages and progress indicators
✅ **Repository-specific** - Only active in home-ops, doesn't affect other repos
✅ **Fallback options** - `gg_original` available if needed
