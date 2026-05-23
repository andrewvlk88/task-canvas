#!/usr/bin/env python3
"""
Task Canvas — Kanban Board (5 columns, tags, RTL) with subtasks, priority, links, due_date, recurring.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

# Load .env for Telegram token
env_path = Path.home() / ".hermes" / ".env"
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                if key not in os.environ:
                    os.environ[key] = val.strip().strip('"').strip("'")

import analytics_utils
from db import (
    init_db, get_all_cards, migrate_from_json, decay_priorities,
    insert_card, update_card, delete_card as db_delete_card, move_card_to_column, get_archived_cards,
    reorder_card,
)
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__, static_folder="static", template_folder="templates")

TASKS_FILE = Path.home() / ".hermes" / "tasks.json"  # legacy — migrated to SQLite
USERNAME = os.environ.get("CANVAS_USER", "andrew")
PASSWORD = os.environ.get("CANVAS_PASS", "hermes666")


def check_auth(username: str, password: str) -> bool:
    return username == USERNAME and password == PASSWORD


def authenticate() -> Response:
    return Response(
        "Access denied. Please log in.",
        401,
        {"WWW-Authenticate": 'Basic realm="Andrew Canvas"'},
    )


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)

    return decorated


# ----------------------- data -----------------------
COLUMN_TITLES = {
    "backlog": "📚 Backlog",
    "week": "📅 משימות השבוע",
    "inprogress": "🚀 In Progress",
    "waiting": "⏳ במעקב",
    "done": "✅ Done",
}


def load_tasks() -> Dict[str, Any]:
    from db import column_order

    init_db()

    # one-time migration from JSON (only if db is empty)
    from db import get_db
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    if count == 0 and TASKS_FILE.exists():
        migrate_from_json(TASKS_FILE)

    decay_priorities()
    cards = get_all_cards()

    columns = []
    for cid in column_order():
        columns.append({
            "id": cid,
            "title": COLUMN_TITLES.get(cid, cid),
            "cards": cards.get(cid, []),
        })
    return {"columns": columns}


def save_tasks(data: Dict[str, Any]) -> None:
    """No-op: all mutations now write directly to db via update_card/insert_card etc.
    Kept for backward compatibility with routes that still call it."""
    pass


TASKS_MD = Path.home() / ".hermes" / "tasks.md"


def sync_json_to_md() -> None:
    from db import get_all_cards, column_order
    cards = get_all_cards()
    lines = ["# 📋 Andrew's Tasks\n"]
    for cid in column_order():
        title = COLUMN_TITLES.get(cid, cid)
        lines.append(f"\n## {title}\n")
        for task in cards.get(cid, []):
            tag = task.get("tag", "")
            tag_str = f" `[{tag}]`" if tag else ""
            prio = task.get("priority", 3)
            prio_map = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢", 5: "⚪"}
            prio_str = prio_map.get(prio, "")
            lines.append(f"- [ ] {prio_str} {task['content']}{tag_str}")
        lines.append("")
    with open(TASKS_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ----------------------- tag detection (simple keyword match) -----------------------
WORK_KEYWORDS = [
    "rubrik",
    "בזק",
    "נמלי",
    "רמבם",
    "רמב\"ם",
    "m365",
    "ee",
    "רישוי",
    "קייס",
    "vmware",
    "k8s",
    "op",
    "שופרסל",
    "tabit",
    "exchange",
    "powershell",
    "dspm",
    "azure",
    "aws",
    "gitlab",
    "jenkins",
    "jira",
    "ticket",
    "deploy",
    "sprint",
    "standup",
    "PR",
    "review",
    "client",
    "לקוח",
]

PERSONAL_KEYWORDS = [
    "ארי",
    "ליר",
    "לירו",
    "לירון",
    "אדם",
    "סיגר",
    "ערק",
    "פוקר",
    "חבילה",
    "ברצלונה",
    "ברצה",
    "barca",
    "כושר",
    "שיפוד",
    "צלחת",
    "מפה",
    "איסוף",
    "פרוקסמוקס",
    "proxmox",
    "docker",
    "ollama",
    "שיפוד",
    "צלחת",
    "מפה",
    "חדר כושר",
    "gym",
    "קניות",
    "ילדים",
    "רופא",
]

DANGER_KEYWORDS = [
    "דחוף",
    "asap",
    "עכשיו",
    "היום",
    "בוקר",
    "הלילה",
    "עד מחר",
    "critical",
    "urgent",
    "blocker",
    "חירום",
    "SLA",
]


def detect_tag(content: str) -> str:
    c = content.lower()
    if any(k in c for k in WORK_KEYWORDS):
        return "עבודה"
    if any(k in c for k in PERSONAL_KEYWORDS):
        return "אישית"
    return ""


def detect_priority(content: str) -> int:
    c = content.lower()
    if any(k in c for k in DANGER_KEYWORDS):
        return 1
    if any(k in c for k in ["חשוב", "important", "היום"]):
        return 2
    if any(k in c for k in ["low", "אפשר לחכות", "when free"]):
        return 4
    if any(k in c for k in ["someday", "אולי", "רעיון"]):
        return 5
    return 3


# ----------------------- routes -----------------------
@app.route("/")
@require_auth
def index():
    return render_template("kanban.html")


@app.route("/api/board", methods=["GET"])
@require_auth
def get_board():
    data = load_tasks()
    sync_json_to_md()
    return jsonify(data)


@app.route("/api/cards", methods=["POST"])
@require_auth
def add_card():
    body = request.get_json(silent=True) or {}
    content: str = body.get("content", "").strip()
    column_id: str = body.get("column_id", "backlog")
    if not content:
        return jsonify({"error": "content is required"}), 400

    tag = body.get("tag") or detect_tag(content)
    priority = body.get("priority") or detect_priority(content)
    subtasks: List[Dict] = body.get("subtasks", [])
    links: List[str] = body.get("links", [])
    due_date: Optional[str] = body.get("due_date")
    recurring: Optional[str] = body.get("recurring")

    now = datetime.now()
    card = {
        "id": f"card-{now.strftime('%Y%m%d-%H%M%S-%f')}",
        "column_id": column_id,
        "content": content,
        "tag": tag,
        "priority": priority,
        "subtasks": subtasks,
        "links": links,
        "due_date": due_date,
        "recurring": recurring,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    insert_card(card)
    sync_json_to_md()
    return jsonify({"ok": True, "card": card})


@app.route("/api/cards/<card_id>/move", methods=["POST"])
@require_auth
def move_card(card_id: str):
    target_col = request.json.get("column_id")
    target_pos = request.json.get("position")
    if not target_col:
        return jsonify({"error": "column_id required"}), 400
    if target_pos is not None:
        reorder_card(card_id, target_col, int(target_pos))
    else:
        move_card_to_column(card_id, target_col)
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>", methods=["DELETE"])
@require_auth
def delete_card(card_id: str):
    db_delete_card(card_id)
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>/edit", methods=["POST"])
@require_auth
def edit_card(card_id: str):
    req_data = request.json or {}
    updates = {}
    if "content" in req_data:
        new_content = req_data.get("content", "").strip()
        if not new_content:
            return jsonify({"error": "content cannot be empty"}), 400
        updates["content"] = new_content
        if "tag" not in req_data:
            updates["tag"] = detect_tag(new_content)
        if "priority" not in req_data:
            updates["priority"] = detect_priority(new_content)
            
    # Support other fields as well for the single-save Card Modal
    for field in ["tag", "priority", "note", "due_date", "recurring", "subtasks", "links"]:
        if field in req_data:
            updates[field] = req_data[field]
            
    if not updates:
        return jsonify({"error": "no updates provided"}), 400
        
    update_card(card_id, updates)
    sync_json_to_md()
    return jsonify({"ok": True})

@app.route("/api/cards/<card_id>/note", methods=["POST"])
@require_auth
def set_note(card_id: str):
    note = request.json.get("note", "")
    update_card(card_id, {"note": note})
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>/tag", methods=["POST"])
@require_auth
def set_tag(card_id: str):
    tag = request.json.get("tag", "")
    update_card(card_id, {"tag": tag})
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>/priority", methods=["POST"])
@require_auth
def set_priority(card_id: str):
    priority = request.json.get("priority")
    if priority is None or not (1 <= int(priority) <= 5):
        return jsonify({"error": "priority must be 1-5"}), 400
    update_card(card_id, {"priority": int(priority)})
    sync_json_to_md()
    return jsonify({"ok": True})


# ---------- Subtasks ----------
@app.route("/api/cards/<card_id>/subtasks", methods=["GET"])
@require_auth
def get_subtasks(card_id: str):
    data = load_tasks()
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                return jsonify({"subtasks": card.get("subtasks", [])})
    return jsonify({"error": "card not found"}), 404


@app.route("/api/cards/<card_id>/subtasks", methods=["POST"])
@require_auth
def add_subtask(card_id: str):
    data = load_tasks()
    body = request.get_json(silent=True) or {}
    content: str = body.get("content", "").strip()
    if not content:
        return jsonify({"error": "subtask content required"}), 400
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                subtask = {
                    "id": f"sub-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
                    "content": content,
                    "done": False,
                }
                updated_subtasks = card.get("subtasks", []) + [subtask]
                update_card(card_id, {"subtasks": updated_subtasks})
                sync_json_to_md()
                return jsonify({"ok": True, "subtask": subtask})
    return jsonify({"error": "card not found"}), 404


@app.route("/api/cards/<card_id>/subtasks/<sub_id>/toggle", methods=["POST"])
@require_auth
def toggle_subtask(card_id: str, sub_id: str):
    data = load_tasks()
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                for sub in card.get("subtasks", []):
                    if sub["id"] == sub_id:
                        sub["done"] = not sub["done"]
                        update_card(card_id, {"subtasks": card["subtasks"]})
                        sync_json_to_md()
                        return jsonify({"ok": True, "subtask": sub})
                break
    return jsonify({"error": "subtask not found"}), 404


@app.route("/api/cards/<card_id>/subtasks/<sub_id>", methods=["DELETE"])
@require_auth
def delete_subtask(card_id: str, sub_id: str):
    data = load_tasks()
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                before = len(card.get("subtasks", []))
                card["subtasks"] = [s for s in card.get("subtasks", []) if s["id"] != sub_id]
                if len(card["subtasks"]) != before:
                    update_card(card_id, {"subtasks": card["subtasks"]})
                    sync_json_to_md()
                    return jsonify({"ok": True})
                break
    return jsonify({"error": "subtask not found"}), 404


# ---------- Links ----------
@app.route("/api/cards/<card_id>/links", methods=["POST"])
@require_auth
def add_link(card_id: str):
    data = load_tasks()
    body = request.get_json(silent=True) or {}
    url: str = body.get("url", "").strip()
    if not url:
        return jsonify({"error": "url required"}), 400
    if not re.match(r"^https?://", url):
        url = "http://" + url
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                updated_links = card.get("links", []) + [url]
                update_card(card_id, {"links": updated_links})
                sync_json_to_md()
                return jsonify({"ok": True, "link": url})
    return jsonify({"error": "card not found"}), 404


@app.route("/api/cards/<card_id>/links/<link_idx>", methods=["DELETE"])
@require_auth
def delete_link(card_id: str, link_idx: str):
    try:
        idx = int(link_idx)
    except ValueError:
        return jsonify({"error": "invalid index"}), 400
    data = load_tasks()
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                links = card.get("links", [])
                if 0 <= idx < len(links):
                    removed = links.pop(idx)
                    update_card(card_id, {"links": links})
                    sync_json_to_md()
                    return jsonify({"ok": True, "removed": removed})
                else:
                    return jsonify({"error": "index out of range"}), 400
    return jsonify({"error": "card not found"}), 404


# ---------- Due Date ----------
@app.route("/api/cards/<card_id>/due_date", methods=["POST"])
@require_auth
def set_due_date(card_id: str):
    due_date = request.json.get("due_date")
    update_card(card_id, {"due_date": due_date})
    sync_json_to_md()
    return jsonify({"ok": True, "due_date": due_date})


# ---------- Recurring ----------
@app.route("/api/cards/<card_id>/recurring", methods=["POST"])
@require_auth
def set_recurring(card_id: str):
    recurring = request.json.get("recurring")
    update_card(card_id, {"recurring": recurring})
    sync_json_to_md()
    return jsonify({"ok": True, "recurring": recurring})


# ---------- AI Breakdown ----------
@app.route("/api/cards/<card_id>/breakdown", methods=["POST"])
@require_auth
def ai_breakdown(card_id: str):
    """AI-powered task decomposition — calls ai_breakdown.py helper."""
    import subprocess, sys

    data = load_tasks()
    card_content = None
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card_content = card["content"]
                break
        if card_content:
            break
            
    # Fallback to payload content if card not found or has empty text
    if not card_content and request.json:
        card_content = request.json.get("content", "").strip()
        
    if not card_content:
        return jsonify({"error": "card content required"}), 404

    # Call the helper script
    helper_path = Path(__file__).parent / "ai_breakdown.py"
    try:
        result = subprocess.run(
            [sys.executable, str(helper_path), card_content],
            capture_output=True, text=True, timeout=90
        )
        subtask_texts = json.loads(result.stdout.strip())
    except Exception:
        # Fallback: naive comma split
        import re
        parts = [p.strip() for p in re.split(r",|;|\\.|ואז", card_content) if p.strip()]
        subtask_texts = parts if len(parts) > 1 else [card_content]

    now = datetime.now()
    subtasks = [
        {"id": f"sub-{now.strftime('%Y%m%d-%H%M%S-%f')}-{i}",
         "content": t, "done": False}
        for i, t in enumerate(subtask_texts[:7])
    ]

    # If it is a preview, return immediately without saving
    preview = False
    if request.json:
        preview = request.json.get("preview", False)
    if preview:
        return jsonify({"ok": True, "subtasks": subtasks})

    # Replace existing subtasks in database
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                update_card(card_id, {"subtasks": subtasks})
                sync_json_to_md()
                return jsonify({"ok": True, "subtasks_added": len(subtasks), "subtasks": subtasks})

    return jsonify({"error": "card not found"}), 404


# ---------- TT Webhook (Telegram → Task) ----------
@app.route("/api/tt", methods=["POST"])
def tt_webhook():
    """Receives {content, auth_token} and adds via Smart Triage. No auth required — uses shared token."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "").strip()
    token = body.get("auth_token", "")
    if token != PASSWORD or not content:
        return jsonify({"ok": False, "error": "unauthorized or empty"}), 403

    # Try LLM triage first, fallback to keyword
    triage = _llm_triage(content)

    card = {
        "id": f"card-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
        "column_id": triage["column"],
        "content": content,
        "tag": triage["tag"],
        "priority": triage["priority"],
        "subtasks": [], "links": [],
        "due_date": triage.get("due_date"),
        "recurring": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "triage_source": triage.get("source", "keyword"),
    }
    insert_card(card)
    sync_json_to_md()
    return jsonify({"ok": True, "card": card})


