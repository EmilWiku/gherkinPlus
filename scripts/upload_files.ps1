# PowerShell script to upload files to server
# Set DEPLOY_SSH_HOST (and optionally DEPLOY_SSH_USER, default root) in the environment.

$sshUser = if ($env:DEPLOY_SSH_USER) { $env:DEPLOY_SSH_USER } else { "root" }
if (-not $env:DEPLOY_SSH_HOST) {
    Write-Host "Set environment variable DEPLOY_SSH_HOST" -ForegroundColor Red
    exit 1
}
$server = "${sshUser}@$($env:DEPLOY_SSH_HOST)"
$remotePath = "/root/pocketoptionbot"
$repoRoot = Split-Path -Parent $PSScriptRoot

Write-Host "🚀 Uploading files to server..." -ForegroundColor Green

Write-Host "📁 Creating directory..." -ForegroundColor Yellow
ssh $server "mkdir -p $remotePath"

Write-Host "📦 Uploading files..." -ForegroundColor Yellow

scp -r "$repoRoot\bot_app" "${server}:${remotePath}/"
scp -r "$repoRoot\versions" "${server}:${remotePath}/"
scp -r "$repoRoot\PocketOptionAPI" "${server}:${remotePath}/"
scp -r "$repoRoot\visualization_lib" "${server}:${remotePath}/"

scp "$repoRoot\requirements\server.txt" "${server}:${remotePath}/requirements_server.txt"
scp "$PSScriptRoot\setup_server.sh" "${server}:${remotePath}/"

Write-Host "✅ Files uploaded!" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "1. SSH to server: ssh $server" -ForegroundColor White
Write-Host "2. Run setup: cd $remotePath && chmod +x setup_server.sh && ./setup_server.sh" -ForegroundColor White
Write-Host "3. Start bot: screen -S bot && source venv/bin/activate && python3 versions/main_v3.py" -ForegroundColor White
