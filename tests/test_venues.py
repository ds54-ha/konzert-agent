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

VOLKSHAUS = """<div class="month-title"><span>OKTOBER 2026</span></div>
<div class="event-item" data-event-id="291"><div><span>FR</span><span>16.10.</span></div><div><span>RICARDO MONTANER</span>
<span>KONZERT 21:00 Uhr</span><div><span>THEATERSAAL</span><a href="https://shop.tilater.com/x "><span>Ticket</span></a>
<a href="https://rollinglive.ch/"><span>Veranstalter</span></a><span>AUSVERKAUFT</span></div></div></div>
<div class="event-item" data-event-id="349"><div><span>DO</span><span>15.10.</span></div><div><span>FRANCESCO DE CARLO</span>
<span>COMEDY 19:40 Uhr</span><div><span>WEISSER SAAL</span></div></div></div>
<div class="month-title"><span>JANUAR 2027</span></div>
<div class="event-item" data-event-id="400"><div><span>SA</span><span>9.1.</span></div><div><span>BASCHI</span>
<span>KONZERT 20:00 Uhr</span><div><span>THEATERSAAL</span></div></div></div>"""

KOMPLEX = [
    {"id": "a1", "date": "2099-10-16T20:00", "artist": "SIX60", "support_acts": ["luca!"], "genre": "Rock", "status": "Ausverkauft"},
    {"id": "a2", "date": "2099-10-17T20:00", "artist": "DÚ MAROC", "genre": "Hip-Hop, Rap", "status": "Abgesagt"},
    {"id": "a3", "date": "2099-10-31T20:00", "artist": "BETONTOD", "genre": "Punk", "status": "Verlegt"},
    {"id": "a4", "date": "2099-11-01T20:00", "artist": "Entwurf", "is_draft": True},
    {"id": "a5", "date": "2020-01-01T20:00", "artist": "Längst vorbei"},
]

THEHALL = """<select><option value="">Alle</option><option value=".rock">Rock</option>
<option value=".jumi-chalet">Jumi Chalet</option></select>
<div class="c-tile c-tile--events all rock jumi-chalet"><a href="/de/eventkalender/2026/amon-amarth/">
<span class="c-tile__text">11. November 2026</span><h5 class="c-tile__title">Amon Amarth</h5></a></div>
<div class="c-tile c-tile--events all"><a href="/de/eventkalender/2026/mustafa-sandal/">
<span class="c-tile__text">28. November 2026</span><h5 class="c-tile__title">Mustafa Sandal</h5></a>
<p>Die Show wurde in eine andere Location verlegt.</p></div>"""

MOODS = {"props": {"pageProps": {"fallback": {"allEvents": [
    {"isVisible": True, "concertId": "114260", "eventCategory": "Moods_Konzert", "eventDate": "2026-10-15",
     "name": "BaBa ZuLa", "slug": "baba-zula-2026-10-15", "timeStart": "20:30", "ticketPrice": "42",
     "genres": [{"label": "Global Sounds"}], "isSoldOut": True, "isCancelled": False},
    {"isVisible": True, "concertId": "118469", "eventCategory": "Moods_Afterparty", "eventDate": "2026-10-15",
     "name": "Yunus Findus", "slug": "yunus-findus-2026-10-15", "timeStart": "22:00"},
]}}}}

PLAZA = """<ul><li class="nu-event" data-nu-edate="2099-10-21 19:00:00" data-nu-eid="5001" data-nu-etitle="Gabirano  (CH) / AUSVERKAUFT"
 data-nu-etype="2"><a class="nu-e-link-ticket" href="https://www.seetickets.com/x ">Tickets</a></li>
<li class="nu-event" data-nu-edate="2020-03-14 19:00:00" data-nu-eid="4000" data-nu-etitle="Alt" data-nu-etype="2"></li></ul>"""