def _llm_triage(content: str) -> dict:
    """Run LLM classification; fallback to keyword if Hermes fails."""
    try:
        prompt = f"""You are Andrew's task classifier. Classify this Hebrew task:

Task: {content}

Andrew: works at Rubrik (cyber/cloud data protection), lives in Rosh HaAyin, wife Liron, kids Ari (5.5) and Adam (2.5).
Return ONLY a JSON object with these fields (no other text):
{{"tag": "עבודה"|"אישית"|"", "priority": 1-5, "column": "backlog"|"week"|"inprogress"|"waiting", "due_date": "YYYY-MM-DD or null"}}

Classification rules:
- Rubrik, clients, vendors, tech → "עבודה", P2
- Family, home, kids, errands, health → "אישית", P2-P3
- "דחוף", "חירום", "ASAP", "עד מחר", "הבוקר" → P1, column "inprogress"
- Date mentioned → set due_date; "השבוע" → column "week"
- Default → column "backlog", P3
"""
        result = subprocess.run(
            ["hermes", "--oneshot", prompt],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HERMES_ACCEPT_HOOKS": "1"}
        )
        output = result.stdout.strip()
        json_start = output.find("{")
        json_end = output.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            triage = json.loads(output[json_start:json_end])
            triage["source"] = "llm"
            return triage
    except Exception:
        pass
    # Fallback
    return {"tag": detect_tag(content), "priority": detect_priority(content),
            "column": smart_fallback(content)["column"], "due_date": None, "source": "keyword"}


