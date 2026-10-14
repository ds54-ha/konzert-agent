import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from konzert_agent.agent import Agent, passes_filters
from konzert_agent.config import ArtistSettings, Config, Settings, VenueConfig
from konzert_agent.models import Event
from konzert_agent.notifiers import TelegramNotifier
from konzert_agent.sources import create_source
from konzert_agent.sources.base import parse_dotted_date
from konzert_agent.sources.generic import parse_any_date
from konzert_agent.sources.petzi import PetziSource
from konzert_agent.store import Store

FIX = Path(__file__).parent / "fixtures"


class FakeFetcher:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return self.pages[url]


def src(type_, url="", **opts):
    return create_source(VenueConfig(id="v", name="V", type=type_, url=url, options=opts), FakeFetcher({}))


class DateTests(unittest.TestCase):
    def test_dotted(self):
        self.assertEqual(parse_dotted_date("14.10.2026"), (date(2026, 10, 14), None))
        self.assertEqual(parse_dotted_date("15.10.26 Donnerstag"), (date(2026, 10, 15), None))
        self.assertEqual(parse_dotted_date("25-28.11.2026"), (date(2026, 11, 25), date(2026, 11, 28)))
        self.assertEqual(parse_dotted_date("30.12-02.01.2027"), (date(2026, 12, 30), date(2027, 1, 2)))

    def test_any(self):
        self.assertEqual(parse_any_date("15 Oct 2026")[0], date(2026, 10, 15))
        self.assertEqual(parse_any_date("Sa, 7. November 2026")[0], date(2026, 11, 7))
        self.assertEqual(parse_any_date("2026-12-03T20:00:00+01:00")[0], date(2026, 12, 3))


