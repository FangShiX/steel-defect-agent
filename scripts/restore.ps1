param(
  [Parameter(Mandatory = $true)][string]$BackupDir,
  [switch]$Confirm,
  [string[]]$ComposeFiles = @("docker-compose.yml"),
  [string]$EnvFile
)

$ErrorActionPreference = "Stop"
if (-not $Confirm) { throw "Restore overwrites database and object storage. Re-run with -Confirm after verifying the backup directory." }
if (-not $env:POSTGRES_USER -or -not $env:POSTGRES_DB) { throw "Set POSTGRES_USER and POSTGRES_DB before restoring." }
if (-not $env:MINIO_ACCESS_KEY -or -not $env:MINIO_SECRET_KEY) { throw "Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY before restoring." }

$resolvedBackupDir = [IO.Path]::GetFullPath($BackupDir)
$composeArgs = @()
if ($EnvFile) { $composeArgs += @("--env-file", $EnvFile) }
foreach ($composeFile in ($ComposeFiles -join ",").Split(",")) {
  if ($composeFile.Trim()) { $composeArgs += @("-f", $composeFile.Trim()) }
}
$manifest = Join-Path $resolvedBackupDir "manifest.json"
if (-not (Test-Path $manifest)) { throw "Backup manifest not found: $manifest" }
$metadata = Get-Content $manifest -Raw | ConvertFrom-Json
$databaseFile = Join-Path $resolvedBackupDir $metadata.database
if (-not (Test-Path $databaseFile)) { throw "Database dump not found: $databaseFile" }

Get-Content -Raw $databaseFile | docker compose @composeArgs exec -T postgres psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB -v ON_ERROR_STOP=1
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore failed." }

$mount = "$resolvedBackupDir`:/backup"
docker run --rm --network ssdd-network -v $mount --entrypoint /bin/sh minio/mc -c "mc alias set local http://minio:9000 `"$env:MINIO_ACCESS_KEY`" `"$env:MINIO_SECRET_KEY`"; mc mirror --overwrite --remove /backup/minio local/ssdd-images"
if ($LASTEXITCODE -ne 0) { throw "MinIO restore failed." }

$runsBackupDir = Join-Path $resolvedBackupDir "runs"
if (Test-Path $runsBackupDir) {
  $services = @(docker compose @composeArgs config --services)
  $backendId = ""
  if ($services -contains "backend") {
    $backendIds = @(docker compose @composeArgs ps -q backend)
    if ($backendIds.Count -gt 0) { $backendId = ([string]$backendIds[0]).Trim() }
  }
  if ($services -contains "backend" -and -not $backendId) {
    throw "Backend must be running to restore the persistent training output volume."
  } elseif ($backendId) {
    docker compose @composeArgs exec -T backend sh -c "rm -rf /app/runs/* && mkdir -p /app/runs"
    if ($LASTEXITCODE -ne 0) { throw "Training output cleanup before restore failed." }
    docker cp (Join-Path $runsBackupDir ".") "${backendId}:/app/runs"
    if ($LASTEXITCODE -ne 0) { throw "Training output restore failed." }
  } else {
    Copy-Item -Recurse -Force (Join-Path $runsBackupDir "*") "runs"
  }
}
Write-Host "Restore completed. Restart the backend and verify /api/health/detail plus alembic current."
