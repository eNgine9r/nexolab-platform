[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateRange(1, 2147483647)]
    [int]$Issue,

    [string]$Title = "",
    [string]$BaseBranch = "main",
    [string]$WorktreeRoot = "",
    [switch]$NoFetch,
    [switch]$InstallDependencies,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Git {
    param(
        [Parameter(Mandatory)][string[]]$Arguments,
        [switch]$AllowFailure
    )

    & git -C $script:RepoRoot @Arguments
    $exitCode = $LASTEXITCODE

    if (-not $AllowFailure -and $exitCode -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $exitCode."
    }

    return $exitCode
}

function ConvertTo-Slug {
    param([Parameter(Mandatory)][string]$Value)

    $slug = $Value.ToLowerInvariant()
    $slug = [regex]::Replace($slug, "[^a-z0-9]+", "-")
    $slug = $slug.Trim("-")

    if ([string]::IsNullOrWhiteSpace($slug)) {
        return "work-package"
    }

    if ($slug.Length -gt 48) {
        $slug = $slug.Substring(0, 48).TrimEnd("-")
    }

    return $slug
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is not available in PATH."
}

$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$repoRootResolved = [string](& git -C $script:RepoRoot rev-parse --show-toplevel)
$repoRootResolved = $repoRootResolved.Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($repoRootResolved)) {
    throw "Unable to resolve the NEXOLAB repository root."
}
$script:RepoRoot = $repoRootResolved

if ([string]::IsNullOrWhiteSpace($Title) -and (Get-Command gh -ErrorAction SilentlyContinue)) {
    try {
        $resolvedTitle = [string](& gh issue view $Issue --repo eNgine9r/nexolab-platform --json title --jq .title 2>$null)
        $resolvedTitle = $resolvedTitle.Trim()
        if ($LASTEXITCODE -eq 0 -and -not [string]::IsNullOrWhiteSpace($resolvedTitle)) {
            $Title = $resolvedTitle
        }
    }
    catch {
        # GitHub CLI lookup is optional; fall back to a stable local name.
    }
}

if ([string]::IsNullOrWhiteSpace($Title)) {
    $Title = "work-package"
}

$slug = ConvertTo-Slug -Value $Title
$branchName = "work/$Issue-$slug"

if ([string]::IsNullOrWhiteSpace($WorktreeRoot)) {
    $repoParent = Split-Path -Parent $script:RepoRoot
    $WorktreeRoot = Join-Path $repoParent "nexolab-worktrees"
}

$worktreePath = Join-Path $WorktreeRoot "$Issue-$slug"
$worktreePath = [System.IO.Path]::GetFullPath($worktreePath)

Write-Host "NEXOLAB Work Package"
Write-Host "  Issue:     #$Issue"
Write-Host "  Title:     $Title"
Write-Host "  Branch:    $branchName"
Write-Host "  Base:      $BaseBranch"
Write-Host "  Worktree:  $worktreePath"

if (-not $NoFetch) {
    if ($DryRun) {
        Write-Host "[DRY RUN] git fetch origin $BaseBranch --prune"
    }
    else {
        Write-Host "Fetching origin/$BaseBranch..."
        Invoke-Git -Arguments @("fetch", "origin", $BaseBranch, "--prune") | Out-Null
    }
}

$localBranchExit = Invoke-Git -Arguments @("show-ref", "--verify", "--quiet", "refs/heads/$branchName") -AllowFailure
if ($localBranchExit -eq 0) {
    throw "Local branch '$branchName' already exists. Refusing to reuse it implicitly."
}

$remoteBranch = [string](& git -C $script:RepoRoot branch --remotes --list "origin/$branchName")
$remoteBranch = $remoteBranch.Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Unable to check remote branch collisions."
}
if (-not [string]::IsNullOrWhiteSpace($remoteBranch)) {
    throw "Remote branch 'origin/$branchName' already exists. Refusing to reuse it implicitly."
}

if (Test-Path $worktreePath) {
    throw "Worktree path already exists: $worktreePath"
}

$baseRef = if ($NoFetch) { $BaseBranch } else { "origin/$BaseBranch" }

if ($DryRun) {
    Write-Host "[DRY RUN] git worktree add -b $branchName $worktreePath $baseRef"
    if ($InstallDependencies) {
        Write-Host "[DRY RUN] npm ci --no-audit (inside the new worktree)"
    }
    Write-Host "[DRY RUN] No files, branches or worktrees were changed."
    exit 0
}

New-Item -ItemType Directory -Path $WorktreeRoot -Force | Out-Null
Invoke-Git -Arguments @("worktree", "add", "-b", $branchName, $worktreePath, $baseRef) | Out-Null

if ($InstallDependencies) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        throw "Worktree was created, but npm is not available in PATH. Run npm ci manually later."
    }

    Write-Host "Installing frontend dependencies in the isolated worktree..."
    Push-Location $worktreePath
    $previousHusky = $env:HUSKY
    try {
        $env:HUSKY = "0"
        & npm ci --no-audit
        if ($LASTEXITCODE -ne 0) {
            throw "npm ci failed with exit code $LASTEXITCODE. The worktree was kept for inspection."
        }
    }
    finally {
        $env:HUSKY = $previousHusky
        Pop-Location
    }
}

Write-Host "`nCreated isolated NEXOLAB worktree successfully."
Write-Host "Next steps:"
Write-Host "  cd `"$worktreePath`""
Write-Host "  ./scripts/verify-project.ps1 -Component All -SkipBuild"
Write-Host "  # implement only Issue #$Issue in this worktree"
Write-Host "  # run full verification before publishing the PR"
Write-Host "  ./scripts/verify-project.ps1 -Component All"
