[CmdletBinding()]
param(
    [switch]$SkipExternalTools,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Write-Step {
    param([Parameter(Mandatory = $true)][string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Install-WinGetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$DisplayName
    )
    Write-Step "Installing or updating $DisplayName"
    Invoke-Checked -Executable "winget.exe" -Description "WinGet installation of $DisplayName" -Arguments @(
        "install",
        "--id", $Id,
        "--exact",
        "--source", "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--silent",
        "--disable-interactivity"
    )
}

function Resolve-UvExecutable {
    $command = Get-Command "uv.exe" -ErrorAction SilentlyContinue
    if ($null -ne $command) {
        return $command.Source
    }
    $candidates = @(
        (Join-Path $env:USERPROFILE ".local\bin\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\uv.exe"),
        (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\uv.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }
    throw "uv was installed but is not visible yet. Close PowerShell, open it again, and rerun this script."
}

function Find-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($null -ne $command -and (Test-Path -LiteralPath $command.Source -PathType Leaf)) {
        return $command.Source
    }
    $winGetCandidate = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\$Name"
    if (Test-Path -LiteralPath $winGetCandidate -PathType Leaf) {
        return $winGetCandidate
    }
    return $null
}

function Install-FluidSynth {
    $installRoot = Join-Path $env:LOCALAPPDATA "MusicWaterfall\tools\fluidsynth"
    $installedExecutable = Join-Path $installRoot "bin\fluidsynth.exe"
    if (Test-Path -LiteralPath $installedExecutable -PathType Leaf) {
        Write-Host "FluidSynth is already installed at $installedExecutable"
        return $installedExecutable
    }
    if (Test-Path -LiteralPath $installRoot) {
        throw "FluidSynth has an incomplete install at $installRoot. Rename that exact directory and rerun the installer."
    }

    Write-Step "Downloading the current official FluidSynth Windows x64 release"
    $headers = @{
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "Music-Waterfall-Windows-Installer"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/FluidSynth/fluidsynth/releases/latest" -Headers $headers
    $asset = $release.assets |
        Where-Object { $_.name -match "(?i)win.*x64.*\.zip$" } |
        Select-Object -First 1
    if ($null -eq $asset) {
        throw "The current FluidSynth release has no recognized Windows x64 ZIP asset."
    }
    if ([string]::IsNullOrWhiteSpace([string]$asset.digest) -or $asset.digest -notmatch "^sha256:(?<hash>[0-9a-fA-F]{64})$") {
        throw "GitHub did not provide a SHA-256 digest for $($asset.name); the installer will not use an unverified archive."
    }

    $expectedHash = $Matches.hash.ToUpperInvariant()
    $systemTempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
    $stage = Join-Path $systemTempRoot ("music-waterfall-fluidsynth-" + [guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        $archive = Join-Path $stage $asset.name
        Invoke-WebRequest -Uri $asset.browser_download_url -Headers $headers -OutFile $archive
        $actualHash = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToUpperInvariant()
        if ($actualHash -ne $expectedHash) {
            throw "FluidSynth archive checksum mismatch. Expected $expectedHash, received $actualHash."
        }

        $expanded = Join-Path $stage "expanded"
        Expand-Archive -LiteralPath $archive -DestinationPath $expanded
        $payloadExecutable = Get-ChildItem -LiteralPath $expanded -Filter "fluidsynth.exe" -File -Recurse |
            Select-Object -First 1
        if ($null -eq $payloadExecutable) {
            throw "The verified FluidSynth archive did not contain fluidsynth.exe."
        }
        $payloadRoot = $payloadExecutable.Directory.Parent.FullName
        $toolsParent = Split-Path -Parent $installRoot
        New-Item -ItemType Directory -Force -Path $toolsParent | Out-Null
        Move-Item -LiteralPath $payloadRoot -Destination $installRoot
    }
    finally {
        $resolvedStage = [System.IO.Path]::GetFullPath($stage)
        if ($resolvedStage.StartsWith($systemTempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and
            (Test-Path -LiteralPath $resolvedStage)) {
            Remove-Item -LiteralPath $resolvedStage -Recurse -Force
        }
    }

    if (-not (Test-Path -LiteralPath $installedExecutable -PathType Leaf)) {
        throw "FluidSynth installation did not create $installedExecutable."
    }
    Write-Host "Installed FluidSynth $($release.tag_name) with verified SHA-256 $expectedHash"
    return $installedExecutable
}

if ($env:OS -ne "Windows_NT") {
    throw "This installer supports Windows 11 only."
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$repoRoot = [System.IO.Path]::GetFullPath($repoRoot)
if (-not (Test-Path -LiteralPath (Join-Path $repoRoot "pyproject.toml") -PathType Leaf)) {
    throw "Run this script from a complete Music Waterfall repository checkout."
}

$winGetLinks = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links"
if (Test-Path -LiteralPath $winGetLinks) {
    $pathEntries = $env:PATH -split ";"
    if ($pathEntries -notcontains $winGetLinks) {
        $env:PATH = "$winGetLinks;$env:PATH"
    }
}

$fluidSynthPath = $null
if (-not $SkipExternalTools) {
    if ($null -eq (Get-Command "winget.exe" -ErrorAction SilentlyContinue)) {
        throw "WinGet is required. Install or repair Microsoft App Installer, then rerun this script."
    }
    Install-WinGetPackage -Id "astral-sh.uv" -DisplayName "uv"
    Install-WinGetPackage -Id "Gyan.FFmpeg" -DisplayName "FFmpeg and FFprobe"
    Install-WinGetPackage -Id "audiveris.org.Audiveris" -DisplayName "Audiveris"
    Install-WinGetPackage -Id "Musescore.Musescore" -DisplayName "MuseScore Studio"
    $fluidSynthPath = Install-FluidSynth
}

$uv = Resolve-UvExecutable
Push-Location -LiteralPath $repoRoot
try {
    Write-Step "Installing Python 3.12 and the locked Music Waterfall environment"
    & $uv "python" "find" "3.12" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Python 3.12 is already available to uv."
    }
    else {
        Invoke-Checked -Executable $uv -Description "Python 3.12 installation" -Arguments @(
            "python", "install", "3.12"
        )
    }
    Invoke-Checked -Executable $uv -Description "Locked dependency synchronization" -Arguments @("sync", "--locked", "--all-groups")

    if ($null -ne $fluidSynthPath) {
        Invoke-Checked -Executable $uv -Description "FluidSynth path configuration" -Arguments @(
            "run", "music-waterfall", "set-tool", "fluidsynth", $fluidSynthPath
        )
    }

    $ffmpegPath = Find-CommandPath -Name "ffmpeg.exe"
    $ffprobePath = Find-CommandPath -Name "ffprobe.exe"
    if ($null -ne $ffmpegPath) {
        Invoke-Checked -Executable $uv -Description "FFmpeg path configuration" -Arguments @(
            "run", "music-waterfall", "set-tool", "ffmpeg", $ffmpegPath
        )
    }
    if ($null -ne $ffprobePath) {
        Invoke-Checked -Executable $uv -Description "FFprobe path configuration" -Arguments @(
            "run", "music-waterfall", "set-tool", "ffprobe", $ffprobePath
        )
    }

    $soundFontCandidates = @(
        (Join-Path $env:ProgramFiles "MuseScore 4\sound\MS Basic.sf3")
    )
    foreach ($soundFontPath in $soundFontCandidates) {
        if (Test-Path -LiteralPath $soundFontPath -PathType Leaf) {
            Invoke-Checked -Executable $uv -Description "SoundFont path configuration" -Arguments @(
                "run", "music-waterfall", "set-tool", "soundfont", $soundFontPath
            )
            break
        }
    }

    Write-Step "Checking the complete local media toolchain"
    Invoke-Checked -Executable $uv -Description "Music Waterfall doctor" -Arguments @(
        "run", "music-waterfall", "doctor"
    )

    if (-not $SkipTests) {
        Write-Step "Running code and media validation"
        Invoke-Checked -Executable $uv -Description "Ruff" -Arguments @(
            "run", "ruff", "check", "src", "tests"
        )
        Invoke-Checked -Executable $uv -Description "Ruff format check" -Arguments @(
            "run", "ruff", "format", "--check", "src", "tests"
        )
        Invoke-Checked -Executable $uv -Description "Pytest" -Arguments @(
            "run", "pytest", "-q"
        )
        Invoke-Checked -Executable $uv -Description "Package build" -Arguments @("build")
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Music Waterfall is ready." -ForegroundColor Green
Write-Host "Launch it from $repoRoot with: uv run music-waterfall-gui"