# ---------- Smart Archive ----------
@app.route("/api/smart-archive", methods=["POST"])
@require_auth
def smart_archive():
    """Archive Done cards older than 7 days. Keeps them in Done column but marks as archived."""
    cards = get_all_cards()
    now = datetime.now()
    archived = 0
    for card in cards.get("done", []):
        created = datetime.fromisoformat(card.get("created_at", now.isoformat()))
        if not card.get("archived") and (now - created).total_seconds() > 72 * 3600:
            update_card(card["id"], {"archived": True})
            archived += 1
    if archived > 0:
        sync_json_to_md()
    return jsonify({"ok": True, "archived": archived})


# ---------- Quick Reminder ----------
@app.route("/api/cards/<card_id>/remind", methods=["POST"])
@require_auth
def quick_remind(card_id: str):
    """Sends or schedules a Telegram reminder. delay: 'now', '1h', '3h', 'morning', 'evening', or ISO datetime."""
    import urllib.request, os, subprocess, sys

    data = load_tasks()
    card_content = None
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card_content = card["content"]
                break
        if card_content:
            break
    if not card_content:
        return jsonify({"error": "card not found"}), 404

    delay = request.json.get("delay", "now") if request.json else "now"
    reminder_text = f"🔔 תזכורת: {card_content}"

    # Resolve delay to actual send time
    now = datetime.now()
    send_at = now
    if delay == "now":
        send_at = now
    elif delay == "1h":
        from datetime import timedelta
        send_at = now + timedelta(hours=1)
    elif delay == "3h":
        from datetime import timedelta
        send_at = now + timedelta(hours=3)
    elif delay == "morning":
        from datetime import timedelta
        tomorrow = now + timedelta(days=1)
        send_at = tomorrow.replace(hour=8, minute=0, second=0, microsecond=0)
    elif delay == "evening":
        from datetime import timedelta
        tomorrow = now + timedelta(days=1)
        send_at = tomorrow.replace(hour=18, minute=0, second=0, microsecond=0)
    else:
        # ISO datetime string
        try:
            send_at = datetime.fromisoformat(delay)
        except:
            send_at = now

    if send_at <= now:
        # Send immediately
        return _send_telegram_now(reminder_text)
    else:
        # Schedule via cron
        return _schedule_reminder(reminder_text, send_at, card_id)


