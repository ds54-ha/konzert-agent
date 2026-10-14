import json
import unittest
from datetime import date

from konzert_agent.config import VenueConfig
from konzert_agent.sources import create_source

DYNAMO = """
<div class="view-grid" id="2026-10-16">
  <article><p><span>Kurs</span> <span>/</span> <span>Gestaltung</span></p> 07:00–11:00
    <a href="/veranstaltung/risografie"><h3>Crashkurs Risografie</h3></a></article>
  <article><p><span>Event</span> <span>/</span> <span>Konzert</span></p> 17:00–21:30
    <a href="/veranstaltung/xoxo"><h3>XOXO &amp; CHOKESLAM</h3></a></article>
  <article><p><span>Event</span> <span>/</span> <span>Party</span></p> 20:00–02:00
    <a href="/veranstaltung/sihlrave"><h3>Sihlrave</h3></a></article>
</div>
<div class="view-grid" id="2026-11-08">
  <article><p>Event / Konzert</p> 18:00–22:00 <a href="/veranstaltung/conway"><h3>CONWAY THE MACHINE (US) live</h3></a></article>
</div>"""

NORDPORTAL = [
    {"id": 1, "slug": "lunik-29-11-2026", "acf": {"event_art": "Liveshow", "datum": "29.11.2026",
     "start_zeit": "2026-11-29 20:00", "event_titel": "<h1>LUNIK «Cycle Breaker» Tour 2026</h1>\n<h2></h2>",
     "ist_ausverkauft": True}},
    {"id": 2, "slug": "tanznacht", "acf": {"event_art": "Party", "datum": "20.11.2026",
     "start_zeit": "2026-11-20 21:00", "event_titel": "<h1>Tanznacht40</h1>"}},
    {"id": 3, "slug": "bluus", "acf": {"event_art": "Liveshow", "datum": "17.12.2026",
     "start_zeit": "2026-12-17 19:00", "event_titel": "<h2>Birthday-Party</h2><h2>«35 Years»</h2>"}},
]

XTRA_PAGE = """<html><head><meta name="csrf-token" content="tok123"></head><body><ul>
<li><a title="Ezhel (TUR)" href="/de/programm/2458/ezhel-tur.html"></a><div class="text"><h2>Ezhel (TUR)</h2><h3>Do 15.10.26</h3></div></li>
</ul><a class="more" href="javascript:void(0)">Alle anzeigen</a></body></html>"""
XTRA_MORE = {"events": '<ul><li><a href="/de/programm/2478/the-hu-mng.html"></a>'
                       '<div class="text"><h2>The Hu (MNG)</h2><h3>Fr 30.10.26</h3></div></li></ul>'}


class FakeFetcher:
    def __init__(self, get=None, post=None):
        self.gets, self.posts = get or {}, post
        self.calls = []

    def get(self, url):
        self.calls.append(("GET", url))
        return self.gets[url] if url in self.gets else next(v for k, v in self.gets.items() if url.startswith(k))

    def post(self, url, data, headers=None):
        self.calls.append(("POST", url, data))
        if isinstance(self.posts, Exception):
            raise self.posts
        return self.posts


def src(type_, url, fetcher=None, **opts):
    return create_source(VenueConfig(id="v", name="V", type=type_, url=url, options=opts), fetcher or FakeFetcher())


class VenueTests(unittest.TestCase):
    def test_dynamo_kinds_and_utc_times(self):
        evs = src("dynamo", "https://www.dynamo.ch/events-kurse").parse(DYNAMO)
        self.assertEqual([(e.title, e.date, e.time) for e in evs],
                         [("XOXO & CHOKESLAM", date(2026, 10, 16), "19:00"),            # Sommerzeit: +2 h
                          ("CONWAY THE MACHINE (US) live", date(2026, 11, 8), "19:00")])  # Winterzeit: +1 h
        self.assertEqual(evs[0].url, "https://www.dynamo.ch/veranstaltung/xoxo")
        self.assertEqual(len(src("dynamo", "", kinds=["Konzert", "Party"]).parse(DYNAMO)), 3)

    def test_nordportal(self):
        evs = src("nordportal", "").parse(json.dumps(NORDPORTAL))
        self.assertEqual([(e.title, e.time, e.sold_out) for e in evs],
                         [("LUNIK «Cycle Breaker» Tour 2026", "20:00", True), ("Birthday-Party", "19:00", False)])
        self.assertEqual(evs[0].url, "https://nordportal.ch/programm/lunik-29-11-2026")

    def test_nordportal_fetch_pages(self):
        page1 = [dict(NORDPORTAL[0], id=i) for i in range(100)]
        f = FakeFetcher({"https://npwp.kailua.ch/wp-json/wp/v2/event?acf_format=standard&per_page=100&page=1": json.dumps(page1),
                         "https://npwp.kailua.ch/wp-json/wp/v2/event?acf_format=standard&per_page=100&page=2": json.dumps(NORDPORTAL)})
        self.assertEqual(len(src("nordportal", "", f).fetch()), 102)

    def test_xtra_load_more_with_csrf(self):
        url = "https://www.x-tra.ch/de/programm/"
        f = FakeFetcher({url: XTRA_PAGE}, post=json.dumps(XTRA_MORE))
        evs = src("xtra", url, f).fetch()
        self.assertEqual([(e.title, e.date) for e in evs], [("Ezhel (TUR)", date(2026, 10, 15)), ("The Hu (MNG)", date(2026, 10, 30))])
        self.assertEqual(f.calls[1], ("POST", url, {"action": "column_events_load_more", "csrf_token": "tok123"}))

    def test_xtra_falls_back_to_first_page(self):
        url = "https://www.x-tra.ch/de/programm/"
        evs = src("xtra", url, FakeFetcher({url: XTRA_PAGE}, post=RuntimeError("403"))).fetch()
        self.assertEqual([e.title for e in evs], ["Ezhel (TUR)"])


if __name__ == "__main__":
    unittest.main()
