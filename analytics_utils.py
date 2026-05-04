import json
from datetime import datetime, timedelta

def get_analytics(data):
    tags = {}
    total_tasks = 0
    done_tasks = 0
    
    # We will simulate velocity based on done column tasks updated_at
    velocity_by_day = {}
    stale_cards = []
    
    now = datetime.now()
    
    for col in data.get("columns", []):
        col_id = col.get("id")
        for card in col.get("cards", []):
            total_tasks += 1
            # Tag distribution
            tag = card.get("tag") or "ללא תגית"
            tags[tag] = tags.get(tag, 0) + 1
            
            # Completion rate & Velocity
            if col_id == "done":
                done_tasks += 1
                updated = card.get("updated_at", card.get("created_at"))
                if updated:
                    try:
                        dt = datetime.fromisoformat(updated)
                        day_str = dt.strftime("%Y-%m-%d")
                        velocity_by_day[day_str] = velocity_by_day.get(day_str, 0) + 1
                    except Exception:
                        pass
            
            # Stale tasks (in progress or week/today for > 48h)
            if col_id in ["inprogress", "today", "week"]:
                updated = card.get("updated_at", card.get("created_at"))
                if updated:
                    try:
                        dt = datetime.fromisoformat(updated)
                        hours_stale = (now - dt).total_seconds() / 3600
                        if hours_stale > 24:
                            stale_cards.append({
                                "content": card.get("content"),
                                "column": col.get("title"),
                                "hours": int(hours_stale)
                            })
                    except Exception:
                        pass
                        
    # sort velocity by date
    velocity = [{"date": k, "count": v} for k, v in sorted(velocity_by_day.items())[-14:]] # last 14 active days
    
    # Stale cards sorted by staleness
    stale_cards = sorted(stale_cards, key=lambda x: x["hours"], reverse=True)[:10]

    return {
        "tag_distribution": [{"tag": k, "count": v} for k, v in tags.items()],
        "completion_rate": int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0,
        "velocity": velocity,
        "stale": stale_cards,
        "total": total_tasks,
        "done": done_tasks
    }
