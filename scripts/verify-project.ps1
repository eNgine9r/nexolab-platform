[CmdletBinding()]
param(
    [ValidateSet("Frontend", "Telemetry", "DeviceAgent", "All")]
    [string]$Component = "All",
    [switch]$InstallDependencies,
    [switch]$SkipBuild,
    [switch]$FullFormatCheck,
    [switch]$IncludeComposeValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Step {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][scriptblock]$Command
    )

    Write-Host "`n==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Verification step failed: $Name (exit code $LASTEXITCODE)"
    }
}

function Get-ChangedPrettierFiles {
    param([string]$BaseRef = "origin/main")

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git is not available in PATH."
    }

    & git rev-parse --verify $BaseRef *> $null
    if ($LASTEXITCODE -ne 0) {
        $BaseRef = "HEAD~1"
    }

    $changedFiles = @(& git diff --name-only --diff-filter=ACMRT "$BaseRef...HEAD")
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to determine files changed against $BaseRef."
    }

    $supportedExtensions = @(
        ".cjs",
        ".css",
        ".html",
        ".js",
        ".json",
        ".jsx",
        ".md",
        ".mdx",
        ".mjs",
        ".scss",
        ".ts",
        ".tsx",
        ".yaml",
        ".yml"
    )

    return @(
        $changedFiles |
            Where-Object {
                (Test-Path $_ -PathType Leaf) -and
                ($supportedExtensions -contains [System.IO.Path]::GetExtension($_).ToLowerInvariant())
            }
    )
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot

try {
    if ($Component -in @("Frontend", "All")) {
        if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
            throw "npm is not available in PATH."
        }

        if ($InstallDependencies) {
            Invoke-Step "Install frontend dependencies" { npm ci }
        }

        if ($FullFormatCheck) {
            Invoke-Step "Full repository format check" { npm run format:check }
        }
        else {
            $formatFiles = @(Get-ChangedPrettierFiles)
            if ($formatFiles.Count -gt 0) {
                Invoke-Step "Format check for changed files" {
                    & npm exec prettier -- --check @formatFiles
                }
            }
            else {
                Write-Host "`n==> Format check for changed files"
                Write-Host "No Prettier-supported files changed against origin/main."
            }
        }

        Invoke-Step "Frontend lint" { npm run lint }
        Invoke-Step "Frontend typecheck" { npm run typecheck }
        Invoke-Step "Frontend tests" { npm test }

        if (-not $SkipBuild) {
            Invoke-Step "Frontend production build" { npm run build }
        }
    }

    if ($Component -in @("Telemetry", "All")) {
        if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
            throw "Python is not available in PATH."
        }

        Push-Location "services/telemetry-service"
        try {
            if ($InstallDependencies) {
                Invoke-Step "Install telemetry-service dependencies" { python -m pip install -r requirements-dev.txt }
            }

            Invoke-Step "Telemetry-service compile check" { python -m compileall -q app tests migrations }
            Invoke-Step "Telemetry-service tests" { python -m pytest -q }
        }
        finally {
            Pop-Location
        }
    }

    if ($Component -in @("DeviceAgent", "All")) {
        if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
            throw "Python is not available in PATH."
        }

        Push-Location "services/device-agent"
        try {
            if ($InstallDependencies) {
                Invoke-Step "Install device-agent dependencies" { python -m pip install -r requirements.txt }
            }

            $compileTargets = @()
            foreach ($candidate in @("app", "tests", "migrations")) {
                if (Test-Path $candidate) {
                    $compileTargets += $candidate
                }
            }

            if ($compileTargets.Count -gt 0) {
                Invoke-Step "Device-agent compile check" { python -m compileall -q @compileTargets }
            }

            if (Test-Path "tests") {
                Invoke-Step "Device-agent tests" { python -m pytest -q }
            }
        }
        finally {
            Pop-Location
        }
    }

    if ($IncludeComposeValidation) {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            throw "Docker is not available in PATH."
        }

        Push-Location "infrastructure/compose"
        try {
            $composeFiles = Get-ChildItem -File -Filter "compose*.yaml"
            foreach ($composeFile in $composeFiles) {
                Invoke-Step "Validate $($composeFile.Name)" {
                    docker compose -f $composeFile.Name config --quiet
                }
            }
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "`nAll requested NEXOLAB verification steps passed."
    Write-Host "Note: software checks do not replace real hardware, offline, backup/restore or controlled-site acceptance evidence."
    if (-not $FullFormatCheck) {
        Write-Host "Formatting was checked only for files changed against origin/main. Use -FullFormatCheck for the repository-wide debt audit."
    }
}
finally {
    Pop-Location
}
