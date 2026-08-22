[CmdletBinding()]
param(
    [string]$QueuePath = ".project/ACTIVE_SPRINT.json",
    [int]$MaxTasks = 0,
    [switch]$DryRun,
    [string[]]$CodexArguments = @("exec", "-")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-OptionalProperty {
    param(
        [Parameter(Mandatory)]$Object,
        [Parameter(Mandatory)][string]$Name
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Get-PythonCommand {
    foreach ($candidate in @("python3", "python")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    throw "Python 3 is required for deterministic State Model v2 mutations."
}

$script:PythonCommand = Get-PythonCommand
$script:StateTool = Join-Path $PSScriptRoot "project-state.py"

function Invoke-StateTool {
    param([Parameter(Mandatory)][string[]]$Arguments)

    & $script:PythonCommand $script:StateTool @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "State Model v2 command failed: $($Arguments -join ' ')"
    }
}

function Test-TaskDependencies {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)]$WorkPackages
    )

    $dependencies = @(Get-OptionalProperty -Object $Task -Name "depends_on")
    foreach ($dependencyIssue in $dependencies) {
        if ($null -eq $dependencyIssue) {
            continue
        }
        $dependency = $WorkPackages |
            Where-Object { $_.issue -eq [int]$dependencyIssue } |
            Select-Object -First 1
        if (-not $dependency) {
            throw "Issue #$($Task.issue) references missing dependency Issue #$dependencyIssue."
        }
        if ($dependency.lifecycle -ne "completed") {
            return $false
        }
    }
    return $true
}

function New-TaskPrompt {
    param([Parameter(Mandatory)]$Task)

    $taskId = Get-OptionalProperty -Object $Task -Name "id"
    if (-not $taskId) {
        $taskId = "NEXOLAB-$($Task.issue)"
    }

    $scopeValues = @(Get-OptionalProperty -Object $Task -Name "scope")
    $verificationValues = @(Get-OptionalProperty -Object $Task -Name "verification")
    $scope = if ($scopeValues.Count -gt 0 -and $null -ne $scopeValues[0]) {
        ($scopeValues | ForEach-Object { "- $_" }) -join "`n"
    }
    else {
        "- Follow the permitted directories and scope in GitHub Issue #$($Task.issue)."
    }
    $verification = if ($verificationValues.Count -gt 0 -and $null -ne $verificationValues[0]) {
        ($verificationValues | ForEach-Object { "- $_" }) -join "`n"
    }
    else {
        "- Follow the verification plan in GitHub Issue #$($Task.issue)."
    }

    return @"
You are implementing one scoped NEXOLAB Work Package.

Before editing:
1. Read PROJECT_PROFILE.yaml.
2. Read docs/AI_DEVELOPMENT_OPERATING_STANDARD.md.
3. Read all applicable AGENTS.md files.
4. Read .project/CURRENT_STATE.md and .project/ACTIVE_SPRINT.json.
5. Inspect GitHub Issue #$($Task.issue) if GitHub access is available.
6. Reconcile the task with the current branch and git diff.

Work Package: $taskId
Title: $($Task.title)
GitHub Issue: #$($Task.issue)

Permitted scope:
$scope

Required verification:
$verification

Rules:
- Work only on this Work Package.
- Deliver a vertical operator/user outcome, not an isolated page edit.
- Core runtime must remain usable without internet or paid services.
- Do not add hidden CDN, cloud-font, telemetry or external API dependencies.
- Never perform Modbus writes.
- Do not perform production/site cutover or destructive data operations.
- Missing real-hardware evidence must be reported as unverified.
- Run targeted checks before broad checks.
- Use State Model v2 tooling for canonical state transitions/checkpoints.
- End with Outcome, Files changed, Checks actually run, Offline/safety evidence, Blockers, Risks and Next action.
"@
}

if (-not (Test-Path $QueuePath)) {
    throw "Sprint queue not found: $QueuePath"
}
if (-not (Test-Path $script:StateTool)) {
    throw "State Model v2 tool not found: $script:StateTool"
}

Invoke-StateTool -Arguments @("validate")
$queue = Get-Content -Path $QueuePath -Raw | ConvertFrom-Json
if ($queue.schema_version -ne 2) {
    throw "Autonomous Sprint Runner requires State Model v2."
}

$workPackages = @($queue.work_packages)
$processed = 0
$readyTasks = $workPackages |
    Where-Object { $_.lifecycle -eq "ready" } |
    Sort-Object priority

foreach ($task in $readyTasks) {
    if ($MaxTasks -gt 0 -and $processed -ge $MaxTasks) {
        break
    }
    if (-not (Test-TaskDependencies -Task $task -WorkPackages $workPackages)) {
        Write-Host "Skipping Issue #$($task.issue): dependencies are not complete."
        continue
    }

    $branch = Get-OptionalProperty -Object $task -Name "branch"
    if (-not $branch) {
        throw "Ready Issue #$($task.issue) must define its feature branch before autonomous execution."
    }

    $taskId = Get-OptionalProperty -Object $task -Name "id"
    if (-not $taskId) {
        $taskId = "NEXOLAB-$($task.issue)"
    }
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $runDirectory = ".project/runs"
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    $promptPath = Join-Path $runDirectory "$timestamp-$taskId-prompt.md"
    $logPath = Join-Path $runDirectory "$timestamp-$taskId-codex.log"
    $prompt = New-TaskPrompt -Task $task
    $prompt | Set-Content -Path $promptPath -Encoding utf8

    if ($DryRun) {
        Write-Host "[DRY RUN] Would execute Issue #$($task.issue) using $promptPath"
        $processed++
        continue
    }
    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
        throw "Codex CLI is not available in PATH. Install/configure Codex or use -DryRun."
    }

    Invoke-StateTool -Arguments @(
        "begin", "--issue", [string]$task.issue,
        "--title", [string]$task.title,
        "--branch", [string]$branch
    )

    Write-Host "Starting $taskId: $($task.title)"
    $prompt | & codex @CodexArguments 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE
    $checkpointTime = (Get-Date).ToUniversalTime().ToString("o")

    if ($exitCode -eq 0) {
        Invoke-StateTool -Arguments @("transition", "--issue", [string]$task.issue, "--to", "review")
        Invoke-StateTool -Arguments @(
            "checkpoint",
            "--event", "issue_$($task.issue)_codex_review",
            "--next-action", "Review diff and exact checks, then publish or update the focused Pull Request.",
            "--timestamp", $checkpointTime,
            "--actor", "Codex Sprint Runner"
        )
        Write-Host "Completed $taskId; moved to review. Team Lead review is required before another Work Package starts."
        $processed++
        break
    }

    Invoke-StateTool -Arguments @(
        "checkpoint",
        "--event", "issue_$($task.issue)_codex_failed",
        "--next-action", "Inspect $logPath, record the blocker, then continue with another independent Ready Work Package.",
        "--timestamp", $checkpointTime,
        "--actor", "Codex Sprint Runner"
    )
    Invoke-StateTool -Arguments @("transition", "--issue", [string]$task.issue, "--to", "blocked")
    Write-Warning "$taskId failed with exit code $exitCode and was marked blocked."
    $processed++
}

if ($processed -eq 0) {
    Write-Host "No unblocked Ready Work Packages were executed."
}
else {
    Write-Host "Sprint runner processed $processed Work Package(s)."
}
