#!/bin/bash
cd /home/andrew/task-canvas
exec python3 run_prod.py > /tmp/canvas.log 2>&1
