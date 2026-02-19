#!/usr/bin/env bash
# drp sync — start the sync client.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Quick dep check
python3 -c "import watchdog, requests" 2>/dev/null || {
    echo "Missing dependencies. Run:  make sync-setup"
    exit 1
}

exec python3 "$SCRIPT_DIR/client.py" "$@"
