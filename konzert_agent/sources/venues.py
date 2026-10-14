"""Spezifische Scraper für Venues, die nicht über PETZI laufen."""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlsplit, parse_qs

from bs4 import BeautifulSoup

from .base import Source, register, parse_dotted_date, parse_time, month_from_name, clean
from ..models import Event


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
    """hallenstadion.ch/events/ – Einträge: 'Titel 15 Oct 2026 … 19:30 Uhr …'."""

    _RE = re.compile(r"^(?P<title>.+?)\s+(?P<d>\d{1,2})\s+(?P<m>[A-Za-zäÄ]{3,})\.?\s+(?P<y>\d{4})(?P<rest>.*)$")

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
