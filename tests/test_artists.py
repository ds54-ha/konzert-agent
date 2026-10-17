import json
import tempfile
import unittest
from datetime import date, timedelta
from urllib.parse import parse_qs, urlsplit

from konzert_agent.agent import Agent
from konzert_agent.artists import ArtistEnricher, ArtistLookup, extract_artists, skip_reason
from konzert_agent.artists.genres import classify, popularity, popularity_label
from konzert_agent.config import ArtistSettings, Config, Settings, VenueConfig
from konzert_agent.models import Event
from konzert_agent.store import Store
from konzert_agent.artists.extract import ArtistName
from konzert_agent.artists.lookup import norm


def names(title):
    return [(a.name, a.countries) for a in extract_artists(title)]


class ExtractTests(unittest.TestCase):
    def test_support_and_countries(self):
        self.assertEqual(names("Bibi Vaplan (CH) & Support: Omisdus (CH)"), [("Bibi Vaplan", ["CH"]), ("Omisdus", ["CH"])])
        self.assertEqual(names("Endless Wellness (AT) & Support"), [("Endless Wellness", ["AT"])])
        self.assertEqual(names("Sofie Royer (AT/ IR) & Support: Jamila (CH)"),
                         [("Sofie Royer", ["AT", "IR"]), ("Jamila", ["CH"])])
        self.assertEqual(names("The Haunted Youth (BEL) & Support"), [("The Haunted Youth", ["BE"])])

    def test_separators(self):
        self.assertEqual(names("Shearwater (US), Loma (US), Any Kind (US)"),
                         [("Shearwater", ["US"]), ("Loma", ["US"]), ("Any Kind", ["US"])])
        self.assertEqual(names("Black Sea Dahu (CH) + Soft Loft (CH)"), [("Black Sea Dahu", ["CH"]), ("Soft Loft", ["CH"])])
        self.assertEqual(names("Eto • Alwa Alibi"), [("Eto", []), ("Alwa Alibi", [])])
        self.assertEqual(names("Harvey Rushmore & the Octopus (CH) & Mord Fuzztang (CH)"),
                         [("Harvey Rushmore & the Octopus", ["CH"]), ("Mord Fuzztang", ["CH"])])
        self.assertEqual(names("Kiioto (UK) feat. Lou Rhodes of LAMB & Support"), [("Kiioto", ["GB"])])

    def test_subtitles_and_labels(self):
        self.assertEqual(names("Baschi (CH) – «TOUR 26/27»"), [("Baschi", ["CH"])])
        self.assertEqual(names("ETO - Sibcity Tour - ZUSATZSHOW"), [("ETO", [])])
        self.assertEqual(names("Charles Nguela | Zusatzshow"), [("Charles Nguela", [])])
        self.assertEqual(names("Pedestrians Goodbye-Tour (Freitag)"), [("Pedestrians", [])])
        self.assertEqual(names("Badener Punk-Night mit Sin Logica (Luzern) • PCA (Züri)"),
                         [("Sin Logica", ["CH"]), ("PCA", ["CH"])])
        self.assertEqual(names("Ska-Night – Kalles Kaviar • Canastron"), [("Kalles Kaviar", []), ("Canastron", [])])
        self.assertEqual(names("MONTAGS 1149 DUO NIK BÄRTSCH - ILVA EIGUS"), [("NIK BÄRTSCH", [])])
        self.assertEqual(names("HGich.T Live + Acid Aftershow - 30 JAHRE TOUR"), [("HGich.T", [])])
        self.assertEqual(names("Infinity Song im Plaza"), [("Infinity Song", [])])
        self.assertEqual(names("Peach Weber 2027"), [("Peach Weber", [])])
        self.assertEqual(names("DANJU - Zehn Jahre „Stoned ohne Grund\""), [("DANJU", [])])

    def test_ampersand_parts(self):
        a = extract_artists("Lo & Leduc – AUSVERKAUFT")[0]
        self.assertEqual((a.name, a.parts), ("Lo & Leduc", ["Lo", "Leduc"]))

    def test_skip(self):
        self.assertEqual(skip_reason("Noche Cubana", ["Party"]), "Party")
        self.assertEqual(skip_reason("Plug Out Festival III", ["Konzert", "Festival", "Metal"]), "Festival")
        self.assertEqual(skip_reason("Comedy im KIFF: Lisa Christ", []), "Comedy")
        self.assertIsNone(skip_reason("Charles Nguela", ["Konzert", "Performance"]))
        self.assertIsNone(skip_reason("Monolord (SE)", ["Konzert", "Metal"]))


