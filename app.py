#!/usr/bin/env python3
"""
Task Canvas — Kanban Board (5 columns, tags, RTL) with subtasks, priority, links, due_date, recurring.
"""

import json
import os
import re
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Dict, List, Optional

import analytics_utils
from flask import Flask, Response, jsonify, render_template, request

app = Flask(__name__, static_folder="static", template_folder="templates")

TASKS_FILE = Path.home() / ".hermes" / "tasks.json"
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
DEFAULT_COLUMNS = [
    {"id": "backlog", "title": "📚 Backlog", "cards": []},
    {"id": "week", "title": "📅 משימות השבוע", "cards": []},
    {"id": "inprogress", "title": "🚀 In Progress", "cards": []},
    {"id": "waiting", "title": "⏳ במעקב", "cards": []},
    {"id": "done", "title": "✅ Done", "cards": []},
]


def load_tasks() -> Dict[str, Any]:
    if not TASKS_FILE.exists():
        return {"columns": DEFAULT_COLUMNS}
    with open(TASKS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    # migrate old 3-col boards (only if fewer than 5 columns)
    if len(data.get("columns", [])) < 5:
        old_cards = []
        for col in data.get("columns", []):
            old_cards.extend(col.get("cards", []))
        data["columns"] = DEFAULT_COLUMNS
        data["columns"][0]["cards"] = old_cards
    # ensure each card has new fields
    for col in data["columns"]:
        for card in col["cards"]:
            card.setdefault("tag", "")
            card.setdefault("priority", 3)
            card.setdefault("subtasks", [])
            card.setdefault("links", [])
            card.setdefault("due_date", None)
            card.setdefault("recurring", None)
            card.setdefault("created_at", datetime.now().isoformat())
            card.setdefault("updated_at", datetime.now().isoformat())
            card.setdefault("decayed", False)

    # Priority Decay: P1 cards older than 72 hours → P2
    now = datetime.now()
    decayed_any = False
    for col in data["columns"]:
        for card in col["cards"]:
            if card.get("priority") == 1 and not card.get("decayed"):
                created = datetime.fromisoformat(card.get("created_at", now.isoformat()))
                if col["id"] != "done" and (now - created).total_seconds() > 72 * 3600:
                    card["priority"] = 2
                    card["decayed"] = True
                    card["updated_at"] = now.isoformat()
                    decayed_any = True
    if decayed_any:
        with open(TASKS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return data


def save_tasks(data: Dict[str, Any]) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TASKS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


TASKS_MD = Path.home() / ".hermes" / "tasks.md"


def sync_json_to_md() -> None:
    data = load_tasks()
    lines = ["# 📋 Andrew's Tasks\n"]
    for col in data.get("columns", []):
        lines.append(f"\n## {col['title']}\n")
        for task in col.get("cards", []):
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
    data = load_tasks()
    body = request.get_json(silent=True) or {}
    content: str = body.get("content", "").strip()
    column_id: str = body.get("column_id", "backlog")
    if not content:
        return jsonify({"error": "content is required"}), 400

    tag = body.get("tag") or detect_tag(content)
    priority = body.get("priority") or detect_priority(content)
    # support subtasks, links, due_date, recurring from body
    subtasks: List[Dict] = body.get("subtasks", [])
    links: List[str] = body.get("links", [])
    due_date: Optional[str] = body.get("due_date")
    recurring: Optional[str] = body.get("recurring")

    card = {
        "id": f"card-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
        "content": content,
        "tag": tag,
        "priority": priority,
        "subtasks": subtasks,
        "links": links,
        "due_date": due_date,
        "recurring": recurring,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    for col in data["columns"]:
        if col["id"] == column_id:
            col["cards"].append(card)
            break

    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True, "card": card})


@app.route("/api/cards/<card_id>/move", methods=["POST"])
@require_auth
def move_card(card_id: str):
    data = load_tasks()
    target_col = request.json.get("column_id")
    found = None
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                found = card
                col["cards"].remove(card)
                break
        if found:
            break
    if not found:
        return jsonify({"error": "card not found"}), 404
    for col in data["columns"]:
        if col["id"] == target_col:
            col["cards"].append(found)
            break
    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>", methods=["DELETE"])
@require_auth
def delete_card(card_id: str):
    data = load_tasks()
    for col in data["columns"]:
        col["cards"] = [c for c in col["cards"] if c["id"] != card_id]
    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>/edit", methods=["POST"])
@require_auth
def edit_card(card_id: str):
    data = load_tasks()
    new_content = request.json.get("content", "").strip()
    if not new_content:
        return jsonify({"error": "content is required"}), 400
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["content"] = new_content
                # update tag/priority if not provided explicitly
                if "tag" not in request.json:
                    card["tag"] = detect_tag(new_content)
                if "priority" not in request.json:
                    card["priority"] = detect_priority(new_content)
                card["updated_at"] = datetime.now().isoformat()
                break
    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>/tag", methods=["POST"])
@require_auth
def set_tag(card_id: str):
    data = load_tasks()
    tag = request.json.get("tag", "")
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["tag"] = tag
                card["updated_at"] = datetime.now().isoformat()
                break
    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True})


