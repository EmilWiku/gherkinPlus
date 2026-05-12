#!/usr/bin/env python3
"""
Direct deployment script for PocketOption Bot
Uses paramiko for SSH and SCP operations
"""
import os
import sys
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot_app"))

from env_setup import load_dotenv_early, require_env

load_dotenv_early()

# Install paramiko if needed
try:
    import paramiko
    from scp import SCPClient
except ImportError:
    print("📥 Installing paramiko...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko", "scp"])
    import paramiko
    from scp import SCPClient

# Server configuration (see .env.example)
SERVER_HOST = require_env("DEPLOY_SSH_HOST")
SERVER_USER = require_env("DEPLOY_SSH_USER")
SERVER_PASSWORD = require_env("DEPLOY_SSH_PASSWORD")
REMOTE_DIR = "/root/pocketoptionbot"

# Local paths (repository root)
BASE_DIR = ROOT

def create_ssh_client():
    """Create and return SSH client"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"🔌 Connecting to {SERVER_HOST}...")
    client.connect(SERVER_HOST, username=SERVER_USER, password=SERVER_PASSWORD, timeout=30)
    print("✅ Connected!")
    return client

def run_remote_command(ssh, command, description="", timeout=300):
    """Run command on remote server"""
    if description:
        print(f"🔧 {description}...")
    
    # Use get_pty for better output handling
    stdin, stdout, stderr = ssh.exec_command(command, get_pty=True)
    
    # Read output in real-time
    output_lines = []
    error_lines = []
    
    # Set timeout
    import select
    import socket
    
    channel = stdout.channel
    while not channel.exit_status_ready():
        if channel.recv_ready():
            rl, wl, xl = select.select([channel], [], [], 0.0)
            if len(rl) > 0:
                data = channel.recv(1024).decode('utf-8', errors='ignore')
                if data:
                    output_lines.append(data)
                    # Print progress for long operations
                    if any(keyword in data.lower() for keyword in ['installing', 'downloading', 'unpacking', 'setting up']):
                        print(f"   {data.strip()[:80]}")
    
    exit_status = channel.recv_exit_status()
    output = ''.join(output_lines)
    error = stderr.read().decode()
    
    if exit_status != 0:
        print(f"⚠️ Command failed with exit code {exit_status}")
        if error:
            print(f"Error: {error[:500]}")
        return False, output, error
    return True, output, error

def upload_directory(ssh, scp, local_path, remote_path):
    """Upload directory recursively"""
    local = Path(local_path)
    if not local.exists():
        print(f"⚠️ Skipping {local_path} (not found)")
        return
    
    print(f"📦 Uploading {local.name}...")
    if local.is_file():
        scp.put(str(local), remote_path)
    else:
        # Create remote directory first
        run_remote_command(ssh, f"mkdir -p {remote_path}", "")
        # Upload all files in directory
        for item in local.rglob('*'):
            if item.is_file():
                rel_path = item.relative_to(local)
                remote_file = f"{remote_path}/{rel_path}".replace('\\', '/')
                # Create remote directory if needed
                remote_dir = '/'.join(remote_file.split('/')[:-1])
                if remote_dir:
                    run_remote_command(ssh, f"mkdir -p {remote_dir}", "")
                scp.put(str(item), remote_file)

def main():
    print("🚀 PocketOption Bot Deployment")
    print("=" * 50)
    
    # Connect to server
    ssh = create_ssh_client()
    
    try:
        # Step 1: Update system and install dependencies
        print("\n📦 Step 1: Installing system packages...")
        print("   (This may take 2-5 minutes, please wait...)")
        commands = [
            ("DEBIAN_FRONTEND=noninteractive apt-get update -y", "Updating package list"),
            ("DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-pip python3-venv screen git build-essential", "Installing packages"),
        ]
        
        for cmd, desc in commands:
            success, output, error = run_remote_command(ssh, cmd, desc)
            if not success:
                print(f"❌ Failed: {desc}")
                return 1
        
        # Step 2: Create directory
        print("\n📁 Step 2: Creating bot directory...")
        run_remote_command(ssh, f"mkdir -p {REMOTE_DIR}", "Creating directory")
        
        # Step 3: Upload files (using tar for faster transfer)
        print("\n📤 Step 3: Uploading files...")
        print("   Creating archive...")
        
        # Create tar archive locally
        import tarfile
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as tmp:
            archive_path = tmp.name
        
        with tarfile.open(archive_path, 'w:gz') as tar:
            # Application package
            bot_app = BASE_DIR / "bot_app"
            if bot_app.is_dir():
                tar.add(bot_app, arcname="bot_app")

            # Add directories at repo root
            dirs_to_add = ['versions', 'PocketOptionAPI', 'visualization_lib']
            for dir_name in dirs_to_add:
                dir_path = BASE_DIR / dir_name
                if dir_path.exists():
                    tar.add(dir_path, arcname=dir_name)

            req_file = BASE_DIR / "requirements" / "server.txt"
            if req_file.is_file():
                tar.add(req_file, arcname="requirements_server.txt")
        
        print(f"   Archive created: {len(Path(archive_path).read_bytes()) / 1024 / 1024:.1f} MB")
        print("   Uploading archive...")
        
        # Upload archive
        scp = SCPClient(ssh.get_transport())
        scp.put(archive_path, f"{REMOTE_DIR}/bot_files.tar.gz")
        scp.close()
        
        # Extract on server
        print("   Extracting files on server...")
        run_remote_command(ssh, f"cd {REMOTE_DIR} && tar -xzf bot_files.tar.gz && rm bot_files.tar.gz", "Extracting")
        
        # Cleanup local archive
        os.unlink(archive_path)
        print("   ✓ Files uploaded!")
        
        # Step 4: Setup Python environment
        print("\n🐍 Step 4: Setting up Python environment...")
        print("   (This may take 3-5 minutes, please wait...)")
        setup_commands = [
            (f"cd {REMOTE_DIR} && python3 -m venv venv", "Creating virtual environment"),
            (f"cd {REMOTE_DIR} && . venv/bin/activate && pip install --upgrade pip -q", "Upgrading pip"),
            (f"cd {REMOTE_DIR} && . venv/bin/activate && pip install -r requirements_server.txt -q", "Installing dependencies"),
        ]
        
        for cmd, desc in setup_commands:
            success, output, error = run_remote_command(ssh, f"bash -c '{cmd}'", desc)
            if not success and "already satisfied" not in error.lower():
                print(f"⚠️ Warning: {desc}")
                if error:
                    print(f"   {error[:200]}")
        
        # Step 5: Create systemd service
        print("\n⚙️ Step 5: Creating systemd service...")
        service_content = f"""[Unit]
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
        
        # Write service file
        stdin, stdout, stderr = ssh.exec_command(f"cat > /etc/systemd/system/pocketoptionbot.service << 'EOF'\n{service_content}EOF\n")
        stdout.channel.recv_exit_status()
        
        # Enable and start service
        print("\n🚀 Step 6: Starting bot service...")
        run_remote_command(ssh, "systemctl daemon-reload", "Reloading systemd")
        run_remote_command(ssh, "systemctl enable pocketoptionbot", "Enabling service")
        run_remote_command(ssh, "systemctl restart pocketoptionbot", "Starting service")
        
        # Check status
        print("\n📊 Step 7: Checking service status...")
        time.sleep(2)
        success, output, error = run_remote_command(ssh, "systemctl status pocketoptionbot --no-pager", "Checking status")
        print(output)
        
        print("\n" + "=" * 50)
        print("✅ Deployment completed!")
        print("\nTo check logs:")
        print(f"  ssh {SERVER_USER}@{SERVER_HOST} 'journalctl -u pocketoptionbot -f'")
        print("\nTo restart bot:")
        print(f"  ssh {SERVER_USER}@{SERVER_HOST} 'systemctl restart pocketoptionbot'")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        ssh.close()
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

