"""Spezifische Scraper für Venues, die nicht über PETZI laufen."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from datetime import date, datetime, timedelta
from urllib.parse import urljoin, urlsplit, parse_qs, urlencode
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .base import (Source, register, parse_dotted_date, parse_time, month_from_name, infer_year, clean, split_status,
                   first_sentence,
                   with_support)
from .generic import CssSource, parse_any_date
from ..models import Event

log = logging.getLogger(__name__)
ZURICH = ZoneInfo("Europe/Zurich")
_MOVED = re.compile(r"verschoben|verlegt|postponed|report[ée]", re.I)     # im Titel, wo es keinen Status gibt


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
                cancelled="abgesagt" in title.lower(), moved=bool(_MOVED.search(title)) and "abgesagt" not in title.lower(),
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
    """dynamo.ch – die Website holt ihr Programm aus einer Drupal-JSON:API (dynamo.nodehive.app). Die Seite selbst
    zeigt nur ~6 Wochen, die API alles. Abgefragt werden nur Titel, Datum, Pfad, Preis und Kategorien
    (`fields[...]`) – die Veranstalter-Kontaktdaten der Events werden gar nicht erst geladen.

    Kategorien: Art (Konzert, Party, Workshops, Theater/Performance) + Genres (Metal, Hip-Hop …) -> Tags.
    Option `kinds`: welche Arten übernommen werden (Standard: nur Konzerte)."""

    API = "https://dynamo.nodehive.app/jsonapi/node/event"
    FIELDS = "field_title,title,field_event_date,path,field_categories,field_event_ticket_price"
    PAGE = 50

    def fetch(self) -> list[Event]:
        q = {"filter[d][condition][path]": "field_event_date.value", "filter[d][condition][operator]": ">=",
             "filter[d][condition][value]": date.today().isoformat(), "sort": "field_event_date.value",
             "include": "field_categories", "fields[node--event]": self.FIELDS,
             "fields[taxonomy_term--event_category]": "name", "page[limit]": self.PAGE}
        data, included = [], []
        for page in range(20):                     # 50 pro Seite, mehr als 1000 kommende gibt es nicht
            d = json.loads(self.fetcher.get(f"{self.API}?{urlencode({**q, 'page[offset]': page * self.PAGE})}"))
            data += d.get("data") or []
            included += d.get("included") or []
            if not (d.get("links") or {}).get("next"):
                break
        return self.parse(json.dumps({"data": data, "included": included}))

    def parse(self, text: str) -> list[Event]:
        d = json.loads(text)
        kinds = {k.lower() for k in self.opt("kinds", ["Konzert"])}
        names = {i["id"]: i["attributes"]["name"] for i in d.get("included") or [] if i.get("type", "").startswith("taxonomy")}
        base = "https://www.dynamo.ch"
        out: dict[str, Event] = {}
        for item in d.get("data") or []:
            a = item.get("attributes") or {}
            rel = ((item.get("relationships") or {}).get("field_categories") or {}).get("data") or []
            cats = [names[c["id"]] for c in rel if c.get("id") in names]
            when, alias = a.get("field_event_date") or {}, (a.get("path") or {}).get("alias")
            if not alias or not when.get("value") or not kinds & {c.lower() for c in cats}:
                continue
            start = datetime.fromisoformat(when["value"]).astimezone(ZURICH)
            end = datetime.fromisoformat(when["end_value"]).astimezone(ZURICH) if when.get("end_value") else None
            title = clean(a.get("field_title") or a.get("title") or "")
            price = a.get("field_event_ticket_price")
            out.setdefault(alias, self.make_event(
                native_id=alias.rstrip("/").rsplit("/", 1)[-1], title=title, date=start.date(),
                time=f"{start:%H:%M}", url=base + alias, tags=cats,
                end_date=end.date() if end and end - start >= timedelta(hours=24) else None,   # nicht: 22–03 Uhr
                extra={"price": f"CHF {price}"} if price else {},
                cancelled=bool(re.search(r"abgesagt|cancelled", title, re.I)),
                moved=bool(_MOVED.search(title)) and not re.search(r"abgesagt|cancelled", title, re.I)))
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
                cancelled=bool(re.search(r"abgesagt|cancelled", title, re.I)),
                moved=bool(_MOVED.search(title)) and not re.search(r"abgesagt|cancelled", title, re.I)))
        return out


def _wanted(kind: str, kinds) -> bool:
    """Option `kinds`: Liste von Event-Arten (Gross/klein egal), [] = alle."""
    return not kinds or kind.lower() in {k.lower() for k in kinds}


@register("volkshaus")
class VolkshausSource(Source):
    """volkshaus.ch/veranstaltungen – Zürich. Monatsüberschriften («OKTOBER 2026») liefern das Jahr; pro Zeile
    Tag, Titel, Art + Zeit («KONZERT 20:00 Uhr»), Saal, Ticket-Link und ggf. «AUSVERKAUFT».

    Option `kinds`: Event-Arten (Konzert, Comedy, Theater, Vortrag …), Standard: nur Konzerte; [] = alle."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        kinds = self.opt("kinds", ["Konzert"])
        year, out = None, {}
        for el in soup.select(".month-title, .event-item"):
            if "month-title" in el["class"]:
                m = re.search(r"\d{4}", el.get_text())
                year = int(m.group()) if m else None
                continue
            cols = el.find_all("div", recursive=False)
            if len(cols) < 2:
                continue
            day = re.search(r"(\d{1,2})\.(\d{1,2})\.", cols[0].get_text(" "))
            lines = [clean(sp.get_text(" ")) for sp in cols[1].find_all("span", recursive=False)]
            if not day or len(lines) < 2:
                continue
            kind = re.sub(r"\s*\d{1,2}[:.]\d{2}.*$", "", lines[1]).strip()
            if not _wanted(kind, kinds):
                continue
            d, mo = int(day.group(1)), int(day.group(2))
            ticket = next((a["href"].strip() for a in cols[1].find_all("a", href=True) if "ticket" in a.get_text().lower()), "")
            st, info = split_status(lines[0]), cols[1].get_text(" ").upper()
            out.setdefault(el["data-event-id"], self.make_event(
                native_id=el["data-event-id"], title=st.title, date=date(year or infer_year(d, mo), mo, d),
                time=parse_time(lines[1]), url=ticket or self.cfg.url, tags=[kind.capitalize()] if kind else [],
                **st.flags(sold_out="AUSVERKAUFT" in info, cancelled="ABGESAGT" in info,
                           moved=bool(re.search(r"VERSCHOBEN|VERLEGT", info)))))
        return list(out.values())