@app.route("/api/cards/<card_id>/priority", methods=["POST"])
@require_auth
def set_priority(card_id: str):
    data = load_tasks()
    priority = request.json.get("priority")
    if priority is None or not (1 <= int(priority) <= 5):
        return jsonify({"error": "priority must be 1-5"}), 400
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["priority"] = int(priority)
                card["updated_at"] = datetime.now().isoformat()
                break
    save_tasks(data)
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
                card.setdefault("subtasks", []).append(subtask)
                card["updated_at"] = datetime.now().isoformat()
                save_tasks(data)
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
                        card["updated_at"] = datetime.now().isoformat()
                        save_tasks(data)
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
                    card["updated_at"] = datetime.now().isoformat()
                    save_tasks(data)
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
    # basic validation
    if not re.match(r"^https?://", url):
        url = "http://" + url
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card.setdefault("links", []).append(url)
                card["updated_at"] = datetime.now().isoformat()
                save_tasks(data)
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
                    card["updated_at"] = datetime.now().isoformat()
                    save_tasks(data)
                    sync_json_to_md()
                    return jsonify({"ok": True, "removed": removed})
                else:
                    return jsonify({"error": "index out of range"}), 400
    return jsonify({"error": "card not found"}), 404


# ---------- Due Date ----------
@app.route("/api/cards/<card_id>/due_date", methods=["POST"])
@require_auth
def set_due_date(card_id: str):
    data = load_tasks()
    due_date = request.json.get("due_date")  # expect ISO string or null
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["due_date"] = due_date
                card["updated_at"] = datetime.now().isoformat()
                save_tasks(data)
                sync_json_to_md()
                return jsonify({"ok": True, "due_date": due_date})
    return jsonify({"error": "card not found"}), 404


# ---------- Recurring ----------
@app.route("/api/cards/<card_id>/recurring", methods=["POST"])
@require_auth
def set_recurring(card_id: str):
    data = load_tasks()
    recurring = request.json.get("recurring")  # e.g., "daily", "weekly", "weekdays", "monthly", "custom:MO,WE,FR"
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["recurring"] = recurring
                card["updated_at"] = datetime.now().isoformat()
                save_tasks(data)
                sync_json_to_md()
                return jsonify({"ok": True, "recurring": recurring})
    return jsonify({"error": "card not found"}), 404


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
    if not card_content:
        return jsonify({"error": "card not found"}), 404

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
        parts = [p.strip() for p in re.split(r",|;|\\.|ואז", card_content) if p.strip()]
        subtask_texts = parts if len(parts) > 1 else [card_content]

    now = datetime.now()
    subtasks = [
        {"id": f"sub-{now.strftime('%Y%m%d-%H%M%S-%f')}-{i}",
         "content": t, "done": False}
        for i, t in enumerate(subtask_texts[:7])
    ]

    # Replace existing subtasks
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["subtasks"] = subtasks
                card["updated_at"] = now.isoformat()
                save_tasks(data)
                sync_json_to_md()
                return jsonify({"ok": True, "subtasks_added": len(subtasks), "subtasks": subtasks})

    return jsonify({"error": "card not found"}), 404


# ---------- TT Webhook (Telegram → Task) ----------
@app.route("/api/tt", methods=["POST"])
def tt_webhook():
    """Receives {content, auth_token} and adds to backlog. No auth required — uses shared token."""
    body = request.get_json(silent=True) or {}
    content = body.get("content", "").strip()
    token = body.get("auth_token", "")
    if token != PASSWORD or not content:
        return jsonify({"ok": False, "error": "unauthorized or empty"}), 403

    data = load_tasks()
    tag = detect_tag(content)
    priority = detect_priority(content)
    card = {
        "id": f"card-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}",
        "content": content, "tag": tag, "priority": priority,
        "subtasks": [], "links": [], "due_date": None, "recurring": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    for col in data["columns"]:
        if col["id"] == "backlog":
            col["cards"].append(card)
            break
    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True, "card": card})


# ---------- Smart Archive ----------
@app.route("/api/smart-archive", methods=["POST"])
@require_auth
def smart_archive():
    """Archive Done cards older than 7 days. Keeps them in Done column but marks as archived."""
    data = load_tasks()
    now = datetime.now()
    archived = 0
    for col in data["columns"]:
        if col["id"] != "done":
            continue
        for card in col["cards"]:
            created = datetime.fromisoformat(card.get("created_at", now.isoformat()))
            if not card.get("archived") and (now - created).total_seconds() > 7 * 86400:
                card["archived"] = True
                card["updated_at"] = now.isoformat()
                archived += 1
    if archived > 0:
        save_tasks(data)
        sync_json_to_md()
    return jsonify({"ok": True, "archived": archived})


