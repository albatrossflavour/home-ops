# DNS Sync Script for Edward

This script allows you to access cluster services (like Sonarr, Radarr, Homepage, etc.) without using the cluster's DNS servers.

## What It Does

- Fetches a list of all cluster services from the Kubernetes cluster
- Updates your Windows hosts file with the correct IP addresses
- Runs automatically every time you run it

## How to Use

### First Time Setup

1. **Copy the script** to your Windows desktop or a convenient location:
   - File: `Sync-ClusterDNS.ps1`
   - Right-click → "Run with PowerShell" (as Administrator)

2. **If you get an execution policy error**, open PowerShell as Administrator and run:

   ```powershell
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   ```

### Running the Script

#### Option 1: Double-click the script

- Right-click `Sync-ClusterDNS.ps1`
- Select "Run with PowerShell"
- Click "Yes" when prompted for administrator access

#### Option 2: From PowerShell (as Administrator)

```powershell
cd C:\Path\To\Script
.\Sync-ClusterDNS.ps1
```

#### Option 3: Test first (Dry Run)

```powershell
.\Sync-ClusterDNS.ps1 -DryRun
```

#### Option 4: Create Chrome Bookmarks

```powershell
.\Sync-ClusterDNS.ps1 -CreateBookmarks
```

This creates a bookmarks file in your Downloads folder that you can import into Chrome. It includes the most useful services with descriptions:

- **Plex** - Stream movies, TV shows, and music
- **Sonarr** - TV show management
- **Radarr** - Movie management
- **Overseerr** - Request new media
- And more!

To import the bookmarks into Chrome:

1. Open Chrome
2. Press `Ctrl+Shift+O` to open Bookmarks Manager
3. Click the three dots (⋮) in the top right
4. Select "Import bookmarks"
5. Choose the file from your Downloads folder: `ClusterServices-Bookmarks.html`

The bookmarks will appear in a "Cluster Services" folder.

### Set Up Automatic Sync (Optional)

To have it update automatically every day:

1. Open PowerShell as Administrator
2. Run these commands (adjust the path to where you saved the script):

```powershell
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\Path\To\Sync-ClusterDNS.ps1"

$trigger = New-ScheduledTaskTrigger -Daily -At 9am

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName "Sync Cluster DNS" -Action $action -Trigger $trigger -Principal $principal
```

## What Services You Can Access

After running the script, you can access these services in your browser:

- **Plex**: https://plex.albatrossflavour.com - Stream movies, TV shows, and music
- **Sonarr**: https://sonarr.albatrossflavour.com - Manage TV shows
- **Radarr**: https://radarr.albatrossflavour.com - Manage movies
- **Overseerr**: https://overseerr.albatrossflavour.com - Request new media
- **Homepage**: https://homepage.albatrossflavour.com - Service dashboard
- **And 50+ other services!**

The script will show you the first 5 services when it completes.

**Tip**: Use the `-CreateBookmarks` option to generate a Chrome bookmarks file with all the useful services and their descriptions!

## Troubleshooting

### "Script won't run - execution policy error"

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### "Can't reach the cluster"

Make sure you're on the home network (192.168.x.x). The script needs to reach `192.168.8.10:30888`.

### "Services still don't load"

1. Run the script again (might have been a temporary issue)
2. Try a different node IP if 192.168.8.10 isn't working:

   ```powershell
   .\Sync-ClusterDNS.ps1 -DNSEndpoint "http://192.168.8.11:30888/dns-entries.json"
   ```

### "Want to see what changed"

Your hosts file is at: `C:\Windows\System32\drivers\etc\hosts`

Look for the section between:

```text
# START: Cluster Services - Auto-managed by Sync-ClusterDNS.ps1
...
# END: Cluster Services
```

## How It Works

1. The cluster has a service that exports all DNS entries as JSON
2. The script downloads this JSON file
3. It updates the "hosts" file on Windows with all the service names and IPs
4. Windows then knows how to find those services without using DNS servers

## Need Help?

Ask Dad if something isn't working!
