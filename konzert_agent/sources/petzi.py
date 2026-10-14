"""PETZI – Verband Schweizer Musikclubs (petzi.ch).

Viele Clubs (KiFF, Royal Baden, Bogen F, Helsinki, Werkk, Piccadilly, Moods, Rote Fabrik …)
verkaufen über PETZI. Jeder Veranstalter hat eine Übersichtsseite mit allen kommenden Events:

    https://www.petzi.ch/de/organiser/<ID>/

Die ID findest du auf jeder Event-Seite unter «Organisiert von». In config.yaml reicht:

    - id: kiff
      type: petzi
      options: {organiser: 5}
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Source, register, parse_dotted_date, clean
from ..models import Event

BASE = "https://www.petzi.ch"
_EVENT_HREF = re.compile(r"/events/(\d+)-[^/]+/?$")
_TITLE_ATTR = re.compile(r"^Mehr Infos(?: und Tickets)?\s*/\s*(?P<title>.*)\s*/\s*(?P<venue>[^/]+)$")
_GCAL_DATES = re.compile(r"dates=(\d{8})T(\d{2})(\d{2})")


@register("petzi")
class PetziSource(Source):

    @property
    def url(self) -> str:
        if self.cfg.url:
            return self.cfg.url
        lang = self.opt("lang", "de")
        return f"{BASE}/{lang}/organiser/{self.opt('organiser')}/"

    def fetch(self) -> list[Event]:
        return self.parse(self.fetcher.get(self.url))

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        events: dict[str, Event] = {}
        for a in soup.find_all("a", href=True):
            m = _EVENT_HREF.search(a["href"].split("?")[0])
            if not m:
                continue
            text = clean(a.get_text(" "))
            dates = parse_dotted_date(text)
            if not dates:
                continue
            title = None
            tm = _TITLE_ATTR.match(clean(a.get("title", "")))
            if tm:
                title = tm["title"].strip()
            if not title:  # Fallback: Text ohne Datum und ohne "Mehr Infos"
                title = re.sub(r"^[\d.\-–]+\s*", "", text)
                title = re.sub(r"\s*Mehr Infos.*$", "", title).strip()
            ev = self.make_event(
                native_id=m.group(1),
                title=title,
                date=dates[0],
                end_date=dates[1],
                url=urljoin(BASE, a["href"]),
                cancelled=bool(re.search(r"abgesagt|cancel|annul", title, re.I)),
            )
            events.setdefault(ev.native_id, ev)
        return list(events.values())

    def enrich(self, event: Event) -> Event:
        """Lädt die Detailseite: Genre-Tags, Beginnzeit, Preis."""
        if not self.opt("details", True):
            return event
        html = self.fetcher.get(event.url)
        return self.parse_detail(html, event)

    @staticmethod
    def parse_detail(html: str, event: Event) -> Event:
        soup = BeautifulSoup(html, "lxml")
        tags = []
        for a in soup.find_all("a", href=re.compile(r"/search/\?q=")):
            t = clean(a.get_text())
            if t and t not in tags:
                tags.append(t)
        if tags:
            event.tags = tags
        gcal = soup.find("a", href=_GCAL_DATES)
        if gcal:
            m = _GCAL_DATES.search(gcal["href"])
            event.time = f"{m.group(2)}:{m.group(3)}"
        price = soup.find(string=re.compile(r"Ab CHF"))
        if price:
            event.extra["price"] = clean(price)
        if soup.find("a", href=re.compile(r"/tickets/")):
            event.extra["tickets"] = True
        return event
