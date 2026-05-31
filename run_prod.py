#!/usr/bin/env python3
"""Production runner for Task Canvas — no debug, no reloader."""
import os
import sys

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("CANVAS_USER", "andrew")
os.environ.setdefault("CANVAS_PASS", "hermes666")

from app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5050"))
    # debug=False, use_reloader=False for systemd stability
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
