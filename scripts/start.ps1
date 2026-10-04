param([switch]$Production, [switch]$Build, [switch]$Logs)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  $configuration = if ($Production) { '.env.production' } else { '.env' }
  $composeFile = if ($Production) { 'docker-compose.prod.yml' } else { 'docker-compose.yml' }
  if (-not (Test-Path -LiteralPath $configuration)) { throw "Create $configuration using scripts/configure.py first." }
  $composeArgs = @('compose', '--env-file', $configuration, '-f', $composeFile)
  if ($Logs) { docker @composeArgs logs --tail 100 -f }
  else {
    $launchArgs = @('up', '-d', '--wait', '--wait-timeout', '300')
    if ($Build) { $launchArgs += '--build' }
    docker @composeArgs @launchArgs
  }
  if ($LASTEXITCODE -ne 0) { throw 'Docker Compose operation failed.' }
} finally { Pop-Location }