KAUFLEUTEN = """<article class="event"><a class="event-link" href="https://kaufleuten.ch/event/fink-konzert/">
<time datetime="2026-10-25T20:00:00+01:00">Sonntag, 25.10.2026</time><header><h3>Fink • Konzert</h3></header></a></article>
<article class="event"><a class="event-link" href="https://kaufleuten.ch/event/caroline-wahl-literatur/">
<time datetime="2026-10-19T20:00:00+02:00">Montag</time><header><h3>Caroline Wahl • Literatur</h3></header></a></article>"""

SALZHAUS = """<div class="sh-event-list-item events" data-status="special_2"><a class="sh-event-link" data-id="11107"
 href="https://www.salzhaus.ch/de/programm/11107/Maggie-ReillySCT" title="Maggie Reilly (SCT) (Live)">
<span class="date">16. Okt 26</span><span class="title">Maggie Reilly <sup>SCT</sup></span><span class="category">Live</span></a></div>
<div class="sh-event-list-item events" data-status=""><a class="sh-event-link" data-id="11108" href="/de/programm/11108/x"
 title="90s are now (Party)"><span class="date">31. Okt 26</span><span class="category">Party</span></a></div>"""

ALBANI = """<a class="accLabel" data-acc-ref="albani_event_1400_0_content" href="#"><div class="albani-event-header">
<div class="albani-event-label"><span class="title">Makthaverskan (SE)<br/>Support: Rémy Sax (CH)</span>
<span class="subline">Post-Punk, Dream Pop</span></div><div class="albani-event-date"><span class="date">Mi 21.10</span>
<span class="subline">20:00 UHR<br/>28 CHF</span></div></div></a>
<div id="albani_event_1400_0_content"><a href="https://www.albani.ch/de/programm/1400/Makthaverskan.html">Bild</a></div>
<a class="accLabel" data-acc-ref="albani_event_1309_0_content" href="#"><div class="albani-event-header">
<div class="albani-event-label"><span class="title">Inzidance</span><span class="subline">Modern Hits</span></div>
<div class="albani-event-date"><span class="date">Fr 16.10</span><span class="subline">23:00 UHR</span></div></div></a>"""

BIERHUEBELI = """<a class="datumlink" href="https://bierhuebeli.ch/event/gavin-degraw/"><div class="eventdatum ed-desktop">Freitag<br/>16.10.2026</div>
<div class="eventdatum ed-mobile">Freitag, 16.10.2026</div><div class="eventtag24 soldout">Ausverkauft</div>
<div class="eventtitel">GAVIN DEGRAW</div><div class="byline">Support: Julian Brown</div></a>"""

PAPIERSAAL = """<div class="row single-act"><h3>Freitag, 23. Okt 2026</h3><h2><a href="/events/1257"><strong>Finojet (AU)</strong></a></h2>
<q>Acoustic Folk</q><p><strong>+ Support: Tom River</strong></p><i><strong>Doors</strong> : 19h00 / <strong>Show</strong> : 19h30</i></div>
<div class="row single-act"><h3>Samstag, 24. Okt 2026</h3><h2><a href="/events/1243">Sixpence None The Richer (US) - ABGESAGT</a></h2></div>"""

HALLE622 = """<div class="entity event"><a href="/622/de/events/event/detail/2025/art-salon.html"><div class="event-text">
<h3>Art Salon Zürich 2026</h3><p>Halle 622<br/>23.10.2026 – 25.10.2026</p></div></a></div>
<div class="entity event"><a href="/622/de/events/event/detail/2026/simple-plan-sold-out.html"><div class="event-text">
<h3>Simple Plan - SOLD OUT!</h3><p>Halle 622<br/>29.10.2026</p></div></a></div>"""

MUEHLE = """<a class="customLink" href="https://www.muehlehunziken.ch/programm/danko-jones-2026-10-24"><span>Sa</span>
<span>24.10.</span><h2>Danko Jones</h2><div class="-mt-1.5 text-sm uppercase">&amp; The Headlines</div></a>
<a class="customLink" href="https://www.muehlehunziken.ch/programm/shakra-2026-10-16"><span>Fr</span><span>16.10.</span>
<h2>Shakra</h2><div class="flag">Ausverkauft</div><div class="flag">Ausverkauft</div></a>
<a class="customLink" href="https://www.muehlehunziken.ch/programm/span-2027"><span>Fr</span><span>17.9.</span><h2>Span</h2></a>"""

