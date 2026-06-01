import os
import pytest
from pathlib import Path
from datetime import datetime

# Set dummy env vars for CI collection/testing so app.py doesn't sys.exit(1)
if not os.environ.get("CANVAS_USER"):
    os.environ["CANVAS_USER"] = "test_user"
if not os.environ.get("CANVAS_PASS"):
    os.environ["CANVAS_PASS"] = "test_pass"

# Redirect database path to a test-isolated location
import db
TEST_DB = Path("/tmp/test_tasks.db")
if TEST_DB.exists():
    try:
        TEST_DB.unlink()
    except OSError:
        pass
db.DB_PATH = TEST_DB

from db import init_db, insert_card, get_all_cards, column_order, move_card_to_column
import app


@pytest.fixture(autouse=True)
def setup_test_db():
    """Wipes and re-initializes the test database before each test run."""
    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except OSError:
            pass
    init_db()
    yield
    if TEST_DB.exists():
        try:
            TEST_DB.unlink()
        except OSError:
            pass


def test_column_order():
    """Verifies that columns are canonical and exactly 4."""
    cols = column_order()
    assert cols == ["backlog", "week", "doing", "done"]


def test_insert_and_get_cards():
    """Tests card insertion, auto-positioning, and retrieval."""
    card1 = {
        "id": "card-1",
        "column_id": "backlog",
        "content": "Test task 1",
        "priority": 3,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    insert_card(card1)

    cards = get_all_cards()
    assert len(cards["backlog"]) == 1
    assert cards["backlog"][0]["content"] == "Test task 1"
    assert cards["backlog"][0]["position"] == 0


def test_move_card():
    """Tests moving a card between columns and resetting position indices."""
    card = {
        "id": "card-move-test",
        "column_id": "backlog",
        "content": "To be moved",
        "priority": 3,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }
    insert_card(card)
    move_card_to_column("card-move-test", "doing")

    cards = get_all_cards()
    assert len(cards["backlog"]) == 0
    assert len(cards["doing"]) == 1
    assert cards["doing"][0]["id"] == "card-move-test"


def test_smart_fallback():
    """Tests keyword-based fallback triage classification."""
    triage1 = app.smart_fallback("דחוף להתקשר לבזק")
    assert triage1["priority"] == 1  # "דחוף" triggers P1
    assert triage1["column"] == "doing"  # "דחוף" triggers "doing" column

    triage2 = app.smart_fallback("לקנות חלב מחר")
    assert triage2["column"] == "week"  # "מחר" triggers "week" column
