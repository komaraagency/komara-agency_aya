"""Persistance locale d'Aya : prospects, événements, tâches et relances.

SQLite est utilisé par défaut pour que le worker ne perde plus les prospects au
redémarrage. La base peut être placée sur un volume persistant via AYA_DATA_DIR.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    root = Path(os.getenv("AYA_DATA_DIR", "."))
    root.mkdir(parents=True, exist_ok=True)
    return root / "aya.sqlite3"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(_db_path())
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with _connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                chat_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                need TEXT NOT NULL DEFAULT '',
                budget TEXT NOT NULL DEFAULT '',
                timeline TEXT NOT NULL DEFAULT '',
                pain TEXT NOT NULL DEFAULT '',
                offer_id TEXT NOT NULL DEFAULT '',
                stage TEXT NOT NULL DEFAULT 'accroche',
                score INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'new',
                state_json TEXT NOT NULL DEFAULT '{}',
                last_message_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                due_at TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                sent_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_followups_due ON followups(status, due_at);
            """
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(leads)")}
        if "state_json" not in columns:
            db.execute("ALTER TABLE leads ADD COLUMN state_json TEXT NOT NULL DEFAULT '{}'")


def upsert_lead(chat_id: int, state: dict[str, Any], score: int = 0, status: str = "active") -> None:
    now = datetime.now(timezone.utc).isoformat()
    fields = {key: str(state.get(key, "")) for key in ("name", "need", "budget", "timeline", "pain", "offer_id", "stage")}
    with _connect() as db:
        db.execute(
            """INSERT INTO leads(chat_id,name,need,budget,timeline,pain,offer_id,stage,score,status,state_json,last_message_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET name=excluded.name,need=excluded.need,budget=excluded.budget,
               timeline=excluded.timeline,pain=excluded.pain,offer_id=excluded.offer_id,stage=excluded.stage,
               score=excluded.score,status=excluded.status,state_json=excluded.state_json,last_message_at=excluded.last_message_at,updated_at=excluded.updated_at""",
            (chat_id, fields["name"], fields["need"], fields["budget"], fields["timeline"], fields["pain"], fields["offer_id"], fields["stage"], score, status, json.dumps(state, ensure_ascii=False), now, now, now),
        )


def record_event(chat_id: int, event_type: str, payload: dict[str, Any] | None = None) -> None:
    with _connect() as db:
        db.execute("INSERT INTO events(chat_id,event_type,payload,created_at) VALUES(?,?,?,?)", (chat_id, event_type, json.dumps(payload or {}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))


def schedule_followup(chat_id: int, message: str, delay_hours: int = 24) -> int:
    due = datetime.now(timezone.utc) + timedelta(hours=max(1, delay_hours))
    with _connect() as db:
        cursor = db.execute("INSERT INTO followups(chat_id,due_at,message) VALUES(?,?,?)", (chat_id, due.isoformat(), message))
        return int(cursor.lastrowid)


def due_followups(limit: int = 50) -> list[sqlite3.Row]:
    with _connect() as db:
        return list(db.execute("SELECT * FROM followups WHERE status='pending' AND due_at<=? ORDER BY due_at LIMIT ?", (datetime.now(timezone.utc).isoformat(), limit)))


def mark_followup_sent(followup_id: int) -> None:
    with _connect() as db:
        db.execute("UPDATE followups SET status='sent',sent_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), followup_id))


def lead(chat_id: int) -> sqlite3.Row | None:
    with _connect() as db:
        return db.execute("SELECT * FROM leads WHERE chat_id=?", (chat_id,)).fetchone()


def conversation_state(chat_id: int) -> dict[str, Any] | None:
    """Reconstruit l'état métier d'un prospect après un redémarrage."""
    row = lead(chat_id)
    if row is None:
        return None
    try:
        saved = json.loads(row["state_json"] or "{}")
    except (TypeError, json.JSONDecodeError):
        saved = {}
    return {**{key: row[key] for key in ("stage", "name", "need", "budget", "timeline", "pain", "offer_id")}, **saved}


def analytics() -> dict[str, Any]:
    with _connect() as db:
        total = db.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        qualified = db.execute("SELECT COUNT(*) FROM leads WHERE score>=75").fetchone()[0]
        handoffs = db.execute("SELECT COUNT(*) FROM events WHERE event_type='handoff'").fetchone()[0]
        messages = db.execute("SELECT COUNT(*) FROM events WHERE event_type='message'").fetchone()[0]
        return {"leads": total, "qualified": qualified, "qualification_rate": round(qualified / total * 100, 1) if total else 0, "handoffs": handoffs, "messages": messages}
