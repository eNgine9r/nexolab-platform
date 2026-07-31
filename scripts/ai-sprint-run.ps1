[CmdletBinding()]
param(
    [string]$QueuePath = ".project/ACTIVE_SPRINT.json",
    [int]$MaxTasks = 0,
    [switch]$DryRun,
    [string[]]$CodexArguments = @("exec", "-")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Save-JsonFile {
    param(
        [Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][string]$Path
    )

    $directory = Split-Path -Parent $Path
    if ($directory -and -not (Test-Path $directory)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $Value | ConvertTo-Json -Depth 30 | Set-Content -Path $Path -Encoding utf8
}

function Test-TaskDependencies {
    param(
        [Parameter(Mandatory)]$Task,
        [Parameter(Mandatory)]$Tasks
    )

    foreach ($dependencyId in @($Task.depends_on)) {
        $dependency = $Tasks | Where-Object { $_.id -eq $dependencyId } | Select-Object -First 1
        if (-not $dependency) {
            throw "Task '$($Task.id)' references missing dependency '$dependencyId'."
        }

        if ($dependency.status -notin @("done", "review")) {
            return $false
        }
    }

    return $true
}

function New-TaskPrompt {
    param([Parameter(Mandatory)]$Task)

    $scope = (@($Task.scope) | ForEach-Object { "- $_" }) -join "`n"
    $verification = (@($Task.verification) | ForEach-Object { "- $_" }) -join "`n"

    return @"
You are implementing one scoped NEXOLAB Work Package.

Before editing:
1. Read PROJECT_PROFILE.yaml.
2. Read docs/AI_DEVELOPMENT_OPERATING_STANDARD.md.
3. Read all applicable AGENTS.md files.
4. Read .project/CURRENT_STATE.md and .project/ACTIVE_SPRINT.json.
5. Inspect GitHub Issue #$($Task.issue) if GitHub access is available.
6. Reconcile the task with the current branch and git diff.

Work Package: $($Task.id)
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
- Update .project/CURRENT_STATE.md and .project/LAST_CHECKPOINT.json before finishing.
- End with Outcome, Files changed, Checks actually run, Offline/safety evidence, Blockers, Risks and Next action.
"@
}

if (-not (Test-Path $QueuePath)) {
    throw "Sprint queue not found: $QueuePath"
}

$queue = Get-Content -Path $QueuePath -Raw | ConvertFrom-Json
$tasks = @($queue.tasks)
$processed = 0

$readyTasks = $tasks |
    Where-Object { $_.status -eq "ready" } |
    Sort-Object priority

foreach ($task in $readyTasks) {
    if ($MaxTasks -gt 0 -and $processed -ge $MaxTasks) {
        break
    }

    if (-not (Test-TaskDependencies -Task $task -Tasks $tasks)) {
        Write-Host "Skipping $($task.id): dependencies are not complete."
        continue
    }

    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $runDirectory = ".project/runs"
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null

    $promptPath = Join-Path $runDirectory "$timestamp-$($task.id)-prompt.md"
    $logPath = Join-Path $runDirectory "$timestamp-$($task.id)-codex.log"
    $prompt = New-TaskPrompt -Task $task
    $prompt | Set-Content -Path $promptPath -Encoding utf8

    if ($DryRun) {
        Write-Host "[DRY RUN] Would execute $($task.id) using $promptPath"
        $processed++
        continue
    }

    if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
        throw "Codex CLI is not available in PATH. Install/configure Codex or use -DryRun."
    }

    $task.status = "in_progress"
    $task | Add-Member -NotePropertyName started_at -NotePropertyValue (Get-Date).ToString("o") -Force
    Save-JsonFile -Value $queue -Path $QueuePath

    Write-Host "Starting $($task.id): $($task.title)"
    $prompt | & codex @CodexArguments 2>&1 | Tee-Object -FilePath $logPath
    $exitCode = $LASTEXITCODE

    $checkpoint = [ordered]@{
        schema_version = 1
        project = $queue.project
        sprint = $queue.sprint.id
        task = $task.id
        issue = $task.issue
        timestamp = (Get-Date).ToString("o")
        prompt_path = $promptPath
        log_path = $logPath
        codex_exit_code = $exitCode
    }

    if ($exitCode -eq 0) {
        $task.status = "review"
        $task | Add-Member -NotePropertyName finished_at -NotePropertyValue (Get-Date).ToString("o") -Force
        $checkpoint.status = "review"
        $checkpoint.next_action = "Review diff, checks and offline/safety evidence, then publish a focused Pull Request or mark Done."
        Write-Host "Completed $($task.id); moved to review."
    }
    else {
        $task.status = "blocked"
        $task | Add-Member -NotePropertyName blocked_at -NotePropertyValue (Get-Date).ToString("o") -Force
        $checkpoint.status = "blocked"
        $checkpoint.next_action = "Inspect the Codex log, record the blocker, then continue with another independent Ready task."
        Write-Warning "$($task.id) failed with exit code $exitCode and was marked blocked."
    }

    Save-JsonFile -Value $checkpoint -Path ".project/LAST_CHECKPOINT.json"
    Save-JsonFile -Value $queue -Path $QueuePath
    $processed++
}

if ($processed -eq 0) {
    Write-Host "No unblocked Ready tasks were executed."
}
else {
    Write-Host "Sprint runner processed $processed task(s)."
}
