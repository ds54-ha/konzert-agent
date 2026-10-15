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
CREATE TABLE IF NOT EXISTS marks (    -- pro Benutzer: «Interessiert» / «Gehe hin» (+ Ticket)
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    event_uid TEXT NOT NULL,
    status    TEXT NOT NULL,       -- interested | going
    ticket    TEXT,                -- bei going: none | own | other
    updated   TEXT NOT NULL,
    PRIMARY KEY (user_id, event_uid)
);
CREATE INDEX IF NOT EXISTS idx_marks_event ON marks(event_uid);
CREATE TABLE IF NOT EXISTS tg_chats (  -- pro Benutzer: verbundener Telegram-Chat (über den Benutzer-Bot)
    user_id   INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    chat_id   TEXT NOT NULL,
    chat_name TEXT,
    prefs     TEXT DEFAULT '{}',   -- was gemeldet wird (JSON, siehe TG_PREFS)
    linked    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tg_codes (  -- Einmal-Codes für «Telegram verbinden» (Deep-Link t.me/<bot>?start=<code>)
    code    TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS follows (   -- Bands, denen ein Benutzer folgt (Schlüssel: normalisierter Name)
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    name    TEXT NOT NULL,             -- wie eingegeben / erkannt, zur Anzeige
    created TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
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
                " AS last_seen, EXISTS(SELECT 1 FROM tg_chats t WHERE t.user_id = users.id) AS telegram"
                " FROM users ORDER BY username").fetchall()
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
            self.db.execute("DELETE FROM marks WHERE user_id=?", (user_id,))
            self.db.execute("DELETE FROM tg_chats WHERE user_id=?", (user_id,))
            self.db.execute("DELETE FROM tg_codes WHERE user_id=?", (user_id,))
            self.db.execute("DELETE FROM follows WHERE user_id=?", (user_id,))
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

    # ------------------------------------------------------------ Bands folgen

    def follow(self, user_id: int, key: str, name: str):
        with self.lock, self.db:
            self.db.execute("INSERT INTO follows (user_id, key, name, created) VALUES (?,?,?,?)"
                            " ON CONFLICT(user_id, key) DO NOTHING", (user_id, key, name, _now()))

    def unfollow(self, user_id: int, key: str) -> bool:
        with self.lock, self.db:
            return self.db.execute("DELETE FROM follows WHERE user_id=? AND key=?", (user_id, key)).rowcount > 0

    def follows(self, user_id: int) -> dict[str, str]:
        """Schlüssel -> Name, alphabetisch."""
        with self.lock:
            rows = self.db.execute("SELECT key, name FROM follows WHERE user_id=? ORDER BY name COLLATE NOCASE",
                                   (user_id,)).fetchall()
        return {r["key"]: r["name"] for r in rows}

    # ------------------------------------------------------------ Telegram pro Benutzer

    # new: off | all | filter (nur Events, die zum gespeicherten Filter passen)
    # cancelled: Absagen von Konzerten melden, die man markiert hat
    # follows: neue Shows gefolgter Bands immer melden (auch bei new=off oder ausserhalb des Filters)
    TG_PREFS = {"new": "all", "filter": {}, "cancelled": True, "follows": True}

    def tg_new_code(self, user_id: int, code: str, minutes: int):
        now = datetime.now()
        with self.lock, self.db:
            self.db.execute("DELETE FROM tg_codes WHERE expires < ? OR user_id = ?", (_now(), user_id))
            self.db.execute("INSERT INTO tg_codes (code, user_id, expires) VALUES (?,?,?)",
                            (code, user_id, (now + timedelta(minutes=minutes)).isoformat(timespec="seconds")))

    def tg_redeem(self, code: str, chat_id: str, chat_name: str) -> dict | None:
        """Einmal-Code einlösen -> Chat mit dem Benutzer verbinden. None = unbekannt, abgelaufen oder gesperrt."""
        with self.lock, self.db:
            row = self.db.execute("SELECT c.user_id FROM tg_codes c JOIN users u ON u.id = c.user_id"
                                  " WHERE c.code = ? AND c.expires >= ? AND u.disabled = 0", (code, _now())).fetchone()
            self.db.execute("DELETE FROM tg_codes WHERE code = ?", (code,))
            if row is None:
                return None
            self.db.execute("INSERT INTO tg_chats (user_id, chat_id, chat_name, prefs, linked) VALUES (?,?,?,?,?)"
                            " ON CONFLICT(user_id) DO UPDATE SET chat_id=excluded.chat_id,"
                            " chat_name=excluded.chat_name, linked=excluded.linked",
                            (row["user_id"], str(chat_id), chat_name, json.dumps(self.TG_PREFS), _now()))
        return self.user_by_id(row["user_id"])

    def tg_chat(self, user_id: int) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT chat_id, chat_name, prefs, linked FROM tg_chats WHERE user_id=?",
                                  (user_id,)).fetchone()
        return None if row is None else {**dict(row), "prefs": {**self.TG_PREFS, **json.loads(row["prefs"] or "{}")}}

    def tg_set_prefs(self, user_id: int, prefs: dict):
        with self.lock, self.db:
            self.db.execute("UPDATE tg_chats SET prefs=? WHERE user_id=?", (json.dumps(prefs), user_id))

    def tg_unlink(self, user_id: int | None = None, chat_id: str | None = None) -> list[str]:
        """Verbindung lösen – per Benutzer (Web/Befehl) oder per Chat (/stop, Bot blockiert). -> Benutzernamen"""
        where, arg = ("t.user_id = ?", user_id) if user_id is not None else ("t.chat_id = ?", str(chat_id))
        with self.lock, self.db:
            names = [r[0] for r in self.db.execute(
                f"SELECT u.username FROM tg_chats t JOIN users u ON u.id = t.user_id WHERE {where}", (arg,))]
            self.db.execute(f"DELETE FROM tg_chats WHERE {where.replace('t.', '')}", (arg,))
        return names

    def tg_users_for_chat(self, chat_id: str) -> list[str]:
        with self.lock:
            return [r[0] for r in self.db.execute("SELECT u.username FROM tg_chats t JOIN users u ON u.id = t.user_id"
                                                  " WHERE t.chat_id = ? ORDER BY u.username", (str(chat_id),))]

    def tg_recipients(self) -> list[dict]:
        """Alle verbundenen, nicht gesperrten Benutzer mit ihren Einstellungen."""
        with self.lock:
            rows = self.db.execute("SELECT u.id AS user_id, u.username, t.chat_id, t.prefs FROM tg_chats t"
                                   " JOIN users u ON u.id = t.user_id WHERE u.disabled = 0").fetchall()
        return [{**dict(r), "prefs": {**self.TG_PREFS, **json.loads(r["prefs"] or "{}")}} for r in rows]

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self.lock:
            row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str):
        with self.lock, self.db:
            self.db.execute("INSERT INTO meta (key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, value))

    # ------------------------------------------------------------ Markierungen

    MARK_STATUS = ("interested", "going")
    TICKETS = ("none", "own", "other")

    def set_mark(self, user_id: int, event_uid: str, status: str | None, ticket: str | None = None):
        """status None = Markierung entfernen. Ticket nur bei «going» (Standard: noch keins)."""
        with self.lock, self.db:
            if status is None:
                self.db.execute("DELETE FROM marks WHERE user_id=? AND event_uid=?", (user_id, event_uid))
                return
            assert status in self.MARK_STATUS and (ticket is None or ticket in self.TICKETS), (status, ticket)
            ticket = (ticket or "none") if status == "going" else None
            self.db.execute("INSERT INTO marks (user_id, event_uid, status, ticket, updated) VALUES (?,?,?,?,?)"
                            " ON CONFLICT(user_id, event_uid) DO UPDATE SET status=excluded.status,"
                            " ticket=excluded.ticket, updated=excluded.updated",
                            (user_id, event_uid, status, ticket, _now()))

    def marks(self, user_id: int) -> dict[str, dict]:
        with self.lock:
            rows = self.db.execute("SELECT event_uid, status, ticket, updated FROM marks WHERE user_id=?",
                                   (user_id,)).fetchall()
        return {r["event_uid"]: {"status": r["status"], "ticket": r["ticket"], "updated": r["updated"]} for r in rows}

    def shared_marks(self, except_user_id: int) -> dict[str, list[dict]]:
        """Markierungen der anderen, die teilen (Opt-in) – nur Name und Status, kein Ticket."""
        with self.lock:
            rows = self.db.execute(
                "SELECT m.event_uid, u.username, m.status FROM marks m JOIN users u ON u.id = m.user_id"
                " WHERE u.share_marks = 1 AND u.disabled = 0 AND u.id != ?"
                " ORDER BY m.status, u.username COLLATE NOCASE", (except_user_id,)).fetchall()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r["event_uid"], []).append({"user": r["username"], "status": r["status"]})
        return out

    def event_exists(self, uid: str) -> bool:
        with self.lock:
            return self.db.execute("SELECT 1 FROM events WHERE uid=?", (uid,)).fetchone() is not None

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
        return [self._event_row(r) for r in rows]

    def marked_events(self, user_id: int) -> list[dict]:
        """Alle vom Benutzer markierten Events (auch vergangene), mit seiner Markierung unter «mark»."""
        with self.lock:
            rows = self.db.execute(
                "SELECT e.*, m.status AS mark_status, m.ticket AS mark_ticket, m.updated AS mark_updated"
                " FROM marks m JOIN events e ON e.uid = m.event_uid WHERE m.user_id = ?"
                " ORDER BY e.date, e.time, e.title", (user_id,)).fetchall()
        out = []
        for r in rows:
            d = self._event_row(r)
            d["mark"] = {"status": d.pop("mark_status"), "ticket": d.pop("mark_ticket"),
                         "updated": d.pop("mark_updated")}
            out.append(d)
        return out

    @staticmethod
    def _event_row(r) -> dict:
        d = dict(r)
        d["tags"] = json.loads(d["tags"] or "[]")
        d["extra"] = json.loads(d["extra"] or "{}")
        d["sold_out"], d["cancelled"] = bool(d["sold_out"]), bool(d["cancelled"])
        return d

    def runs(self) -> dict[str, dict]:
        with self.lock:
            return {r["venue_id"]: dict(r) for r in self.db.execute("SELECT * FROM runs")}

    def counts(self) -> dict[str, int]:
        today = date.today().isoformat()
        with self.lock:
            return {r[0]: r[1] for r in self.db.execute(
                "SELECT venue_id, COUNT(*) FROM events WHERE COALESCE(end_date,date) >= ? GROUP BY venue_id", (today,))}
