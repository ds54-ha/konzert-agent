"""Bands folgen: passt ein Event zu einer gefolgten Band?

Schlüssel = normalisierter Name (wie im Band-Cache: ohne Akzente, «The», Satzzeichen, Leerzeichen).
Treffer, wenn eine erkannte Band (extra["artists"]) so heisst – oder der Name als ganze Wörter im Titel steht.
Letzteres fängt auch Support-Bands und Events ohne Band-Infos ab, ohne dass «Elin» in «Berlin» passt.
Erkannte Bands werden vorher aus dem Titel entfernt – sonst passte «Sports» auch auf «PA Sports».
"""
from __future__ import annotations

import re

from .artists.lookup import norm

_WORD = re.compile(r"[\w'’&.+-]+")
MAX_WORDS = 6


def follow_key(name: str) -> str:
    return norm(name)


def title_keys(title: str) -> set[str]:
    """Alle Wortfolgen (bis 6 Wörter) des Titels, normalisiert."""
    words = _WORD.findall(title)
    return {norm(" ".join(words[i:j])) for i in range(len(words)) for j in range(i + 1, min(i + MAX_WORDS, len(words)) + 1)}


def event_keys(title: str, extra: dict) -> set[str]:
    keys, rest = set(), title
    for a in extra.get("artists") or []:
        for n in (a.get("name"), a.get("query")):
            if n:
                keys.add(norm(n))
                rest = re.sub(rf"(?<!\w){re.escape(n)}(?!\w)", " ", rest, flags=re.I)
    keys |= title_keys(rest)
    keys.discard("")
    return keys


def matching(title: str, extra: dict, follows: dict[str, str]) -> list[str]:
    """Namen der gefolgten Bands, die zum Event passen (follows: Schlüssel -> Anzeigename)."""
    keys = event_keys(title, extra)
    return [name for key, name in follows.items() if key in keys]