class FakeApi:
    def __init__(self, mb, dz):
        self.mb, self.dz, self.calls = mb, dz, []

    def get(self, url):
        self.calls.append(url)
        q = parse_qs(urlsplit(url).query)
        if "musicbrainz" in url:
            name = q["query"][0].split('"')[1]
            return json.dumps({"artists": self.mb.get(name, [])})
        return json.dumps({"data": self.dz.get(q["q"][0], [])})


class LookupTests(unittest.TestCase):
    def test_norm(self):
        self.assertEqual(norm("The Beauty of Gemina"), norm("beauty of gemina"))
        self.assertEqual(norm("Árstíðir"), norm("ARSTIÐIR"))

    def test_country_picks_homonym(self):
        mb = {"Elin": [
            {"id": "se", "name": "Elin", "country": "SE", "tags": [{"name": "pop", "count": 9}]},
            {"id": "ch", "name": "Elin", "country": "CH", "tags": [{"name": "indie", "count": 1}]}]}
        look = ArtistLookup("t", fetcher=FakeApi(mb, {}))
        info = look.lookup_name("Elin", ["CH"])
        self.assertEqual((info.mbid, info.tags), ("ch", ["indie"]))
        self.assertIn("per Land gewählt", info.notes[0])
        self.assertEqual(info.confidence, "tief")       # kurzer Name, nur MusicBrainz

    def test_exact_match_only_and_most_fans(self):
        dz = {"Placebo": [{"id": 1, "name": "!PLACEBO!", "nb_fan": 11}, {"id": 2, "name": "Placebo", "nb_fan": 704},
                          {"id": 3, "name": "Placebo Effect", "nb_fan": 99999}]}
        mb = {"Placebo": [{"id": "p", "name": "Placebo", "country": "GB",
                           "tags": [{"name": "alternative rock", "count": 5}]}]}
        info = ArtistLookup("t", fetcher=FakeApi(mb, dz)).lookup_name("Placebo")
        self.assertEqual((info.fans, info.confidence), (704, "hoch"))

    def test_ampersand_fallback_and_cache(self):
        api = FakeApi({}, {"Main Concept": [{"id": 1, "name": "Main Concept", "nb_fan": 5000}],
                           "Retrogott": [{"id": 2, "name": "Retrogott", "nb_fan": 3000}]})
        look = ArtistLookup("t", fetcher=api)
        a = ArtistName("Main Concept & Retrogott", parts=["Main Concept", "Retrogott"])
        self.assertEqual([i.fans for i in look.lookup(a)], [5000, 3000])
        n = len(api.calls)
        look.lookup(a)
        self.assertEqual(len(api.calls), n)              # zweites Mal aus dem Cache

    def test_retry_on_503(self):
        import requests
        from unittest import mock
        api = FakeApi({"Monolord": [{"id": "m", "name": "Monolord", "tags": [{"name": "doom metal", "count": 3}]}]}, {})
        real_get, failed = api.get, []

        def flaky(url):
            if "musicbrainz" in url and not failed:
                failed.append(url)
                raise requests.HTTPError(response=mock.Mock(status_code=503))
            return real_get(url)
        api.get = flaky
        with mock.patch("konzert_agent.artists.lookup.time.sleep"):
            info = ArtistLookup("t", fetcher=api).lookup_name("Monolord")
        self.assertEqual(info.tags, ["doom metal"])

    def test_nothing_found(self):
        info = ArtistLookup("t", fetcher=FakeApi({}, {})).lookup_name("Omisdus", ["CH"])
        self.assertEqual((info.found, info.confidence), (False, "keine"))


    def test_override_none_and_ids(self):
        api = FakeApi({}, {})
        real_get = api.get

        def get(url):
            if url.endswith("/artist/77"):
                return json.dumps({"id": 77, "name": "Sports", "nb_fan": 1234})
            return real_get(url)
        api.get = get
        look = ArtistLookup("t", fetcher=api, overrides={"Sports": {"deezer": 77, "genres": ["indie rock"]},
                                                         "Leila": None})
        s = look.lookup_name("SPORTS")
        self.assertEqual((s.fans, s.tags, s.confidence), (1234, ["indie rock"], "hoch"))
        l = look.lookup_name("Leila")
        self.assertEqual((l.found, l.confidence, l.notes), (False, "keine", ["manuell"]))
        self.assertEqual(api.calls, [])                   # Korrekturen lösen keine Namenssuche aus

    def test_persistent_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(f"{tmp}/t.db")
            api = FakeApi({}, {"Monolord": [{"id": 1, "name": "Monolord", "nb_fan": 9585}]})
            ArtistLookup("t", fetcher=api, cache=store).lookup_name("Monolord")
            n = len(api.calls)
            info = ArtistLookup("t", fetcher=api, cache=store).lookup_name("Monolord")   # neue Instanz
            self.assertEqual((info.fans, len(api.calls)), (9585, n))


