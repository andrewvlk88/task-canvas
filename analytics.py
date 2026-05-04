from datetime import datetime, timedelta
import json
from pathlib import Path

def generate_analytics(data):
    # data is the output of load_tasks()
    stats = {
        "tag_distribution": {},
        "completion_rate": 0,
        "velocity": {},
        "bottlenecks": {},
        "stale": []
    }
    return stats
