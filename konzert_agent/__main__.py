"""Kommandozeile.

    python -m konzert_agent serve            # Web-UI + periodischer Scheduler (Standard im Docker)
    python -m konzert_agent run              # einmal alle Venues prüfen und benachrichtigen
    python -m konzert_agent run --no-notify  # nur einsammeln
    python -m konzert_agent test kiff        # eine Venue testen, nichts speichern
    python -m konzert_agent test-notify      # Testnachricht an alle Kanäle
    python -m konzert_agent types            # verfügbare Quellentypen
    python -m konzert_agent artists kiff     # erkannte Bands + Genre/Popularität prüfen
    python -m konzert_agent artists --save   # Band-Infos aller Events neu berechnen und speichern
    python -m konzert_agent user add anna    # Benutzer anlegen (fragt nach dem Passwort)
    python -m konzert_agent user list        # Benutzer anzeigen; weitere: passwd, disable, enable,
                                             #   delete, logout (alle Sitzungen beenden), new-ical,
                                             #   telegram-off (Telegram-Verbindung lösen)
"""
from __future__ import annotations

import argparse
import getpass
import logging
import os
import re
import sys
import threading
import time
from datetime import date

from . import __version__
from .agent import Agent, event_from_row, load_plugins, passes_filters
from .artists import ArtistEnricher, ArtistLookup
from .config import load_config
from .auth import hash_password, new_token
from .fetch import Fetcher
from .models import Event
from .sources import REGISTRY, create_source
from .store import Store

log = logging.getLogger("konzert_agent")
_BOT_TOKEN = re.compile(r"bot\d+:[\w-]+")


class RedactingFormatter(logging.Formatter):
    """Telegram-Token aus Logs entfernen – Fehlermeldungen von requests enthalten die ganze URL (…/bot<TOKEN>/…)."""

    def format(self, record):
        return _BOT_TOKEN.sub("bot<TOKEN>", super().format(record))


def scheduler_loop(agent: Agent, hours: float):
    time.sleep(5)
    while True:
        try:
            agent.run()
        except Exception:  # noqa: BLE001
            log.exception("Lauf fehlgeschlagen")
        time.sleep(max(hours, 0.25) * 3600)


def _fans(n: int | None) -> str:
    if n is None:
        return "–"
    return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}k" if n >= 1e3 else str(n)


def artists_report(agent: Agent, only: list[str], lookup: bool = True, limit: int = 0, save: bool = False):
    """Zeigt pro Event die erkannten Bands und was MusicBrainz/Deezer dazu wissen (inkl. Korrekturen)."""
    cfg = agent.config
    venues = [v for v in cfg.venues if v.enabled and (not only or v.id in only)]
    if only and len(venues) < len(only):
        sys.exit(f"Unbekannte Location: {', '.join(set(only) - {v.id for v in venues})}")
    enricher = agent.artists or ArtistEnricher(ArtistLookup(cfg.settings.user_agent, cfg.settings.request_delay,
                                                            cache=agent.store, overrides=cfg.artists.overrides),
                                               cfg.artists.titles, cfg.artists.events)
    stats = {"events": 0, "skipped": 0, "artists": 0, "genres": 0, "fans": 0}
    conf: dict[str, int] = {}
    for vc in venues:
        rows = agent.filtered_events(agent.store.events(start=date.today(), venues=[vc.id]))
        if limit:
            rows = rows[:limit]
        print(f"\n═══ {vc.name} ({len(rows)} Events)")
        for d in rows:
            stats["events"] += 1
            ev = event_from_row(d)
            print(f"{ev.date}  {ev.title}")
            if not lookup:
                names, reason = enricher.names_for(ev)
                print(f"      – übersprungen: {reason}" if reason else "      – keine Band erkannt" if not names else
                      "\n".join(f"      → {n.name}" + (f" [{'/'.join(n.countries)}]" if n.countries else "")
                                + (f"   (Teile: {' | '.join(n.parts)})" if n.parts else "") for n in names))
                continue
            x = enricher.apply(ev).extra
            if save:
                agent.store.update_extra(d["uid"], x)
            if x.get("artists_skip"):
                stats["skipped"] += 1
                print(f"      – übersprungen: {x['artists_skip']}")
            for art in x["artists"]:
                stats["artists"] += 1
                stats["genres"] += bool(art["genres"])
                stats["fans"] += art["fans"] is not None
                conf[art["confidence"]] = conf.get(art["confidence"], 0) + 1
                mark = {"hoch": "✓", "mittel": "~", "tief": "?", "keine": "✗"}[art["confidence"]]
                if art["confidence"] == "keine":
                    print(f"      {mark} {art['query']}  – nichts gefunden")
                    continue
                origin = f" ({art['country']})" if art["country"] else ""
                print(f"      {mark} {art['query']} → {art['name']}{origin} · {', '.join(art['styles']) or 'keine Genres'}"
                      f" · {_fans(art['fans'])} Fans  [{art['confidence']}]")
            if x["genres"] or x["popularity"] is not None:
                src = " (von der Location)" if x["genres_source"] == "location" else ""
                pop = f" · Popularität {x['popularity']} ({x['popularity_label']})" if x["popularity"] is not None else ""
                print(f"      ⇒ {', '.join(x['genres']) or 'kein Genre'}{src}{pop}")
    print(f"\n{stats['events']} Events, davon {stats['skipped']} übersprungen (Party/Comedy/Festival …)")
    if lookup:
        n = stats["artists"] or 1
        print(f"{stats['artists']} Bands · mit Genres: {stats['genres']} ({stats['genres'] * 100 // n}%)"
              f" · mit Fan-Zahl: {stats['fans']} ({stats['fans'] * 100 // n}%)")
        print("Sicherheit: " + ", ".join(f"{k} {conf.get(k, 0)}" for k in ("hoch", "mittel", "tief", "keine"))
              + "   (✓ hoch · ~ mittel · ? tief · ✗ nichts)")
        print("Gespeichert." if save else "Nicht gespeichert – mit --save übernehmen.")


