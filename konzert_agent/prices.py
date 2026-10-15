"""Ticketpreise einheitlich anzeigen – jede Quelle schreibt sie anders.

    «Ab CHF 20,00» -> «ab CHF 20»   ·   «CHF VVK 25.- / AK 30.-» -> «CHF 25–30»   ·   «CHF 38» -> «CHF 38»
    «ab CHF 0» / «Gratiseintritt» -> «gratis»   ·   ohne Zahl (z.B. «Verlosung») -> unverändert

Die Quellen speichern den Rohtext in extra["price"]; umgeformt wird erst beim Anzeigen.
"""
from __future__ import annotations

import re

_AMOUNT = re.compile(r"(?<![\d.,])(\d{1,4})(?:[.,](\d{2}))?(?:\.-|(?![\d.,]))")


def _fmt(whole: str, cents: str | None) -> str:
    return whole if not cents or cents == "00" else f"{whole}.{cents}"


def format_price(raw: str | None) -> str:
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    if not text:
        return ""
    if re.search(r"gratis|kostenlos|free|eintritt frei", text, re.I):
        return "gratis"
    amounts = sorted({(int(w) + int(c or 0) / 100, _fmt(w, c)) for w, c in _AMOUNT.findall(text)})
    if not amounts:
        return text
    if amounts[-1][0] == 0:
        return "gratis"
    amounts = [a for a in amounts if a[0] > 0]
    low, high = amounts[0][1], amounts[-1][1]
    if re.search(r"\bab\b", text, re.I):
        return f"ab CHF {low}"
    return f"CHF {low}" if low == high else f"CHF {low}–{high}"