def _send_telegram_now(text: str):
    import urllib.request, os
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = "359802219"
    success = False
    if bot_token:
        try:
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())
            success = result.get("ok", False)
        except:
            success = False
    return jsonify({"ok": True, "reminder": text, "sent": success})


def _schedule_reminder(text: str, send_at: datetime, card_id: str):
    """Schedules a one-shot cron job for the reminder using the native cronjob tool."""
    import http.client, json, os

    timestamp = send_at.strftime("%Y-%m-%dT%H:%M:%S")
    schedule_str = send_at.isoformat(timespec="seconds")

    # Build the cron prompt — the cron agent just needs to send the text
    prompt = f"Send this exact message to Andrew via Telegram: '{text}'"

    # Use the native Hermes gateway to create a cron job
    # POST directly to the gateway API so Hebrew survives
    gateway_port = os.environ.get("HERMES_GATEWAY_PORT", "9119")
    try:
        conn = http.client.HTTPConnection("127.0.0.1", gateway_port.split(":")[-1] if ":" in gateway_port else gateway_port, timeout=10)
        payload = json.dumps({
            "action": "create",
            "schedule": schedule_str,
            "prompt": prompt,
            "name": f"remind-{card_id[:20]}",
            "repeat": 1,
            "deliver": "origin"
        })
        conn.request("POST", "/api/cronjob", body=payload, headers={"Content-Type": "application/json"})
        resp = conn.getresponse()
        if resp.status == 200:
            return jsonify({"ok": True, "reminder": text, "sent": False, "scheduled": timestamp})
    except Exception:
        pass

    # Last resort: try CLI
    try:
        subprocess.run(
            ["hermes", "cron", "create",
             "--schedule", schedule_str,
             "--prompt", prompt,
             "--deliver", "origin",
             "--repeat", "1"],
            capture_output=True, timeout=15, env={**os.environ}
        )
        return jsonify({"ok": True, "reminder": text, "sent": False, "scheduled": timestamp})
    except Exception as e:
        return jsonify({"ok": False, "reminder": text, "error": f"Failed to schedule: {str(e)[:80]}"})