# ---------- Quick Reminder ----------
@app.route("/api/cards/<card_id>/remind", methods=["POST"])
@require_auth
def quick_remind(card_id: str):
    """Sends a Telegram reminder via Hermes. Falls back to returning the link."""
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

    reminder_text = f"🔔 תזכורת: {card_content}"
    # Try sending via Hermes send_message
    try:
        import subprocess, sys
        subprocess.run(
            [sys.executable, "-c", f'''
import urllib.request, json
data = json.dumps({{"message": "{reminder_text}"}}).encode()
req = urllib.request.Request("http://localhost:5050/api/tt", data=data, headers={{"Content-Type":"application/json"}})
'''],
            capture_output=True, timeout=10
        )
    except:
        pass

    return jsonify({"ok": True, "reminder": reminder_text, "link": f"https://zone-shadily-chowder.ngrok-free.dev"})


# ---------- Eisenhower Matrix ----------
@app.route("/api/eisenhower", methods=["GET"])
@require_auth
def eisenhower_data():
    """Returns tasks categorized by urgent/important based on priority + tag."""
    data = load_tasks()
    matrix = {
        "urgent_important": [],       # P1, tag=עבודה
        "not_urgent_important": [],   # P2, tag=עבודה
        "urgent_not_important": [],   # P1, tag=אישית
        "not_urgent_not_important": [],  # rest
    }
    for col in data["columns"]:
        if col["id"] == "done":
            continue
        for card in col["cards"]:
            entry = {"id": card["id"], "content": card["content"], "col": col["id"],
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
    count = 0
    data = load_tasks()
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    weekday = now.strftime("%a").upper()[:2]  # MO, TU, etc.

    for col in data["columns"]:
        for card in col["cards"]:
            recurring = card.get("recurring")
            if not recurring:
                continue
            # Check if already handled today
            last_check = card.get("last_recurring_check", "")
            if last_check == today_str and col["id"] != "done":
                continue

            should_repeat = False
            if recurring == "daily":
                should_repeat = True
            elif recurring == "weekly":
                should_repeat = (now.weekday() == 0)  # Monday
            elif recurring == "weekdays":
                should_repeat = (now.weekday() < 5)
            elif recurring == "monthly":
                should_repeat = (now.day == 1)
            elif recurring.startswith("custom:"):
                days = recurring.split(":")[1].split(",")
                should_repeat = (weekday in days)

            if should_repeat:
                # Clone the card and add to backlog
                new_card = {
                    "id": f"card-{now.strftime('%Y%m%d-%H%M%S-%f')}",
                    "content": card["content"],
                    "tag": card.get("tag", ""),
                    "priority": card.get("priority", 3),
                    "subtasks": [],
                    "links": [],
                    "due_date": None,
                    "recurring": None,  # don't recurse
                    "created_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }
                for c in data["columns"]:
                    if c["id"] == "backlog":
                        c["cards"].append(new_card)
                        break
                count += 1

            card["last_recurring_check"] = today_str
            card["updated_at"] = now.isoformat()

    if count > 0:
        save_tasks(data)
        sync_json_to_md()
    return jsonify({"ok": True, "recurring_added": count})


# ---------- Auto-tag ----------
@app.route("/api/auto-tag", methods=["POST"])
@require_auth
def auto_tag_all():
    data = load_tasks()
    count = 0
    for col in data["columns"]:
        for card in col["cards"]:
            if not card.get("tag"):
                card["tag"] = detect_tag(card["content"])
                count += 1
    save_tasks(data)
    sync_json_to_md()
    return jsonify({"ok": True, "tagged": count})



@app.route("/analytics")
@require_auth
def analytics_page():
    return render_template("analytics.html")

# ---------- Archived cards ----------
@app.route("/api/archived", methods=["GET"])
@require_auth
def get_archived():
    data = load_tasks()
    archived = []
    for col in data["columns"]:
        for card in col["cards"]:
            if card.get("archived"):
                archived.append({"id": card["id"], "content": card["content"],
                    "tag": card.get("tag",""), "priority": card.get("priority",3),
                    "created_at": card.get("created_at",""), "col": col["id"]})
    return jsonify({"ok": True, "archived": archived})

@app.route("/api/archived/<card_id>/restore", methods=["POST"])
@require_auth
def restore_archived(card_id: str):
    data = load_tasks()
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["archived"] = False
                card["updated_at"] = datetime.now().isoformat()
                # Move to backlog
                for c in data["columns"]:
                    if c["id"] == "backlog":
                        c["cards"].append(card)
                        col["cards"].remove(card)
                        break
                save_tasks(data)
                sync_json_to_md()
                return jsonify({"ok": True})
    return jsonify({"error": "card not found"}), 404

@app.route("/api/cards/<card_id>/archive", methods=["POST"])
@require_auth
def archive_card(card_id: str):
    data = load_tasks()
    for col in data["columns"]:
        for card in col["cards"]:
            if card["id"] == card_id:
                card["archived"] = True
                card["updated_at"] = datetime.now().isoformat()
                save_tasks(data)
                sync_json_to_md()
                return jsonify({"ok": True})
    return jsonify({"error": "card not found"}), 404



@app.route("/api/analytics", methods=["GET"])
@require_auth
def get_analytics():
    data = load_tasks()
    stats = analytics_utils.get_analytics(data)
    return jsonify(stats)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    print(f"\n📋 Andrew's Task Canvas → http://localhost:{port}")
    print(f"   Username: {USERNAME}")
    app.run(host="0.0.0.0", port=port, debug=True)