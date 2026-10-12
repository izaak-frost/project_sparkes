param(
    [string]$ListenAddress = '192.168.0.28',
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$projectDataRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$pythonCandidates = @(
    (Join-Path $projectDataRoot '.venv-health\Scripts\python.exe'),
    (Join-Path $projectDataRoot 'venv\Scripts\python.exe')
)
$pythonExecutable = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExecutable) { throw 'Install requirements.txt in a local virtual environment first.' }
$localEnv = Join-Path $projectDataRoot 'support\credentials\local.env'
if (-not (Test-Path -LiteralPath $localEnv)) {
    $localEnvDirectory = Split-Path -Parent $localEnv
    New-Item -ItemType Directory -Path $localEnvDirectory -Force | Out-Null
    $uploadToken = & $pythonExecutable -c 'import secrets; print(secrets.token_urlsafe(32))'
    if ($LASTEXITCODE -ne 0) { throw 'Unable to generate the local upload token.' }
    Set-Content -LiteralPath $localEnv -Value "HEALTH_UPLOAD_TOKEN=$uploadToken`nHEALTH_TIMEZONE=Europe/London" -Encoding ascii
}
Push-Location $projectDataRoot
try {
    & $pythonExecutable -m uvicorn health_extract.receiver:create_app --factory --env-file $localEnv --host $ListenAddress --port $Port --no-access-log
} finally {
    Pop-Location
}
