"""MusicBrainz-Tags und Location-Tags auf grobe Genre-Gruppen abbilden, Fans -> Popularität.

Ein Tag kann in mehrere Gruppen fallen («pop rap» -> Hip-Hop & Rap + Pop, «indie rock» -> Indie + Rock).
Tags ohne Gruppe (Länder, «german», «female vocalist» …) werden nicht als Stil übernommen.
"""
from __future__ import annotations

import math
import re

GENRE_GROUPS: list[tuple[str, str]] = [
    ("Metal", r"metal|doom|sludge|grind|djent|deathcore|drone"),
    ("Punk & Hardcore", r"punk|hardcore|\bemo\b|screamo|beatdown"),
    ("Hip-Hop & Rap", r"hip[ -]?hop|\brap\b|trap\b|grime|drill\b|urban"),
    ("Electronic", r"electr|techno|house|\bedm\b|trance|dubstep|drum and bass|ambient|synth|downtempo|idm|dance\b"),
    ("Jazz", r"jazz|swing\b|bebop"),
    ("Soul, R&B & Funk", r"soul|r&b|rnb|funk|gospel|rare groove"),
    ("Reggae & Ska", r"reggae|\bska\b|\bdub\b|dancehall"),
    ("Blues", r"blues"),
    ("Folk & Singer-Songwriter", r"folk|songwrit|acoustic|americana|\bcountry\b|liedermacher|chanson"),
    ("Schlager & Volksmusik", r"schlager|volksmusik|volkstümlich"),
    ("Klassik", r"classical|klassik|orchestr|opera|soundtrack"),
    ("Indie & Alternative", r"indie|alternative|shoegaze|post-punk|grunge"),
    ("Rock", r"rock|garage|psychedel|stoner|\bprog"),
    ("Pop", r"pop\b"),
    ("Experimental", r"experimental|noise|avant"),
    ("Latin", r"latin|salsa|reggaeton|cumbia|cubana"),
]
_COMPILED = [(name, re.compile(rx, re.I)) for name, rx in GENRE_GROUPS]


def groups_for(tag: str) -> list[str]:
    return [name for name, rx in _COMPILED if rx.search(tag)]


def classify(tags: list[str], max_groups: int = 3, max_styles: int = 5) -> tuple[list[str], list[str]]:
    """(Genre-Gruppen, Stile) – Reihenfolge nach Gewicht; frühe Tags (= meiste Stimmen) zählen mehr."""
    score: dict[str, float] = {}
    styles: list[str] = []
    for i, tag in enumerate(tags):
        gs = groups_for(tag)
        if not gs:
            continue
        if tag.lower() not in (s.lower() for s in styles):
            styles.append(tag)
        for g in gs:
            score[g] = score.get(g, 0) + 1 / (i + 1)
    groups = sorted(score, key=lambda g: -score[g])
    return groups[:max_groups], styles[:max_styles]


# ---------------------------------------------------------------- Popularität

POPULARITY_LABELS = [(300_000, "Star"), (20_000, "bekannt"), (1_000, "Szene"), (0, "lokal")]


def popularity(fans: int | None) -> int | None:
    """Deezer-Fans logarithmisch auf 0–100: 100 ≈ 10 Mio., 86 ≈ 1 Mio., 43 ≈ 1000, 29 ≈ 100."""
    if fans is None:
        return None
    return max(0, min(100, round(100 * math.log10(fans + 1) / 7)))


def popularity_label(fans: int | None) -> str | None:
    if fans is None:
        return None
    return next(label for limit, label in POPULARITY_LABELS if fans >= limit)
