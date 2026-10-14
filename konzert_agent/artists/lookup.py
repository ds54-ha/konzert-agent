"""Artist-Infos aus offenen Musik-Datenbanken.

* MusicBrainz – Genres/Stile (Community-Tags), Herkunftsland. Kein Key, max. 1 Anfrage/s.
* Deezer      – Anzahl Fans als Mass für die Popularität. Kein Key.

Beide sind offizielle APIs für Programme. MusicBrainz sperrt `/ws` per robots.txt für Crawler, erlaubt
den Zugriff über die API aber ausdrücklich (mit Pause und erkennbarem User-Agent) – darum läuft die Suche
über einen eigenen Fetcher ohne robots-Prüfung, aber mit derselben Pause pro Server.

Zuordnung: nur exakte Namenstreffer (ohne Gross-/Kleinschreibung, Akzente, Satzzeichen). Gibt es mehrere
gleichnamige Artists, entscheidet zuerst das Land aus dem Titel («(SE)»), dann die Anzahl Tags.
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from urllib.parse import urlencode

import requests

from ..fetch import Fetcher
from .extract import ArtistName

log = logging.getLogger(__name__)

MB_URL = "https://musicbrainz.org/ws/2/artist"
DEEZER_URL = "https://api.deezer.com/search/artist"
DEEZER_ARTIST_URL = "https://api.deezer.com/artist"


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c)).casefold().replace("&", "and")
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"[^a-z0-9]", "", s)


@dataclass
class ArtistInfo:
    query: str
    name: str | None = None              # gefundener Name
    country: str | None = None           # laut MusicBrainz
    disambiguation: str = ""
    mbid: str | None = None
    tags: list[str] = field(default_factory=list)
    deezer_id: int | None = None
    fans: int | None = None
    confidence: str = "keine"            # hoch | mittel | tief | keine
    notes: list[str] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.mbid or self.deezer_id)


    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ArtistInfo":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class ArtistLookup:
    """Sucht Artists; `cache` (z.B. der Store) hält Ergebnisse über Läufe hinweg, `overrides` sind
    die manuellen Korrekturen aus config.yaml (Schlüssel = Name, Wert = None oder {mbid, deezer, genres})."""

    def __init__(self, user_agent: str, delay: float = 2.0, fetcher: Fetcher | None = None,
                 cache=None, refresh_days: int = 30, overrides: dict | None = None):
        self.fetcher = fetcher or Fetcher(user_agent, delay=max(delay, 1.1), respect_robots=False)
        self.store = cache
        self.refresh_days = refresh_days
        self.overrides = {norm(k): v for k, v in (overrides or {}).items()}
        self._cache: dict[str, ArtistInfo] = {}

    def lookup(self, artist: ArtistName) -> list[ArtistInfo]:
        """Ganzen Namen suchen; nichts gefunden und «A & B» -> die Teile einzeln."""
        info = self.lookup_name(artist.name, artist.countries)
        if info.found or not artist.parts:
            return [info]
        infos = [self.lookup_name(p, artist.countries) for p in artist.parts]
        return infos if any(i.found for i in infos) else [info]

    def lookup_name(self, name: str, countries: list[str] | None = None) -> ArtistInfo:
        if norm(name) in self.overrides:
            return self._override(name, self.overrides[norm(name)])
        key = f"{norm(name)}|{','.join(countries or [])}"
        if key in self._cache:
            return self._cache[key]
        if self.store is not None:
            cached = self.store.get_artist(key, max_age_days=self.refresh_days)
            if cached:
                self._cache[key] = ArtistInfo.from_dict(cached)
                return self._cache[key]
        info = ArtistInfo(query=name)
        mb_unique = self._musicbrainz(info, countries or [])
        dz_unique = self._deezer(info)
        info.confidence = self._confidence(info, mb_unique, dz_unique)
        self._cache[key] = info
        # bei Abruf-Fehlern nicht speichern, sonst bleibt die Lücke bis zum nächsten Refresh
        if self.store is not None and not any(n.endswith("-Fehler") for n in info.notes):
            self.store.put_artist(key, info.to_dict())
        return info

    def _override(self, name: str, ov) -> ArtistInfo:
        """Manuelle Korrektur: None/«none» = nie zuordnen; sonst feste IDs und/oder Genres."""
        key = f"override|{norm(name)}|{json.dumps(ov, sort_keys=True)}"
        if key in self._cache:
            return self._cache[key]
        info = ArtistInfo(query=name, notes=["manuell"])
        if isinstance(ov, dict):
            if ov.get("mbid"):
                data = self._get_json(f"{MB_URL}/{ov['mbid']}?{urlencode({'inc': 'tags', 'fmt': 'json'})}",
                                      info, "MusicBrainz") or {}
                info.mbid, info.name, info.country = ov["mbid"], data.get("name"), data.get("country")
                info.disambiguation = data.get("disambiguation", "")
                info.tags = [t["name"] for t in sorted(data.get("tags", []), key=lambda t: -t.get("count", 0))[:6]]
            if ov.get("deezer"):
                data = self._get_json(f"{DEEZER_ARTIST_URL}/{ov['deezer']}", info, "Deezer") or {}
                info.deezer_id, info.fans = int(ov["deezer"]), data.get("nb_fan")
                info.name = info.name or data.get("name")
            if ov.get("genres"):
                info.tags = list(ov["genres"]) + [t for t in info.tags if t not in ov["genres"]]
            info.name = info.name or name
            info.confidence = "hoch"
        self._cache[key] = info
        return info

    def _get_json(self, url: str, info: ArtistInfo, source: str) -> dict | None:
        try:
            try:
                return json.loads(self.fetcher.get(url))
            except requests.HTTPError as e:
                if e.response is None or e.response.status_code != 503:
                    raise
                time.sleep(5)                    # MusicBrainz: 503 = «zu viele Anfragen», einmal nachfassen
                return json.loads(self.fetcher.get(url))
        except Exception as e:  # noqa: BLE001 – eine Quelle darf ausfallen
            log.warning("%s-Suche für %r fehlgeschlagen: %s", source, info.query, e)
            info.notes.append(f"{source}-Fehler")
            return None

    # ------------------------------------------------------------ MusicBrainz

    def _musicbrainz(self, info: ArtistInfo, countries: list[str]) -> bool:
        q = info.query.replace("\\", "\\\\").replace('"', '\\"')
        data = self._get_json(f"{MB_URL}?{urlencode({'query': f'artist:\"{q}\"', 'fmt': 'json', 'limit': 10})}",
                              info, "MusicBrainz")
        target = norm(info.query)
        hits = [a for a in (data or {}).get("artists", [])
                if norm(a.get("name", "")) == target
                or any(norm(al.get("name", "")) == target for al in a.get("aliases", []))]
        if not hits:
            return False
        by_country = [a for a in hits if countries and a.get("country") in countries]
        pick = max(by_country or hits, key=lambda a: sum(t.get("count", 0) for t in a.get("tags", [])))
        info.name = pick["name"]
        info.mbid = pick["id"]
        info.country = pick.get("country")
        info.disambiguation = pick.get("disambiguation", "")
        info.tags = [t["name"] for t in sorted(pick.get("tags", []), key=lambda t: -t.get("count", 0))[:6]]
        if len(hits) > 1:
            info.notes.append(f"{len(hits)} gleichnamige bei MusicBrainz"
                              + (", per Land gewählt" if by_country else ""))
        return len(hits) == 1 or len(by_country) == 1

    # ------------------------------------------------------------ Deezer

    def _deezer(self, info: ArtistInfo) -> bool:
        data = self._get_json(f"{DEEZER_URL}?{urlencode({'q': info.query, 'limit': 10})}", info, "Deezer")
        target = norm(info.query)
        hits = sorted((a for a in (data or {}).get("data", []) if norm(a.get("name", "")) == target),
                      key=lambda a: -a.get("nb_fan", 0))
        if not hits:
            return False
        info.deezer_id, info.fans = hits[0]["id"], hits[0].get("nb_fan", 0)
        info.name = info.name or hits[0]["name"]
        # mehrere gleichnamige mit ähnlich vielen Fans -> unklar, welcher gemeint ist
        if len(hits) > 1 and hits[1].get("nb_fan", 0) * 5 > info.fans:
            info.notes.append(f"{len(hits)} gleichnamige bei Deezer")
            return False
        return True

    @staticmethod
    def _confidence(info: ArtistInfo, mb_unique: bool, dz_unique: bool) -> str:
        if not info.found:
            return "keine"
        # je Quelle ein Punkt, wenn sie genau einen passenden Artist kennt (bzw. das Land entschieden hat)
        level = bool(info.mbid and mb_unique) + bool(info.deezer_id and dz_unique)
        if len(norm(info.query)) <= 4:          # «Elin», «JAS», «Bac»: kurze Namen sind oft Verwechslungen
            level -= 1
        return ["tief", "mittel", "hoch"][max(level, 0)]