@register("komplex457")
class Komplex457Source(Source):
    """komplex-457.ch – die Seite ist eine App, die ihr Programm aus einer öffentlichen Base44-API lädt
    (dieselbe Abfrage macht der Browser). Status: Aktiv / Ausverkauft / Abgesagt / Verlegt – «Verlegt» heisst
    meist in eine andere Halle (Dynamo, Halle 622) und gilt hier darum als abgesagt."""

    API = "https://base44.app/api/apps/68d4063c05f4a36a19b01270/entities/Event"

    def fetch(self) -> list[Event]:
        q = {"q": json.dumps({"is_draft": False, "is_archived": False}), "sort": "date", "limit": 500}
        return self.parse(self.fetcher.get(f"{self.API}?{urlencode(q)}"))

    def parse(self, text: str) -> list[Event]:
        out = []
        for e in json.loads(text):
            if e.get("is_draft") or e.get("is_archived") or e.get("is_sample") or not e.get("date"):
                continue
            start = datetime.fromisoformat(e["date"])
            if start.date() < date.today() - timedelta(days=1):
                continue
            title = clean(e.get("artist") or e.get("name") or "")
            support = [s for s in e.get("support_acts") or [] if s]
            status = (e.get("status") or "").lower()
            out.append(self.make_event(
                native_id=e["id"], title=f"{title} & Support: {', '.join(support)}" if support else title,
                date=start.date(), time=f"{start:%H:%M}", url=f"https://komplex-457.ch/EventDetail?id={e['id']}",
                tags=[t.strip() for t in re.split(r"[,/]", e.get("genre") or "") if t.strip()],
                extra={"price": f"CHF {e['ticket_price']:g}"} if (e.get("ticket_price") or 0) > 0 else {},
                sold_out=status == "ausverkauft", cancelled=status == "abgesagt",
                moved=status == "verlegt", moved_note=first_sentence(e.get("postponed_info") or "") if status == "verlegt" else ""))
        return out


