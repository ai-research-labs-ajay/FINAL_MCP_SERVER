#!/bin/bash
# ============================================================
#  MCP WebScraper - Quick Setup Script
# ============================================================
set -e

echo "=== MCP WebScraper Setup ==="
echo ""

# 1. Create virtual environment
echo "[1/4] Creating virtual environment..."
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
echo "[2/4] Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 3. Install Playwright browsers
echo "[3/4] Installing Playwright Chromium browser..."
playwright install chromium

# 4. Verify
echo "[4/4] Verifying installation..."
python -c "from mcp_webscraper.server import mcp; print('Server loaded successfully!')"

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "To run the server:"
echo "  python -m mcp_webscraper.server"
echo ""
echo "To use with Claude Desktop, add the config from claude_desktop_config.json"
echo "to your Claude Desktop settings file."
