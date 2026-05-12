#!/usr/bin/env python3
"""Upload SSID extraction scripts to server"""
import sys
from pathlib import Path

import paramiko
from scp import SCPClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot_app"))

from env_setup import load_dotenv_early, require_env

load_dotenv_early()

SCRIPTS = Path(__file__).resolve().parent

SERVER_HOST = require_env("DEPLOY_SSH_HOST")
SERVER_USER = require_env("DEPLOY_SSH_USER")
SERVER_PASSWORD = require_env("DEPLOY_SSH_PASSWORD")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASSWORD, timeout=10)

scp = SCPClient(ssh.get_transport())

# Upload scripts
print("📤 Uploading scripts...")
scp.put(str(SCRIPTS / "get_ssid_automated.py"), "/root/pocketoptionbot/get_ssid_automated.py")
scp.put(str(SCRIPTS / "diagnose_connection.py"), "/root/pocketoptionbot/diagnose_connection.py")

scp.close()

# Install Chrome and dependencies on server
print("📦 Installing Chrome and dependencies on server...")
commands = [
    "apt-get update -y",
    "apt-get install -y chromium-browser chromium-chromedriver xvfb",
    "cd /root/pocketoptionbot && source venv/bin/activate && pip install selenium webdriver-manager -q"
]

for cmd in commands:
    stdin, stdout, stderr = ssh.exec_command(cmd)
    exit_status = stdout.channel.recv_exit_status()
    if exit_status != 0:
        error = stderr.read().decode()
        print(f"⚠️ Warning: {error[:200]}")

ssh.close()

print("✅ Scripts uploaded!")
print("\n📋 To get SSID on server:")
print("  cd /root/pocketoptionbot")
print("  source venv/bin/activate")
print("  python3 get_ssid_automated.py")
print("\nOr with visible browser (if X11 forwarding):")
print("  python3 get_ssid_automated.py --no-headless")

