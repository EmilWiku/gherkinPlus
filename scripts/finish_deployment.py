#!/usr/bin/env python3
"""Finish deployment - install dependencies and setup service"""
import paramiko
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot_app"))

from env_setup import load_dotenv_early, require_env

load_dotenv_early()

SERVER_HOST = require_env("DEPLOY_SSH_HOST")
SERVER_USER = require_env("DEPLOY_SSH_USER")
SERVER_PASSWORD = require_env("DEPLOY_SSH_PASSWORD")
REMOTE_DIR = "/root/pocketoptionbot"

def run_command(ssh, cmd, desc):
    print(f"🔧 {desc}...")
    stdin, stdout, stderr = ssh.exec_command(cmd, get_pty=True)
    exit_status = stdout.channel.recv_exit_status()
    output = stdout.read().decode()
    if exit_status != 0:
        error = stderr.read().decode()
        print(f"⚠️ Warning: {error[:200]}")
    return exit_status == 0

print("🚀 Finishing deployment...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASSWORD, timeout=30)

try:
    # Install dependencies
    print("\n📥 Installing Python dependencies...")
    run_command(ssh, f"cd {REMOTE_DIR} && . venv/bin/activate && pip install -q -r requirements_server.txt", "Installing")
    
    # Create systemd service
    print("\n⚙️ Creating systemd service...")
    service = f"""[Unit]
Description=PocketOption M2 Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}
Environment="PATH={REMOTE_DIR}/venv/bin"
Environment="PYTHONPATH={REMOTE_DIR}/bot_app:{REMOTE_DIR}/PocketOptionAPI"
ExecStart={REMOTE_DIR}/venv/bin/python3 {REMOTE_DIR}/versions/main_v3.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    
    stdin, stdout, stderr = ssh.exec_command(f"cat > /etc/systemd/system/pocketoptionbot.service << 'EOF'\n{service}EOF\n")
    stdout.channel.recv_exit_status()
    
    # Enable and start
    print("\n🚀 Starting bot...")
    run_command(ssh, "systemctl daemon-reload", "Reloading systemd")
    run_command(ssh, "systemctl enable pocketoptionbot", "Enabling service")
    run_command(ssh, "systemctl restart pocketoptionbot", "Starting service")
    
    # Check status
    print("\n📊 Checking status...")
    import time
    time.sleep(2)
    stdin, stdout, stderr = ssh.exec_command("systemctl status pocketoptionbot --no-pager -l")
    output = stdout.read().decode()
    print(output[:1000])
    
    print("\n✅ Deployment complete!")
    print(f"\nTo check logs: ssh {SERVER_USER}@{SERVER_HOST} 'journalctl -u pocketoptionbot -f'")
    
except Exception as e:
    print(f"❌ Error: {e}")
finally:
    ssh.close()