# ---------- Eisenhower Matrix ----------
@app.route("/api/eisenhower", methods=["GET"])
@require_auth
def eisenhower_data():
    """Returns tasks categorized by urgent/important based on priority + tag."""
    cards = get_all_cards()
    matrix = {
        "urgent_important": [],
        "not_urgent_important": [],
        "urgent_not_important": [],
        "not_urgent_not_important": [],
    }
    for cid, col_cards in cards.items():
        if cid == "done":
            continue
        for card in col_cards:
            entry = {"id": card["id"], "content": card["content"], "col": cid,
                     "priority": card.get("priority", 3), "tag": card.get("tag", ""),
                     "created_at": card.get("created_at", "")}
            p = card.get("priority", 3)
            t = card.get("tag", "")
            if p <= 2 and t == "עבודה":
                matrix["urgent_important"].append(entry)
            elif p <= 2 and t == "אישית":
                matrix["urgent_not_important"].append(entry)
            elif p > 2 and t == "עבודה":
                matrix["not_urgent_important"].append(entry)
            else:
                matrix["not_urgent_not_important"].append(entry)
    return jsonify({"ok": True, "matrix": matrix})


# ---------- Recurring Tasks Check (run on page load) ----------
@app.route("/api/recurring/check", methods=["POST"])
@require_auth
def check_recurring():
    """Check if recurring tasks need to be re-added. Returns count of tasks re-added."""
    cards = get_all_cards()
    count = 0
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%a").upper()[:2]

    for cid, col_cards in cards.items():
        for card in col_cards:
            recurring = card.get("recurring")
            if not recurring:
                continue
            last_check = card.get("last_recurring_check", "")
            if last_check == today_str and cid != "done":
                continue

            should_repeat = False
            if recurring == "daily":
                should_repeat = True
            elif recurring == "weekly":
                should_repeat = (now.weekday() == 0)
            elif recurring == "weekdays":
                should_repeat = (now.weekday() < 5)
            elif recurring == "monthly":
                should_repeat = (now.day == 1)
            elif recurring.startswith("custom:"):
                days = recurring.split(":")[1].split(",")
                should_repeat = (weekday in days)

            if should_repeat:
                new_card = {
                    "id": f"card-{now.strftime('%Y%m%d-%H%M%S-%f')}",
                    "column_id": "backlog",
                    "content": card["content"],
                    "tag": card.get("tag", ""),
                    "priority": card.get("priority", 3),
                    "subtasks": [],
                    "links": [],
                    "due_date": None,
                    "recurring": None,
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                insert_card(new_card)
                count += 1

            update_card(card["id"], {"note": f"last_recurring_check: {today_str}"})

    if count > 0:
        sync_json_to_md()
    return jsonify({"ok": True, "recurring_added": count})


# ---------- Auto-tag ----------
@app.route("/api/auto-tag", methods=["POST"])
@require_auth
def auto_tag_all():
    cards = get_all_cards()
    count = 0
    for cid, col_cards in cards.items():
        for card in col_cards:
            if not card.get("tag"):
                update_card(card["id"], {"tag": detect_tag(card["content"])})
                count += 1
    sync_json_to_md()
    return jsonify({"ok": True, "tagged": count})



@app.route("/analytics")
@require_auth
def analytics_page():
    return render_template("analytics.html")

# ---------- Archive Page ----------
@app.route("/archive")
@require_auth
def archive_page():
    return render_template("archive.html")

# ---------- Archived cards ----------
@app.route("/api/archived", methods=["GET"])
@require_auth
def get_archived():
    archived = get_archived_cards()
    result = [{"id": c["id"], "content": c["content"],
               "tag": c.get("tag",""), "priority": c.get("priority",3),
               "created_at": c.get("created_at",""), "col": c["column_id"]}
              for c in archived]
    return jsonify({"ok": True, "archived": result})

@app.route("/api/archived/<card_id>/restore", methods=["POST"])
@require_auth
def restore_archived(card_id: str):
    update_card(card_id, {"archived": False, "column_id": "backlog"})
    sync_json_to_md()
    return jsonify({"ok": True})

@app.route("/api/cards/<card_id>/archive", methods=["POST"])
@require_auth
def archive_card(card_id: str):
    update_card(card_id, {"archived": True})
    sync_json_to_md()
    return jsonify({"ok": True})



@app.route("/api/analytics", methods=["GET"])
@require_auth
def get_analytics():
    data = load_tasks()
    stats = analytics_utils.get_analytics(data)
    return jsonify(stats)


# ---------- Sports Ticker ----------
SPORTS_FILE = Path.home() / ".hermes" / "sports.json"

@app.route("/api/sports", methods=["GET"])
@require_auth
def get_sports():
    """Read sports data from dedicated JSON file (updated by cron jobs). No Canvas cards involved."""
    if SPORTS_FILE.exists():
        with open(SPORTS_FILE, "r", encoding="utf-8") as f:
            return jsonify(json.load(f))
    return jsonify({"barcelona": None, "f1": None})


@app.route("/api/sports", methods=["POST"])
@require_auth
def update_sports():
    """Cron jobs POST here to update the ticker data."""
    body = request.get_json(silent=True) or {}
    with open(SPORTS_FILE, "w", encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
    return jsonify({"ok": True})


# ───── CLI Command ─────
@app.route("/api/command", methods=["POST"])
@require_auth
def cli_command():
    """שורת פקודה חיה — Hermes מבצע את הפקודה על ה-Kanban."""
    body = request.get_json(silent=True) or {}
    command = body.get("command", "").strip()
    if not command:
        return jsonify({"error": "command required"}), 400

    # Build a one-shot prompt for Hermes
    prompt = f"""You are a Kanban board operator. The board uses SQLite at /home/andrew/.hermes/tasks.db.
The API is at http://localhost:5050/api with auth 'andrew:hermes666'.

Execute the user's command by making API calls. When done, print ONLY "OK: <brief Hebrew summary>".

Command: {command}

Rules:
- Use curl -u andrew:hermes666 for API calls
- Column IDs: backlog, week, inprogress, waiting, done
- Priority: 1 (highest) to 5 (lowest)
- Tags: "עבודה" or "אישית"
- Never ask for confirmation — just execute
- Print ONLY "OK: <summary>" when done
"""

    try:
        result = subprocess.run(
            ["hermes", "--oneshot", prompt],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "HERMES_ACCEPT_HOOKS": "1"}
        )
        output = result.stdout.strip() or result.stderr.strip()
        # Extract the OK: line
        ok_line = ""
        for line in output.split("\n"):
            if line.startswith("OK:"):
                ok_line = line
                break
        if not ok_line:
            ok_line = output[:150]
        return jsonify({"ok": True, "result": ok_line})
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "result": "⏰ הפקודה לקחה יותר מדי זמן"}), 504
    except Exception as e:
        return jsonify({"ok": False, "result": f"❌ {str(e)[:100]}"}), 500


