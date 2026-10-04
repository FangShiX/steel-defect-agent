param(
  [Parameter(Mandatory = $true)][string]$BackupDir,
  [string[]]$ComposeFiles = @("docker-compose.yml"),
  [string]$EnvFile
)

$ErrorActionPreference = "Stop"
$resolvedBackupDir = [IO.Path]::GetFullPath($BackupDir)
New-Item -ItemType Directory -Force -Path $resolvedBackupDir, (Join-Path $resolvedBackupDir "minio"), (Join-Path $resolvedBackupDir "runs") | Out-Null
$composeArgs = @()
if ($EnvFile) { $composeArgs += @("--env-file", $EnvFile) }
foreach ($composeFile in ($ComposeFiles -join ",").Split(",")) {
  if ($composeFile.Trim()) { $composeArgs += @("-f", $composeFile.Trim()) }
}

if (-not $env:POSTGRES_USER -or -not $env:POSTGRES_DB) {
  throw "Set POSTGRES_USER and POSTGRES_DB before running the backup."
}
if (-not $env:MINIO_ACCESS_KEY -or -not $env:MINIO_SECRET_KEY) {
  throw "Set MINIO_ACCESS_KEY and MINIO_SECRET_KEY before running the backup."
}

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$databaseFile = Join-Path $resolvedBackupDir "postgres-$timestamp.sql"
docker compose @composeArgs exec -T postgres pg_dump -U $env:POSTGRES_USER -d $env:POSTGRES_DB --clean --if-exists | Set-Content -NoNewline -Encoding utf8 $databaseFile
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed." }

$mount = "$resolvedBackupDir`:/backup"
docker run --rm --network ssdd-network -v $mount --entrypoint /bin/sh steel-defect-agent-minio:2025-10-15 -c "mc alias set local http://minio:9000 `"$env:MINIO_ACCESS_KEY`" `"$env:MINIO_SECRET_KEY`"; mc mirror --overwrite local/ssdd-images /backup/minio"
if ($LASTEXITCODE -ne 0) { throw "MinIO backup failed." }

$services = @(docker compose @composeArgs config --services)
$backendId = ""
if ($services -contains "backend") {
  $backendIds = @(docker compose @composeArgs ps -q backend)
  if ($backendIds.Count -gt 0) { $backendId = ([string]$backendIds[0]).Trim() }
}
if ($services -contains "backend" -and -not $backendId) {
  throw "Backend must be running to back up the persistent training output volume."
} elseif ($backendId) {
  docker cp "${backendId}:/app/runs/." (Join-Path $resolvedBackupDir "runs")
  if ($LASTEXITCODE -ne 0) { throw "Training output backup failed." }
} elseif (Test-Path "runs") {
  Copy-Item -Recurse -Force "runs\\*" (Join-Path $resolvedBackupDir "runs")
}
@{ created_at = (Get-Date).ToString("o"); database = (Split-Path -Leaf $databaseFile); minio_bucket = "ssdd-images"; training_output = "runs" } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $resolvedBackupDir "manifest.json")
Write-Host "Backup completed: $resolvedBackupDir"
