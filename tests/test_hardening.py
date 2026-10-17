import logging
import tempfile
import unittest
from datetime import date, timedelta

from starlette.requests import Request

from konzert_agent.__main__ import RedactingFormatter
from konzert_agent.auth import LoginLimiter
from konzert_agent.config import ArtistSettings, Config, Settings, VenueConfig
from konzert_agent.agent import Agent
from konzert_agent.models import Event
from konzert_agent.sources.base import infer_year, parse_dotted_date
from konzert_agent.sources.generic import parse_any_date
from konzert_agent.store import Store
from konzert_agent.web.app import create_app
from konzert_agent.web.security import client_ip, parse_networks
from tests.test_agent import FakeFetcher, src
from tests.test_auth import call


def request(peer: str, headers: dict) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "client": (peer, 1234),
                    "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})


class ClientIpTests(unittest.TestCase):
    def test_header_trusted_without_list(self):            # bisheriges Verhalten bleibt
        self.assertEqual(client_ip(request("10.0.0.9", {"CF-Connecting-IP": "1.2.3.4"}), "CF-Connecting-IP"), "1.2.3.4")

    def test_header_only_from_trusted_proxy(self):
        trusted = parse_networks(["192.168.0.10", "10.1.0.0/16"])
        hdr = {"CF-Connecting-IP": "1.2.3.4"}
        self.assertEqual(client_ip(request("192.168.0.10", hdr), "CF-Connecting-IP", trusted), "1.2.3.4")
        self.assertEqual(client_ip(request("10.1.5.5", hdr), "CF-Connecting-IP", trusted), "1.2.3.4")
        self.assertEqual(client_ip(request("::ffff:192.168.0.10", hdr), "CF-Connecting-IP", trusted), "1.2.3.4")
        self.assertEqual(client_ip(request("192.168.0.77", hdr), "CF-Connecting-IP", trusted), "192.168.0.77")


class LimiterTests(unittest.TestCase):
    def test_lookups_do_not_grow_memory(self):
        lim = LoginLimiter(max_failures=3, lockout_minutes=15)
        for i in range(100):
            lim.locked_for(f"u:{i}", f"ip:{i}")
        self.assertEqual(len(lim._fails), 0)
        lim.failure("u:a")
        lim.window = -1                                      # alles abgelaufen
        self.assertEqual(lim.locked_for("u:a"), 0)
        self.assertEqual(len(lim._fails), 0)


class InvalidDateTests(unittest.TestCase):
    def test_helpers_return_none(self):
        self.assertIsNone(parse_dotted_date("31.09.2026"))
        self.assertIsNone(parse_any_date("Do 31.09."))
        self.assertIsNone(parse_any_date("31. September 2026"))

    def test_leap_day_without_year(self):
        self.assertEqual(infer_year(29, 2, date(2026, 10, 17)), 2028)
        self.assertEqual(infer_year(29, 2, date(2028, 1, 10)), 2028)

    def test_one_bad_date_skips_only_that_event(self):
        html = ('<a href="/de/events/1-x-a/">31.09.2026 Kaputt</a>'
                '<a href="/de/events/2-x-b/">14.10.2026 Gut</a>')
        evs = src("petzi", organiser=1).parse(html)
        self.assertEqual([e.native_id for e in evs], ["2"])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(f"{self.tmp.name}/s.db")

    def tearDown(self):
        self.tmp.cleanup()

    def test_retry_survives_price_update(self):
        d = date.today() + timedelta(days=5)
        ev = Event(venue_id="v", native_id="1", title="Band", date=d)
        self.store.upsert([ev])
        self.store.update_extra(ev.uid, {"artists": [], "artists_retry": True})
        ev.extra = {"price": "CHF 20"}
        self.store.upsert([ev])                              # json_set speichert ohne Leerzeichen
        self.assertEqual([r["uid"] for r in self.store.events(without_artists=True)], [ev.uid])
        self.store.update_extra(ev.uid, {"artists": []})
        self.assertEqual(self.store.events(without_artists=True), [])

    def test_existing_db_does_not_flood_on_upgrade(self):
        path = f"{self.tmp.name}/old.db"
        s = Store(path)
        s.upsert([Event(venue_id="v", native_id="1", title="Alt", date=date.today() + timedelta(days=3))])
        s.db.execute("DELETE FROM meta WHERE key='notify_queue'"); s.db.commit()   # wie vor v1.18.1
        self.assertEqual(len(Store(path).unnotified_events()), 0)


class RestartTests(unittest.TestCase):
    """Neustart zwischen Speichern und Melden: das Event wird beim nächsten Lauf trotzdem gemeldet."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = date.today() + timedelta(days=10)
        self.url = "https://www.petzi.ch/de/organiser/1/"
        self.fetcher = FakeFetcher({self.url: f'<a href="/de/events/1-x-a/">{d:%d.%m.%Y} Band A</a>',
                                    "https://www.petzi.ch/de/events/1-x-a/": "",
                                    "https://www.petzi.ch/de/events/2-x-b/": ""})
        self.d = d
        cfg = Config(settings=Settings(database=f"{self.tmp.name}/t.db"),
                     venues=[VenueConfig(id="x", name="X", type="petzi", options={"organiser": 1})],
                     notifiers=[], artists=ArtistSettings(enabled=False))
        self.agent = Agent(cfg, fetcher=self.fetcher)
        self.sent = []
        outer = self

        class Rec:
            def send(self, new, cancelled):
                outer.sent.append([e.title for e in new])
        self.agent.notifiers = [Rec()]

    def tearDown(self):
        self.tmp.cleanup()

    def test_pending_event_sent_after_crash(self):
        self.agent.run()                                     # Erstimport
        self.fetcher.pages[self.url] += f'<a href="/de/events/2-x-b/">{self.d:%d.%m.%Y} Band B</a>'
        real = self.agent.pending_events
        self.agent.pending_events = lambda: (_ for _ in ()).throw(SystemExit)   # «Absturz» vor dem Melden
        with self.assertRaises(SystemExit):
            self.agent.run()
        self.agent.pending_events = real
        self.agent.run()                                     # nichts Neues auf der Seite – trotzdem gemeldet
        self.assertEqual(self.sent, [["Band B"]])
        self.agent.run()
        self.assertEqual(self.sent, [["Band B"]])            # nur einmal

    def test_no_notify_run_stays_silent(self):
        self.agent.run()
        self.fetcher.pages[self.url] += f'<a href="/de/events/2-x-b/">{self.d:%d.%m.%Y} Band B</a>'
        self.agent.run(notify=False)
        self.agent.run()
        self.assertEqual(self.sent, [])

    def test_bad_query_is_400(self):
        app = create_app(self.agent)
        self.agent.config.auth.enabled = False
        for q in ("from=foo", "to=2026-13-01", "new=x"):
            self.assertEqual(call(app, "GET", f"/api/events?{q}")["status"], 400, q)
        self.assertEqual(call(app, "GET", "/api/events?new=7")["status"], 200)


class RedactTests(unittest.TestCase):
    def test_token_removed(self):
        rec = logging.LogRecord("x", logging.WARNING, "", 0,
                                "Max retries exceeded with url: /bot123456:AAH-x_y9/getUpdates", None, None)
        out = RedactingFormatter("%(message)s").format(rec)
        self.assertNotIn("AAH-x_y9", out)
        self.assertIn("bot<TOKEN>/getUpdates", out)


if __name__ == "__main__":
    unittest.main()
