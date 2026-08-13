"""
Local SQLite database for persistent data.

Used for:
    * conversation history (Phase 2)
    * later: notes, reminders, user-approved memory, preferences

Thread-safety: AI replies are generated in a background thread, so the
connection is opened with `check_same_thread=False` and every call is
guarded by a lock.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger

log = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL DEFAULT 'Conversation',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS notes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL UNIQUE,
    content    TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    due_at     TEXT NOT NULL,
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    recurrence TEXT,
    anchor     TEXT
);

CREATE TABLE IF NOT EXISTS mood_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    emotion    TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scripts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    steps       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS security_events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    level    TEXT NOT NULL,
    category TEXT NOT NULL,
    action   TEXT NOT NULL,
    detail   TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()
        self._current_conversation_id: int | None = None

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._add_missing_columns()
            self._conn.commit()

    def _add_missing_columns(self) -> None:
        """Add columns added in Phase 30 to databases created earlier."""
        additions = (
            ("reminders", "recurrence", "TEXT"),
            ("reminders", "anchor", "TEXT"),
        )
        for table, column, col_type in additions:
            cols = {
                row["name"]
                for row in self._conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in cols:
                self._conn.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- Conversations ------------------------------------------------------
    def create_conversation(self, title: str = "Conversation") -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO conversations (title, created_at) VALUES (?, ?)",
                (title, _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def start_conversation(self, title: str = "Conversation") -> int:
        """Create (or reset to) a conversation used for the current session."""
        self._current_conversation_id = self.create_conversation(title)
        return self._current_conversation_id

    def resume_latest_conversation(self, title: str = "Conversation") -> int:
        """Reuse the most recent conversation, creating one if none exists.

        Phase 22: this is what makes chat history survive a restart - the
        app keeps talking in the same conversation instead of starting a
        brand-new (empty) one every launch.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM conversations ORDER BY id DESC LIMIT 1"
            ).fetchone()
        conversation_id = int(row["id"]) if row else self.create_conversation(title)
        self._current_conversation_id = conversation_id
        return conversation_id

    def switch_conversation(self, conversation_id: int) -> None:
        """Make another saved conversation the active one (history dialog)."""
        self._current_conversation_id = conversation_id

    def rename_conversation(self, conversation_id: int, title: str) -> None:
        """Set a human-friendly title (e.g. the first user message)."""
        title = (title or "Conversation").strip()[:80] or "Conversation"
        with self._lock:
            self._conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, conversation_id),
            )
            self._conn.commit()

    def conversation_preview(self, conversation_id: int | None = None) -> dict | None:
        """Return the {id, title, created_at, message_count} of the active
        (or given) conversation, or None if there is no active conversation."""
        conversation_id = conversation_id or self._current_conversation_id
        if conversation_id is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT c.id, c.title, c.created_at, "
                "       (SELECT COUNT(*) FROM messages m "
                "         WHERE m.conversation_id = c.id) AS message_count "
                "FROM conversations c WHERE c.id = ?",
                (conversation_id,),
            ).fetchone()
        return dict(row) if row else None

    def current_conversation_id(self) -> int | None:
        return self._current_conversation_id

    # -- Messages -----------------------------------------------------------
    def save_message(self, role: str, content: str) -> int | None:
        """Save a message to the active conversation. No-op if none active."""
        if self._current_conversation_id is None:
            return None
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) "
                "VALUES (?, ?, ?, ?)",
                (self._current_conversation_id, role, content, _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def load_messages(self, conversation_id: int | None = None) -> list[dict]:
        """Return all messages for a conversation (most recent last)."""
        conversation_id = conversation_id or self._current_conversation_id
        if conversation_id is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_conversations(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT c.id, c.title, c.created_at, "
                "       (SELECT COUNT(*) FROM messages m "
                "         WHERE m.conversation_id = c.id) AS message_count "
                "FROM conversations c ORDER BY c.id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_conversation(self, conversation_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM conversations WHERE id = ?", (conversation_id,)
            )
            self._conn.commit()

    # -- Notes (Phase 11) ----------------------------------------------------
    def save_note(self, title: str, content: str) -> None:
        """Insert or overwrite a note (title is unique)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO notes (title, content, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(title) DO UPDATE SET "
                "content = excluded.content, updated_at = excluded.updated_at",
                (title, content, _now()),
            )
            self._conn.commit()

    def list_notes(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT title, content, updated_at FROM notes ORDER BY title ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_note(self, title: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT title, content, updated_at FROM notes WHERE title = ?",
                (title,),
            ).fetchone()
        return dict(row) if row else None

    def delete_note(self, title: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM notes WHERE title = ?", (title,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- Reminders (Phase 11/30) ----------------------------------------------
    def add_reminder(self, text: str, due_at: str) -> int:
        return self.add_recurring_reminder(text, due_at, recurrence=None, anchor=None)

    def add_recurring_reminder(
        self,
        text: str,
        due_at: str,
        recurrence: str | None = None,
        anchor: str | None = None,
    ) -> int:
        """Add a one-off (recurrence=None) or repeating reminder.

        ``recurrence`` is "daily", "weekly" or "every N unit(s)" (e.g.
        "every 2 hours", "every 7 days"). ``anchor`` is the ISO timestamp
        used to compute the next occurrence.
        """
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO reminders (text, due_at, done, created_at, recurrence, anchor) "
                "VALUES (?, ?, 0, ?, ?, ?)",
                (text, due_at, _now(), recurrence, anchor or due_at),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_reminders(self) -> list[dict]:
        """Pending (not done) reminders, soonest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, due_at, recurrence FROM reminders WHERE done = 0 "
                "ORDER BY due_at ASC, id ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_reminder(self, reminder_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM reminders WHERE id = ?", (reminder_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_reminder_done(self, reminder_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE reminders SET done = 1 WHERE id = ? AND done = 0",
                (reminder_id,),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def get_reminder(self, reminder_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, text, due_at, recurrence, anchor FROM reminders "
                "WHERE id = ?",
                (reminder_id,),
            ).fetchone()
        return dict(row) if row else None

    def due_reminders(self) -> list[dict]:
        """Pending reminders whose due time has passed, soonest first."""
        now = _now()
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, due_at, recurrence, anchor FROM reminders "
                "WHERE done = 0 AND due_at <= ? ORDER BY due_at ASC",
                (now,),
            ).fetchall()
        return [dict(row) for row in rows]

    def reschedule_reminder(self, reminder_id: int, new_due_at: str) -> None:
        """Push a recurring reminder's due time forward to its next run."""
        with self._lock:
            self._conn.execute(
                "UPDATE reminders SET due_at = ? WHERE id = ?",
                (new_due_at, reminder_id),
            )
            self._conn.commit()

    # -- Mood log (Phase 30) ----------------------------------------------------
    def log_mood(self, emotion: str, confidence: float) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO mood_log (emotion, confidence, created_at) "
                "VALUES (?, ?, ?)",
                (emotion, float(confidence), _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def recent_moods(self, limit: int = 12) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT emotion, confidence, created_at FROM mood_log "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def mood_counts(self, since_hours: int = 48) -> dict[str, int]:
        """Count emotions logged in the last N hours (mostly for reports)."""
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(hours=int(since_hours))).isoformat(
            timespec="seconds"
        )
        with self._lock:
            rows = self._conn.execute(
                "SELECT emotion, COUNT(*) AS n FROM mood_log "
                "WHERE created_at >= ? GROUP BY emotion",
                (cutoff,),
            ).fetchall()
        return {row["emotion"]: int(row["n"]) for row in rows}

    # -- Message search (Phase 30) ----------------------------------------------
    def search_messages(self, term: str, limit: int = 20) -> list[dict]:
        """Search across all conversations for a phrase in any message."""
        term = (term or "").strip()
        if not term:
            return []
        like = f"%{term}%"
        with self._lock:
            rows = self._conn.execute(
                "SELECT m.id, m.conversation_id, m.role, m.content, m.created_at, c.title "
                "FROM messages m JOIN conversations c ON c.id = m.conversation_id "
                "WHERE m.content LIKE ? COLLATE NOCASE "
                "ORDER BY m.id DESC LIMIT ?",
                (like, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_messages_in_conversation(
        self, conversation_id: int, limit: int = 10000
    ) -> list[dict]:
        """Return every message of one conversation (oldest first) for export."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT role, content, created_at FROM messages "
                "WHERE conversation_id = ? ORDER BY id ASC LIMIT ?",
                (conversation_id, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    # -- Memories (Phase 14) --------------------------------------------------
    def add_memory(self, content: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO memories (content, created_at) VALUES (?, ?)",
                (content, _now()),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def has_memory(self, content: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM memories WHERE content = ? COLLATE NOCASE",
                (content,),
            ).fetchone()
        return row is not None

    def list_memories(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, content, created_at FROM memories "
                "ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_memory(self, memory_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memories WHERE id = ?", (memory_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    def delete_memory_containing(self, text: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM memories WHERE LOWER(content) LIKE LOWER(?)",
                (f"%{text}%",),
            )
            self._conn.commit()
            return cur.rowcount > 0

    # -- Preferences (Phase 14) ------------------------------------------------
    def get_preference(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM preferences WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_preference(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO preferences (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    def all_preferences(self) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute("SELECT key, value FROM preferences").fetchall()
        return {row["key"]: row["value"] for row in rows}

    # -- Scripts (Phase 15) ---------------------------------------------------
    def save_script(self, name: str, description: str, steps_json: str) -> None:
        """Insert or overwrite a task script (name is unique)."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO scripts (name, description, steps, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET "
                "description = excluded.description, steps = excluded.steps",
                (name, description, steps_json, _now()),
            )
            self._conn.commit()

    def get_script(self, name: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, name, description, steps FROM scripts WHERE name = ?",
                (name,),
            ).fetchone()
        return dict(row) if row else None

    def list_scripts(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, description, steps FROM scripts ORDER BY name ASC"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_script(self, name: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM scripts WHERE name = ?", (name,))
            self._conn.commit()
            return cur.rowcount > 0

    # -- Security events (Phase 16) ------------------------------------------
    def add_security_event(
        self, level: str, category: str, action: str, detail: str
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO security_events (level, category, action, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (level, category, action, detail, _now()),
            )
            self._conn.commit()

    def recent_security_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT level, category, action, detail, created_at "
                "FROM security_events ORDER BY id DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]


_shared_db: "Database | None" = None


def get_shared_database() -> "Database":
    """A lazily created Database at the configured default path.

    Tools that need persistence use this when the app has not supplied
    its own instance (e.g. offline/standalone use or tests).
    """
    global _shared_db
    if _shared_db is None:
        from config import settings

        _shared_db = Database(settings.data_dir / "database" / "jarvis.db")
    return _shared_db
