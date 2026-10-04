param([switch]$Production)
$ErrorActionPreference = 'Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  $configuration = if ($Production) { '.env.production' } else { '.env' }
  $composeFile = if ($Production) { 'docker-compose.prod.yml' } else { 'docker-compose.yml' }
  docker compose --env-file $configuration -f $composeFile down
  if ($LASTEXITCODE -ne 0) { throw 'Docker Compose stop failed.' }
} finally { Pop-Location }