class GenreTests(unittest.TestCase):
    def test_classify(self):
        groups, styles = classify(["doom metal", "stoner rock", "gothenburg", "metal", "psychedelic rock"])
        self.assertEqual(groups, ["Metal", "Rock"])
        self.assertEqual(styles, ["doom metal", "stoner rock", "metal", "psychedelic rock"])
        self.assertEqual(classify(["pop rap", "german"])[0], ["Hip-Hop & Rap", "Pop"])
        self.assertEqual(classify(["Konzert", "Electro", "Pop"])[0], ["Electronic", "Pop"])   # PETZI-Tags

    def test_popularity(self):
        self.assertEqual([popularity(f) for f in (None, 0, 100, 1000, 1_000_000)], [None, 0, 29, 43, 86])
        self.assertEqual([popularity_label(f) for f in (126, 9585, 69_000, 2_000_000)],
                         ["lokal", "Szene", "bekannt", "Star"])


MB = {"Monolord": [{"id": "m", "name": "Monolord", "country": "SE",
                    "tags": [{"name": "doom metal", "count": 5}, {"name": "stoner rock", "count": 3}]}]}
DZ = {"Monolord": [{"id": 1, "name": "Monolord", "nb_fan": 9585}],
      "Omisdus": [{"id": 2, "name": "OMISDUS", "nb_fan": 6}]}


