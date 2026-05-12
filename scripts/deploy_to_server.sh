#!/bin/bash
# Deployment script for pocketoptionbot to Linux server
# Usage: DEPLOY_SSH_USER=root DEPLOY_SSH_HOST=your.host ./deploy_to_server.sh
# Run from anywhere; paths resolve relative to this script.

set -eu
: "${DEPLOY_SSH_USER:?Set DEPLOY_SSH_USER}"
: "${DEPLOY_SSH_HOST:?Set DEPLOY_SSH_HOST}"

SERVER="${DEPLOY_SSH_USER}@${DEPLOY_SSH_HOST}"
SERVER_DIR="/root/pocketoptionbot"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "🚀 Starting deployment to server..."

echo "📁 Creating directory on server..."
ssh $SERVER "mkdir -p $SERVER_DIR"

echo "📦 Transferring files..."
scp -r "$REPO_ROOT/bot_app" "$REPO_ROOT/versions" "$REPO_ROOT/PocketOptionAPI" "$REPO_ROOT/visualization_lib" "$SERVER:$SERVER_DIR/"
scp "$REPO_ROOT/requirements/server.txt" "$SERVER:$SERVER_DIR/requirements_server.txt"

echo "📥 Installing Python dependencies..."
ssh $SERVER << 'ENDSSH'
cd /root/pocketoptionbot

apt-get update -y
apt-get install -y python3 python3-pip python3-venv

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install aiohttp websockets python-dotenv tzlocal typing-extensions rich pydantic pandas

pip install matplotlib pillow numpy
pip install plotly seaborn kaleido || echo "Optional visualization libraries not installed"

echo "✅ Dependencies installed"
ENDSSH

echo "✅ Deployment complete!"
echo ""
echo "To run the bot, SSH to server and execute:"
echo "  ssh $SERVER"
echo "  cd $SERVER_DIR"
echo "  source venv/bin/activate"
echo "  export PYTHONPATH=$SERVER_DIR/bot_app:$SERVER_DIR/PocketOptionAPI"
echo "  python3 versions/main_v3.py"
