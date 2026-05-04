import json
import os
import re

path = '/home/andrew/task-canvas/app.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the broken DEFAULT_COLUMNS syntax
bad_pattern = r'DEFAULT_COLUMNS = \[\n    \{"id": "backlog", "title": "📚 Backlog", "cards": \[\]\},\n    \{"id": "week", "title": "📅 משימות השבוע", "cards": \[\]\},\n    \{"id": "inprogress", "title": "🚀 In Progress", "cards": \[\]\},\n    \{"id": "waiting", "title": "⏳ במעקב", "cards": \[\]\},\n    \{"id": "done", "title": "✅ Done", "cards": \[\]\},\n\]\},\n    \{"id": "week", "title": "📅 משימות השבוע", "cards": \[\]\},\n    \{"id": "today", "title": "☀️ משימות היום", "cards": \[\]\},\n    \{"id": "inprogress", "title": "🚀 In Progress", "cards": \[\]\},\n    \{"id": "done", "title": "✅ Done", "cards": \[\]\},\n\]'

good_pattern = '''DEFAULT_COLUMNS = [
    {"id": "backlog", "title": "📚 Backlog", "cards": []},
    {"id": "week", "title": "📅 משימות השבוע", "cards": []},
    {"id": "inprogress", "title": "🚀 In Progress", "cards": []},
    {"id": "waiting", "title": "⏳ במעקב", "cards": []},
    {"id": "done", "title": "✅ Done", "cards": []},
]'''

content = re.sub(bad_pattern, good_pattern, content)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
