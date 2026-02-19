#!/usr/bin/env bash
# drp sync — install dependencies and run setup wizard.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "drp sync installer"
echo "═══════════════════"
echo ""

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "✗ python3 not found. Install Python 3.10+ first."
    exit 1
fi

echo "✓ python3 found: $(python3 --version)"

# Install deps
echo ""
echo "Installing dependencies…"
pip3 install --quiet watchdog requests
echo "✓ watchdog + requests installed"

# Run setup wizard
echo ""
python3 "$SCRIPT_DIR/client.py" --setup