# ───── Smart Triage ─────
@app.route("/api/cards/smart-add", methods=["POST"])
@require_auth
def smart_add():
    """LLM סיווג חכם — מנתח תוכן ומחליט תגית, עדיפות ועמודה."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400
    column_id = body.get("column_id", "backlog")

    # Let Hermes classify the task
    prompt = f"""You are Andrew's task classifier. Classify this Hebrew task:

Task: {content}

Andrew: works at Rubrik (cyber/cloud data protection), lives in Rosh HaAyin, wife Liron, kids Ari (5.5) and Adam (2.5).
Return ONLY a JSON object with these fields (no other text):
{{"tag": "עבודה"|"אישית"|"", "priority": 1-5, "column": "backlog"|"week"|"inprogress"|"waiting", "due_date": "YYYY-MM-DD or null"}}

Classification rules:
- Rubrik, clients, vendors, tech → "עבודה", P2
- Family, home, kids, errands, health → "אישית", P2-P3
- "דחוף", "חירום", "ASAP", "עד מחר", "הבוקר" → P1, column "inprogress"
- Date mentioned (e.g. "ביום שלישי", "מחר", "10/06") → set due_date
- "השבוע" → column "week"
- "צריך לבדוק", "להתקשר", "לשלוח" → column "inprogress" if urgent, else "week"
- Default → column "backlog", P3
"""

    try:
        result = subprocess.run(
            ["hermes", "--oneshot", prompt],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HERMES_ACCEPT_HOOKS": "1"}
        )
        output = result.stdout.strip()
        # Extract the JSON object from output
        json_start = output.find("{")
        json_end = output.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            triage = json.loads(output[json_start:json_end])
        else:
            # Fallback: keyword-based classification
            triage = smart_fallback(content)

        # Apply triage results
        tag = triage.get("tag") or detect_tag(content)
        priority = triage.get("priority") or detect_priority(content)
        target_column = triage.get("column", column_id)
        due_date = triage.get("due_date")

        card = {
            "id": f"card-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
            "column_id": target_column,
            "content": content,
            "tag": tag,
            "priority": int(priority),
            "subtasks": [],
            "links": [],
            "due_date": due_date,
            "recurring": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "triage_source": "llm" if json_start >= 0 else "fallback",
        }

        insert_card(card)
        sync_json_to_md()
        return jsonify({"ok": True, "card": card})
    except Exception as e:
        # Fallback to basic add
        return add_card()


def smart_fallback(content: str) -> dict:
    """Keyword-based fallback when LLM fails."""
    c = content.lower()
    tag = detect_tag(content)
    priority = detect_priority(content)
    column = "backlog"
    if any(k in c for k in ["דחוף", "asap", "עכשיו", "בוקר", "הלילה", "חירום"]):
        column = "inprogress"
    elif any(k in c for k in ["השבוע", "מחר", "שלישי", "רביעי", "חמישי", "שישי"]):
        column = "week"
    return {"tag": tag, "priority": priority, "column": column, "due_date": None}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"\n📋 Andrew's Task Canvas → http://localhost:{port}")
    print(f"   Username: {USERNAME}")
    app.run(host="127.0.0.1", port=port, debug=True)