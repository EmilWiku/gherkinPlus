#!/bin/bash
# Quick setup script to run on the server
# Run this ON THE SERVER after uploading files

echo "🔧 Setting up PocketOption Bot on server..."

# Update system
echo "📦 Updating system packages..."
apt-get update -y

# Install Python and tools
echo "🐍 Installing Python..."
apt-get install -y python3 python3-pip python3-venv screen git

# Create virtual environment
echo "📁 Creating virtual environment..."
cd /root/pocketoptionbot
python3 -m venv venv
source venv/bin/activate

# Upgrade pip
echo "⬆️ Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📥 Installing Python dependencies..."
pip install -r requirements_server.txt

echo "✅ Setup complete!"
echo ""
echo "To run the bot:"
echo "  cd /root/pocketoptionbot"
echo "  source venv/bin/activate"
echo "  screen -S bot"
echo "  python3 versions/main_v3.py"
echo ""
echo "Press Ctrl+A then D to detach from screen"
echo "Use 'screen -r bot' to reattach"

