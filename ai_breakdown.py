#!/usr/bin/env python3
"""AI Breakdown helper — called by the Flask endpoint to decompose tasks."""
import json, re, sys, subprocess, os

def breakdown(content):
    prompt = "You are a personal assistant. Break down the following task into 3-5 actionable subtasks, ordered logically. Each subtask should be one clear sentence in Hebrew. Return only the list, one per line, no numbers, no bullets, no preamble.\n\nTask: " + content

    try:
        result = subprocess.run(
            ["hermes", "--oneshot", prompt, "--quiet"],
            capture_output=True, text=True, timeout=90,
            env={**os.environ}
        )
        output = result.stdout.strip()
        if not output:
            output = result.stderr.strip()
    except Exception:
        output = ""
    
    # Parse
    lines = [l.strip() for l in output.split("\n") if l.strip()]
    lines = [l for l in lines if not l.startswith("```") and len(l) > 2]
    
    if not lines or len(lines) < 1:
        # Fallback: split by commas
        parts = [p.strip() for p in re.split(r",|;|\\.|ואז", content) if p.strip()]
        if len(parts) <= 1:
            parts = [content]
        lines = parts
    
    return lines[:7]


if __name__ == "__main__":
    task = sys.argv[1] if len(sys.argv) > 1 else ""
    if not task:
        print(json.dumps([]))
        sys.exit(1)
    subtasks = breakdown(task)
    print(json.dumps(subtasks, ensure_ascii=False))
