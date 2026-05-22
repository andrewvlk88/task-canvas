#!/bin/bash
cd /home/andrew/task-canvas
exec python3 app.py > /tmp/canvas.log 2>&1
