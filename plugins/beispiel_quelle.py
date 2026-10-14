"""Beispiel für eine eigene Quelle.

In config.yaml aktivieren:

    plugins: [plugins/beispiel_quelle.py]
    venues:
      - id: meine_bar
        name: Meine Bar
        city: Baden
        type: meine_bar
        url: https://www.meine-bar.ch/agenda
"""
import re

from bs4 import BeautifulSoup

from konzert_agent.sources import Source, register
from konzert_agent.sources.base import parse_dotted_date, parse_time, clean


@register("meine_bar")
class MeineBar(Source):
    def parse(self, html):
        soup = BeautifulSoup(html, "lxml")
        events = []
        for row in soup.select("li.agenda-item"):          # an die Seite anpassen
            text = clean(row.get_text(" "))
            dates = parse_dotted_date(text)
            link = row.find("a", href=True)
            if not dates or not link:
                continue
            events.append(self.make_event(
                native_id=link["href"],
                title=clean(link.get_text()),
                date=dates[0],
                time=parse_time(text),
                url=link["href"],
                sold_out=bool(re.search(r"ausverkauft", text, re.I)),
            ))
        return events