@register("thehall")
class TheHallSource(Source):
    """thehall.ch/de/eventkalender/ – Dübendorf. Kacheln mit Datum («11. November 2026»), Titel und Hinweisen
    («ausverkauft», «abgesagt», «verlegt»); die Genres stehen als CSS-Klassen an der Kachel."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        genres = {o["value"].lstrip("."): clean(o.get_text()) for o in soup.select("option[value^='.']")}
        genres.pop("jumi-chalet", None)            # Raclette-Chalet zum Konzert buchbar – kein Genre
        base = self.cfg.url or "https://www.thehall.ch/de/eventkalender/"
        out = {}
        for tile in soup.select(".c-tile--events"):
            a, title_el, date_el = tile.find("a", href=True), tile.select_one(".c-tile__title"), tile.select_one(".c-tile__text")
            d = parse_any_date(date_el.get_text(" ")) if date_el else None
            if not a or not title_el or not d:
                continue
            note = tile.get_text(" ").lower()
            # «… in eine andere Location verlegt.» = weg von hier; «… auf dieses Datum verschoben.» = Datum ist das neue
            moved = next((first_sentence(p.get_text(" ")) for p in tile.find_all("p")
                          if re.search(r"verlegt|verschoben", p.get_text(), re.I)
                          and "dieses datum" not in p.get_text().lower()), "")
            url = urljoin(base, a["href"])
            out.setdefault(url, self.make_event(
                native_id=urlsplit(url).path.strip("/").split("/", 2)[-1], title=clean(title_el.get_text(" ")),
                date=d[0], url=url, tags=[genres[c] for c in tile["class"] if c in genres],
                sold_out="ausverkauft" in note, cancelled="abgesagt" in note and not moved,
                moved=bool(moved), moved_note=moved))
        return list(out.values())


@register("moods")
class MoodsSource(Source):
    """moods.ch – Zürich. Die Next.js-Seite bringt das ganze Programm als JSON mit (`__NEXT_DATA__`):
    Genres, Beginn, Preis, ausverkauft/abgesagt.

    Option `kinds`: Kategorien nach «Moods_»/«Vermietung_» (Konzert, Late_Night, Afterparty, Kinderkonzert),
    Standard: nur Konzerte."""

    def parse(self, html: str) -> list[Event]:
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            raise ValueError("Moods: kein __NEXT_DATA__ auf der Seite")
        items = json.loads(m.group(1))["props"]["pageProps"]["fallback"].get("allEvents") or []
        kinds = self.opt("kinds", ["Konzert"])
        out = {}
        for e in items:
            kind = (e.get("eventCategory") or "").split("_", 1)[-1]
            if not e.get("isVisible", True) or not e.get("eventDate") or not _wanted(kind, kinds):
                continue
            price = e.get("ticketPrice")
            out.setdefault(e["slug"], self.make_event(
                native_id=e.get("concertId") or e["slug"], title=clean(e.get("name") or ""),
                date=date.fromisoformat(e["eventDate"]), time=parse_time(e.get("timeStart") or ""),
                url=f"https://www.moods.ch/{e['slug']}", tags=[g["label"] for g in e.get("genres") or []],
                extra={"price": f"CHF {price}"} if price else {},
                sold_out=bool(e.get("isSoldOut")), cancelled=bool(e.get("isCancelled")),
                moved=bool(e.get("isPostponed")) and not e.get("isCancelled")))
        return list(out.values())


@register("plaza")
class PlazaSource(Source):
    """plaza-zurich.ch/program/liveshows/ – jedes Event als <li> mit Datum, ID und Titel in data-Attributen;
    «/ AUSVERKAUFT» steht im Titel."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        out = {}
        for li in soup.select("li.nu-event[data-nu-eid]"):
            start = datetime.strptime(li["data-nu-edate"][:16], "%Y-%m-%d %H:%M")
            if start.date() < date.today() - timedelta(days=1):     # vereinzelt hängen vergangene Shows in der Liste
                continue
            st = split_status(clean(li.get("data-nu-etitle", "")))
            ticket = li.select_one("a.nu-e-link-ticket[href]")
            presale = re.search(r"Vorverkauf[^\d]{0,25}(\d+(?:\.\d\d)?)", li.get_text(" "))   # «Vorverkauf CHF 38.-»
            out.setdefault(li["data-nu-eid"], self.make_event(
                native_id=li["data-nu-eid"], title=st.title, date=start.date(), time=f"{start:%H:%M}",
                url=ticket["href"].strip() if ticket else self.cfg.url,
                tags=["Live"] if li.get("data-nu-etype") == "2" else [], **st.flags(),
                extra={"price": f"CHF {presale.group(1)}"} if presale else {}))
        return list(out.values())


