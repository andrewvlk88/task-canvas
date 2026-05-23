"""SQLite storage for Task Canvas — replaces tasks.json."""
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path.home() / ".hermes" / "tasks.db"


def get_db() -> sqlite3.Connection:
    """Return a connection with WAL mode and foreign keys enabled."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            column_id TEXT NOT NULL DEFAULT 'backlog',
            content TEXT NOT NULL,
            tag TEXT DEFAULT '',
            priority INTEGER DEFAULT 3,
            subtasks TEXT DEFAULT '[]',
            links TEXT DEFAULT '[]',
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

        CREATE INDEX IF NOT EXISTS idx_tasks_column ON tasks(column_id, position);

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_values TEXT,
            new_values TEXT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_log(task_id);
    """)
    conn.commit()
    conn.close()


def column_order() -> List[str]:
    """Return column IDs in display order."""
    return ["backlog", "week", "doing", "done"]


def get_all_cards() -> Dict[str, List[Dict]]:
    """Return {column_id: [card_dict, ...]} for all non-archived cards."""
    conn = get_db()
    result = {cid: [] for cid in column_order()}
    rows = conn.execute(
        "SELECT * FROM tasks WHERE archived = 0 ORDER BY column_id, position"
    ).fetchall()
    conn.close()
    for row in rows:
        card = dict(row)
        card["subtasks"] = json.loads(card["subtasks"])
        card["links"] = json.loads(card["links"])
        card["archived"] = bool(card["archived"])
        card["decayed"] = bool(card["decayed"])
        card["done"] = bool(card["done"])
        result.setdefault(card["column_id"], []).append(card)
    return result


def get_archived_cards() -> List[Dict]:
    """Return all archived cards."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE archived = 1 ORDER BY updated_at DESC"
    ).fetchall()
    conn.close()
    cards = []
    for row in rows:
        card = dict(row)
        card["subtasks"] = json.loads(card["subtasks"])
        card["links"] = json.loads(card["links"])
        card["archived"] = True
        card["decayed"] = bool(card["decayed"])
        card["done"] = bool(card["done"])
        cards.append(card)
    return cards


def insert_card(card: Dict) -> None:
    """Insert a new card. card must have id, column_id, content."""
    conn = get_db()
    cur = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE column_id = ?",
        (card["column_id"],),
    )
    position = cur.fetchone()[0]
    conn.execute(
        """INSERT INTO tasks (id, column_id, content, tag, priority, subtasks, links,
           due_date, recurring, note, archived, decayed, done, triage_source, position,
           created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            card["id"],
            card["column_id"],
            card["content"],
            card.get("tag", ""),
            card.get("priority", 3),
            json.dumps(card.get("subtasks", [])),
            json.dumps(card.get("links", [])),
            card.get("due_date"),
            card.get("recurring"),
            card.get("note", ""),
            int(card.get("archived", False)),
            int(card.get("decayed", False)),
            int(card.get("done", False)),
            card.get("triage_source"),
            position,
            card["created_at"],
            card["updated_at"],
        ),
    )
    _audit(conn, card["id"], "insert", None, card)
    conn.commit()
    conn.close()


def update_card(card_id: str, updates: Dict) -> None:
    """Update fields on a card. Only updates provided keys."""
    conn = get_db()
    old = conn.execute("SELECT * FROM tasks WHERE id = ?", (card_id,)).fetchone()
    if not old:
        conn.close()
        return
    allowed = {
        "content", "tag", "priority", "due_date", "recurring", "note",
        "archived", "decayed", "done", "triage_source", "column_id"
    }
    sets = []
    values = []
    for k in allowed:
        if k in updates:
            val = updates[k]
            if k in ("archived", "decayed", "done"):
                val = int(val)
            sets.append(f"{k} = ?")
            values.append(val)
    if "subtasks" in updates:
        sets.append("subtasks = ?")
        values.append(json.dumps(updates["subtasks"]))
    if "links" in updates:
        sets.append("links = ?")
        values.append(json.dumps(updates["links"]))
    if not sets:
        conn.close()
        return
    sets.append("updated_at = ?")
    values.append(datetime.now().isoformat())
    values.append(card_id)
    conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", values)
    new = conn.execute("SELECT * FROM tasks WHERE id = ?", (card_id,)).fetchone()
    _audit(conn, card_id, "update", dict(old) if old else None, dict(new) if new else None)
    conn.commit()
    conn.close()


def delete_card(card_id: str) -> None:
    """Hard-delete a card and audit it."""
    conn = get_db()
    old = conn.execute("SELECT * FROM tasks WHERE id = ?", (card_id,)).fetchone()
    if old:
        _audit(conn, card_id, "delete", dict(old), None)
        conn.execute("DELETE FROM tasks WHERE id = ?", (card_id,))
    conn.commit()
    conn.close()


