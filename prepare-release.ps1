[CmdletBinding()]
param(
    [string]$Version,
    [switch]$DryRun,
    [switch]$Resume
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$VersionFile = Join-Path $Root "VERSION"
$BuildScript = Join-Path $Root "build-installer.ps1"

function Invoke-Git {
    param([string[]]$Arguments)

    $output = & git -C $Root @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed (exit $LASTEXITCODE)."
    }
    return $output
}

function ConvertTo-AppVersion {
    param([string]$Value)

    if ($Value -notmatch '^\d+\.\d+\.\d+(\.\d+)?$') {
        throw "Version must use format 1.2.3 or 1.2.3.4. Current value: $Value"
    }
    foreach ($part in $Value.Split('.')) {
        if ([long]$part -gt 65535) {
            throw "Windows version components must be between 0 and 65535: $Value"
        }
    }
    return [version]$Value
}

Push-Location -LiteralPath $Root
try {
    Get-Command git -ErrorAction Stop | Out-Null
    if (-not (Test-Path -LiteralPath $BuildScript -PathType Leaf)) {
        throw "build-installer.ps1 was not found."
    }
    $repoRoot = Invoke-Git -Arguments @('rev-parse', '--show-toplevel')
    if ([IO.Path]::GetFullPath($repoRoot) -ne [IO.Path]::GetFullPath($Root)) {
        throw "The release script must be located at the Git repository root."
    }
    $branch = Invoke-Git -Arguments @('symbolic-ref', '--quiet', '--short', 'HEAD')
    $head = Invoke-Git -Arguments @('log', '-1', '--format=%h %s')
    $conflicts = Invoke-Git -Arguments @('ls-files', '--unmerged')
    if ($conflicts) {
        throw "Resolve Git conflicts before preparing a release."
    }

    $currentVersion = (Get-Content -LiteralPath $VersionFile -Raw).Trim()
    $current = ConvertTo-AppVersion -Value $currentVersion
    $headVersion = (Invoke-Git -Arguments @('show', 'HEAD:VERSION')).Trim()
    $committed = ConvertTo-AppVersion -Value $headVersion
    $status = @(Invoke-Git -Arguments @('status', '--short', '--untracked-files=all'))

    if ($Resume) {
        if ($Version) {
            throw "Use -Resume without -Version."
        }
        $subject = Invoke-Git -Arguments @('log', '-1', '--format=%s')
        if ($status.Count -gt 0 -or $subject -ne "Release v$currentVersion" -or $currentVersion -ne $headVersion) {
            throw "-Resume requires a clean working tree and HEAD named 'Release v$currentVersion'."
        }
        $Version = $currentVersion
    } else {
        if ($current -lt $committed) {
            throw "VERSION is older than HEAD:VERSION ($headVersion). Restore or update it first."
        }
        if (-not $Version) {
            if ($current -gt $committed) {
                # Respect a version already prepared by build-installer.bat or by hand.
                $Version = $currentVersion
            } else {
                $parts = $currentVersion.Split('.')
                $parts[2] = [string]([int]$parts[2] + 1)
                $Version = $parts -join '.'
            }
        }
        $next = ConvertTo-AppVersion -Value $Version
        if ($next -le $committed -or $next -lt $current) {
            throw "Release version must be newer than HEAD:VERSION ($headVersion) and at least VERSION ($currentVersion)."
        }
        $existingTag = Invoke-Git -Arguments @('tag', '--list', "v$Version")
        if ($existingTag) {
            throw "Local tag v$Version already exists. Choose a newer -Version."
        }
    }

    Write-Host "Branch: $branch"
    Write-Host "Current commit: $head"
    Write-Host "VERSION: $currentVersion"
    Write-Host "Release commit: Release v$Version"
    Write-Host "Build: build-installer.ps1 -NoVersionBump"
    if (-not $Resume) {
        Write-Host "All non-ignored changes will be included:"
        $status | ForEach-Object { Write-Host $_ }
    }
    if ($DryRun) {
        Write-Host "Preview only. No files, commits or build artifacts were changed."
        return
    }

    if (-not $Resume) {
        # Check identity before modifying VERSION or the index.
        Invoke-Git -Arguments @('var', 'GIT_AUTHOR_IDENT') | Out-Null
        Invoke-Git -Arguments @('var', 'GIT_COMMITTER_IDENT') | Out-Null
        Set-Content -LiteralPath $VersionFile -Value $Version -Encoding ASCII
        Invoke-Git -Arguments @('add', '--all') | Out-Null
        Invoke-Git -Arguments @('commit', '-m', "Release v$Version") | ForEach-Object { Write-Host $_ }
    }

    # A separate process gives a terminating build error a reliable exit code.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $BuildScript -NoVersionBump
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed. Release commit was kept. Fix the build environment and run .\prepare-release.ps1 -Resume, or rebuild with .\build-installer-check.bat."
    }
    Write-Host "Release v$Version is ready. Run git push origin $branch when ready."
} finally {
    Pop-Location
}
