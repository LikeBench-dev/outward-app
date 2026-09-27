param(
    [string]$Version,
    [switch]$NoVersionBump,
    [switch]$PublishRelease,
    [string]$Repository = "LikeBench-dev/outward-app",
    [string]$ReleaseNotesFile,
    [switch]$DraftRelease,
    [switch]$Prerelease
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$AppInfoFile = Join-Path $Root "outward_app\app_info.py"
$AppNameLine = Get-Content -LiteralPath $AppInfoFile | Where-Object { $_ -match '^APP_NAME\s*=\s*"(.+)"' } | Select-Object -First 1
if (-not $AppNameLine) {
    throw "APP_NAME was not found in outward_app\app_info.py."
}
$AppName = [regex]::Match($AppNameLine, '^APP_NAME\s*=\s*"(.+)"').Groups[1].Value
$AppExeName = "$AppName.exe"
$VersionFile = Join-Path $Root "VERSION"
$DistExe = Join-Path $Root "dist\$AppExeName"
$InstallerScript = Join-Path $Root "installer\OutwardApp.iss"
$VersionInfoFile = Join-Path $Root "build\version_info.txt"
$InstallDepsScript = Join-Path $Root "install-deps.ps1"
$SingBoxVersionFile = Join-Path $Root "SING_BOX_VERSION"
$DefaultReleaseNotesFile = Join-Path $Root "release-notes.md"

function Resolve-Python {
    $candidates = @(
        (Join-Path $Root ".venv\Scripts\python.exe"),
        (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    throw "Python was not found. Install Python 3 or create .venv in the project folder."
}

function Resolve-InnoCompiler {
    $command = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    throw "Inno Setup Compiler was not found. Install Inno Setup 6: https://jrsoftware.org/isdl.php"
}


function Get-PinnedSingBoxVersion {
    if (-not (Test-Path $SingBoxVersionFile)) {
        throw "SING_BOX_VERSION was not found."
    }
    return (Get-Content -LiteralPath $SingBoxVersionFile -TotalCount 1).Trim().TrimStart("v")
}

function Get-InstalledSingBoxVersion {
    $singBoxExe = Join-Path $Root "bin\sing-box.exe"
    if (-not (Test-Path $singBoxExe)) {
        return ""
    }
    try {
        $output = & $singBoxExe version 2>$null | Select-Object -First 1
        if ($output -match 'sing-box version\s+([0-9]+\.[0-9]+\.[0-9]+)') {
            return $Matches[1]
        }
    } catch {
        return ""
    }
    return ""
}

function Ensure-SingBoxDependency {
    $pinnedVersion = Get-PinnedSingBoxVersion
    $installedVersion = Get-InstalledSingBoxVersion
    if ($installedVersion -eq $pinnedVersion) {
        Write-Host "sing-box dependency: $installedVersion"
        return
    }
    if (-not (Test-Path $InstallDepsScript)) {
        throw "install-deps.ps1 was not found. Cannot install sing-box $pinnedVersion."
    }
    Write-Host "Installing sing-box dependency $pinnedVersion..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File $InstallDepsScript -SingBoxVersion $pinnedVersion
    if ($LASTEXITCODE -ne 0) {
        throw "install-deps.ps1 failed."
    }
}

function Resolve-GitHubCli {
    $command = Get-Command "gh.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $command = Get-Command "gh" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "GitHub CLI was not found. Install it from https://cli.github.com/ and run gh auth login, or build without -PublishRelease."
}

function Test-AppVersion {
    param([string]$AppVersion)
    return $AppVersion -match '^\d+\.\d+\.\d+(\.\d+)?$'
}

function Get-NextPatchVersion {
    param([string]$CurrentVersion)

    if (-not (Test-AppVersion -AppVersion $CurrentVersion)) {
        throw "Version must use format 1.2.3 or 1.2.3.4. Current value: $CurrentVersion"
    }

    $parts = New-Object System.Collections.Generic.List[int]
    foreach ($part in $CurrentVersion.Split(".")) {
        $parts.Add([int]$part)
    }

    $parts[2] = $parts[2] + 1
    return ($parts -join ".")
}

function Write-VersionInfo {
    param([string]$AppVersion)

    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $VersionInfoFile) | Out-Null
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($part in $AppVersion.Split(".")) {
        $parts.Add($part)
    }
    while ($parts.Count -lt 4) {
        $parts.Add("0")
    }
    $commaVersion = $parts -join ", "

    $versionInfo = @"
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($commaVersion),
    prodvers=($commaVersion),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', ''),
        StringStruct('FileDescription', ''),
        StringStruct('FileVersion', '$AppVersion'),
        StringStruct('InternalName', ''),
        StringStruct('OriginalFilename', ''),
        StringStruct('ProductName', ''),
        StringStruct('ProductVersion', '$AppVersion')])
      ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@

    Set-Content -LiteralPath $VersionInfoFile -Value $versionInfo -Encoding UTF8
}

