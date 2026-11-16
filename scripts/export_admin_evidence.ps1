[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][guid]$TenantId,
    [Parameter(Mandatory = $true)][ValidateSet("PowerPlatform")][string]$Service,
    [Parameter(Mandatory = $true)][string]$OutputPath,
    [ValidateSet("Auto", "Interactive", "Browser", "DeviceCode")][string]$Login = "Auto"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$output = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $output) { throw "Existing export must not be overwritten." }

$reads = [Collections.Generic.List[object]]::new()
$verified = $false
$version = "not_installed"

function Read-Property($Object, [string]$Name) {
    if ($null -eq $Object) { return $null }
    $property = $Object.PSObject.Properties[$Name]
    if ($null -ne $property) { return $property.Value }
    return $null
}

function Resolve-LoginMode([string]$Mode) {
    if ($Mode -ne "Auto") { return $Mode }
    $headless = $env:CODESPACES -or $env:SSH_CONNECTION -or $env:SSH_TTY -or -not [Environment]::UserInteractive -or (
        $PSVersionTable.PSEdition -eq "Core" -and -not $IsWindows -and -not $env:DISPLAY -and -not $env:WAYLAND_DISPLAY
    )
    if ($headless) { return "DeviceCode" }
    return "Interactive"
}

function Error-Reason($Record) {
    if ($Record.CategoryInfo.Category -eq "PermissionDenied") { return "permission_denied" }
    if ($Record.Exception -is [NotSupportedException]) { return "feature_unavailable" }
    $response = Read-Property $Record.Exception "Response"
    $status = Read-Property $response "StatusCode"
    if ($null -ne $status) {
        if ([int]$status -in @(401, 403)) { return "permission_denied" }
        if ([int]$status -in @(404, 405, 501)) { return "feature_unavailable" }
    }
    if ($Record.Exception -is [Management.Automation.CommandNotFoundException]) { return "feature_unavailable" }
    return "error"
}

function Failed-Read([string]$Source, [string]$Command, [string]$Reason, [string]$Detail) {
    $reads.Add([ordered]@{
        source = $Source; command = $Command; module_version = $version
        scope = "separate administrator read; unavailable or incomplete"
        completed = $false; object_count = $null; reason = $Reason; detail = $Detail
        observed_at = [datetimeoffset]::UtcNow.ToString("o")
    })
}

function Invoke-Read([scriptblock]$Operation) {
    for ($attempt = 0; $attempt -lt 4; $attempt++) {
        try { return & $Operation } catch {
            $response = Read-Property $_.Exception "Response"
            $status = Read-Property $response "StatusCode"
            if ($null -eq $status -or [int]$status -notin @(429, 500, 502, 503, 504) -or $attempt -eq 3) {
                throw
            }
            Write-Warning "Transient read failure; retrying the same official read command."
            Start-Sleep -Seconds ([math]::Pow(2, $attempt))
        }
    }
}

$pairs = @(
    @("powerplatform.environment_roles", "Get-AdminPowerAppEnvironmentRoleAssignment"),
    @("powerplatform.dlp_policies", "Get-AdminDlpPolicy")
)
$ready = $false
try {
    Import-Module Microsoft.PowerApps.Administration.PowerShell -MinimumVersion 2.0.220 -ErrorAction Stop
    $version = (Get-Module Microsoft.PowerApps.Administration.PowerShell).Version.ToString()
    $ready = $true
} catch {
    foreach ($pair in $pairs) {
        Failed-Read $pair[0] $pair[1] "feature_unavailable" ("Official module unavailable: " + $_.Exception.GetType().Name)
    }
}
if ($ready) {
    try {
        $mode = Resolve-LoginMode $Login
        if ($mode -eq "DeviceCode") {
            throw [NotSupportedException]::new("The official Power Apps module has no device-code sign-in; use -Login Browser or Interactive on a desktop terminal.")
        }
        Add-PowerAppsAccount -Endpoint prod -TenantID $TenantId.ToString() -UseSystemBrowser:($mode -eq "Browser") -ErrorAction Stop | Out-Null
        $verified = $true
    } catch {
        foreach ($pair in $pairs) {
            Failed-Read $pair[0] $pair[1] (Error-Reason $_) ("Administrator login failed: " + $_.Exception.GetType().Name)
        }
    }
    if ($verified) {
        foreach ($pair in $pairs) {
            try {
                $command = $pair[1]
                $rows = @(Invoke-Read { & $command -ErrorAction Stop })
                $scope = if ($pair[0] -eq "powerplatform.environment_roles") {
                    "administrator-visible non-Dataverse environment role assignments; not unique Maker users"
                } else { "DLP policy objects returned by the official tenant administrator cmdlet" }
                $reads.Add([ordered]@{
                    source = $pair[0]; command = $command; module_version = $version
                    scope = $scope; completed = $true; object_count = $rows.Count
                    observed_at = [datetimeoffset]::UtcNow.ToString("o")
                    detail = "Object count only; connector classifications, group members and policy effectiveness not inferred. No people or policy content exported."
                })
            } catch {
                Failed-Read $pair[0] $pair[1] (Error-Reason $_) ("Official read failed: " + $_.Exception.GetType().Name)
            }
        }
    }
}

$packet = [ordered]@{
    schema_version = 1; source_type = "official_admin_read"; tenant_id = $TenantId.ToString()
    tenant_verified = $verified; exported_at = [datetimeoffset]::UtcNow.ToString("o"); reads = @($reads.ToArray())
}
$parent = [IO.Path]::GetDirectoryName($output)
[void][IO.Directory]::CreateDirectory($parent)
[IO.File]::WriteAllText($output, ($packet | ConvertTo-Json -Depth 10), [Text.UTF8Encoding]::new($false))
Write-Output ("Administrator read export saved: " + $output)
if (@($reads | Where-Object { -not $_.completed }).Count -gt 0) { exit 2 }
exit 0
