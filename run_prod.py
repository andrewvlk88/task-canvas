#!/usr/bin/env python3
"""Production runner for Task Canvas — no debug, no reloader."""
import os
import sys
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env variables
env_path = Path.home() / ".hermes" / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                if key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")

if not os.environ.get("CANVAS_USER") or not os.environ.get("CANVAS_PASS"):
    print("FATAL: CANVAS_USER and CANVAS_PASS environment variables must be set.", file=sys.stderr)
    sys.exit(1)

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    # debug=False, use_reloader=False for systemd stability
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
