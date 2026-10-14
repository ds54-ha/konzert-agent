"""SQLite-Speicher für Events und Scrape-Läufe."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    uid        TEXT PRIMARY KEY,
    venue_id   TEXT NOT NULL,
    native_id  TEXT NOT NULL,
    title      TEXT NOT NULL,
    date       TEXT NOT NULL,
    end_date   TEXT,
    time       TEXT,
    url        TEXT,
    tags       TEXT DEFAULT '[]',
    sold_out   INTEGER DEFAULT 0,
    cancelled  INTEGER DEFAULT 0,
    extra      TEXT DEFAULT '{}',
    first_seen TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    notified   INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(date);
CREATE INDEX IF NOT EXISTS idx_events_venue ON events(venue_id);
CREATE TABLE IF NOT EXISTS runs (
    venue_id  TEXT PRIMARY KEY,
    last_run  TEXT,
    last_ok   TEXT,
    last_error TEXT,
    found     INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE COLLATE NOCASE,
    pw_hash     TEXT NOT NULL,
    ical_token  TEXT NOT NULL UNIQUE,  -- geheimes Token für Kalender-Abos
    share_marks INTEGER DEFAULT 0,     -- Opt-in: andere sehen, wohin man geht
    disabled    INTEGER DEFAULT 0,
    created     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,       -- SHA-256 des Cookie-Tokens, nie das Token selbst
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created    TEXT NOT NULL,
    last_seen  TEXT NOT NULL,
    expires    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artists (
    key        TEXT PRIMARY KEY,   -- normalisierter Name | Länder-Hinweis
    data       TEXT NOT NULL,      -- ArtistInfo als JSON
    fetched_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.execute("PRAGMA foreign_keys = ON")
            self.db.executescript(SCHEMA)

    # ------------------------------------------------------------ Schreiben

    def venue_has_events(self, venue_id: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM events WHERE venue_id=? LIMIT 1", (venue_id,)).fetchone() is not None

    def upsert(self, events: list[Event]) -> tuple[list[Event], list[Event]]:
        """Speichert Events. Gibt (neu, frisch_abgesagt) zurück."""
        new, cancelled = [], []
        now = _now()
        with self.lock, self.db:
            for ev in events:
                row = self.db.execute("SELECT cancelled FROM events WHERE uid=?", (ev.uid,)).fetchone()
                if row is None:
                    self.db.execute(
                        "INSERT INTO events (uid, venue_id, native_id, title, date, end_date, time, url, tags,"
                        " sold_out, cancelled, extra, first_seen, last_seen) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (ev.uid, ev.venue_id, ev.native_id, ev.title, ev.date.isoformat(),
                         ev.end_date.isoformat() if ev.end_date else None, ev.time, ev.url,
                         json.dumps(ev.tags), int(ev.sold_out), int(ev.cancelled), json.dumps(ev.extra), now, now))
                    new.append(ev)
                else:
                    if ev.cancelled and not row["cancelled"]:
                        cancelled.append(ev)
                    # Felder aktualisieren, aber angereicherte Daten (Tags/Zeit) nicht mit leeren Werten überschreiben
                    self.db.execute(
                        "UPDATE events SET title=?, date=?, end_date=?, url=?, sold_out=?, cancelled=?, last_seen=?,"
                        " time=COALESCE(?, time), tags=CASE WHEN ?='[]' THEN tags ELSE ? END WHERE uid=?",
                        (ev.title, ev.date.isoformat(), ev.end_date.isoformat() if ev.end_date else None, ev.url,
                         int(ev.sold_out), int(ev.cancelled), now, ev.time,
                         json.dumps(ev.tags), json.dumps(ev.tags), ev.uid))
        return new, cancelled

    def update_details(self, ev: Event):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET tags=?, time=COALESCE(?, time), extra=? WHERE uid=?",
                            (json.dumps(ev.tags), ev.time, json.dumps(ev.extra), ev.uid))

    def update_extra(self, uid: str, extra: dict):
        with self.lock, self.db:
            self.db.execute("UPDATE events SET extra=? WHERE uid=?", (json.dumps(extra), uid))

    def get_artist(self, key: str, max_age_days: int | None = None) -> dict | None:
        sql, args = "SELECT data FROM artists WHERE key=?", [key]
        if max_age_days:
            sql += " AND fetched_at >= ?"; args.append((datetime.now() - timedelta(days=max_age_days)).isoformat())
        with self.lock:
            row = self.db.execute(sql, args).fetchone()
        return json.loads(row["data"]) if row else None

    def put_artist(self, key: str, data: dict):
        with self.lock, self.db:
            self.db.execute("INSERT INTO artists (key, data, fetched_at) VALUES (?,?,?) ON CONFLICT(key) DO UPDATE"
                            " SET data=excluded.data, fetched_at=excluded.fetched_at", (key, json.dumps(data), _now()))

    def mark_notified(self, uids: list[str]):
        with self.lock, self.db:
            self.db.executemany("UPDATE events SET notified=1 WHERE uid=?", [(u,) for u in uids])

    def record_run(self, venue_id: str, found: int, error: str | None = None):
        now = _now()
        with self.lock, self.db:
            self.db.execute(
                "INSERT INTO runs (venue_id, last_run, last_ok, last_error, found) VALUES (?,?,?,?,?) "
                "ON CONFLICT(venue_id) DO UPDATE SET last_run=excluded.last_run, last_error=excluded.last_error,"
                " found=excluded.found, last_ok=COALESCE(excluded.last_ok, runs.last_ok)",
                (venue_id, now, None if error else now, error, found))

    # ------------------------------------------------------------ Benutzer & Sitzungen

    _USER_COLS = "id, username, pw_hash, ical_token, share_marks, disabled, created"

    def _user(self, where: str, args) -> dict | None:
        with self.lock:
            row = self.db.execute(f"SELECT {self._USER_COLS} FROM users WHERE {where}", args).fetchone()
        return dict(row) if row else None

    def create_user(self, username: str, pw_hash: str, ical_token: str) -> int:
        with self.lock, self.db:
            cur = self.db.execute("INSERT INTO users (username, pw_hash, ical_token, created) VALUES (?,?,?,?)",
                                  (username, pw_hash, ical_token, _now()))
            return cur.lastrowid

    def user_by_name(self, username: str) -> dict | None:
        return self._user("username = ?", (username,))

    def user_by_id(self, user_id: int) -> dict | None:
        return self._user("id = ?", (user_id,))

    def user_by_ical_token(self, token: str) -> dict | None:
        return self._user("ical_token = ? AND disabled = 0", (token,))

    def users(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                f"SELECT {self._USER_COLS}, (SELECT MAX(last_seen) FROM sessions s WHERE s.user_id = users.id)"
                " AS last_seen FROM users ORDER BY username").fetchall()
        return [dict(r) for r in rows]

    def update_user(self, user_id: int, **fields):
        allowed = {"pw_hash", "ical_token", "share_marks", "disabled"}
        assert set(fields) <= allowed, fields
        with self.lock, self.db:
            self.db.execute(f"UPDATE users SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?",
                            (*fields.values(), user_id))

    def delete_user(self, user_id: int):
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            self.db.execute("DELETE FROM users WHERE id=?", (user_id,))

    def create_session(self, token_hash: str, user_id: int, days: int):
        now = datetime.now()
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE expires < ?", (now.isoformat(timespec="seconds"),))
            self.db.execute("INSERT INTO sessions (token_hash, user_id, created, last_seen, expires) VALUES (?,?,?,?,?)",
                            (token_hash, user_id, _now(), _now(),
                             (now + timedelta(days=days)).isoformat(timespec="seconds")))

    def session_user(self, token_hash: str, days: int) -> dict | None:
        """Benutzer zur Sitzung; verlängert die Sitzung (gleitend) höchstens einmal pro Stunde."""
        now = datetime.now()
        with self.lock:
            row = self.db.execute(
                f"SELECT s.last_seen, {', '.join('u.' + c for c in self._USER_COLS.split(', '))} FROM sessions s"
                " JOIN users u ON u.id = s.user_id WHERE s.token_hash = ? AND s.expires >= ? AND u.disabled = 0",
                (token_hash, now.isoformat(timespec="seconds"))).fetchone()
            if row is None:
                return None
            if row["last_seen"] < (now - timedelta(hours=1)).isoformat():
                with self.db:
                    self.db.execute("UPDATE sessions SET last_seen=?, expires=? WHERE token_hash=?",
                                    (_now(), (now + timedelta(days=days)).isoformat(timespec="seconds"), token_hash))
        user = dict(row)
        user.pop("last_seen")
        return user

    def delete_session(self, token_hash: str):
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))

    def delete_sessions(self, user_id: int) -> int:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount

    def count_users(self) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # ------------------------------------------------------------ Lesen

    def events(self, start: date | None = None, end: date | None = None, venues: list[str] | None = None,
               q: str | None = None, new_days: int | None = None, without_artists: bool = False) -> list[dict]:
        sql, args = "SELECT * FROM events WHERE 1=1", []
        if start:
            sql += " AND COALESCE(end_date, date) >= ?"; args.append(start.isoformat())
        if end:
            sql += " AND date <= ?"; args.append(end.isoformat())
        if venues:
            sql += f" AND venue_id IN ({','.join('?' * len(venues))})"; args += venues
        if q:
            sql += " AND (title LIKE ? OR tags LIKE ? OR extra LIKE ?)"; args += [f"%{q}%"] * 3
        if without_artists:
            sql += " AND (extra NOT LIKE '%\"artists\":%' OR extra LIKE '%\"artists_retry\": true%')"
        if new_days:
            sql += " AND first_seen >= ?"; args.append((datetime.now() - timedelta(days=new_days)).isoformat())
        sql += " ORDER BY date, time, title"
        with self.lock:
            rows = self.db.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["tags"] = json.loads(d["tags"] or "[]")
            d["extra"] = json.loads(d["extra"] or "{}")
            d["sold_out"], d["cancelled"] = bool(d["sold_out"]), bool(d["cancelled"])
            out.append(d)
        return out

    def runs(self) -> dict[str, dict]:
        with self.lock:
            return {r["venue_id"]: dict(r) for r in self.db.execute("SELECT * FROM runs")}

    def counts(self) -> dict[str, int]:
        today = date.today().isoformat()
        with self.lock:
            return {r[0]: r[1] for r in self.db.execute(
                "SELECT venue_id, COUNT(*) FROM events WHERE COALESCE(end_date,date) >= ? GROUP BY venue_id", (today,))}
