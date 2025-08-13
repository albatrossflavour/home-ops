# Simple Enhanced gg Installation

## What it does

- **In home-ops repo**: Auto-retry with pre-commit fixing
- **In other repos**: Your normal gg behavior
- **One function**: No complex setup needed

## Installation

1. **Replace your existing gg function** in `~/.zshrc`:

   ```bash
   # Remove or comment out your old gg function, then add:

   gg() {
       # Check if we're in a git repo first
       if [ "$(git rev-parse 2>/dev/null 1>/dev/null; echo $?)" -eq 128 ]; then
           echo "Not in a git repo"
           return 1
       fi

       # Check if we're in the home-ops repository
       local repo_root
       repo_root=$(git rev-parse --show-toplevel 2>/dev/null)
       local is_home_ops=false

       if [[ "$repo_root" == *"home-ops"* ]] || [[ -f "$repo_root/.envrc" && -f "$repo_root/kubeconfig" ]]; then
           is_home_ops=true
           echo "🚀 Using enhanced gg for home-ops repository"
       fi

       # Show status
       git status
       echo
       echo "Press Enter to continue with commit (Ctrl+C to cancel)..."
       read -r _

       # Stage all changes
       git add -A

       if [ "$is_home_ops" = true ]; then
           # Enhanced behavior with auto-retry for home-ops
           local max_retries=3
           local retry_count=0

           echo "🚀 Starting commit with pre-commit auto-fix retry..."

           while [ $retry_count -lt $max_retries ]; do
               echo "📝 Commit attempt $((retry_count + 1))/$max_retries"

               if [ -n "$1" ]; then
                   if git commit -m "$*"; then
                       echo "✅ Commit successful!"
                       break
                   fi
               else
                   if git commit; then
                       echo "✅ Commit successful!"
                       break
                   fi
               fi

               retry_count=$((retry_count + 1))
               if [ $retry_count -lt $max_retries ]; then
                   echo "🔧 Pre-commit failed, auto-fixing and retrying..."
                   git add -A
                   sleep 1
               else
                   echo "❌ Max retries reached. Fix issues manually and run:"
                   echo "   git add -A && git commit && git push"
                   return 1
               fi
           done

           echo "🚀 Pushing to remote..."
           if git push; then
               echo "✅ Complete! Changes are live."
           else
               echo "❌ Push failed. Try: git pull --rebase && git push"
               return 1
           fi
       else
           # Original behavior for other repos
           if [ -n "$1" ]; then
               git commit -m "$*"
           else
               git commit
           fi
           git push
       fi
   }
   ```

2. **Reload your shell**:

   ```bash
   source ~/.zshrc
   ```

## Test it

```bash
# In home-ops directory
cd ~/dev/home-ops
gg "test: enhanced function"
# Should show: "🚀 Using enhanced gg for home-ops repository"

# In any other git repo  
cd ~/some-other-repo
gg "test: normal behavior"
# Uses normal gg behavior
```

## What you get

✅ **Same command**: `gg "commit message"`  
✅ **Smart detection**: Automatically knows when you're in home-ops  
✅ **Auto-fixing**: Handles whitespace, formatting issues automatically  
✅ **Retry logic**: Up to 3 attempts with fixes between retries  
✅ **Backward compatible**: Other repos work exactly as before  
✅ **No extra tools**: No direnv, no complex setup  

That's it! One function replacement, maximum convenience.
