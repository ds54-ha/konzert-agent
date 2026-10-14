"""Der eigentliche Agent: alle Venues abklappern, Neues erkennen, benachrichtigen."""
from __future__ import annotations

import importlib.util
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .artists import ArtistEnricher, ArtistLookup
from .config import Config, VenueConfig
from .fetch import Fetcher
from .models import Event
from .notifiers import create_notifiers
from .sources import create_source
from .store import Store

log = logging.getLogger(__name__)


def load_plugins(paths: list[str]):
    """Lädt eigene Quellen-/Notifier-Dateien (registrieren sich per Decorator)."""
    for p in paths:
        spec = importlib.util.spec_from_file_location(Path(p).stem, p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        log.info("Plugin geladen: %s", p)


def passes_filters(ev: Event, cfg: VenueConfig) -> bool:
    hay = " ".join([ev.title, *ev.tags, *ev.extra.get("genres", []), *ev.extra.get("styles", [])])
    if cfg.include and not any(re.search(p, hay, re.I) for p in cfg.include):
        return False
    if cfg.exclude and any(re.search(p, hay, re.I) for p in cfg.exclude):
        return False
    return True


def event_from_row(d: dict) -> Event:
    return Event(venue_id=d["venue_id"], native_id=d["native_id"], title=d["title"], url=d.get("url") or "",
                 date=date.fromisoformat(d["date"]), tags=d["tags"], extra=dict(d.get("extra") or {}))


@dataclass
class RunResult:
    new: list[Event] = field(default_factory=list)
    cancelled: list[Event] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    found: dict[str, int] = field(default_factory=dict)


class Agent:
    def __init__(self, config: Config, store: Store | None = None, fetcher: Fetcher | None = None):
        self.config = config
        s = config.settings
        self.store = store or Store(s.database)
        self.fetcher = fetcher or Fetcher(s.user_agent, s.request_delay, s.respect_robots)
        names = {v.id: v.name for v in config.venues}
        self.notifiers = create_notifiers(config.notifiers, names, s.base_url)
        self._run_lock = threading.Lock()
        a = config.artists
        self.artists = ArtistEnricher(
            ArtistLookup(s.user_agent, s.request_delay, cache=self.store, refresh_days=a.refresh_days,
                         overrides=a.overrides), a.titles) if a.enabled else None

    def enrich_artists(self, ev: Event):
        if not self.artists:
            return
        try:
            self.artists.apply(ev)
        except Exception:  # noqa: BLE001 – Band-Infos sind Zusatz, der Lauf geht weiter
            log.exception("Band-Infos für %r nicht geladen", ev.title)

    def backfill_artists(self, limit: int | None = None, venues: list[str] | None = None, redo: bool = False) -> int:
        """Band-Infos für bestehende Events nachholen (redo=True: alle neu berechnen, z.B. nach Korrekturen)."""
        if not self.artists:
            return 0
        rows = self.store.events(start=date.today(), venues=venues, without_artists=not redo)
        for d in rows[:limit] if limit else rows:
            ev = event_from_row(d)
            self.enrich_artists(ev)
            self.store.update_extra(d["uid"], ev.extra)
        return len(rows[:limit] if limit else rows)

    def run_venue(self, cfg: VenueConfig, result: RunResult):
        src = create_source(cfg, self.fetcher)
        first_run = not self.store.venue_has_events(cfg.id)
        today = date.today()
        try:
            events = [e for e in src.fetch() if (e.end_date or e.date) >= today]
        except Exception as e:  # noqa: BLE001 – eine kaputte Venue soll nicht alles stoppen
            log.exception("Venue %s fehlgeschlagen", cfg.id)
            self.store.record_run(cfg.id, 0, f"{type(e).__name__}: {e}")
            result.errors[cfg.id] = str(e)
            return
        if not events:
            log.warning("Venue %s: keine Events gefunden – Seitenstruktur geändert?", cfg.id)

        new, cancelled = self.store.upsert(events)
        # Details nur für neue Events nachladen (spart Requests), dann filtern
        for ev in new:
            try:
                src.enrich(ev)
            except Exception as e:  # noqa: BLE001
                log.warning("Details für %s nicht geladen: %s", ev.url, e)
            self.enrich_artists(ev)            # nach enrich(): PETZI-Tags dienen als Genre-Rückfall
            self.store.update_details(ev)
        new = [e for e in new if passes_filters(e, cfg) and not e.cancelled]
        cancelled = [e for e in cancelled if passes_filters(e, cfg)]

        self.store.record_run(cfg.id, len(events), None if events else "0 Events gefunden")
        result.found[cfg.id] = len(events)
        if first_run and not self.config.settings.notify_on_first_run:
            log.info("Venue %s: Erstimport von %d Events (ohne Benachrichtigung)", cfg.id, len(events))
            self.store.mark_notified([e.uid for e in new])
            return
        log.info("Venue %s: %d Events, %d neu, %d abgesagt", cfg.id, len(events), len(new), len(cancelled))
        result.new += new
        result.cancelled += cancelled

    def run(self, only: list[str] | None = None, notify: bool = True) -> RunResult:
        if not self._run_lock.acquire(blocking=False):
            log.info("Lauf bereits aktiv – übersprungen")
            return RunResult(errors={"_": "Lauf bereits aktiv"})
        try:
            result = RunResult()
            for cfg in self.config.venues:
                if not cfg.enabled or (only and cfg.id not in only):
                    continue
                self.run_venue(cfg, result)
            if not only:
                n = self.backfill_artists(self.config.artists.backfill_per_run)
                if n:
                    log.info("Band-Infos für %d bestehende Events nachgeholt", n)
            if notify and (result.new or result.cancelled):
                for n in self.notifiers:
                    try:
                        n.send(result.new, result.cancelled)
                    except Exception:  # noqa: BLE001
                        log.exception("Benachrichtigung über %s fehlgeschlagen", type(n).__name__)
                self.store.mark_notified([e.uid for e in result.new])
            return result
        finally:
            self._run_lock.release()

    def filtered_events(self, events: list[dict]) -> list[dict]:
        """Wendet include/exclude auch auf die Web-Ansicht an."""
        cfgs = {v.id: v for v in self.config.venues}
        out = []
        for d in events:
            cfg = cfgs.get(d["venue_id"])
            if cfg is None:
                continue
            if passes_filters(event_from_row(d), cfg):
                out.append(d)
        return out
