# Task Canvas — Andrew's Personal Kanban Board

5-column task management board (RTL) with subtasks, priorities, links, due dates, recurring tasks, and a modern mobile-first UI.

## Architecture

| Component | File | Description |
|-----------|------|-------------|
| Flask server | `app.py` | REST API + static file serving |
| Database layer | `db.py` | SQLite storage with audit logging |
| Frontend (desktop) | `templates/kanban.html` | Aether Edition 5-column Kanban |
| Frontend (mobile) | `templates/index.html` | Mobile-first daily view |
| Analytics | `analytics_utils.py` | Task metrics and reporting |

## Storage — SQLite (`tasks.db`)

**Migrated from `tasks.json` → SQLite** (May 2026). All task data is stored in `~/.hermes/tasks.db` with:

- **WAL mode** — concurrent reads, no locking conflicts
- **Foreign keys** — referential integrity
- **Audit log** — every `INSERT`, `UPDATE`, `DELETE`, and column `MOVE` is recorded with old/new values and timestamp
- **Atomic writes** — single-writer, no corruption risk (unlike JSON file overwrites)
- **Migration** — one-time import from `tasks.json` via `migrate_from_json()`; only runs if DB is empty

### Schema

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    column_id TEXT NOT NULL DEFAULT 'backlog',
    content TEXT NOT NULL,
    tag TEXT DEFAULT '',
    priority INTEGER DEFAULT 3,
    subtasks TEXT DEFAULT '[]',    -- JSON array
    links TEXT DEFAULT '[]',       -- JSON array of {url, title}
    due_date TEXT,
    recurring TEXT,
    note TEXT DEFAULT '',
    archived INTEGER DEFAULT 0,
    decayed INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    triage_source TEXT,
    position INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    action TEXT NOT NULL,          -- insert | update | delete | move
    old_values TEXT,               -- JSON
    new_values TEXT,               -- JSON
    timestamp TEXT NOT NULL DEFAULT (datetime('now'))
);
```

## Columns

Single source of truth: `db.column_order()` in `db.py`. The frontend, README, and
LLM triage prompts all reference these IDs. If you ever add a column, update
`column_order()` first — nothing else is canonical.

| ID | Display |
|----|---------|
| `backlog` | 📚 Backlog |
| `week` | 📅 משימות השבוע |
| `doing` | 🚀 Doing |
| `done` | ✅ Done |

## API Endpoints

All endpoints require HTTP Basic Auth (`CANVAS_USER` / `CANVAS_PASS`).

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Kanban board (desktop) |
| GET | `/api/board` | Full board JSON |
| POST | `/api/cards` | Create card |
| POST | `/api/cards/<id>/move` | Move to column |
| DELETE | `/api/cards/<id>` | Delete card |
| POST | `/api/cards/<id>/edit` | Edit content |
| POST | `/api/cards/<id>/note` | Add/update note |
| POST | `/api/cards/<id>/tag` | Set tag |
| POST | `/api/cards/<id>/priority` | Set priority (P1-P5) |
| GET/POST | `/api/cards/<id>/subtasks` | Manage subtasks |
| POST | `/api/cards/<id>/subtasks/<sid>/toggle` | Toggle subtask |
| POST | `/api/cards/<id>/links` | Add link |
| POST | `/api/cards/<id>/due_date` | Set due date |
| POST | `/api/cards/<id>/recurring` | Set recurrence |
| POST | `/api/cards/<id>/remind` | Trigger Telegram reminder |
| POST | `/api/smart-archive` | Auto-archive done tasks |
| GET | `/api/eisenhower` | Eisenhower matrix view |
| POST | `/api/recurring/check` | Check and renew recurring tasks |
| POST | `/api/auto-tag` | Auto-tag based on keywords |
| GET | `/archive` | Archived tasks page |
| GET | `/analytics` | Analytics dashboard |

## Running

```bash
cd /home/andrew/task-canvas
python3 app.py
# Serves on http://127.0.0.1:5050
```

The server also exposes a CLI command bar at `/api/tt` for LLM-powered smart triage.

## Deployment

- **Local:** Flask binds `127.0.0.1:5050`
- **External:** Cloudflare Tunnel → `andrew.avolkov.click`
- **Auth:** HTTP Basic Auth (env vars `CANVAS_USER` / `CANVAS_PASS`, defaults: `andrew` / `hermes666`)

## Tech Stack

- Python 3.11+ / Flask
- SQLite (WAL mode, `tasks.db`)
- Vanilla HTML/CSS/JS (no framework)
- Cloudflare Tunnel for public access
