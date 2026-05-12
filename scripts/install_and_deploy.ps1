# PowerShell script to install Ansible and deploy bot
# Run as Administrator

Write-Host "🚀 PocketOption Bot Deployment Script" -ForegroundColor Green
Write-Host ""

# Check if running as admin
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "❌ Please run as Administrator!" -ForegroundColor Red
    exit 1
}

# Check if Python is installed
Write-Host "🐍 Checking Python installation..." -ForegroundColor Yellow
$pythonVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Python not found. Installing Python..." -ForegroundColor Red
    Write-Host "Please install Python 3.8+ from https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Yellow
    exit 1
}
Write-Host "✅ $pythonVersion" -ForegroundColor Green

# Check if pip is installed
Write-Host "📦 Checking pip..." -ForegroundColor Yellow
$pipVersion = pip --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ pip not found. Installing pip..." -ForegroundColor Red
    python -m ensurepip --upgrade
}
Write-Host "✅ $pipVersion" -ForegroundColor Green

# Install Ansible
Write-Host ""
Write-Host "📥 Installing Ansible..." -ForegroundColor Yellow
pip install ansible --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ Failed to install Ansible" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Ansible installed" -ForegroundColor Green

# Verify Ansible installation
$ansibleVersion = ansible --version 2>&1 | Select-Object -First 1
Write-Host "✅ $ansibleVersion" -ForegroundColor Green

# Change to ansible directory
Write-Host ""
Write-Host "📁 Changing to ansible directory..." -ForegroundColor Yellow
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $repoRoot "ansible")

# Run Ansible playbook
Write-Host ""
Write-Host "🚀 Starting deployment..." -ForegroundColor Green
Write-Host ""

ansible-playbook deploy.yml -v

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "✅ Deployment completed successfully!" -ForegroundColor Green
    Write-Host ""
    $sshUser = if ($env:DEPLOY_SSH_USER) { $env:DEPLOY_SSH_USER } else { "root" }
    $sshHost = $env:DEPLOY_SSH_HOST
    if ($sshHost) {
        $sshTarget = "${sshUser}@${sshHost}"
        Write-Host "To check bot status:" -ForegroundColor Cyan
        Write-Host "  ssh $sshTarget 'systemctl status pocketoptionbot'" -ForegroundColor White
        Write-Host ""
        Write-Host "To view logs:" -ForegroundColor Cyan
        Write-Host "  ssh $sshTarget 'journalctl -u pocketoptionbot -f'" -ForegroundColor White
    } else {
        Write-Host "Set DEPLOY_SSH_HOST (and optional DEPLOY_SSH_USER) to ssh into the server." -ForegroundColor Cyan
    }
} else {
    Write-Host ""
    Write-Host "❌ Deployment failed. Check errors above." -ForegroundColor Red
    exit 1
}

