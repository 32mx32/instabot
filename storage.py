"""SQLite-хранилище: кэш file_id, история отправок, избранное, статистика.

Сами медиафайлы не хранятся — только их file_id в Telegram и метаданные,
поэтому база остаётся маленькой (килобайты на тысячи роликов).
"""

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL UNIQUE,
    platform    TEXT NOT NULL,
    kind        TEXT NOT NULL,
    file_id     TEXT,
    file_type   TEXT,
    caption     TEXT,
    author      TEXT,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    media_id    INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    user_id     INTEGER,
    chat_id     INTEGER NOT NULL,
    chat_type   TEXT,
    message_id  INTEGER,
    source      TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deliveries_user ON deliveries(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_deliveries_chat ON deliveries(chat_id, created_at);

CREATE TABLE IF NOT EXISTS favorites (
    user_id     INTEGER NOT NULL,
    media_id    INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    created_at  INTEGER NOT NULL,
    PRIMARY KEY (user_id, media_id)
);

CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    first_seen  INTEGER NOT NULL,
    last_seen   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS counters (
    name        TEXT PRIMARY KEY,
    value       INTEGER NOT NULL DEFAULT 0
);
"""


class Storage:
    """Потокобезопасная обёртка над SQLite. Все запросы короткие, поэтому
    вызываются прямо из обработчиков без отдельного потока."""

    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        # Встроенный lower()/LIKE в SQLite не понимает кириллицу — используем Python
        self._conn.create_function("pylower", 1, lambda value: value.lower() if isinstance(value, str) else value)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)

    def _fetchone(self, sql: str, params: Tuple = ()) -> Optional[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    def _fetchall(self, sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _execute(self, sql: str, params: Tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # --- media -------------------------------------------------------------

    def get_media(self, media_id: int) -> Optional[sqlite3.Row]:
        return self._fetchone("SELECT * FROM media WHERE id = ?", (media_id,))

    def get_media_by_url(self, url: str) -> Optional[sqlite3.Row]:
        return self._fetchone("SELECT * FROM media WHERE url = ?", (url,))

    def save_media(
        self,
        url: str,
        platform: str,
        kind: str,
        caption: Optional[str] = None,
        author: Optional[str] = None,
    ) -> int:
        """Создаёт или обновляет запись о медиа и возвращает её id."""
        self._execute(
            """
            INSERT INTO media (url, platform, kind, caption, author, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                caption = COALESCE(excluded.caption, media.caption),
                author  = COALESCE(excluded.author, media.author)
            """,
            (url, platform, kind, caption, author, int(time.time())),
        )
        return self.get_media_by_url(url)["id"]

    def set_file_id(self, media_id: int, file_id: str, file_type: str) -> None:
        self._execute(
            "UPDATE media SET file_id = ?, file_type = ? WHERE id = ?", (file_id, file_type, media_id)
        )

    def forget_file_id(self, media_id: int) -> None:
        self._execute("UPDATE media SET file_id = NULL, file_type = NULL WHERE id = ?", (media_id,))

    # --- deliveries, users, counters ---------------------------------------

    def record_delivery(
        self,
        media_id: int,
        chat_id: int,
        user_id: Optional[int],
        chat_type: Optional[str],
        message_id: Optional[int],
        source: str,
    ) -> None:
        self._execute(
            """
            INSERT INTO deliveries (media_id, user_id, chat_id, chat_type, message_id, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (media_id, user_id, chat_id, chat_type, message_id, source, int(time.time())),
        )

    def touch_user(self, user_id: int) -> None:
        now = int(time.time())
        self._execute(
            """
            INSERT INTO users (user_id, first_seen, last_seen) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET last_seen = excluded.last_seen
            """,
            (user_id, now, now),
        )

    def user_count(self) -> int:
        return self._fetchone("SELECT COUNT(*) FROM users")[0]

    def incr(self, name: str, amount: int = 1) -> None:
        self._execute(
            """
            INSERT INTO counters (name, value) VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET value = value + excluded.value
            """,
            (name, amount),
        )

    def counters(self) -> Dict[str, int]:
        return {row["name"]: row["value"] for row in self._fetchall("SELECT name, value FROM counters")}

    # --- favorites ---------------------------------------------------------

    def toggle_favorite(self, user_id: int, media_id: int) -> bool:
        """Добавляет в избранное или убирает оттуда. Возвращает True, если добавлено."""
        with self._lock:
            removed = self._conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND media_id = ?", (user_id, media_id)
            ).rowcount
            if removed:
                return False
            self._conn.execute(
                "INSERT INTO favorites (user_id, media_id, created_at) VALUES (?, ?, ?)",
                (user_id, media_id, int(time.time())),
            )
            return True

    def list_favorites(
        self, user_id: int, query: Optional[str] = None, limit: int = 10, offset: int = 0
    ) -> Tuple[List[sqlite3.Row], int]:
        """Избранное пользователя (новые сверху) с поиском по подписи, автору и ссылке."""
        where = "f.user_id = ?"
        params: List[Any] = [user_id]
        if query:
            where += (
                " AND (pylower(m.caption) LIKE ? OR pylower(m.author) LIKE ?"
                " OR pylower(m.url) LIKE ? OR pylower(m.platform) LIKE ?)"
            )
            pattern = f"%{query.lower()}%"
            params += [pattern, pattern, pattern, pattern]

        total = self._fetchone(
            f"SELECT COUNT(*) FROM favorites f JOIN media m ON m.id = f.media_id WHERE {where}",
            tuple(params),
        )[0]
        rows = self._fetchall(
            f"""
            SELECT m.* FROM favorites f JOIN media m ON m.id = f.media_id
            WHERE {where}
            ORDER BY f.created_at DESC, f.rowid DESC
            LIMIT ? OFFSET ?
            """,
            tuple(params + [limit, offset]),
        )
        return rows, total
