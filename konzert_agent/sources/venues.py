"""Spezifische Scraper für Venues, die nicht über PETZI laufen."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import date, datetime, timezone
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .base import Source, register, parse_dotted_date, parse_time, month_from_name, clean
from .generic import CssSource
from ..models import Event

log = logging.getLogger(__name__)
ZURICH = ZoneInfo("Europe/Zurich")


@register("exil")
class ExilSource(Source):
    """exil.club – Zürich. Einträge: 'Titel 15.10.26 Donnerstag [Sold Out] live|dj'.

    Option `kinds`: welche Event-Arten übernommen werden (Standard: nur 'live')."""

    _RE = re.compile(r"^(?P<title>.+?)\s+(?P<date>\d{2}\.\d{2}\.\d{2})\s+\S+\s*(?P<sold>Sold Out)?\s*(?P<kind>live|dj)\s*$",
                     re.I)

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        kinds = {k.lower() for k in self.opt("kinds", ["live"])}
        out: dict[str, Event] = {}
        base = self.cfg.url or "https://exil.club"
        for a in soup.find_all("a", href=re.compile(r"/events/[^/?#]+")):
            m = self._RE.match(clean(a.get_text(" ")))
            if not m or m["kind"].lower() not in kinds:
                continue
            d, _ = parse_dotted_date(m["date"])
            title = m["title"].strip()
            url = urljoin(base, a["href"])
            out.setdefault(url, self.make_event(
                native_id=urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1],
                title=title, date=d, url=url,
                sold_out=bool(m["sold"]),
                cancelled="abgesagt" in title.lower(),
                tags=["Live"] if m["kind"].lower() == "live" else ["DJ"],
            ))
        return list(out.values())


@register("hallenstadion")
class HallenstadionSource(Source):
    """hallenstadion.ch/events/ – Einträge: 'Titel 15 Oct 2026 … 19:30 Uhr …'.

    Die Seite zeigt nur 12 Events; der Rest kommt per «mehr laden» über admin-ajax.php
    (`/events/page/N/` liefert immer wieder Seite 1). Anzahl Seiten steht in `data-max_pages`.
    Option `max_pages` begrenzt die Anzahl Abrufe (Standard 20)."""

    _RE = re.compile(r"^(?P<title>.+?)\s+(?P<d>\d{1,2})\s+(?P<m>[A-Za-zäÄ]{3,})\.?\s+(?P<y>\d{4})(?P<rest>.*)$")
    _MAX_PAGES = re.compile(r'data-max_pages="(\d+)"')
    _FILTERS = ("filter_by_genre", "filter_by_events_type", "filter_by_date", "from_date", "to_date")

    def fetch(self) -> list[Event]:
        base = self.cfg.url or "https://hallenstadion.ch/events/"
        html = self.fetcher.get(base)
        events = {e.native_id: e for e in self.parse(html)}
        m = self._MAX_PAGES.search(html)
        pages = min(int(m.group(1)), int(self.opt("max_pages", 20))) if m else 1
        ajax = urljoin(base, "/wp-admin/admin-ajax.php")
        for page in range(2, pages + 1):
            params = {"action": "events_filter", "paged": page, **dict.fromkeys(self._FILTERS, "")}
            for ev in self.parse(self.fetcher.get(f"{ajax}?{urlencode(params)}")):
                events.setdefault(ev.native_id, ev)
        return list(events.values())

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        out: dict[str, Event] = {}
        base = self.cfg.url or "https://hallenstadion.ch/events/"
        for a in soup.find_all("a", href=re.compile(r"/events/[^/?#]+")):
            href = a["href"]
            m = self._RE.match(clean(a.get_text(" ")))
            if not m:
                continue
            month = month_from_name(m["m"])
            if not month:
                continue
            url = urljoin(base, href)
            q = parse_qs(urlsplit(url).query)
            slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
            native = q.get("availability_id", [slug])[0]
            out.setdefault(native, self.make_event(
                native_id=native, title=m["title"].strip(),
                date=date(int(m["y"]), month, int(m["d"])),
                time=parse_time(m["rest"]), url=url,
            ))
        return list(out.values())


@register("xtra")
class XtraSource(CssSource):
    """x-tra.ch/de/programm/ – zeigt 9 Events, der Rest kommt über «Alle anzeigen» (POST auf dieselbe Seite
    mit dem CSRF-Token aus dem <meta>-Tag, genau wie der Browser). Klappt das Nachladen nicht, bleiben
    wenigstens die ersten 9."""

    DEFAULTS = {"item": "li:has(> a[href*='/programm/'])", "title": "h2", "date": "h3", "link": "a"}

    def __init__(self, cfg, fetcher):
        super().__init__(replace(cfg, options={**self.DEFAULTS, **cfg.options}), fetcher)

    def fetch(self) -> list[Event]:
        url = self.cfg.url or "https://www.x-tra.ch/de/programm/"
        html = self.fetcher.get(url)
        token = re.search(r'name="csrf-token"\s+content="([^"]+)"', html)
        try:
            data = json.loads(self.fetcher.post(url, {"action": "column_events_load_more",
                                                      "csrf_token": token.group(1) if token else ""},
                                                headers={"X-Requested-With": "XMLHttpRequest"}))
            html += data.get("events") or ""
        except Exception as e:  # noqa: BLE001
            log.warning("X-tra: «Alle anzeigen» fehlgeschlagen (%s) – nur die ersten Events", e)
        return self.parse(html)


@register("dynamo")
class DynamoSource(Source):
    """dynamo.ch/events-kurse – ein Block pro Tag (<div class="view-grid" id="2026-10-16">), darin
    Karten mit Kategorie («Event / Konzert», «Kurs / Gestaltung»). Die Seite zeigt nur ~6 Wochen.

    Achtung: die Uhrzeiten in der Liste sind UTC (Detailseite: 19:00, Liste: 17:00) -> umrechnen.
    Option `kinds`: welche Event-Kategorien übernommen werden (Standard: nur Konzerte)."""

    _TIME = re.compile(r"\b(\d{1,2}):(\d{2})\s*[–-]")

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        kinds = {k.lower() for k in self.opt("kinds", ["Konzert"])}
        base = self.cfg.url or "https://www.dynamo.ch/events-kurse"
        out: dict[str, Event] = {}
        for day in soup.select("div.view-grid[id]"):
            try:
                d = date.fromisoformat(day["id"])
            except ValueError:
                continue
            for art in day.find_all("article"):
                link = art.find("a", href=re.compile(r"/veranstaltung/"))
                cat = clean(art.find("p").get_text(" ")) if art.find("p") else ""
                main, _, kind = (c.strip() for c in cat.partition("/"))
                if not link or main.lower() != "event" or kind.lower() not in kinds:
                    continue
                title_el = art.find(["h3", "h2"])
                title = clean(title_el.get_text(" ") if title_el else link.get_text(" "))
                m = self._TIME.search(art.get_text(" "))
                time = None
                if m:
                    utc = datetime(d.year, d.month, d.day, int(m[1]), int(m[2]), tzinfo=timezone.utc)
                    time = f"{utc.astimezone(ZURICH):%H:%M}"
                url = urljoin(base, link["href"])
                out.setdefault(url, self.make_event(
                    native_id=link["href"].rstrip("/").rsplit("/", 1)[-1], title=title, date=d, time=time,
                    url=url, tags=[kind], cancelled=bool(re.search(r"abgesagt|cancelled", title, re.I))))
        return list(out.values())


@register("nordportal")
class NordportalSource(Source):
    """nordportal.ch – die Programmseite lädt die Events per JavaScript aus einer WordPress-API
    (npwp.kailua.ch/wp-json/wp/v2/event). Dieselbe Abfrage macht jeder Browser beim Seitenaufruf.

    Option `kinds`: Event-Arten (Party, Liveshow, Sonstiges), Standard: nur Liveshows."""

    API = "https://npwp.kailua.ch/wp-json/wp/v2/event"

    def fetch(self) -> list[Event]:
        items = []
        for page in range(1, 11):                  # 100 pro Seite, mehr als 1000 gibt es nicht
            batch = json.loads(self.fetcher.get(f"{self.API}?{urlencode({'acf_format': 'standard', 'per_page': 100, 'page': page})}"))
            items += batch
            if len(batch) < 100:
                break
        return self.parse(json.dumps(items))

    def parse(self, text: str) -> list[Event]:
        kinds = {k.lower() for k in self.opt("kinds", ["Liveshow"])}
        out = []
        for item in json.loads(text):
            acf = item.get("acf") or {}
            kind = (acf.get("event_art") or "").strip()
            if kind.lower() not in kinds:
                continue
            d = parse_dotted_date(acf.get("datum") or "")
            if not d:
                continue
            head = BeautifulSoup(acf.get("event_titel") or "", "lxml")
            title_el = head.find("h1") or head.find(["h2", "h3"])
            title = clean(title_el.get_text(" ")) if title_el else clean(item.get("title", {}).get("rendered", ""))
            out.append(self.make_event(
                native_id=str(item["id"]), title=title, date=d[0],
                time=parse_time((acf.get("start_zeit") or "")[10:]),
                url=f"https://nordportal.ch/programm/{item.get('slug')}",
                tags=[kind], sold_out=bool(acf.get("ist_ausverkauft")),
                cancelled=bool(re.search(r"abgesagt|cancelled", title, re.I))))
        return out
