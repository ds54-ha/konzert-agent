"""Telegram pro Benutzer: eigener Bot, mit dem sich jeder selbst verbindet.

Ablauf: Web «Telegram verbinden» -> Einmal-Code -> Link t.me/<bot>?start=<code> -> in Telegram «Start» ->
der Bot liest die Nachricht (Long-Polling, kein öffentlicher Webhook nötig) und verbindet den Chat.
Wichtig: nur EIN Programm darf die Nachrichten eines Bots lesen – darum ein eigener Bot, nicht der
für die allgemeinen Meldungen (notifiers).
"""
from __future__ import annotations

import html
import logging
import secrets
import time

import requests

from .kinds import event_kind
from .models import Event
from .notifiers import TelegramNotifier
from .store import Store

log = logging.getLogger(__name__)
NEW_MODES = ("off", "all", "filter")
FILTER_KEYS = ("venues", "genres", "kinds", "pops")


class BotBlocked(Exception):
    """Chat existiert nicht mehr oder hat den Bot blockiert."""


def matches(ev: Event, flt: dict) -> bool:
    """Gespeicherter Filter (wie in der Seitenleiste): leere Liste = alle."""
    if flt.get("venues") and ev.venue_id not in flt["venues"]:
        return False
    if flt.get("kinds") and event_kind(ev.title, ev.tags) not in flt["kinds"]:
        return False
    if flt.get("genres") and not set(flt["genres"]) & set(ev.extra.get("genres") or []):
        return False
    if flt.get("pops") and ev.extra.get("popularity_label") not in flt["pops"]:
        return False
    return True


def clean_prefs(body) -> dict | None:
    """Einstellungen aus dem Web prüfen; None = ungültig."""
    if not isinstance(body, dict) or body.get("new") not in NEW_MODES or not isinstance(body.get("cancelled"), bool):
        return None
    flt = body.get("filter") or {}
    if not isinstance(flt, dict):
        return None
    out = {}
    for k in FILTER_KEYS:
        v = flt.get(k) or []
        if not isinstance(v, list) or not all(isinstance(x, str) and len(x) < 200 for x in v) or len(v) > 500:
            return None
        if v:
            out[k] = v
    return {"new": body["new"], "filter": out, "cancelled": body["cancelled"]}


