param(
    [string]$SingBoxVersion,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$VersionFile = Join-Path $Root "SING_BOX_VERSION"
$BinDir = Join-Path $Root "bin"
$SingBoxExe = Join-Path $BinDir "sing-box.exe"
$DownloadDir = Join-Path $Root "build\deps"

function Get-PinnedSingBoxVersion {
    if ($SingBoxVersion) {
        return $SingBoxVersion.Trim().TrimStart("v")
    }
    if (-not (Test-Path $VersionFile)) {
        throw "SING_BOX_VERSION was not found."
    }
    return (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim().TrimStart("v")
}

function Get-InstalledSingBoxVersion {
    if (-not (Test-Path $SingBoxExe)) {
        return ""
    }
    try {
        $output = & $SingBoxExe version 2>$null | Select-Object -First 1
        if ($output -match 'sing-box version\s+([0-9]+\.[0-9]+\.[0-9]+)') {
            return $Matches[1]
        }
    } catch {
        return ""
    }
    return ""
}

function Invoke-GitHubJson {
    param([string]$Url)
    $headers = @{ "User-Agent" = "OutwardAppDependencyInstaller" }
    return Invoke-RestMethod -Uri $Url -Headers $headers
}

$pinnedVersion = Get-PinnedSingBoxVersion
$installedVersion = Get-InstalledSingBoxVersion
if ((-not $Force) -and $installedVersion -eq $pinnedVersion) {
    Write-Host "sing-box $pinnedVersion already installed: $SingBoxExe"
    return
}

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null

$releaseUrl = "https://api.github.com/repos/SagerNet/sing-box/releases/tags/v$pinnedVersion"
Write-Host "Resolving sing-box v$pinnedVersion from $releaseUrl"
$release = Invoke-GitHubJson -Url $releaseUrl
$asset = $release.assets | Where-Object { $_.name -match 'windows-amd64.*\.zip$' } | Select-Object -First 1
if (-not $asset) {
    throw "Could not find sing-box windows-amd64 zip asset for v$pinnedVersion."
}

$zipPath = Join-Path $DownloadDir $asset.name
$extractDir = Join-Path $DownloadDir "sing-box-$pinnedVersion"
Write-Host "Downloading $($asset.name)"
Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -Headers @{ "User-Agent" = "OutwardAppDependencyInstaller" }

if (Test-Path $extractDir) {
    Remove-Item -LiteralPath $extractDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $extractDir | Out-Null
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

$downloadedExe = Get-ChildItem -LiteralPath $extractDir -Recurse -Filter "sing-box.exe" | Select-Object -First 1
if (-not $downloadedExe) {
    throw "Downloaded sing-box archive did not contain sing-box.exe."
}

Copy-Item -LiteralPath $downloadedExe.FullName -Destination $SingBoxExe -Force
$finalVersion = Get-InstalledSingBoxVersion
if ($finalVersion -ne $pinnedVersion) {
    throw "Installed sing-box version mismatch. Expected $pinnedVersion, got $finalVersion."
}

Write-Host "Installed sing-box ${finalVersion}: $SingBoxExe"