class EnrichTests(unittest.TestCase):
    def enricher(self, **titles):
        return ArtistEnricher(ArtistLookup("t", fetcher=FakeApi(MB, DZ)), titles)

    def ev(self, title, tags=()):
        return Event(venue_id="v", native_id=title, title=title, date=date.today(), tags=list(tags))

    def test_event_fields(self):
        ev = self.enricher().apply(self.ev("Monolord (SE) & Support: Omisdus (CH)", ["Konzert"]))
        x = ev.extra
        self.assertEqual([a["name"] for a in x["artists"]], ["Monolord", "OMISDUS"])
        self.assertEqual((x["genres"], x["genres_source"]), (["Metal", "Rock"], "bands"))
        self.assertEqual((x["popularity"], x["popularity_label"]), (popularity(9585), "Szene"))

    def test_popularity_from_headliner(self):
        x = self.enricher().apply(self.ev("Omisdus (CH) + Monolord (SE)")).extra
        self.assertEqual(x["popularity"], popularity(6))

    def test_location_tags_fallback_and_skip(self):
        x = self.enricher().apply(self.ev("Unbekannt", ["Konzert", "Indie", "Pop"])).extra
        self.assertEqual((x["genres"], x["genres_source"], x["popularity"]),
                         (["Indie & Alternative", "Pop"], "location", None))
        x = self.enricher().apply(self.ev("Noche Cubana", ["Party"])).extra
        self.assertEqual((x["artists"], x["artists_skip"]), ([], "Party"))

    def test_failed_source_marks_retry(self):
        api = FakeApi(MB, DZ)
        real_get = api.get

        def down(url):
            if "musicbrainz" in url:
                raise ConnectionError("down")
            return real_get(url)
        api.get = down
        x = ArtistEnricher(ArtistLookup("t", fetcher=api)).apply(self.ev("Monolord (SE)")).extra
        self.assertTrue(x["artists_retry"])
        api.get = real_get                                   # wieder erreichbar -> Flag verschwindet
        x = ArtistEnricher(ArtistLookup("t", fetcher=api)).apply(self.ev("Monolord (SE)")).extra
        self.assertNotIn("artists_retry", x)
        self.assertEqual(x["genres"], ["Metal", "Rock"])

    def test_title_override(self):
        enr = self.enricher(**{"Goth Night": [], "Ska-Night": ["Monolord"]})
        self.assertEqual(enr.apply(self.ev("Goth Night – Volume 2 • heavy beats")).extra["artists_skip"], "manuell")
        self.assertEqual(enr.apply(self.ev("Ska-Night – X • Y")).extra["artists"][0]["name"], "Monolord")

    def test_event_override_hits_only_that_show(self):
        enr = ArtistEnricher(ArtistLookup("t", fetcher=FakeApi(MB, DZ)), {},
                             {f"v {date.today().isoformat()}": ["Monolord", "Omisdus"]})
        names = lambda ev: [n.name for n in enr.names_for(ev)[0]]
        self.assertEqual(names(self.ev("MONOLORD")), ["Monolord", "Omisdus"])            # Support von Hand
        later = Event(venue_id="v", native_id="2", title="MONOLORD", date=date.today() + timedelta(days=90))
        self.assertEqual(names(later), ["MONOLORD"])                                    # spätere Show: nur der Titel
        other = Event(venue_id="w", native_id="3", title="MONOLORD", date=date.today())
        self.assertEqual(names(other), ["MONOLORD"])                                    # andere Location, gleicher Tag


class AgentArtistTests(unittest.TestCase):
    def test_run_backfill_and_genre_filter(self):
        from tests.test_agent import FakeFetcher
        with tempfile.TemporaryDirectory() as tmp:
            d = date.today() + timedelta(days=5)
            url = "https://www.petzi.ch/de/organiser/1/"
            page = (f'<a href="/de/events/1-x-a/" title="Mehr Infos / Monolord (SE) / X">{d:%d.%m.%Y} M</a>'
                    f'<a href="/de/events/2-x-b/" title="Mehr Infos / Omisdus / X">{d:%d.%m.%Y} O</a>')
            fetcher = FakeFetcher({url: page, "https://www.petzi.ch/de/events/1-x-a/": "",
                                   "https://www.petzi.ch/de/events/2-x-b/": ""})
            cfg = Config(settings=Settings(database=f"{tmp}/t.db", notify_on_first_run=True),
                         venues=[VenueConfig(id="x", name="X", type="petzi", options={"organiser": 1},
                                             include=["Metal"])],
                         notifiers=[], artists=ArtistSettings(enabled=False))
            agent = Agent(cfg, fetcher=fetcher)
            agent.run(notify=False)                                   # ohne Band-Infos importiert
            self.assertEqual(agent.filtered_events(agent.store.events()), [])
            agent.artists = ArtistEnricher(ArtistLookup("t", fetcher=FakeApi(MB, DZ), cache=agent.store))
            self.assertEqual(agent.backfill_artists(), 2)
            self.assertEqual(agent.backfill_artists(), 0)            # schon erledigt
            row = agent.store.events()[0]
            agent.store.update_extra(row["uid"], {**row["extra"], "artists_retry": True})
            self.assertEqual(agent.backfill_artists(), 1)            # fehlgeschlagene werden wiederholt
            agent.run(notify=False)                                   # Re-Scrape darf Genres nicht löschen
            shown = agent.filtered_events(agent.store.events())
            self.assertEqual([e["title"] for e in shown], ["Monolord (SE)"])  # include: Metal greift
            self.assertEqual(shown[0]["extra"]["genres"], ["Metal", "Rock"])


if __name__ == "__main__":
    unittest.main()
