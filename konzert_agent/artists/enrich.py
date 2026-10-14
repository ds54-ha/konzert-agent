"""Bands eines Events nachschlagen und das Ergebnis in `event.extra` ablegen.

    extra["artists"]          – pro Band: Name, Genres, Stile, Fans, Popularität, Sicherheit
    extra["genres"]           – Genre-Gruppen des Events (aus den Bands, sonst aus den Location-Tags)
    extra["styles"]           – feinere Stile («doom metal», «stoner rock»)
    extra["popularity"]       – 0–100, vom Headliner (erste gefundene Band im Titel)
    extra["popularity_label"] – lokal | Szene | bekannt | Star
    extra["artists_skip"]     – Grund, falls keine Bands gesucht wurden (Party, Comedy …)
    extra["artists_retry"]    – true, wenn eine Quelle nicht antwortete -> Backfill versucht es erneut

Genres und Popularität stammen nur aus Treffern mit Sicherheit «hoch» oder «mittel»; unsichere Treffer
stehen zwar in extra["artists"], fliessen aber nicht ein.
"""
from __future__ import annotations

import re

from ..models import Event
from .extract import ArtistName, extract_artists, skip_reason
from .genres import classify, popularity, popularity_label
from .lookup import ArtistLookup

CONFIDENT = {"hoch", "mittel"}
EXTRA_KEYS = ("artists", "genres", "genres_source", "styles", "popularity", "popularity_label", "artists_skip",
              "artists_retry")


class ArtistEnricher:
    def __init__(self, lookup: ArtistLookup, title_overrides: dict | None = None):
        self.lookup = lookup
        # config: artists.titles – Regex auf den Titel -> Liste der Bands ([] = keine Bands)
        self.titles = [(re.compile(k, re.I), v or []) for k, v in (title_overrides or {}).items()]

    def names_for(self, ev: Event) -> tuple[list[ArtistName], str | None]:
        for rx, names in self.titles:
            if rx.search(ev.title):
                return [ArtistName(n) for n in names], None if names else "manuell"
        reason = skip_reason(ev.title, ev.tags)
        return ([], reason) if reason else (extract_artists(ev.title), None)

    def apply(self, ev: Event) -> Event:
        for k in EXTRA_KEYS:
            ev.extra.pop(k, None)
        names, reason = self.names_for(ev)
        artists, failed = [], False
        for n in names:
            for info in self.lookup.lookup(n):
                failed |= any(note.endswith("-Fehler") for note in info.notes)
                groups, styles = classify(info.tags)
                artists.append({
                    "name": info.name or info.query, "query": info.query, "confidence": info.confidence,
                    "genres": groups, "styles": styles, "fans": info.fans,
                    "popularity": popularity(info.fans), "popularity_label": popularity_label(info.fans),
                    "country": info.country, "mbid": info.mbid, "deezer_id": info.deezer_id,
                })
        sure = [a for a in artists if a["confidence"] in CONFIDENT]
        genres = list(dict.fromkeys(g for a in sure for g in a["genres"]))[:3]
        styles = list(dict.fromkeys(s for a in sure for s in a["styles"]))[:5]
        source = "bands"
        if not genres:                                   # Rückfall: Tags der Location (PETZI, Schüür …)
            genres, _ = classify(ev.tags)
            source = "location" if genres else None
        # Popularität des Abends = Headliner (steht im Titel zuerst), nicht die bekannteste Vorband
        top = next((a for a in sure if a["fans"] is not None), None)
        ev.extra.update({
            "artists": artists, "genres": genres, "genres_source": source, "styles": styles,
            "popularity": top["popularity"] if top else None,
            "popularity_label": top["popularity_label"] if top else None,
        })
        if reason:
            ev.extra["artists_skip"] = reason
        if failed:
            ev.extra["artists_retry"] = True
        return ev
