"""Generische Quellen – neue Venues ohne eigenen Python-Code anbinden.

* jsonld – Seiten mit schema.org-Event-Daten (<script type="application/ld+json">), sehr verbreitet
* ical   – ein .ics-Kalenderfeed
* css    – beliebige HTML-Liste über CSS-Selektoren aus config.yaml
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import (Source, register, parse_dotted_date, parse_time, month_from_name, infer_year, full_year, clean,
                   split_status, with_support)
from ..models import Event

_DMY_WORD = re.compile(r"(\d{1,2})\.?\s+([A-Za-zäéû]{3,})\.?\s+(\d{4}|\d{2}(?!\d))")    # «16. Okt 26» auch
_DM_SHORT = re.compile(r"(\d{1,2})\.(\d{1,2})\b\.?(?![\d.])")                         # «Fr 16.10.», «Fr 16.10»


def parse_any_date(text: str, fmt: str | None = None) -> tuple[date, date | None] | None:
    text = clean(text)
    if fmt:
        try:
            return datetime.strptime(text, fmt).date(), None
        except ValueError:
            pass
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        return date(*map(int, iso.groups())), None
    r = parse_dotted_date(text)
    if r:
        return r
    m = _DMY_WORD.search(text)
    if m and month_from_name(m.group(2)):
        return date(full_year(int(m.group(3))), month_from_name(m.group(2)), int(m.group(1))), None
    m = _DM_SHORT.search(text)               # "Fr 16.10." ohne Jahr
    if m and 1 <= int(m.group(2)) <= 12:
        d, mo = int(m.group(1)), int(m.group(2))
        return date(infer_year(d, mo), mo, d), None
    return None


# --------------------------------------------------------------------- JSON-LD

@register("jsonld")
class JsonLdSource(Source):
    EVENT_TYPES = {"Event", "MusicEvent", "Festival", "ComedyEvent", "TheaterEvent", "DanceEvent"}

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        out: dict[str, Event] = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            for item in self._walk(data):
                ev = self._to_event(item)
                if ev:
                    out.setdefault(ev.native_id, ev)
        return list(out.values())

    def _walk(self, data):
        if isinstance(data, list):
            for d in data:
                yield from self._walk(d)
        elif isinstance(data, dict):
            t = data.get("@type")
            types = set(t) if isinstance(t, list) else {t}
            if types & self.EVENT_TYPES:
                yield data
            for key in ("@graph", "itemListElement", "item", "subEvent", "event", "events"):
                if key in data:
                    yield from self._walk(data[key])

    def _to_event(self, item: dict) -> Event | None:
        start = str(item.get("startDate") or "")
        if not start or not item.get("name"):
            return None
        d = parse_any_date(start)
        if not d:
            return None
        end = parse_any_date(str(item.get("endDate") or ""))
        url = urljoin(self.cfg.url, item.get("url") or "") or self.cfg.url
        status = str(item.get("eventStatus") or "")
        avail = json.dumps(item.get("offers") or "")
        return self.make_event(
            native_id=str(item.get("@id") or url or f"{item['name']}|{start}"),
            title=clean(item["name"]), date=d[0],
            end_date=end[0] if end and end[0] != d[0] else None,
            time=parse_time(start.split("T", 1)[1][:5]) if "T" in start else None,
            url=url, cancelled="Cancelled" in status, sold_out="SoldOut" in avail,
            moved="Postponed" in status,
        )


# --------------------------------------------------------------------- iCal

@register("ical")
class ICalSource(Source):
    def parse(self, text: str) -> list[Event]:
        text = re.sub(r"\r?\n[ \t]", "", text)        # Zeilenfaltung auflösen
        out = []
        for block in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", text, re.S):
            props = {}
            for line in block.strip().splitlines():
                if ":" not in line:
                    continue
                key, val = line.split(":", 1)
                props.setdefault(key.split(";")[0].upper(), val.strip())
            raw = props.get("DTSTART", "")
            m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", raw)
            if not m or not props.get("SUMMARY"):
                continue
            title = props["SUMMARY"].replace("\\,", ",").replace("\\;", ";")
            out.append(self.make_event(
                native_id=props.get("UID") or f"{title}|{raw}",
                title=title, date=date(int(m[1]), int(m[2]), int(m[3])),
                time=f"{m[4]}:{m[5]}" if m[4] else None,
                url=props.get("URL", ""),
                tags=[t.strip() for t in props.get("CATEGORIES", "").split(",") if t.strip()],
                cancelled=props.get("STATUS", "").upper() == "CANCELLED",
            ))
        return out


# --------------------------------------------------------------------- CSS

@register("css")
class CssSource(Source):
    """Beispiel in config.yaml:

        type: css
        url: https://www.beispiel.ch/programm
        options:
          item: "article.event"        # ein Element pro Event
          title: "h2"                  # relativ zu item
          date: ".date"                # Text wird automatisch geparst
          date_format: "%d.%m.%Y"      # optional, sonst Auto-Erkennung
          time: ".time"                # optional
          link: "a"                    # optional, sonst erstes <a>
          tags: ".genre"               # optional, mehrere Treffer erlaubt
          support: "p"                 # optional: Zeile mit «Support: …» -> an den Titel angehängt

    «Ausverkauft», «Sold out!», «Abgesagt», «Verschoben» am Titelende werden entfernt und als Status übernommen.
    """

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        sel = self.cfg.options
        out: dict[str, Event] = {}
        for item in soup.select(sel["item"]):
            title_el = item.select_one(sel["title"]) if sel.get("title") else item
            date_el = item.select_one(sel["date"]) if sel.get("date") else item
            if not title_el or not date_el:
                continue
            date_src = date_el.get(sel.get("date_attr")) if sel.get("date_attr") else date_el.get_text(" ")
            d = parse_any_date(date_src or "", sel.get("date_format"))
            if not d:
                continue
            link = item.select_one(sel.get("link", "a")) if sel.get("link", "a") else None
            if link is None and item.name == "a":
                link = item
            url = urljoin(self.cfg.url, link["href"]) if link and link.has_attr("href") else self.cfg.url
            time_el = item.select_one(sel["time"]) if sel.get("time") else None
            st = split_status(clean(title_el.get_text(" ")))
            title = st.title
            if sel.get("support"):
                title = with_support(title, *(el.get_text(" ") for el in item.select(sel["support"])))
            ev = self.make_event(
                native_id=url if url != self.cfg.url else f"{title}|{d[0]}",
                title=title, date=d[0], end_date=d[1], url=url,
                time=parse_time(time_el.get_text(" ")) if time_el else None,
                tags=[clean(t.get_text()) for t in item.select(sel["tags"])] if sel.get("tags") else [],
                **st.flags(),
            )
            out.setdefault(ev.native_id, ev)
        return list(out.values())
