"""Benachrichtigungskanäle. Neue Kanäle: Klasse mit `send(new, cancelled)` + @register."""
from __future__ import annotations

import html
import logging
from collections import defaultdict

import requests

from ..models import Event

log = logging.getLogger(__name__)
REGISTRY: dict[str, type] = {}
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def register(name):
    def deco(cls):
        REGISTRY[name] = cls
        return cls
    return deco


def create_notifiers(cfgs: list[dict], venue_names: dict[str, str], base_url: str = "") -> list:
    out = []
    for c in cfgs:
        c = dict(c)
        if not c.pop("enabled", True):
            continue
        kind = c.pop("type")
        if kind == "telegram" and not (c.get("token") and c.get("chat_id")):
            log.warning("Telegram ist aktiviert, aber TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID fehlen – übersprungen")
            continue
        out.append(REGISTRY[kind](venue_names=venue_names, base_url=base_url, **c))
    return out


def fmt_date(ev: Event) -> str:
    s = f"{WEEKDAYS[ev.date.weekday()]} {ev.date:%d.%m.%y}"
    if ev.end_date:
        s += f"–{ev.end_date:%d.%m.}"
    if ev.time:
        s += f" {ev.time}"
    return s


class Notifier:
    def __init__(self, venue_names: dict[str, str], base_url: str = ""):
        self.venue_names = venue_names
        self.base_url = base_url

    def send(self, new: list[Event], cancelled: list[Event]):
        raise NotImplementedError


@register("telegram")
class TelegramNotifier(Notifier):
    """Bot via @BotFather anlegen, Token + Chat-ID in .env setzen."""
    LIMIT = 3900

    def __init__(self, token: str, chat_id: str, silent: bool = False, **kw):
        super().__init__(**kw)
        self.token, self.chat_id, self.silent = token, str(chat_id), silent

    def build_messages(self, new: list[Event], cancelled: list[Event]) -> list[str]:
        lines = []
        if new:
            n = len(new)
            lines.append(f"🎸 <b>{n} neue{'s' if n == 1 else ''} Konzert{'e' if n > 1 else ''}</b>")
            by_venue = defaultdict(list)
            for ev in sorted(new, key=lambda e: (e.date, e.time or "")):
                by_venue[ev.venue_id].append(ev)
            for vid, evs in by_venue.items():
                lines.append("")
                lines.append(f"<b>{html.escape(self.venue_names.get(vid, vid))}</b>")
                for ev in evs:
                    flags = (" 🔴 ausverkauft" if ev.sold_out else "")
                    tags = f" <i>({html.escape(', '.join(ev.tags[:3]))})</i>" if ev.tags else ""
                    lines.append(f"• {fmt_date(ev)} · <a href=\"{html.escape(ev.url)}\">{html.escape(ev.title)}</a>"
                                 f"{tags}{flags}")
        for heading, evs in (("❌ <b>Abgesagt</b>", [e for e in cancelled if not e.moved]),
                             ("↪️ <b>Verschoben</b>", [e for e in cancelled if e.moved])):
            if not evs:
                continue
            lines.append("")
            lines.append(heading)
            for ev in evs:
                note = f" → {html.escape(ev.moved_note)}" if ev.moved and ev.moved_note else ""
                lines.append(f"• {fmt_date(ev)} · {html.escape(self.venue_names.get(ev.venue_id, ev.venue_id))}: "
                             f"{html.escape(ev.title)}{note}")
        if self.base_url:
            lines.append("")
            lines.append(f"<a href=\"{html.escape(self.base_url)}\">📅 Zum Konzertkalender</a>")
        # in Telegram-taugliche Stücke teilen
        msgs, cur = [], ""
        for line in lines:
            if len(cur) + len(line) + 1 > self.LIMIT:
                msgs.append(cur)
                cur = ""
            cur += line + "\n"
        if cur.strip():
            msgs.append(cur)
        return msgs

    def send(self, new, cancelled):
        for text in self.build_messages(new, cancelled):
            r = requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage", timeout=20, json={
                "chat_id": self.chat_id, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": True, "disable_notification": self.silent,
            })
            if not r.ok:
                raise RuntimeError(f"Telegram-Fehler {r.status_code}: {r.text[:200]}")


@register("webhook")
class WebhookNotifier(Notifier):
    """Sendet JSON an eine URL – z.B. einen Home-Assistant-Webhook-Trigger."""

    def __init__(self, url: str, **kw):
        super().__init__(**kw)
        self.url = url

    def send(self, new, cancelled):
        def ser(ev):
            d = ev.to_dict()
            d["venue"] = self.venue_names.get(ev.venue_id, ev.venue_id)
            return d
        r = requests.post(self.url, timeout=20, json={
            "new": [ser(e) for e in new], "cancelled": [ser(e) for e in cancelled],
            "summary": ", ".join(f"{e.title} ({self.venue_names.get(e.venue_id, e.venue_id)})" for e in new[:10]),
        })
        r.raise_for_status()
