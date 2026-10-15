import json
import unittest
from datetime import date

from konzert_agent.config import VenueConfig
from konzert_agent.sources import create_source

DYNAMO = {"data": [
    {"attributes": {"field_title": "Crashkurs Risografie", "path": {"alias": "/veranstaltung/risografie"},
                    "field_event_date": {"value": "2026-10-16T09:00:00+02:00"}},
     "relationships": {"field_categories": {"data": [{"id": "w"}]}}},
    {"attributes": {"field_title": "XOXO & CHOKESLAM", "path": {"alias": "/veranstaltung/xoxo"}, "field_event_ticket_price": 25,
                    "field_event_date": {"value": "2026-10-16T19:00:00+02:00", "end_value": "2026-10-16T23:30:00+02:00"}},
     "relationships": {"field_categories": {"data": [{"id": "k"}, {"id": "h"}]}}},
    {"attributes": {"field_title": "Sihlrave", "path": {"alias": "/veranstaltung/sihlrave"},
                    "field_event_date": {"value": "2026-10-16T22:00:00+02:00", "end_value": "2026-10-17T04:00:00+02:00"}},
     "relationships": {"field_categories": {"data": [{"id": "p"}]}}},
    {"attributes": {"field_title": "Heartline Festival", "path": {"alias": "/veranstaltung/heartline"},
                    "field_event_date": {"value": "2026-11-28T14:30:00Z", "end_value": "2026-11-29T23:00:00Z"}},
     "relationships": {"field_categories": {"data": [{"id": "k"}]}}},
], "included": [{"type": "taxonomy_term--event_category", "id": i, "attributes": {"name": n}}
                for i, n in [("w", "Workshops"), ("k", "Konzert"), ("h", "Hardcore/Punk"), ("p", "Party")]]}

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
    def test_dynamo_api(self):
        evs = src("dynamo", "").parse(json.dumps(DYNAMO))
        self.assertEqual([(e.title, e.date, e.time, e.end_date) for e in evs],
                         [("XOXO & CHOKESLAM", date(2026, 10, 16), "19:00", None),
                          ("Heartline Festival", date(2026, 11, 28), "15:30", date(2026, 11, 30))])   # UTC -> Zürich
        self.assertEqual((evs[0].url, evs[0].native_id), ("https://www.dynamo.ch/veranstaltung/xoxo", "xoxo"))
        self.assertEqual((evs[0].tags, evs[0].extra), (["Konzert", "Hardcore/Punk"], {"price": "CHF 25"}))
        self.assertEqual(len(src("dynamo", "", kinds=["Konzert", "Party"]).parse(json.dumps(DYNAMO))), 3)

    def test_dynamo_pages_and_only_needed_fields(self):
        page = lambda n, more: json.dumps({"data": [DYNAMO["data"][1]] if n == 0 else [DYNAMO["data"][3]],
                                           "included": DYNAMO["included"], "links": {"next": {"href": "…"}} if more else {}})
        f = FakeFetcher()
        f.get = lambda url: (f.calls.append(url), page(len(f.calls) - 1, len(f.calls) == 1))[1]
        evs = src("dynamo", "", fetcher=f).fetch()
        self.assertEqual(len(evs), 2)
        self.assertEqual(len(f.calls), 2)
        self.assertIn("fields%5Bnode--event%5D=field_title", f.calls[0])
        self.assertNotIn("organizer", f.calls[0])

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
