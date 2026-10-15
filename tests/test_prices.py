import json
import unittest
from datetime import date, timedelta

from konzert_agent.config import VenueConfig
from konzert_agent.models import Event
from konzert_agent.prices import format_price
from konzert_agent.web.app import create_app
from tests.test_auth import MemberBase, call

D = date.today() + timedelta(days=10)


class FormatTests(unittest.TestCase):
    def test_formats_from_the_sources(self):
        cases = {
            "Ab CHF 20,00": "ab CHF 20",                 # PETZI
            "Ab CHF 11,50": "ab CHF 11.50",
            "CHF VVK 25.- / AK 30.-": "CHF 25–30",       # Dynamo
            "CHF 46.60.-": "CHF 46.60",
            "CHF 42.- plus Servicegebühren": "CHF 42",
            "28 CHF": "CHF 28",                          # Albani
            "Ab 25 CHF": "ab CHF 25",
            "ab CHF 0": "gratis",                        # Kaufleuten: Gratiseintritt
            "CHF Free Entry <3": "gratis",
            "CHF Stehplatz 38.- (regulär)\r\nStehplatz 19.- (Kulturlegi)": "CHF 19–38",
            "Verlosung": "Verlosung",
            "": "",
            None: "",
        }
        for raw, want in cases.items():
            self.assertEqual(format_price(raw), want, raw)


class StoreAndWebTests(MemberBase):
    def test_price_added_later_is_stored_and_shown(self):
        self.agent.config.venues = [VenueConfig("kiff", "Kiff", "petzi", city="Aarau")]
        self.app = create_app(self.agent)
        self.store.upsert([Event("kiff", "9", "Monolord", D)])                       # noch kein Vorverkauf
        self.store.upsert([Event("kiff", "9", "Monolord", D, extra={"price": "Ab CHF 35,00"})])
        self.store.update_extra("kiff:9", {**self.store.events(venues=["kiff"])[-1]["extra"], "genres": ["Metal"]})
        self.store.upsert([Event("kiff", "9", "Monolord", D)])                       # ohne Preis: bleibt stehen
        e = next(e for e in json.loads(call(self.app, "GET", "/api/events")["text"]) if e["uid"] == "kiff:9")
        self.assertEqual((e["price"], e["extra"]["price"], e["extra"]["genres"]), ("ab CHF 35", "Ab CHF 35,00", ["Metal"]))
        self.store.set_mark(self.anna, "kiff:9", "going", "own")
        ical = call(self.app, "GET", f"/ical/{self.store.user_by_id(self.anna)['ical_token']}.ics")["text"]
        self.assertIn("Preis: ab CHF 35", ical.replace("\r\n ", ""))


if __name__ == "__main__":
    unittest.main()