def move_card_to_column(card_id: str, target_column: str) -> None:
    """Move a card to a different column, reordering positions."""
    conn = get_db()
    conn.execute("UPDATE tasks SET column_id = ?, position = -1, updated_at = ? WHERE id = ?",
                 (target_column, datetime.now().isoformat(), card_id))
    cur = conn.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM tasks WHERE column_id = ? AND id != ?",
        (target_column, card_id),
    )
    new_pos = cur.fetchone()[0]
    conn.execute("UPDATE tasks SET position = ? WHERE id = ?", (new_pos, card_id))
    _audit(conn, card_id, "move", {"column_id": "?"}, {"column_id": target_column})
    conn.commit()
    conn.close()


def decay_priorities() -> int:
    """Decay P1 cards older than 72 hours → P2. Returns count of decayed."""
    from datetime import timedelta
    conn = get_db()
    threshold = (datetime.now() - timedelta(hours=72)).isoformat()
    rows = conn.execute(
        """SELECT id FROM tasks
           WHERE priority = 1 AND decayed = 0 AND column_id != 'done'
           AND created_at < ?""",
        (threshold,),
    ).fetchall()
    now = datetime.now().isoformat()
    count = 0
    for row in rows:
        conn.execute(
            "UPDATE tasks SET priority = 2, decayed = 1, updated_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        count += 1
    conn.commit()
    conn.close()
    return count


def _audit(conn: sqlite3.Connection, task_id: str, action: str,
           old: Optional[Dict], new: Optional[Dict]) -> None:
    """Write an audit log entry."""
    conn.execute(
        "INSERT INTO audit_log (task_id, action, old_values, new_values) VALUES (?, ?, ?, ?)",
        (
            task_id,
            action,
            json.dumps(old, default=str) if old else None,
            json.dumps(new, default=str) if new else None,
        ),
    )


def migrate_from_json(json_path: Path) -> int:
    """Import tasks from tasks.json into SQLite. Returns count of imported cards."""
    if not json_path.exists():
        return 0
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    count = 0
    for col in data.get("columns", []):
        for pos, card in enumerate(col.get("cards", [])):
            card["column_id"] = col["id"]
            card.setdefault("tag", "")
            card.setdefault("priority", 3)
            card.setdefault("subtasks", [])
            card.setdefault("links", [])
            card.setdefault("due_date", None)
            card.setdefault("recurring", None)
            card.setdefault("note", card.get("note", ""))
            card.setdefault("archived", card.get("archived", False))
            card.setdefault("decayed", card.get("decayed", False))
            card.setdefault("done", card.get("done", False))
            card.setdefault("position", pos)
            card.setdefault("triaged_source", card.get("triaged_source"))
            now = datetime.now().isoformat()
            card.setdefault("created_at", now)
            card.setdefault("updated_at", card.get("created_at", now))
            insert_card(card)
            count += 1
    return count


def reorder_card(card_id: str, target_column: str, target_position: int) -> None:
    """Move a card to a specific position in target_column, reordering both source and target columns."""
    conn = get_db()
    # 1. Get current column of the card
    row = conn.execute("SELECT column_id, position FROM tasks WHERE id = ?", (card_id,)).fetchone()
    if not row:
        conn.close()
        return
    source_column = row["column_id"]
    old_pos = row["position"]
    
    # 2. Get all other non-archived cards in target column, sorted by position
    target_cards = conn.execute(
        "SELECT id FROM tasks WHERE column_id = ? AND archived = 0 AND id != ? ORDER BY position",
        (target_column, card_id)
    ).fetchall()
    target_card_ids = [r["id"] for r in target_cards]
    
    # Insert card_id at target_position
    if target_position < 0:
        target_position = 0
    if target_position > len(target_card_ids):
        target_position = len(target_card_ids)
    target_card_ids.insert(target_position, card_id)
    
    # Update positions in target column
    now = datetime.now().isoformat()
    for idx, cid in enumerate(target_card_ids):
        conn.execute(
            "UPDATE tasks SET column_id = ?, position = ?, updated_at = ? WHERE id = ?",
            (target_column, idx, now, cid)
        )
        
    # 3. If source and target are different, also re-index source column to prevent gaps
    if source_column != target_column:
        source_cards = conn.execute(
            "SELECT id FROM tasks WHERE column_id = ? AND archived = 0 AND id != ? ORDER BY position",
            (source_column, card_id)
        ).fetchall()
        for idx, r in enumerate(source_cards):
            conn.execute(
                "UPDATE tasks SET position = ?, updated_at = ? WHERE id = ?",
                (idx, now, r["id"])
            )
            
    _audit(conn, card_id, "move", {"column_id": source_column, "position": old_pos}, {"column_id": target_column, "position": target_position})
    conn.commit()
    conn.close()
