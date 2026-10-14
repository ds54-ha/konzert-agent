"""Konfiguration laden (config.yaml + Umgebungsvariablen)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand_env(value):
    """Ersetzt ${VAR} bzw. ${VAR:-default} in Strings rekursiv."""
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


@dataclass
class VenueConfig:
    id: str
    name: str
    type: str
    url: str = ""
    city: str = ""
    enabled: bool = True
    include: list[str] = field(default_factory=list)   # Regex: Titel/Tags müssen eins davon treffen
    exclude: list[str] = field(default_factory=list)   # Regex: Treffer werden verworfen
    options: dict = field(default_factory=dict)        # quellenspezifische Optionen


@dataclass
class Settings:
    database: str = "data/konzerte.db"
    interval_hours: float = 6
    user_agent: str = "KonzertAgent/1.0 (privater Konzert-Notifier)"
    request_delay: float = 2.0
    respect_robots: bool = True
    notify_on_first_run: bool = False
    base_url: str = ""
    new_badge_days: int = 7


@dataclass
class Config:
    settings: Settings
    venues: list[VenueConfig]
    notifiers: list[dict]
    plugins: list[str] = field(default_factory=list)

    def venue(self, venue_id: str) -> VenueConfig | None:
        return next((v for v in self.venues if v.id == venue_id), None)


def load_config(path: str | Path) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    raw = _expand_env(raw)
    settings = Settings(**(raw.get("settings") or {}))
    venues = []
    seen = set()
    for v in raw.get("venues") or []:
        vc = VenueConfig(**v)
        if vc.id in seen:
            raise ValueError(f"Doppelte Venue-ID in config: {vc.id}")
        seen.add(vc.id)
        venues.append(vc)
    return Config(settings=settings, venues=venues, notifiers=raw.get("notifiers") or [],
                  plugins=raw.get("plugins") or [])