MIN_PASSWORD = 10


def _ask_password(from_stdin: bool) -> str:
    if from_stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        pw = getpass.getpass("Passwort: ")
        if pw != getpass.getpass("Passwort wiederholen: "):
            sys.exit("Passwörter stimmen nicht überein.")
    if len(pw) < MIN_PASSWORD:
        sys.exit(f"Passwort zu kurz (mindestens {MIN_PASSWORD} Zeichen).")
    return pw


def user_command(store: Store, a) -> None:
    if a.action == "list":
        users = store.users()
        if not users:
            print("Noch keine Benutzer. Anlegen mit: python -m konzert_agent user add <name>")
        for u in users:
            flags = [f for f, on in (("gesperrt", u["disabled"]), ("teilt Konzerte", u["share_marks"]),
                                     ("Telegram", u["telegram"])) if on]
            print(f"{u['username']:20} angelegt {u['created'][:10]} · zuletzt aktiv {(u['last_seen'] or 'nie')[:16]}"
                  + (f" · {', '.join(flags)}" if flags else ""))
        return
    if not a.name:
        sys.exit(f"user {a.action}: Benutzername fehlt")
    if a.action == "add":
        if store.user_by_name(a.name):
            sys.exit(f"Benutzer '{a.name}' existiert schon.")
        store.create_user(a.name, hash_password(_ask_password(a.password_stdin)), new_token())
        print(f"Benutzer '{a.name}' angelegt.")
        return
    user = store.user_by_name(a.name)
    if not user:
        sys.exit(f"Benutzer '{a.name}' nicht gefunden.")
    if a.action == "passwd":
        store.update_user(user["id"], pw_hash=hash_password(_ask_password(a.password_stdin)))
        n = store.delete_sessions(user["id"])
        print(f"Passwort geändert, {n} Sitzung(en) beendet.")
    elif a.action in ("disable", "enable"):
        store.update_user(user["id"], disabled=int(a.action == "disable"))
        if a.action == "disable":
            store.delete_sessions(user["id"])
        print(f"Benutzer '{a.name}' {'gesperrt' if a.action == 'disable' else 'freigegeben'}.")
    elif a.action == "delete":
        store.delete_user(user["id"])
        print(f"Benutzer '{a.name}' gelöscht.")
    elif a.action == "logout":
        print(f"{store.delete_sessions(user['id'])} Sitzung(en) von '{a.name}' beendet.")
    elif a.action == "telegram-off":
        print("Telegram getrennt." if store.tg_unlink(user["id"]) else f"'{a.name}' hat kein Telegram verbunden.")
    elif a.action == "new-ical":
        store.update_user(user["id"], ical_token=new_token())
        print("Neuer Kalender-Link erzeugt – alte Abos funktionieren nicht mehr.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="konzert_agent")
    p.add_argument("-c", "--config", default=os.environ.get("KONZERT_CONFIG", "config.yaml"))
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8080)
    s.add_argument("--no-scheduler", action="store_true")
    r = sub.add_parser("run"); r.add_argument("venues", nargs="*"); r.add_argument("--no-notify", action="store_true")
    t = sub.add_parser("test"); t.add_argument("venue"); t.add_argument("--details", action="store_true")
    sub.add_parser("test-notify")
    sub.add_parser("types")
    ar = sub.add_parser("artists"); ar.add_argument("venues", nargs="*")
    ar.add_argument("--no-lookup", action="store_true", help="nur Namen erkennen, nichts nachschlagen")
    ar.add_argument("--limit", type=int, default=0, help="max. Events pro Location")
    ar.add_argument("--save", action="store_true", help="Ergebnis in die Events übernehmen (z.B. nach Korrekturen)")
    us = sub.add_parser("user", help="Benutzer verwalten")
    us.add_argument("action", choices=["add", "list", "passwd", "disable", "enable", "delete", "logout", "new-ical",
                                       "telegram-off"])
    us.add_argument("name", nargs="?")
    us.add_argument("--password-stdin", action="store_true", help="Passwort von stdin lesen (für Skripte)")
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO)
    for h in logging.getLogger().handlers:
        h.setFormatter(RedactingFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    cfg = load_config(a.config)
    load_plugins(cfg.plugins)

    if a.cmd == "user":
        user_command(Store(cfg.settings.database), a)
        return

    if a.cmd == "types":
        print("\n".join(sorted(REGISTRY)))
        return

    if a.cmd == "test":
        vc = cfg.venue(a.venue)
        if not vc:
            sys.exit(f"Venue '{a.venue}' nicht in config gefunden")
        s = cfg.settings
        src = create_source(vc, Fetcher(s.user_agent, s.request_delay, s.respect_robots))
        try:
            events = sorted(src.fetch(), key=lambda e: e.date)
        except Exception as e:  # noqa: BLE001
            sys.exit(f"{vc.name}: Abruf fehlgeschlagen – {type(e).__name__}: {e}")
        print(f"{vc.name}: {len(events)} Events gefunden\n")
        for ev in events:
            if a.details:
                src.enrich(ev)
            mark = " " if passes_filters(ev, vc) else "✗"
            extra = f"  [{', '.join(ev.tags)}]" if ev.tags else ""
            print(f" {mark} {ev.date} {ev.time or '     '}  {ev.title}{extra}")
        print("\n✗ = durch include/exclude-Filter ausgeblendet")
        return

    agent = Agent(cfg)

    if a.cmd == "artists":
        artists_report(agent, a.venues, lookup=not a.no_lookup, limit=a.limit, save=a.save)
        return

    if a.cmd == "test-notify":
        demo = Event(venue_id=cfg.venues[0].id, native_id="test", title="Testkonzert (Konzert-Agent funktioniert)",
                     date=date.today(), time="20:00", url=cfg.settings.base_url or "https://www.petzi.ch",
                     tags=["Test"])
        for n in agent.notifiers:
            n.send([demo], [])
            print(f"OK: {type(n).__name__}")
        if not agent.notifiers:
            print("Keine Benachrichtigungskanäle konfiguriert.")
        return

    if a.cmd == "run":
        res = agent.run(only=a.venues or None, notify=not a.no_notify)
        print(f"{len(res.new)} neu, {len(res.cancelled)} abgesagt/verschoben, Fehler: {res.errors or 'keine'}")
        return

    if a.cmd == "serve":
        import uvicorn
        from .web.app import create_app
        if not a.no_scheduler:
            threading.Thread(target=scheduler_loop, args=(agent, cfg.settings.interval_hours), daemon=True).start()
        if agent.user_bot:                  # Benutzer verbinden sich selbst über den Bot (README «Telegram pro Benutzer»)
            threading.Thread(target=agent.user_bot.poll_forever, daemon=True).start()
        uvicorn.run(create_app(agent), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
