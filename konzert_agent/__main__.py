"""Kommandozeile.

    python -m konzert_agent serve            # Web-UI + periodischer Scheduler (Standard im Docker)
    python -m konzert_agent run              # einmal alle Venues prüfen und benachrichtigen
    python -m konzert_agent run --no-notify  # nur einsammeln
    python -m konzert_agent test kiff        # eine Venue testen, nichts speichern
    python -m konzert_agent test-notify      # Testnachricht an alle Kanäle
    python -m konzert_agent types            # verfügbare Quellentypen
    python -m konzert_agent artists kiff     # erkannte Bands + Genre/Popularität prüfen
    python -m konzert_agent artists --save   # Band-Infos aller Events neu berechnen und speichern
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import date

from . import __version__
from .agent import Agent, event_from_row, load_plugins, passes_filters
from .artists import ArtistEnricher, ArtistLookup
from .config import load_config
from .fetch import Fetcher
from .models import Event
from .sources import REGISTRY, create_source

log = logging.getLogger("konzert_agent")


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
                                               cfg.artists.titles)
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
    a = p.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    cfg = load_config(a.config)
    load_plugins(cfg.plugins)

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
        print(f"{len(res.new)} neu, {len(res.cancelled)} abgesagt, Fehler: {res.errors or 'keine'}")
        return

    if a.cmd == "serve":
        import uvicorn
        from .web.app import create_app
        if not a.no_scheduler:
            threading.Thread(target=scheduler_loop, args=(agent, cfg.settings.interval_hours), daemon=True).start()
        uvicorn.run(create_app(agent), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