class ParserTests(unittest.TestCase):
    def test_petzi_organiser(self):
        evs = src("petzi", organiser=5).parse((FIX / "petzi_organiser.html").read_text())
        self.assertEqual(len(evs), 5)
        by = {e.native_id: e for e in evs}
        self.assertEqual(by["63212"].title, "Monolord (SE)")
        self.assertEqual(by["63212"].date, date(2026, 10, 14))
        self.assertEqual(by["63212"].url, "https://www.petzi.ch/de/events/63212-kiff-monolord-se/")
        self.assertEqual(by["63752"].end_date, date(2026, 11, 28))
        self.assertEqual(by["63752"].title, "diagonal - Club Festival Aarau")

    def test_petzi_url(self):
        self.assertEqual(src("petzi", organiser=225).url, "https://www.petzi.ch/de/organiser/225/")

    def test_petzi_detail(self):
        ev = Event(venue_id="kiff", native_id="63212", title="Monolord", date=date(2026, 10, 14))
        PetziSource.parse_detail((FIX / "petzi_event.html").read_text(), ev)
        self.assertEqual(ev.tags, ["Konzert", "Metal", "Rock"])
        self.assertEqual(ev.time, "20:00")
        self.assertEqual(ev.extra["price"], "Ab CHF 35,00")

    def test_exil(self):
        evs = src("exil", "https://exil.club").parse((FIX / "exil.html").read_text())
        titles = [e.title for e in evs]
        self.assertNotIn("Choke mit Fadi Mohem & KUSS", titles)   # DJ-Abend gefiltert
        self.assertEqual(len(evs), 4)
        thizzy = evs[0]
        self.assertTrue(thizzy.sold_out)
        self.assertEqual(thizzy.date, date(2026, 10, 15))
        self.assertTrue(next(e for e in evs if e.native_id == "54-ultra").cancelled)
        self.assertEqual(evs[-1].date, date(2027, 1, 26))

    def test_exil_with_dj(self):
        evs = src("exil", "https://exil.club", kinds=["live", "dj"]).parse((FIX / "exil.html").read_text())
        self.assertEqual(len(evs), 5)

    def test_hallenstadion(self):
        evs = src("hallenstadion", "https://hallenstadion.ch/events/").parse((FIX / "hallenstadion.html").read_text())
        self.assertEqual(len(evs), 5)                               # zwei Lobrecht-Termine getrennt
        self.assertEqual(evs[0].title, "Laura Pausini")
        self.assertEqual(evs[0].time, "19:30")
        self.assertEqual(evs[0].date, date(2026, 10, 15))

    def test_hallenstadion_ajax_pages(self):
        first = (FIX / "hallenstadion.html").read_text()
        page2 = ('<div data-paged="1" data-max_pages="2"><a href="https://hallenstadion.ch/events/placebo'
                 '?availability_id=43066"><h3>Placebo</h3> <span>04 Dec 2026</span> <span>20:00 Uhr</span></a></div>')
        ajax = ("https://hallenstadion.ch/wp-admin/admin-ajax.php?action=events_filter&paged=2&filter_by_genre="
                "&filter_by_events_type=&filter_by_date=&from_date=&to_date=")
        fetcher = FakeFetcher({"https://hallenstadion.ch/events/": first, ajax: page2})
        s = create_source(VenueConfig(id="v", name="V", type="hallenstadion",
                                      url="https://hallenstadion.ch/events/"), fetcher)
        evs = s.fetch()
        self.assertEqual(len(evs), 6)
        self.assertEqual(fetcher.calls, ["https://hallenstadion.ch/events/", ajax])
        self.assertEqual(evs[-1].title, "Placebo")

    def test_jsonld(self):
        html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
          {"@type":"MusicEvent","name":"Band X","startDate":"2026-11-20T20:30:00+01:00","url":"/e/1",
           "offers":{"availability":"https://schema.org/SoldOut"}},
          {"@type":"Organization","name":"nope"}]}</script>"""
        evs = src("jsonld", "https://club.ch/programm").parse(html)
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0].title, evs[0].time, evs[0].url, evs[0].sold_out),
                         ("Band X", "20:30", "https://club.ch/e/1", True))

    def test_ical(self):
        ics = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:abc\r\nDTSTART;TZID=Europe/Zurich:20261205T203000\r\n"
               "SUMMARY:Lo & Leduc\\, live\r\nURL:https://x.ch/1\r\nCATEGORIES:Pop,Mundart\r\nEND:VEVENT\r\n"
               "BEGIN:VEVENT\r\nUID:def\r\nDTSTART;VALUE=DATE:20261231\r\nSUMMARY:Silvester\r\n"
               "  Party\r\nEND:VEVENT\r\nEND:VCALENDAR")
        evs = src("ical", "https://x.ch/f.ics").parse(ics)
        self.assertEqual(evs[0].title, "Lo & Leduc, live")
        self.assertEqual(evs[0].time, "20:30")
        self.assertEqual(evs[0].tags, ["Pop", "Mundart"])
        self.assertEqual(evs[1].title, "Silvester Party")

    def test_css(self):
        html = """<article class="event"><h3>Band Y</h3><span class="date">Fr 20.11.2026</span>
                  <span class="time">Beginn 21:00</span><a href="/y">mehr</a><i class="genre">Indie</i></article>
                  <article class="event"><h3>Ohne Datum</h3></article>"""
        evs = src("css", "https://club.ch/", item="article.event", title="h3", date=".date",
                  time=".time", tags=".genre").parse(html)
        self.assertEqual(len(evs), 1)
        self.assertEqual((evs[0].title, evs[0].time, evs[0].url, evs[0].tags),
                         ("Band Y", "21:00", "https://club.ch/y", ["Indie"]))


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = date.today() + timedelta(days=10)
        self.d = d
        self.page1 = (f'<a href="/de/events/1-x-a/" title="Mehr Infos / Band A / X">{d:%d.%m.%Y} Band A X</a>'
                      f'<a href="/de/events/2-x-b/" title="Mehr Infos / Comedy B / X">{d:%d.%m.%Y} Comedy B X</a>')
        self.url = "https://www.petzi.ch/de/organiser/1/"
        self.detail = '<a href="/de/search/?q=rock">Rock</a>'
        self.fetcher = FakeFetcher({self.url: self.page1,
                                    "https://www.petzi.ch/de/events/1-x-a/": self.detail,
                                    "https://www.petzi.ch/de/events/2-x-b/": self.detail,
                                    "https://www.petzi.ch/de/events/3-x-c/": self.detail})
        cfg = Config(settings=Settings(database=f"{self.tmp.name}/t.db"),
                     venues=[VenueConfig(id="x", name="Club X", city="Baden", type="petzi",
                                         options={"organiser": 1}, exclude=["Comedy"])],
                     notifiers=[], artists=ArtistSettings(enabled=False))
        self.agent = Agent(cfg, fetcher=self.fetcher)
        self.sent = []
        outer = self

        class Rec:
            def send(self, new, cancelled):
                outer.sent.append((new, cancelled))
        self.agent.notifiers = [Rec()]

    def tearDown(self):
        self.tmp.cleanup()

    def test_flow(self):
        r1 = self.agent.run()
        self.assertEqual(r1.found, {"x": 2})
        self.assertEqual(self.sent, [])                     # Erstimport bleibt still
        # zweiter Lauf ohne Änderungen: nichts Neues
        self.agent.run()
        self.assertEqual(self.sent, [])
        # neues Event + Absage
        d = self.d
        self.fetcher.pages[self.url] = (
            f'<a href="/de/events/1-x-a/" title="Mehr Infos / Band A (abgesagt) / X">{d:%d.%m.%Y} Band A X</a>'
            f'<a href="/de/events/3-x-c/" title="Mehr Infos / Band C / X">{d:%d.%m.%Y} Band C X</a>')
        self.agent.run()
        self.assertEqual(len(self.sent), 1)
        new, cancelled = self.sent[0]
        self.assertEqual([e.title for e in new], ["Band C"])
        self.assertEqual(new[0].tags, ["Rock"])             # Details geladen
        self.assertEqual([e.title for e in cancelled], ["Band A (abgesagt)"])
        # Detailseite wurde nur für neue Events geholt
        self.assertEqual(self.fetcher.calls.count("https://www.petzi.ch/de/events/1-x-a/"), 1)
        # Web-Filter blendet Comedy aus
        evs = self.agent.filtered_events(self.agent.store.events())
        self.assertEqual(sorted(e["title"] for e in evs), ["Band A (abgesagt)", "Band C"])

    def test_broken_venue_does_not_crash(self):
        self.fetcher.pages.pop(self.url)
        r = self.agent.run()
        self.assertIn("x", r.errors)
        self.assertTrue(self.agent.store.runs()["x"]["last_error"])


class TelegramTests(unittest.TestCase):
    def test_message(self):
        n = TelegramNotifier(token="t", chat_id="1", venue_names={"kiff": "KiFF"}, base_url="http://lab:8080")
        ev = Event(venue_id="kiff", native_id="1", title="Boris <live>", date=date(2026, 10, 27), time="20:00",
                   url="https://p.ch/1", tags=["Konzert", "Metal"])
        msgs = n.build_messages([ev], [])
        self.assertEqual(len(msgs), 1)
        self.assertIn("Di 27.10.26 20:00", msgs[0])
        self.assertIn("Boris &lt;live&gt;", msgs[0])
        self.assertIn("<b>KiFF</b>", msgs[0])
        many = [Event(venue_id="kiff", native_id=str(i), title="X" * 80, date=date(2026, 10, 27)) for i in range(200)]
        self.assertTrue(all(len(m) <= 4096 for m in n.build_messages(many, [])))


if __name__ == "__main__":
    unittest.main()
