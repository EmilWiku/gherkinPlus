#!/usr/bin/env python3
"""Check bot and show how to start it"""
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

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASSWORD, timeout=10)

print("🔍 Checking bot setup...\n")

# Check if main file exists
stdin, stdout, stderr = ssh.exec_command("test -f /root/pocketoptionbot/versions/main_v3.py && echo 'OK' || echo 'MISSING'")
main_exists = stdout.read().decode().strip()
print(f"Main file: {main_exists}")

# Check Python
stdin, stdout, stderr = ssh.exec_command("cd /root/pocketoptionbot && . venv/bin/activate && python3 --version")
py_version = stdout.read().decode().strip()
print(f"Python: {py_version}")

# Try to import main modules
stdin, stdout, stderr = ssh.exec_command("cd /root/pocketoptionbot && . venv/bin/activate && python3 -c \"import sys; sys.path[:0]=['/root/pocketoptionbot/bot_app','/root/pocketoptionbot/PocketOptionAPI']; from beautiful_time import get_next_beautiful_time; print('OK')\" 2>&1")
import_test = stdout.read().decode().strip()
print(f"Import test: {import_test[:100]}")

ssh.close()

print("\n" + "="*60)
print("📋 TO START THE BOT ON SERVER:")
print("="*60)
print("\n1. Connect to server:")
print(f"   ssh {SERVER_USER}@{SERVER_HOST}")
print("\n2. Start bot manually (to see errors):")
print("   cd /root/pocketoptionbot")
print("   source venv/bin/activate")
print("   python3 versions/main_v3.py")
print("\n3. OR start as service:")
print("   systemctl start pocketoptionbot")
print("   systemctl status pocketoptionbot")
print("\n4. View logs:")
print("   journalctl -u pocketoptionbot -f")
print("\n5. Stop bot:")
print("   systemctl stop pocketoptionbot")

