$ErrorActionPreference = "Stop"

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker command was not found. Start Docker Desktop and ensure docker.exe is in PATH."
}

if (-not (Test-Path -LiteralPath ".env")) {
    throw "Missing .env. Run: Copy-Item .env.example .env"
}

$line = Get-Content -LiteralPath ".env" |
    Where-Object { $_ -match '^CLOUDDRIVE_MOUNT_PATH=' } |
    Select-Object -First 1

if (-not $line) {
    throw "CLOUDDRIVE_MOUNT_PATH is missing from .env."
}

$hostPath = ($line -split '=', 2)[1].Trim()
if ($hostPath.StartsWith('"') -and $hostPath.EndsWith('"')) {
    $hostPath = $hostPath.Substring(1, $hostPath.Length - 2)
}
if (-not (Test-Path -LiteralPath $hostPath -PathType Container)) {
    throw "CloudDrive2 directory does not exist or is inaccessible: $hostPath"
}

docker compose config --quiet
if ($LASTEXITCODE -ne 0) {
    throw "docker compose config failed."
}

Write-Host "Compose configuration is valid." -ForegroundColor Green
Write-Host "Host directory: $hostPath" -ForegroundColor Green
Write-Host "Container directory: /mnt/clouddrive (read-only)" -ForegroundColor Green
