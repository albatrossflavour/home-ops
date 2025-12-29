#Requires -RunAsAdministrator

<#
.SYNOPSIS
    Syncs Kubernetes cluster DNS entries to Windows hosts file
.DESCRIPTION
    Fetches DNS entries from the cluster's DNS export service and updates the Windows hosts file.
    This allows access to cluster services without using the cluster's DNS servers.
.PARAMETER DNSEndpoint
    The URL to fetch DNS entries from. Defaults to using NodePort on node IP.
.PARAMETER HostsPath
    Path to the Windows hosts file. Defaults to C:\Windows\System32\drivers\etc\hosts
.PARAMETER DryRun
    If specified, shows what would be changed without actually modifying the hosts file
.EXAMPLE
    .\Sync-ClusterDNS.ps1
    Syncs DNS entries to the hosts file
.EXAMPLE
    .\Sync-ClusterDNS.ps1 -DryRun
    Shows what changes would be made without applying them
#>

param(
    [string]$DNSEndpoint = "http://192.168.8.10:30888/dns-entries.json",
    [string]$HostsPath = "$env:SystemRoot\System32\drivers\etc\hosts",
    [switch]$DryRun
)

# Marker comments to identify our managed section
$startMarker = "# START: Cluster Services - Auto-managed by Sync-ClusterDNS.ps1"
$endMarker = "# END: Cluster Services"

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

    if (-not $DryRun) {
        Write-Host "`n=== Sync Complete! ===" -ForegroundColor Magenta
        Write-Host "You can now access cluster services like:" -ForegroundColor Green
        $dnsEntries | Select-Object -First 5 | ForEach-Object {
            Write-Host "  - http://$($_.hostname)" -ForegroundColor Cyan
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
