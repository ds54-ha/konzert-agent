import unittest
from datetime import date, timedelta

from konzert_agent.config import VenueConfig
from konzert_agent.follows import follow_key, matching
from konzert_agent.models import Event

from konzert_agent.web.app import create_app
from tests.test_auth import MemberBase


class MatchingTests(unittest.TestCase):
    def test_key(self):
        self.assertEqual(follow_key("The Beauty of Gemina"), follow_key("beauty of gemina"))
        self.assertEqual(follow_key("Sigur Rós"), "sigurros")
        self.assertEqual(follow_key("AC/DC"), follow_key("ac dc"))

    def test_title_and_artists(self):
        f = {follow_key(n): n for n in ("Monolord", "Elin", "Slope", "AC/DC")}
        self.assertEqual(matching("Monolord (SE)", {}, f), ["Monolord"])
        self.assertEqual(matching("Headliner + Support: Slope", {}, f), ["Slope"])       # Support-Band im Titel
        self.assertEqual(matching("Berlin Calling Party", {}, f), [])                      # nicht «Elin» in «Berlin»
        self.assertEqual(matching("Tour 2026", {"artists": [{"name": "Monolord", "query": "MONOLORD"}]}, f),
                         ["Monolord"])
        self.assertEqual(matching("AC/DC Tribute Night", {}, f), ["AC/DC"])
        sports = {follow_key("Sports"): "Sports"}
        self.assertEqual(matching("PA Sports", {"artists": [{"name": "PA Sports", "query": "PA Sports"}]}, sports), [])
        self.assertEqual(matching("Sports", {"artists": [{"name": "Sports", "query": "Sports"}]}, sports), ["Sports"])
        self.assertEqual(matching("Monolord + Sports", {"artists": [{"name": "Monolord", "query": "Monolord"}]}, sports),
                         ["Sports"])


class FollowApiTests(MemberBase):
    def test_follow_unfollow(self):
        self.agent.config.venues = [VenueConfig("kiff", "Kiff", "petzi", city="Aarau")]
        self.app = create_app(self.agent)
        self.store.upsert([Event("kiff", "3", "Monolord (SE) + Slope", date.today() + timedelta(days=7))])
        self.assertEqual(self.req("GET", "/api/follows")["status"], 401)              # Gäste nicht
        r = self.req("POST", "/api/follows", self.c_anna, {"name": "  Slope "})
        self.assertEqual(r["json"]["follows"], [{"key": "slope", "name": "Slope"}])
        self.assertEqual([(e["title"], e["follows"]) for e in r["json"]["events"]], [("Monolord (SE) + Slope", ["Slope"])])
        self.assertEqual(self.req("GET", "/api/follows", self.c_ben)["json"]["follows"], [])   # pro Benutzer
        self.req("POST", "/api/follows", self.c_anna, {"name": "SLOPE"})                       # doppelt: bleibt einmal
        self.assertEqual(len(self.req("GET", "/api/follows", self.c_anna)["json"]["follows"]), 1)
        self.assertEqual(self.req("POST", "/api/follows", self.c_anna, {"name": "!"})["status"], 400)
        r = self.req("DELETE", "/api/follows/slope", self.c_anna)
        self.assertEqual(r["json"], {"follows": [], "events": []})
        self.store.follow(self.anna, "x1", "X1")
        self.store.delete_user(self.anna)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM follows").fetchone()[0], 0)