SCHUETZI = """<div class="article-introtext"><h5>Samstag, 31. Oktober 2026<br/>Türöffnung: 19:00 Uhr<br/>20:00 Uhr</h5>
<h1>Frölein Da Capo | Halbzeit Show</h1><div class="readmore"><a href="/schuetzi-programm/schuetzi-live/42-froelein">Weiterlesen</a></div></div>"""


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

    def test_volkshaus_year_from_month_heading(self):
        evs = src("volkshaus", "https://www.volkshaus.ch/veranstaltungen").parse(VOLKSHAUS)
        self.assertEqual([(e.title, e.date, e.time, e.sold_out) for e in evs],
                         [("RICARDO MONTANER", date(2026, 10, 16), "21:00", True), ("BASCHI", date(2027, 1, 9), "20:00", False)])
        self.assertEqual((evs[0].native_id, evs[0].url, evs[0].tags), ("291", "https://shop.tilater.com/x", ["Konzert"]))
        self.assertEqual(len(src("volkshaus", "", kinds=[]).parse(VOLKSHAUS)), 3)

    def test_komplex457_api(self):
        evs = src("komplex457", "").parse(json.dumps(KOMPLEX))
        self.assertEqual([(e.title, e.sold_out, e.cancelled) for e in evs],
                         [("SIX60 & Support: luca!", True, False), ("DÚ MAROC", False, True), ("BETONTOD", False, True)])
        self.assertEqual((evs[0].time, evs[0].url), ("20:00", "https://komplex-457.ch/EventDetail?id=a1"))
        self.assertEqual(evs[1].tags, ["Hip-Hop", "Rap"])

    def test_komplex457_fetch_only_published(self):
        f = FakeFetcher({"https://base44.app/": json.dumps(KOMPLEX)})
        src("komplex457", "", f).fetch()
        self.assertIn("is_draft%22%3A+false", f.calls[0][1])

    def test_thehall_genres_and_status(self):
        evs = src("thehall", "https://www.thehall.ch/de/eventkalender/").parse(THEHALL)
        self.assertEqual([(e.title, e.date, e.tags, e.cancelled) for e in evs],
                         [("Amon Amarth", date(2026, 11, 11), ["Rock"], False), ("Mustafa Sandal", date(2026, 11, 28), [], True)])
        self.assertEqual(evs[0].url, "https://www.thehall.ch/de/eventkalender/2026/amon-amarth/")

    def test_moods_next_data(self):
        html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(MOODS)}</script>'
        evs = src("moods", "https://www.moods.ch/").parse(html)
        self.assertEqual([(e.title, e.time, e.sold_out, e.tags, e.extra) for e in evs],
                         [("BaBa ZuLa", "20:30", True, ["Global Sounds"], {"price": "CHF 42"})])
        self.assertEqual(evs[0].url, "https://www.moods.ch/baba-zula-2026-10-15")
        self.assertEqual(len(src("moods", "", kinds=["Konzert", "Afterparty"]).parse(html)), 2)

    def test_plaza_status_in_title_and_old_entries(self):
        evs = src("plaza", "https://www.plaza-zurich.ch/program/liveshows/").parse(PLAZA)
        self.assertEqual([(e.title, e.time, e.sold_out, e.url) for e in evs],
                         [("Gabirano (CH)", "19:00", True, "https://www.seetickets.com/x")])

    def test_kaufleuten_category_from_title(self):
        evs = src("kaufleuten", "https://kaufleuten.ch/events/kultur/").parse(KAUFLEUTEN)
        self.assertEqual([(e.title, e.date, e.time, e.tags) for e in evs], [("Fink", date(2026, 10, 25), "20:00", ["Konzert"])])
        self.assertEqual(len(src("kaufleuten", "", kinds=[]).parse(KAUFLEUTEN)), 2)

    def test_salzhaus_category_and_short_year(self):
        evs = src("salzhaus", "https://www.salzhaus.ch/").parse(SALZHAUS)
        self.assertEqual([(e.title, e.date, e.native_id, e.tags) for e in evs],
                         [("Maggie Reilly (SCT)", date(2026, 10, 16), "11107", ["Live"])])
        self.assertEqual(src("salzhaus", "https://www.salzhaus.ch/", kinds=["Party"]).parse(SALZHAUS)[0].url,
                         "https://www.salzhaus.ch/de/programm/11108/x")

    def test_albani_support_lines_and_club_nights(self):
        evs = src("albani", "https://www.albani.ch/").parse(ALBANI)
        self.assertEqual([(e.title, e.time, e.tags) for e in evs],
                         [("Makthaverskan (SE) & Support: Rémy Sax (CH)", "20:00", ["Post-Punk, Dream Pop"]),
                          ("Inzidance", "23:00", ["Modern Hits", "Club"])])
        self.assertEqual((evs[0].native_id, evs[0].date.month, evs[0].date.day), ("1400", 10, 21))
        self.assertEqual(evs[0].url, "https://www.albani.ch/de/programm/1400/Makthaverskan.html")

    def test_bierhuebeli(self):
        evs = src("bierhuebeli", "https://bierhuebeli.ch/konzerte/").parse(BIERHUEBELI)
        self.assertEqual([(e.title, e.date, e.sold_out, e.native_id) for e in evs],
                         [("GAVIN DEGRAW & Support: Julian Brown", date(2026, 10, 16), True, "gavin-degraw")])

    def test_css_status_support_and_h_time(self):
        evs = src("css", "https://www.papiersaal.ch/", item=".single-act", title="h2", date="h3", time="i",
                  link="h2 a", tags="q", support="p").parse(PAPIERSAAL)
        self.assertEqual([(e.title, e.date, e.time, e.cancelled) for e in evs],
                         [("Finojet (AU) & Support: Tom River", date(2026, 10, 23), "19:00", False),
                          ("Sixpence None The Richer (US)", date(2026, 10, 24), None, True)])

    def test_muehlehunziken_year_from_slug(self):
        evs = src("muehlehunziken", "https://www.muehlehunziken.ch/").parse(MUEHLE)
        self.assertEqual([(e.title, e.date, e.sold_out) for e in evs],
                         [("Danko Jones & Support: The Headlines", date(2026, 10, 24), False),
                          ("Shakra", date(2026, 10, 16), True), ("Span", date(2027, 9, 17), False)])
        self.assertEqual(evs[0].native_id, "danko-jones-2026-10-24")

    def test_css_schuetzi_word_date_with_colon(self):
        evs = src("css", "https://schuetzi-olten.ch/schuetzi-programm/schuetzi-live", item=".article-introtext",
                  title="h1", date="h5", time="h5", link=".readmore a").parse(SCHUETZI)
        self.assertEqual([(e.title, e.date, e.time, e.url) for e in evs],
                         [("Frölein Da Capo | Halbzeit Show", date(2026, 10, 31), "19:00",
                           "https://schuetzi-olten.ch/schuetzi-programm/schuetzi-live/42-froelein")])

    def test_css_date_range_and_sold_out(self):
        evs = src("css", "https://www.halle622.ch/622/de/events.html", item=".entity.event", title="h3",
                  date=".event-text p", link="a").parse(HALLE622)
        self.assertEqual([(e.title, e.date, e.end_date, e.sold_out) for e in evs],
                         [("Art Salon Zürich 2026", date(2026, 10, 23), date(2026, 10, 25), False),
                          ("Simple Plan", date(2026, 10, 29), None, True)])


if __name__ == "__main__":
    unittest.main()
