#Requires -RunAsAdministrator

<#
.SYNOPSIS
    Syncs Kubernetes cluster DNS entries to Windows hosts file and creates Chrome bookmarks
.DESCRIPTION
    Fetches DNS entries from the cluster's DNS export service and updates the Windows hosts file.
    This allows access to cluster services without using the cluster's DNS servers.
    Optionally creates a Chrome-compatible bookmarks HTML file for easy access to services.
.PARAMETER DNSEndpoint
    The URL to fetch DNS entries from. Defaults to using NodePort on node IP.
.PARAMETER HostsPath
    Path to the Windows hosts file. Defaults to C:\Windows\System32\drivers\etc\hosts
.PARAMETER DryRun
    If specified, shows what would be changed without actually modifying the hosts file
.PARAMETER CreateBookmarks
    If specified, creates a Chrome-compatible bookmarks HTML file
.PARAMETER BookmarksPath
    Path where the bookmarks HTML file will be created. Defaults to current user's Downloads folder
.EXAMPLE
    .\Sync-ClusterDNS.ps1
    Syncs DNS entries to the hosts file
.EXAMPLE
    .\Sync-ClusterDNS.ps1 -DryRun
    Shows what changes would be made without applying them
.EXAMPLE
    .\Sync-ClusterDNS.ps1 -CreateBookmarks
    Syncs DNS entries and creates a Chrome bookmarks file
#>

param(
    [string]$DNSEndpoint = "http://192.168.8.10:30888/dns-entries.json",
    [string]$HostsPath = "$env:SystemRoot\System32\drivers\etc\hosts",
    [string]$BookmarksPath = "$env:USERPROFILE\Downloads\ClusterServices-Bookmarks.html",
    [switch]$DryRun,
    [switch]$CreateBookmarks
)

# Marker comments to identify our managed section
$startMarker = "# START: Cluster Services - Auto-managed by Sync-ClusterDNS.ps1"
$endMarker = "# END: Cluster Services"

# Service descriptions for bookmarks
$serviceDescriptions = @{
    'plex'     = 'Plex Media Server - Stream movies, TV shows, and music'
    'sonarr'   = 'Sonarr - TV show management and automation'
    'radarr'   = 'Radarr - Movie management and automation'
    'overseerr' = 'Overseerr - Media request management'
    'sabnzbd'  = 'SABnzbd - Usenet download manager'
    'qbittorrent' = 'qBittorrent - Torrent download manager'
    'prowlarr' = 'Prowlarr - Indexer manager'
    'bazarr'   = 'Bazarr - Subtitle management'
    'tautulli' = 'Tautulli - Plex monitoring and statistics'
    'homepage' = 'Homepage - Service dashboard'
    'immich'   = 'Immich - Photo and video management'
    'paperless' = 'Paperless - Document management'
}

function Get-ClusterDNSEntries {
    Write-Host "Fetching DNS entries from cluster..." -ForegroundColor Cyan
    Write-Host "Endpoint: $DNSEndpoint" -ForegroundColor Gray

    try {
        $entries = Invoke-RestMethod -Uri $DNSEndpoint -TimeoutSec 10 -ErrorAction Stop

        if ($null -eq $entries -or $entries.Count -eq 0) {
            Write-Host "No DNS entries found!" -ForegroundColor Yellow
            return @()
        }

        Write-Host "Found $($entries.Count) services" -ForegroundColor Green
        return $entries
    }
    catch {
        Write-Host "Failed to fetch DNS entries: $_" -ForegroundColor Red
        Write-Host "Make sure you can reach the cluster at $DNSEndpoint" -ForegroundColor Yellow
        throw
    }
}

function Update-HostsFile {
    param(
        [array]$Entries
    )

    Write-Host "`nUpdating hosts file: $HostsPath" -ForegroundColor Cyan

    # Read current hosts file
    $hostsContent = Get-Content -Path $HostsPath -Raw -ErrorAction SilentlyContinue
    if (-not $hostsContent) {
        $hostsContent = ""
    }

    # Remove existing managed section (if it exists)
    $pattern = "(?s)$([regex]::Escape($startMarker)).*?$([regex]::Escape($endMarker))\r?\n?"
    $hostsContent = $hostsContent -replace $pattern, ""

    # Build new managed section
    $managedSection = @()
    $managedSection += $startMarker
    $managedSection += "# Updated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    $managedSection += "# This section is automatically managed - do not edit manually!"
    $managedSection += ""

    # Group by IP and sort
    $grouped = $Entries | Group-Object ip | Sort-Object Name
    foreach ($group in $grouped) {
        $managedSection += "# Services on $($group.Name)"
        foreach ($entry in ($group.Group | Sort-Object hostname)) {
            $managedSection += "$($entry.ip)`t$($entry.hostname)"
        }
        $managedSection += ""
    }

    $managedSection += $endMarker

    # Combine content
    $newContent = $hostsContent.TrimEnd() + "`n`n" + ($managedSection -join "`n")

    if ($DryRun) {
        Write-Host "`n=== DRY RUN - Would add these entries to hosts file ===" -ForegroundColor Yellow
        Write-Host ($managedSection -join "`n") -ForegroundColor Gray
        Write-Host "`n=== END DRY RUN ===" -ForegroundColor Yellow
        return
    }

    # Backup current hosts file
    $backupPath = "$HostsPath.backup.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    try {
        Copy-Item -Path $HostsPath -Destination $backupPath -ErrorAction Stop
        Write-Host "Backed up hosts file to: $backupPath" -ForegroundColor Yellow
    }
    catch {
        Write-Host "Warning: Could not create backup: $_" -ForegroundColor Yellow
    }

    # Write new content
    try {
        Set-Content -Path $HostsPath -Value $newContent -NoNewline -ErrorAction Stop
        Write-Host "✓ Hosts file updated successfully!" -ForegroundColor Green
    }
    catch {
        Write-Host "Failed to update hosts file: $_" -ForegroundColor Red
        throw
    }

    # Flush DNS cache
    Write-Host "Flushing DNS cache..." -ForegroundColor Cyan
    try {
        ipconfig /flushdns | Out-Null
        Write-Host "✓ DNS cache flushed!" -ForegroundColor Green
    }
    catch {
        Write-Host "Warning: Could not flush DNS cache: $_" -ForegroundColor Yellow
    }
}