class UserBot:
    def __init__(self, token: str, store: Store, venue_names: dict[str, str], base_url: str = "",
                 link_minutes: int = 15):
        self.token, self.store, self.link_minutes = token, store, link_minutes
        self.fmt = TelegramNotifier(token=token, chat_id="", venue_names=venue_names, base_url=base_url)
        self._username: str | None = None

    # ------------------------------------------------------------ Telegram-API

    def api(self, method: str, http_timeout: float = 20, **params) -> dict:
        r = requests.post(f"https://api.telegram.org/bot{self.token}/{method}", json=params, timeout=http_timeout)
        data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 403 or (r.status_code == 400 and "chat not found" in str(data.get("description"))):
            raise BotBlocked(data.get("description", r.status_code))
        if not data.get("ok"):
            raise RuntimeError(f"Telegram {method}: {r.status_code} {str(data.get('description') or r.text)[:200]}")
        return data["result"]

    @property
    def username(self) -> str:
        if self._username is None:
            self._username = self.api("getMe")["username"]
        return self._username

    def send(self, chat_id: str, text: str) -> bool:
        """False = Chat nicht mehr erreichbar (blockiert) -> Verbindung wird gelöst."""
        try:
            self.api("sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
            return True
        except BotBlocked as e:
            names = self.store.tg_unlink(chat_id=chat_id)
            log.info("Telegram-Chat von %s nicht erreichbar (%s) – Verbindung gelöst", ", ".join(names) or "?", e)
            return False

    # ------------------------------------------------------------ Verbinden

    def new_link(self, user_id: int) -> str:
        code = secrets.token_urlsafe(18)              # Telegram erlaubt A-Z a-z 0-9 _ - (max. 64)
        self.store.tg_new_code(user_id, code, self.link_minutes)
        return f"https://t.me/{self.username}?start={code}"

    def handle(self, update: dict):
        """Eine Nachricht an den Bot. Fremde ohne gültigen Code bekommen nur einen kurzen Hinweis."""
        member = update.get("my_chat_member")
        if member and member.get("new_chat_member", {}).get("status") == "kicked":   # Bot blockiert
            self.store.tg_unlink(chat_id=str(member["chat"]["id"]))
            return
        msg = update.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private" or not isinstance(msg.get("text"), str):
            return                                    # nur private Chats, nur Text
        chat_id, text = str(msg["chat"]["id"]), msg["text"].strip()
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()
        if cmd == "/start" and arg:
            frm = msg.get("from") or {}
            name = frm.get("first_name") or ""
            if frm.get("username"):
                name = f"{name} (@{frm['username']})".strip()
            user = self.store.tg_redeem(arg.strip(), chat_id, name[:100])
            if user:
                log.info("Telegram mit Benutzer %s verbunden", user["username"])
                self.send(chat_id, f"✅ Verbunden mit dem Konzertkalender (<b>{html.escape(user['username'])}</b>).\n"
                                   "Einstellungen im Konzertkalender unter «Meine». Trennen: /stop")
            else:
                self.send(chat_id, "Dieser Link ist abgelaufen oder schon benutzt. "
                                   "Im Konzertkalender unter «Meine» → «Telegram verbinden» einen neuen holen.")
        elif cmd == "/stop":
            names = self.store.tg_unlink(chat_id=chat_id)
            if names:
                self.send(chat_id, "Getrennt – du bekommst keine Meldungen mehr. Neu verbinden geht im Konzertkalender.")
        elif cmd in ("/start", "/status", "/help"):
            names = self.store.tg_users_for_chat(chat_id)
            if names:
                self.send(chat_id, f"Verbunden mit: <b>{html.escape(', '.join(names))}</b>.\n"
                                   "Einstellungen im Konzertkalender unter «Meine». Trennen: /stop")
            else:
                self.send(chat_id, "Dieser Bot meldet neue Konzerte aus dem Konzertkalender. Verbinden: im "
                                   "Konzertkalender anmelden → «Meine» → «Telegram verbinden».")

    def poll_forever(self):
        """Long-Polling – läuft im Hintergrund von «serve». Fortschritt in der DB, damit nach einem
        Neustart nichts doppelt verarbeitet wird."""
        offset = int(self.store.get_meta("tg_offset", "0"))
        delay = 5
        while True:
            try:
                updates = self.api("getUpdates", http_timeout=60, offset=offset, timeout=50,
                                   allowed_updates=["message", "my_chat_member"])
            except Exception as e:  # noqa: BLE001 – Netz weg, Telegram down: später nochmals
                hint = " – liest ein anderes Programm diesen Bot? (eigener Bot nötig)" if "409" in str(e) else ""
                log.warning("Telegram-Bot: Nachrichten nicht abrufbar (%s)%s – neuer Versuch in %ds", e, hint, delay)
                time.sleep(delay)
                delay = min(delay * 2, 300)
                continue
            delay = 5
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    self.handle(u)
                except Exception:  # noqa: BLE001
                    log.exception("Telegram-Nachricht nicht verarbeitet")
                self.store.set_meta("tg_offset", str(offset))

    # ------------------------------------------------------------ Melden

    def notify(self, new: list[Event], cancelled: list[Event]):
        """Neue Konzerte nach den Einstellungen jedes Benutzers; Absagen markierter Konzerte."""
        for r in self.store.tg_recipients():
            p = r["prefs"]
            flt = p["filter"] if p["new"] == "filter" else {}
            my_new = [] if p["new"] == "off" else [e for e in new if matches(e, flt)]
            marked = self.store.marks(r["user_id"]) if p["cancelled"] else {}
            my_cancelled = [e for e in cancelled
                            if e.uid in marked or (p["new"] != "off" and matches(e, flt))]
            if not (my_new or my_cancelled):
                continue
            for text in self.fmt.build_messages(my_new, my_cancelled):
                try:
                    if not self.send(r["chat_id"], text):
                        break
                except Exception:  # noqa: BLE001 – ein Benutzer soll die anderen nicht aufhalten
                    log.exception("Telegram an %s fehlgeschlagen", r["username"])
                    break
