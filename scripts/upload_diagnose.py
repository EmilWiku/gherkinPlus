#!/usr/bin/env python3
"""Upload diagnose script to server"""
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
scp.put(str(SCRIPTS / "diagnose_connection.py"), "/root/pocketoptionbot/diagnose_connection.py")
scp.close()

print("✅ Diagnostic script uploaded!")
print("\nRun on server:")
print("  cd /root/pocketoptionbot")
print("  source venv/bin/activate")
print("  python3 diagnose_connection.py")

ssh.close()