function New-ChromeBookmarks {
    param(
        [array]$Entries
    )

    Write-Host "`nCreating Chrome bookmarks file..." -ForegroundColor Cyan

    # Define priority services to include in bookmarks
    $priorityServices = @('plex', 'sonarr', 'radarr', 'overseerr', 'sabnzbd', 'qbittorrent',
                          'prowlarr', 'bazarr', 'tautulli', 'homepage', 'immich', 'paperless')

    # Filter entries for services we want to bookmark
    $bookmarkEntries = $Entries | Where-Object {
        $hostname = $_.hostname
        $priorityServices | Where-Object { $hostname -match $_ }
    }

    if ($bookmarkEntries.Count -eq 0) {
        Write-Host "No matching services found for bookmarks" -ForegroundColor Yellow
        return
    }

    # Build Chrome-compatible HTML bookmarks file
    $html = @"
<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="$(Get-Date -UFormat %s)" LAST_MODIFIED="$(Get-Date -UFormat %s)">Cluster Services</H3>
    <DL><p>
"@

    # Add each service as a bookmark
    foreach ($entry in ($bookmarkEntries | Sort-Object hostname)) {
        $hostname = $entry.hostname
        $url = "https://$hostname"

        # Try to match service name from hostname
        $serviceName = $null
        $description = $hostname

        foreach ($service in $serviceDescriptions.Keys) {
            if ($hostname -match $service) {
                $serviceName = $service.Substring(0,1).ToUpper() + $service.Substring(1)
                $description = $serviceDescriptions[$service]
                break
            }
        }

        if (-not $serviceName) {
            $serviceName = $hostname -replace '\..*$', ''
            $serviceName = $serviceName.Substring(0,1).ToUpper() + $serviceName.Substring(1)
        }

        $timestamp = Get-Date -UFormat %s
        $html += "        <DT><A HREF=`"$url`" ADD_DATE=`"$timestamp`">$serviceName - $description</A>`n"
    }

    $html += @"
    </DL><p>
</DL><p>
"@

    if ($DryRun) {
        Write-Host "`n=== DRY RUN - Would create bookmarks file ===" -ForegroundColor Yellow
        Write-Host "File: $BookmarksPath" -ForegroundColor Gray
        Write-Host "Services: $($bookmarkEntries.Count)" -ForegroundColor Gray
        $bookmarkEntries | ForEach-Object {
            Write-Host "  - $($_.hostname)" -ForegroundColor Cyan
        }
        Write-Host "=== END DRY RUN ===" -ForegroundColor Yellow
        return
    }

    try {
        Set-Content -Path $BookmarksPath -Value $html -Encoding UTF8 -ErrorAction Stop
        Write-Host "✓ Bookmarks file created: $BookmarksPath" -ForegroundColor Green
        Write-Host "  Services included: $($bookmarkEntries.Count)" -ForegroundColor Cyan
        Write-Host "`nTo import into Chrome:" -ForegroundColor Yellow
        Write-Host "  1. Open Chrome" -ForegroundColor Gray
        Write-Host "  2. Press Ctrl+Shift+O to open Bookmarks Manager" -ForegroundColor Gray
        Write-Host "  3. Click the three dots (⋮) in the top right" -ForegroundColor Gray
        Write-Host "  4. Select 'Import bookmarks'" -ForegroundColor Gray
        Write-Host "  5. Choose the file: $BookmarksPath" -ForegroundColor Gray
    }
    catch {
        Write-Host "Failed to create bookmarks file: $_" -ForegroundColor Red
    }
}

# Main execution
try {
    Write-Host "=== Kubernetes Cluster DNS Sync ===" -ForegroundColor Magenta
    Write-Host ""

    # Get DNS entries from cluster
    $dnsEntries = Get-ClusterDNSEntries

    if ($dnsEntries.Count -eq 0) {
        Write-Host "`nNo DNS entries to sync." -ForegroundColor Yellow
        exit 0
    }

    # Update hosts file
    Update-HostsFile -Entries $dnsEntries

    # Create bookmarks if requested
    if ($CreateBookmarks) {
        New-ChromeBookmarks -Entries $dnsEntries
    }

    if (-not $DryRun) {
        Write-Host "`n=== Sync Complete! ===" -ForegroundColor Magenta
        Write-Host "You can now access cluster services like:" -ForegroundColor Green
        $dnsEntries | Select-Object -First 5 | ForEach-Object {
            Write-Host "  - https://$($_.hostname)" -ForegroundColor Cyan
        }
        if ($dnsEntries.Count > 5) {
            Write-Host "  ... and $($dnsEntries.Count - 5) more services" -ForegroundColor Cyan
        }
    }

} catch {
    Write-Host "`nError: $_" -ForegroundColor Red
    Write-Host $_.ScriptStackTrace -ForegroundColor Red
    exit 1
}
