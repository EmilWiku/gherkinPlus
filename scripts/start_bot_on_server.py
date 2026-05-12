#!/usr/bin/env python3
"""Start bot on server - check status and start if needed"""
import paramiko
import time
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

print("🔍 Checking bot status on server...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASSWORD, timeout=30)

try:
    # Check if dependencies are installed
    print("\n📦 Checking Python dependencies...")
    stdin, stdout, stderr = ssh.exec_command(f"cd {REMOTE_DIR} && . venv/bin/activate && pip list | grep -E '(aiohttp|websockets|pandas)'")
    deps = stdout.read().decode()
    if not deps or 'aiohttp' not in deps:
        print("⚠️ Dependencies not fully installed. Installing...")
        stdin, stdout, stderr = ssh.exec_command(f"cd {REMOTE_DIR} && . venv/bin/activate && pip install -q -r requirements_server.txt", get_pty=True)
        # Wait for completion
        stdout.channel.recv_exit_status()
        print("✅ Dependencies installed")
    else:
        print("✅ Dependencies OK")
    
    # Create systemd service if not exists
    print("\n⚙️ Setting up systemd service...")
    service_content = f"""[Unit]
Description=PocketOption M2 Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory={REMOTE_DIR}
Environment="PATH={REMOTE_DIR}/venv/bin"
ExecStart={REMOTE_DIR}/venv/bin/python3 {REMOTE_DIR}/versions/main_v3.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
    
    stdin, stdout, stderr = ssh.exec_command(f"cat > /etc/systemd/system/pocketoptionbot.service << 'EOFSERVICE'\n{service_content}EOFSERVICE\n")
    stdout.channel.recv_exit_status()
    
    # Reload and enable
    stdin, stdout, stderr = ssh.exec_command("systemctl daemon-reload")
    stdout.channel.recv_exit_status()
    
    stdin, stdout, stderr = ssh.exec_command("systemctl enable pocketoptionbot")
    stdout.channel.recv_exit_status()
    
    # Start bot
    print("\n🚀 Starting bot...")
    stdin, stdout, stderr = ssh.exec_command("systemctl restart pocketoptionbot")
    stdout.channel.recv_exit_status()
    
    # Wait a moment
    time.sleep(2)
    
    # Check status
    print("\n📊 Bot status:")
    stdin, stdout, stderr = ssh.exec_command("systemctl status pocketoptionbot --no-pager -l | head -20")
    output = stdout.read().decode()
    print(output)
    
    # Check if running
    stdin, stdout, stderr = ssh.exec_command("systemctl is-active pocketoptionbot")
    status = stdout.read().decode().strip()
    
    if status == "active":
        print("\n✅ Bot is running!")
        print("\n📋 Useful commands:")
        print(f"  View logs: ssh {SERVER_USER}@{SERVER_HOST} 'journalctl -u pocketoptionbot -f'")
        print(f"  Stop bot: ssh {SERVER_USER}@{SERVER_HOST} 'systemctl stop pocketoptionbot'")
        print(f"  Restart bot: ssh {SERVER_USER}@{SERVER_HOST} 'systemctl restart pocketoptionbot'")
        print(f"  Check status: ssh {SERVER_USER}@{SERVER_HOST} 'systemctl status pocketoptionbot'")
    else:
        print(f"\n⚠️ Bot status: {status}")
        print(f"Check logs: ssh {SERVER_USER}@{SERVER_HOST} 'journalctl -u pocketoptionbot -n 50'")
        
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
finally:
    ssh.close()