@register("kaufleuten")
class KaufleutenSource(Source):
    """kaufleuten.ch/events/kultur/ – Titel «Fink • Konzert»: der Teil nach «•» ist die Sparte
    (Konzert, Literatur, Comedy, Podcast …). Option `kinds`: Sparten, Standard: nur Konzerte; [] = alle."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        kinds = self.opt("kinds", ["Konzert"])
        out = {}
        for art in soup.select("article.event"):
            a, t, h = art.select_one("a.event-link[href]"), art.select_one("time[datetime]"), art.find("h3")
            if not a or not t or not h:
                continue
            name, _, kind = clean(h.get_text(" ")).rpartition(" • ")
            name, kind = (name, kind) if name else (kind, "")
            if not _wanted(kind, kinds):
                continue
            start = datetime.fromisoformat(t["datetime"])
            st = split_status(name)
            tickets = clean(art.select_one("ul.tickets").get_text(" ")) if art.select_one("ul.tickets") else ""
            out.setdefault(a["href"], self.make_event(
                native_id=a["href"].rstrip("/").rsplit("/", 1)[-1], title=st.title, date=start.date(),
                time=f"{start:%H:%M}", url=a["href"], tags=[kind] if kind else [],
                extra={"price": tickets} if "CHF" in tickets else {},          # «ab CHF 48»; «Verlosung» = kein Preis
                **st.flags(sold_out="ausverkauft" in art.get_text().lower())))
        return list(out.values())


@register("salzhaus")
class SalzhausSource(Source):
    """salzhaus.ch – Winterthur. Links mit title «Maggie Reilly (SCT) (Live)»: die letzte Klammer ist die
    Kategorie. Option `kinds`: Kategorien (Live, Party, Spass, Ü30 …), Standard: nur Live; [] = alle."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        kinds = self.opt("kinds", ["Live"])
        base = self.cfg.url or "https://www.salzhaus.ch/"
        out = {}
        for a in soup.select("a.sh-event-link[href]"):
            cat_el, date_el = a.select_one(".category"), a.select_one(".date")
            cat = clean(cat_el.get_text()) if cat_el else ""
            d = parse_any_date(date_el.get_text(" ")) if date_el else None
            if not d or not _wanted(cat, kinds):
                continue
            title = re.sub(rf"\s*\({re.escape(cat)}\)$", "", clean(a.get("title", ""))) if cat else clean(a.get("title", ""))
            st = split_status(title)
            status = (a.parent.get("data-status") or "").lower()
            url = urljoin(base, a["href"])
            out.setdefault(url, self.make_event(
                native_id=a.get("data-id") or url, title=st.title, date=d[0], url=url, tags=[cat] if cat else [],
                **st.flags(sold_out="sold" in status or "ausverkauft" in status, cancelled="cancel" in status,
                           moved="postpone" in status or "verschoben" in status)))
        return list(out.values())