function Write-ReleaseArtifacts {
    param(
        [string]$InstallerPath,
        [string]$AppVersion
    )

    $installerName = Split-Path -Leaf $InstallerPath
    $outputDir = Split-Path -Parent $InstallerPath
    $checksumFile = Join-Path $outputDir "$installerName.sha256"
    $releaseNotesOutput = Join-Path $outputDir "release-notes-$AppVersion.md"
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $InstallerPath).Hash.ToLowerInvariant()
    $checksumLine = "$hash  $installerName"

    Set-Content -LiteralPath $checksumFile -Value $checksumLine -Encoding ASCII

    $notesPrefix = "# $AppName $AppVersion`r`n`r`n"
    $notesSourceFile = $ReleaseNotesFile
    if (-not $notesSourceFile -and (Test-Path $DefaultReleaseNotesFile)) {
        $notesSourceFile = $DefaultReleaseNotesFile
    }

    if ($notesSourceFile) {
        if (-not (Test-Path $notesSourceFile)) {
            throw "Release notes file was not found: $notesSourceFile"
        }

        $notesSource = (Get-Content -LiteralPath $notesSourceFile -Raw -Encoding UTF8).Trim()
        if ($notesSource) {
            if ($ReleaseNotesFile) {
                $notesPrefix = $notesSource.TrimEnd() + "`r`n`r`n"
            } else {
                $notesBody = [regex]::Replace($notesSource, '^\s*# .+?(\r?\n)+', '')
                $notesPrefix = "# $AppName $AppVersion`r`n`r`n" + $notesBody.TrimEnd() + "`r`n`r`n"
            }
        }
    }

    $notes = $notesPrefix + "## SHA256`r`n`r`n$checksumLine`r`n"
    Set-Content -LiteralPath $releaseNotesOutput -Value $notes -Encoding UTF8

    return [PSCustomObject]@{
        Installer = $InstallerPath
        ChecksumFile = $checksumFile
        ReleaseNotesFile = $releaseNotesOutput
        Sha256 = $hash
    }
}

function Publish-GitHubRelease {
    param(
        [string]$Tag,
        [string]$AppVersion,
        [object]$Artifacts
    )

    $gh = Resolve-GitHubCli
    Write-Host "GitHub CLI: $gh"
    Write-Host "Release repository: $Repository"
    Write-Host "Release tag: $Tag"

    & $gh auth status --hostname github.com | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated. Run gh auth login first."
    }

    & $gh release view $Tag --repo $Repository *> $null
    $releaseExists = $LASTEXITCODE -eq 0

    if ($releaseExists) {
        Write-Host "Updating existing GitHub Release..."
        & $gh release edit $Tag --repo $Repository --title "$AppName $AppVersion" --notes-file $Artifacts.ReleaseNotesFile
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to update GitHub Release $Tag."
        }
        & $gh release upload $Tag $Artifacts.Installer $Artifacts.ChecksumFile --repo $Repository --clobber
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to upload release artifacts to $Tag."
        }
    } else {
        Write-Host "Creating GitHub Release..."
        $createArgs = @(
            "release", "create", $Tag,
            $Artifacts.Installer,
            $Artifacts.ChecksumFile,
            "--repo", $Repository,
            "--title", "$AppName $AppVersion",
            "--notes-file", $Artifacts.ReleaseNotesFile
        )
        if ($DraftRelease) {
            $createArgs += "--draft"
        }
        if ($Prerelease) {
            $createArgs += "--prerelease"
        }
        & $gh @createArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to create GitHub Release $Tag."
        }
    }
}

if (-not (Test-Path $VersionFile)) {
    throw "VERSION file was not found."
}

$currentVersion = (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim()
if (-not (Test-AppVersion -AppVersion $currentVersion)) {
    throw "VERSION must use format 1.2.3 or 1.2.3.4. Current value: $currentVersion"
}

if ([string]::IsNullOrWhiteSpace($Version)) {
    if ($NoVersionBump) {
        $Version = $currentVersion
    } else {
        $Version = Get-NextPatchVersion -CurrentVersion $currentVersion
    }
}

if (-not (Test-AppVersion -AppVersion $Version)) {
    throw "Version must use format 1.2.3 or 1.2.3.4. Current value: $Version"
}

Set-Content -LiteralPath $VersionFile -Value $Version -Encoding ASCII

Ensure-SingBoxDependency

if (-not (Test-Path (Join-Path $Root "assets\outward.ico"))) {
    throw "assets\outward.ico was not found."
}

$python = Resolve-Python
$innoCompiler = Resolve-InnoCompiler

Write-Host "Previous version: $currentVersion"
Write-Host "Build version: $Version"
Write-Host "Python: $python"
Write-Host "Inno Setup: $innoCompiler"

Write-VersionInfo -AppVersion $Version

Write-Host "Building application exe..."
& $python -m PyInstaller --clean --noconfirm (Join-Path $Root "OutwardApp.spec")

if (-not (Test-Path $DistExe)) {
    throw "PyInstaller did not create $DistExe"
}

Write-Host "Building installer..."
& $innoCompiler "/DProjectRoot=$Root" "/DAppVersion=$Version" "/DAppName=$AppName" $InstallerScript

$installer = Join-Path $Root "installer-output\$AppName Setup-$Version.exe"
if (-not (Test-Path $installer)) {
    throw "Inno Setup did not create $installer"
}

$releaseArtifacts = Write-ReleaseArtifacts -InstallerPath $installer -AppVersion $Version
Write-Host "SHA256: $($releaseArtifacts.Sha256)"
Write-Host "Checksum: $($releaseArtifacts.ChecksumFile)"
Write-Host "Release notes: $($releaseArtifacts.ReleaseNotesFile)"

if ($PublishRelease) {
    Publish-GitHubRelease -Tag "v$Version" -AppVersion $Version -Artifacts $releaseArtifacts
}

Write-Host ""
Write-Host "Done: $installer"

