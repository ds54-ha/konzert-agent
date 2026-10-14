"""Event-Typ (Konzert / Party / Andere) aus Tags und Titel – keine Quelle liefert das einheitlich.

Zuerst zählen die Tags der Location (PETZI: «Konzert», «Party», «Performance» …), erst ohne passende Tags
eindeutige Wörter im Titel. Im Zweifel «Konzert» – es ist ein Konzertkalender.
"""
from __future__ import annotations

import re

KINDS = ("Konzert", "Party", "Andere")

_TAG_CONCERT = re.compile(r"^(konzert|konzert/show|live|liveshow|concert)$", re.I)
_TAG_PARTY = re.compile(r"^(party|club|tanzveranstaltung|disco|dj)$", re.I)
_TAG_OTHER = re.compile(r"^(performance|workshop|comedy|lesung|theater|kino|film|kabarett|literatur|vortrag|markt)$", re.I)
_TITLE_PARTY = re.compile(r"\b(party|disco|djs?|dj-set|ü\d\d)\b", re.I)
_TITLE_OTHER = re.compile(r"\b(comedy|lesung|quiz|workshop|kino|flohmarkt|vortrag|kabarett|podcast)\b", re.I)


def event_kind(title: str, tags: list[str]) -> str:
    if any(_TAG_CONCERT.match(t) for t in tags):          # «Club, Konzert, Party» = Konzert mit Party danach
        return "Konzert"
    if any(_TAG_PARTY.match(t) for t in tags):
        return "Party"
    if any(_TAG_OTHER.match(t) for t in tags):
        return "Andere"
    if _TITLE_PARTY.search(title):
        return "Party"
    if _TITLE_OTHER.search(title):
        return "Andere"
    return "Konzert"