@register("albani")
class AlbaniSource(Source):
    """albani.ch – Winterthur. Aufklappbare Liste: Titel, Unterzeilen (Support, Genre), «Fr 16.10» ohne Jahr,
    «20:00 UHR». Konzerte und Clubnächte sind nicht getrennt – was ab 22 Uhr beginnt, bekommt den Tag «Club»
    (zählt als Party und lässt sich im Typ-Filter ausblenden)."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        base = self.cfg.url or "https://www.albani.ch/"
        out = {}
        for label in soup.select("a.accLabel[data-acc-ref]"):
            head = label.select_one(".albani-event-label")
            title_el, date_el = head.select_one(".title") if head else None, label.select_one(".albani-event-date .date")
            d = parse_any_date(date_el.get_text(" ")) if date_el else None
            if not title_el or not d:
                continue
            lines = [clean(t) for t in title_el.stripped_strings]           # «Makthaverskan (SE)<br>Support: …»
            if re.match(r"ersatzdatum", lines[0], re.I) and len(lines) > 1:   # «ERSATZDATUM:<br>Prince Jelleh (CH)»
                lines = lines[1:]
            genre = head.select_one(".subline")
            when = label.select_one(".albani-event-date .subline")             # «20:00 UHR<br>Ab 25 CHF»
            time = parse_time(when.get_text(" ") if when else "")
            price = re.search(r"(?:ab\s*)?\d+\s*CHF", when.get_text(" "), re.I) if when else None
            st = split_status(lines[0].rstrip(":"))
            tags = [clean(genre.get_text(" "))] if genre else []
            if time and time >= "22:00":
                tags.append("Club")
            content = soup.find(id=label["data-acc-ref"])
            link = content.find("a", href=re.compile(r"/programm/")) if content else None
            native = re.search(r"albani_event_(\d+)", label["data-acc-ref"])
            out.setdefault(label["data-acc-ref"], self.make_event(
                native_id=native.group(1) if native else f"{st.title}|{d[0]}", title=with_support(st.title, *lines[1:]),
                date=d[0], time=time, url=urljoin(base, link["href"]) if link else base, tags=tags,
                extra={"price": price.group()} if price else {},
                **st.flags(sold_out="ausverkauft" in label.get_text().lower())))
        return list(out.values())


@register("bierhuebeli")
class BierhuebeliSource(Source):
    """bierhuebeli.ch/konzerte/ – Bern. Pro Event ein Link mit Datum, Titel, Unterzeile («Support: …») und
    Hinweisen («Ausverkauft», «Letzte Tickets»). Einige Shows finden im Kursaal statt (steht im Titel)."""

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        out = {}
        for a in soup.select("a.datumlink[href]"):
            date_el, title_el, by = a.select_one(".eventdatum.ed-mobile"), a.select_one(".eventtitel"), a.select_one(".byline")
            d = parse_any_date(date_el.get_text(" ")) if date_el else None
            if not d or not title_el:
                continue
            st, text = split_status(clean(title_el.get_text(" "))), a.get_text(" ")
            out.setdefault(a["href"], self.make_event(
                native_id=a["href"].rstrip("/").rsplit("/", 1)[-1], date=d[0], url=a["href"],
                title=with_support(st.title, by.get_text(" ") if by else ""),
                **st.flags(sold_out=bool(a.select_one(".soldout")), cancelled=bool(re.search(r"abgesagt", text, re.I)),
                           moved=bool(re.search(r"verschoben|verlegt", text, re.I)))))
        return list(out.values())


@register("muehlehunziken")
class MuehleHunzikenSource(Source):
    """muehlehunziken.ch – Rubigen. Pro Event ein Link «/programm/<name>-2026-10-24» mit «Sa 24.10.», Titel,
    Unterzeile («& The Headlines», «Special Guest: …») und Hinweis «Ausverkauft». Das Jahr steht meist im Link
    («-2026-10-24» oder nur «-2027»), sonst wird es geschätzt."""

    _SLUG_DATE = re.compile(r"-(20\d\d)(?:-(\d{2})-(\d{2}))?/?$")          # «…-2026-10-24» oder «span-2027»

    def parse(self, html: str) -> list[Event]:
        soup = BeautifulSoup(html, "lxml")
        out = {}
        for a in soup.select("a.customLink[href*='/programm/']"):
            h2, day = a.find("h2"), re.search(r"(\d{1,2})\.(\d{1,2})\.", a.get_text(" "))
            if not h2 or not day:
                continue
            d, mo = int(day.group(1)), int(day.group(2))
            m = self._SLUG_DATE.search(a["href"])
            year = int(m.group(1)) if m and (not m.group(2) or (int(m.group(2)), int(m.group(3))) == (mo, d)) \
                else infer_year(d, mo)
            sub = a.select_one("div.uppercase")
            sub = clean(sub.get_text(" ")) if sub else ""
            st = split_status(clean(h2.get_text(" ")))
            title, flags = st.title, [clean(f.get_text()).lower() for f in a.select(".flag")]
            if sub.startswith("& "):                                 # «Danko Jones» + «& The Headlines» (Vorband)
                title = f"{title} & Support: {sub[2:]}"
            else:
                title = with_support(title, sub)
            out.setdefault(a["href"], self.make_event(
                native_id=a["href"].rstrip("/").rsplit("/", 1)[-1], title=title, date=date(year, mo, d), url=a["href"],
                **st.flags(sold_out="ausverkauft" in flags,
                           cancelled=any("abgesagt" in f for f in flags),
                           moved=any(re.search(r"verschoben|verlegt", f) for f in flags))))
        return list(out.values())
