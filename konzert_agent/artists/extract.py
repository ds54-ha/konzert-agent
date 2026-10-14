"""Bandnamen aus Event-Titeln herauslesen.

Titel sehen z.B. so aus:

    Bibi Vaplan (CH) & Support: Omisdus (CH)       -> Bibi Vaplan [CH], Omisdus [CH]
    Badener Punk-Night mit Sin Logica (Luzern) • PCA (Züri)  -> Sin Logica [CH], PCA [CH]
    Baschi (CH) – «TOUR 26/27»                     -> Baschi [CH]
    Lo & Leduc                                     -> Lo & Leduc  (Teile «Lo», «Leduc» als Ausweichkandidaten)

`&` ist mehrdeutig («Lo & Leduc» ist ein Act, «Open Season & Jahcoustix» sind zwei). Darum wird der
ganze Name zuerst gesucht; die Einzelteile stehen in `parts` und werden nur verwendet, wenn der
ganze Name nicht gefunden wird.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Events ohne Bands: Tags (PETZI/Schüür) oder Stichworte im Titel
NON_MUSIC_TAGS = {"party", "performance", "workshop", "live-podcast", "tanzveranstaltung", "comedy"}
SKIP_TITLE = re.compile(
    r"\b(party|disco|comedy|podcast|buchvernissage|buchklub|lesung|open mic|kleinkunst\w*|tribute|"
    r"festival|fest)\b", re.I)

# «Label – Bands», «Label: Bands», «Label mit Bands»: das Label wird verworfen
_LABEL = re.compile(r"night|nacht|surprise act|präsentiert|presents", re.I)
_LABEL_SPLIT = re.compile(r"\s+(?:–|-|mit)\s+|:\s+", re.I)
# ohne Label: alles ab « – », « - », « | », «: » ist Untertitel (Tour, Zusatzshow, Album …)
_SUBTITLE = re.compile(r"\s+[–|-]\s+.*$|:\s+.*$")
_QUOTED = re.compile(r"«[^»]*»|„[^“\"]*[“\"]|\"[^\"]*\"")
_PREFIX = re.compile(r"^(?:(?:montags\s+\d+|duo|trio)\s+)+", re.I)
_FEAT = re.compile(r"\s+(?:feat\.?|ft\.|featuring)\s+.*$", re.I)
# Trenner zwischen mehreren Acts
_SUPPORT = re.compile(r"\s*&\s*support\b\s*:?\s*", re.I)
_SPLIT = re.compile(r"\s*•\s*|\s+\+\s+|\s*,\s+|\s+x\s+|(?<=\))\s*&\s*")
_PAREN = re.compile(r"\(([^)]*)\)")
_TRAILING = re.compile(
    r"\s+(?:live|solo|[\w-]*tour\b.*|plattentaufe.*|ep[ -]?taufe.*|albumfeier.*|zusatz(?:show|konzert).*|"
    r"ausverkauft.*|im\s+\w+|(?:19|20)\d\d)$", re.I)
_JUNK_PART = re.compile(r"^(?:support|friends|special guests?)$|aftershow", re.I)

COUNTRY_ALIASES = {"UK": "GB", "BEL": "BE", "CAN": "CA", "IRL": "IE", "BMU": "BM", "SUI": "CH", "GER": "DE"}
SWISS_PLACES = {"züri", "zürich", "luzern", "winthi", "winterthur", "bern", "basel", "aarau", "baden", "solothurn"}


@dataclass
class ArtistName:
    name: str
    countries: list[str] = field(default_factory=list)   # ISO-Codes aus «(SE)», «(AT/ IR)», «(Züri)» -> CH
    parts: list[str] = field(default_factory=list)       # Ausweichkandidaten bei «A & B»


def _countries(paren_texts: list[str]) -> list[str]:
    out = []
    for txt in paren_texts:
        for tok in re.split(r"[/,]\s*", txt.strip()):
            tok = tok.strip()
            code = COUNTRY_ALIASES.get(tok.upper(), tok.upper())
            if re.fullmatch(r"[A-Z]{2}", code) and tok.isupper():
                out.append(code)
            elif tok.lower() in SWISS_PLACES:
                out.append("CH")
    return list(dict.fromkeys(out))


def _clean_part(part: str) -> ArtistName | None:
    countries = _countries(_PAREN.findall(part))
    name = _PAREN.sub(" ", part)
    name = re.sub(r"\s*&\s*friends\b", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip()
    prev = None
    while prev != name:                       # «Pedestrians Goodbye-Tour», «HGich.T Live» …
        prev = name
        name = _TRAILING.sub("", name).strip(" .!,;:-–")
    if not name or _JUNK_PART.search(name):
        return None
    parts = [p for p in re.split(r"\s*&\s*|\s+and\s+", name, flags=re.I) if p] if re.search(r"&|\band\b", name) else []
    return ArtistName(name=name, countries=countries, parts=parts if len(parts) > 1 else [])


def skip_reason(title: str, tags: list[str] | None = None) -> str | None:
    """Warum ein Event keine Band-Suche bekommt (Party, Comedy, Festival …) – sonst None."""
    tagset = {t.lower() for t in tags or []}
    if tagset & NON_MUSIC_TAGS and "konzert" not in tagset:
        return next(t for t in tags if t.lower() in NON_MUSIC_TAGS)
    m = SKIP_TITLE.search(title)
    return m.group(1).capitalize() if m else None


def extract_artists(title: str) -> list[ArtistName]:
    t = title.replace("\xad", "").replace("’", "'").replace("´", "'")
    t = _QUOTED.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = _PREFIX.sub("", t)
    t = _SUPPORT.sub(" • ", t)                # vor dem Untertitel-Schnitt, sonst fällt «Support: X» weg

    m = _LABEL_SPLIT.search(t)
    if m and _LABEL.search(t[:m.start()]):
        # Label vorne weg; danach trennen « – » die Acts («Surprise Act – The Monsters – Molotov Cunts»)
        t = re.sub(r"\s+[–-]\s+", " • ", t[m.end():])
    else:
        t = _SUBTITLE.sub("", t)

    t = _FEAT.sub("", t)
    out: list[ArtistName] = []
    for part in _SPLIT.split(t):
        a = _clean_part(part)
        if a and a.name.lower() not in {x.name.lower() for x in out}:
            out.append(a)
    return out
