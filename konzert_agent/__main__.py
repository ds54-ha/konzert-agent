"""Kommandozeile.

    python -m konzert_agent serve            # Web-UI + periodischer Scheduler (Standard im Docker)
    python -m konzert_agent run              # einmal alle Venues prüfen und benachrichtigen
    python -m konzert_agent run --no-notify  # nur einsammeln
    python -m konzert_agent test kiff        # eine Venue testen, nichts speichern
    python -m konzert_agent test-notify      # Testnachricht an alle Kanäle
    python -m konzert_agent types            # verfügbare Quellentypen
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from datetime import date

from .agent import Agent, load_plugins, passes_filters
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="konzert_agent")
    p.add_argument("-c", "--config", default=os.environ.get("KONZERT_CONFIG", "config.yaml"))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve"); s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8080)
    s.add_argument("--no-scheduler", action="store_true")
    r = sub.add_parser("run"); r.add_argument("venues", nargs="*"); r.add_argument("--no-notify", action="store_true")
    t = sub.add_parser("test"); t.add_argument("venue"); t.add_argument("--details", action="store_true")
    sub.add_parser("test-notify")
    sub.add_parser("types")
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
