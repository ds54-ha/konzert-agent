import json
from datetime import date, timedelta

from konzert_agent.config import VenueConfig
from konzert_agent.models import Event
from konzert_agent.web.app import create_app
from tests.test_auth import MemberBase, call


class ArchiveTests(MemberBase):
    def test_past_events_newest_first(self):
        self.agent.config.venues = [VenueConfig("kiff", "Kiff", "petzi", city="Aarau")]
        self.app = create_app(self.agent)
        t = date.today()
        self.store.upsert([Event("kiff", "p1", "Vor einer Woche", t - timedelta(days=7)),
                           Event("kiff", "p2", "Gestern", t - timedelta(days=1)),
                           Event("kiff", "p3", "Festival läuft noch", t - timedelta(days=2), end_date=t + timedelta(days=1)),
                           Event("kiff", "p4", "Heute", t)])
        r = call(self.app, "GET", "/api/events?past=1")                     # auch für Gäste
        self.assertEqual(r["status"], 200)
        self.assertEqual([e["title"] for e in json.loads(r["text"])], ["Gestern", "Vor einer Woche"])
        upcoming = [e["title"] for e in json.loads(call(self.app, "GET", "/api/events")["text"])]
        self.assertIn("Festival läuft noch", upcoming)
        self.assertNotIn("Gestern", upcoming)
        q = json.loads(call(self.app, "GET", "/api/events?past=1&q=woche")["text"])   # Filter wirken
        self.assertEqual([e["title"] for e in q], ["Vor einer Woche"])
