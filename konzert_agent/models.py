"""Datenmodell für Events."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date


@dataclass
class Event:
    venue_id: str            # ID aus config.yaml, z.B. "kiff"
    native_id: str           # stabile ID innerhalb der Quelle (z.B. PETZI-Event-ID oder URL)
    title: str
    date: date               # Starttag
    url: str = ""
    end_date: date | None = None
    time: str | None = None  # "20:00" (Konzertbeginn), falls bekannt
    tags: list[str] = field(default_factory=list)
    sold_out: bool = False
    cancelled: bool = False
    moved: bool = False      # verschoben/verlegt (nicht abgesagt) – moved_note sagt wohin bzw. auf wann
    moved_note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def uid(self) -> str:
        raw = f"{self.venue_id}:{self.native_id}"
        if len(raw) <= 120:
            return raw
        return f"{self.venue_id}:{hashlib.sha1(self.native_id.encode()).hexdigest()}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["uid"] = self.uid
        d["date"] = self.date.isoformat()
        d["end_date"] = self.end_date.isoformat() if self.end_date else None
        return d
