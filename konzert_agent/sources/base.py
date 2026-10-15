"""Basisklasse, Registry und Datums-Helfer für Quellen.

Eine neue Quelle schreiben:

    from .base import Source, register

    @register("meine_venue")
    class MeineVenue(Source):
        def parse(self, html: str) -> list[Event]:
            ...

Danach in config.yaml eine Venue mit `type: meine_venue` anlegen.
Für viele Seiten reicht aber schon ein generischer Typ (petzi, jsonld, ical, css).
"""
from __future__ import annotations

import re
from datetime import date

from ..config import VenueConfig
from ..fetch import Fetcher
from ..models import Event

REGISTRY: dict[str, type["Source"]] = {}


def register(name: str):
    def deco(cls):
        REGISTRY[name] = cls
        cls.type_name = name
        return cls
    return deco


def create_source(cfg: VenueConfig, fetcher: Fetcher) -> "Source":
    try:
        cls = REGISTRY[cfg.type]
    except KeyError:
        raise ValueError(f"Unbekannter Quellentyp '{cfg.type}' für Venue '{cfg.id}'. "
                         f"Verfügbar: {', '.join(sorted(REGISTRY))}") from None
    return cls(cfg, fetcher)


class Source:
    type_name = "base"

    def __init__(self, cfg: VenueConfig, fetcher: Fetcher):
        self.cfg = cfg
        self.fetcher = fetcher

    def opt(self, key, default=None):
        return self.cfg.options.get(key, default)

    def fetch(self) -> list[Event]:
        """Holt die Programmseite und parst sie. Für Paginierung o.ä. überschreiben."""
        return self.parse(self.fetcher.get(self.cfg.url))

    def parse(self, html: str) -> list[Event]:
        raise NotImplementedError

    def enrich(self, event: Event) -> Event:
        """Optional: Details nachladen – wird nur für NEUE Events aufgerufen."""
        return event

    def make_event(self, **kw) -> Event:
        return Event(venue_id=self.cfg.id, **kw)


# ---------------------------------------------------------------- Datums-Helfer

MONTHS = {
    # deutsch
    "jan": 1, "januar": 1, "jän": 1, "feb": 2, "februar": 2, "mär": 3, "märz": 3, "maerz": 3,
    "apr": 4, "april": 4, "mai": 5, "jun": 6, "juni": 6, "jul": 7, "juli": 7, "aug": 8,
    "august": 8, "sep": 9, "sept": 9, "september": 9, "okt": 10, "oktober": 10, "nov": 11,
    "november": 11, "dez": 12, "dezember": 12,
    # englisch / französisch
    "mar": 3, "march": 3, "may": 5, "june": 6, "july": 7, "oct": 10, "october": 10,
    "dec": 12, "december": 12, "january": 1, "february": 2,
    "janv": 1, "févr": 2, "fév": 2, "mars": 3, "avr": 4, "juin": 6, "juil": 7, "août": 8, "déc": 12,
}


def month_from_name(name: str) -> int | None:
    n = name.strip(". ").lower()
    return MONTHS.get(n) or MONTHS.get(n[:3])


def full_year(y: int, today: date | None = None) -> int:
    return y + 2000 if y < 100 else y


def infer_year(day: int, month: int, today: date | None = None) -> int:
    """Für Angaben ohne Jahr: liegt das Datum >2 Monate zurück, ist nächstes Jahr gemeint."""
    today = today or date.today()
    candidate = date(today.year, month, day)
    if (today - candidate).days > 60:
        return today.year + 1
    return today.year


_RANGE_RE = re.compile(
    r"(?P<d1>\d{1,2})\.?(?:(?P<m1>\d{1,2})\.?)?\s*[-–]\s*(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})\.(?P<y>\d{2,4})")
_SINGLE_RE = re.compile(r"(?P<d>\d{1,2})\.(?P<m>\d{1,2})\.(?P<y>\d{2,4})")


_FULL_RANGE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s*[-–]\s*(\d{1,2})\.(\d{1,2})\.(\d{4})")


def parse_dotted_date(text: str) -> tuple[date, date | None] | None:
    """'14.10.2026', '14.10.26', '25-28.11.2026', '30.10-02.11.2026', '17.10.2026 – 18.10.2026' -> (start, ende)."""
    m = _FULL_RANGE_RE.search(text)
    if m:
        d1, m1, y1, d2, m2, y2 = map(int, m.groups())
        return date(y1, m1, d1), date(y2, m2, d2)
    m = _RANGE_RE.search(text)
    if m:
        y = full_year(int(m["y"]))
        m2 = int(m["m2"])
        m1 = int(m["m1"]) if m["m1"] else m2
        start = date(y if m1 <= m2 else y - 1, m1, int(m["d1"]))
        return start, date(y, m2, int(m["d2"]))
    m = _SINGLE_RE.search(text)
    if m:
        return date(full_year(int(m["y"])), int(m["m"]), int(m["d"])), None
    return None


_TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\b")          # 20:00, 20.00, 20h00


def parse_time(text: str) -> str | None:
    m = _TIME_RE.search(text or "")
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


# Status-Zusätze am Titelende: «Simple Plan - SOLD OUT!», «… / AUSVERKAUFT», «Masego - VERSCHOBEN!»
_STATUS = re.compile(r"\s*[-–/|:]?\s*[(\[]?\s*(ausverkauft|sold[\s-]*out|abgesagt|cancell?ed|verschoben|postponed|"
                     r"neues datum)\s*!?[)\]]?\s*$", re.I)


def split_status(title: str) -> tuple[str, bool, bool]:
    """Titel ohne Status-Zusatz -> (titel, ausverkauft, abgesagt)."""
    sold = cancelled = False
    while (m := _STATUS.search(title)) and m.start() > 0:
        word = m.group(1).lower()
        sold |= word.startswith(("ausverkauft", "sold"))
        cancelled |= word.startswith(("abgesagt", "cancel"))
        title = title[:m.start()].rstrip()
    return title, sold, cancelled


_SUPPORT_TXT = re.compile(r"\b(?:support|s(?:pe|ep)cial guests?|warm-?up)\s*:\s*(.+)$", re.I)


def with_support(title: str, *texts: str) -> str:
    """Hängt «Support: X» aus einer Unterzeile an den Titel – so liest die Band-Erkennung die Vorband mit."""
    acts = [m.group(1).strip() for t in texts if (m := _SUPPORT_TXT.search(clean(t)))]
    return f"{title} & Support: {', '.join(acts)}" if acts else title
