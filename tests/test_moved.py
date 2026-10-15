import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

from konzert_agent.config import VenueConfig
from konzert_agent.models import Event
from konzert_agent.notifiers import TelegramNotifier
from konzert_agent.sources.base import first_sentence, split_status
from konzert_agent.store import Store
from konzert_agent.web.app import create_app
from tests.test_auth import MemberBase, call

D = date.today() + timedelta(days=10)


class SplitStatusTests(unittest.TestCase):
    def test_words_at_the_end(self):
        st = split_status("Masego - VERSCHOBEN!")
        self.assertEqual((st.title, st.moved, st.cancelled, st.moved_note), ("Masego", True, False, ""))
        self.assertEqual(split_status("Simple Plan - SOLD OUT!").flags(),
                         {"sold_out": True, "cancelled": False, "moved": False, "moved_note": ""})
        self.assertTrue(split_status("Gabirano (CH) / ABGESAGT").cancelled)

    def test_new_date_is_not_moved(self):           # das angezeigte Datum IST das neue
        st = split_status("Azet - Neues Datum")
        self.assertEqual((st.title, st.moved), ("Azet", False))

    def test_target_becomes_note(self):
        st = split_status("Betontod – verlegt ins Dynamo")
        self.assertEqual((st.title, st.moved, st.moved_note), ("Betontod", True, "verlegt ins Dynamo"))
        st = split_status("RAPK (verschoben auf 13.04.2027)")
        self.assertEqual((st.title, st.moved_note), ("RAPK", "verschoben auf 13.04.2027"))

    def test_cancelled_beats_moved(self):
        f = split_status("Band - VERSCHOBEN").flags(cancelled=True)
        self.assertEqual((f["cancelled"], f["moved"], f["moved_note"]), (True, False, ""))


class FirstSentenceTests(unittest.TestCase):
    def test_dates_do_not_split(self):
        self.assertEqual(first_sentence("Die Show von Saint Levant am 24.11. wird in die Halle 622 hochverlegt. "
                                        "Bereits gekaufte Tickets behalten ihre Gültigkeit."),
                         "Die Show von Saint Levant am 24.11. wird in die Halle 622 hochverlegt")
        self.assertEqual(first_sentence("Neu am Dienstag, 13.04.2027 im Dynamo Saal"), "Neu am Dienstag, 13.04.2027 im Dynamo Saal")


class StoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = f"{tmp.name}/t.db"

    def test_old_database_gets_columns(self):
        db = sqlite3.connect(self.path)
        db.execute("CREATE TABLE events (uid TEXT PRIMARY KEY, venue_id TEXT NOT NULL, native_id TEXT NOT NULL,"
                   " title TEXT NOT NULL, date TEXT NOT NULL, end_date TEXT, time TEXT, url TEXT, tags TEXT DEFAULT '[]',"
                   " sold_out INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0, extra TEXT DEFAULT '{}',"
                   " first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, notified INTEGER DEFAULT 0)")
        db.execute("INSERT INTO events (uid, venue_id, native_id, title, date, first_seen, last_seen)"
                   " VALUES ('v:1','v','1','Alt',?, 'x', 'x')", (D.isoformat(),))
        db.commit()
        db.close()
        store = Store(self.path)
        e = store.events()[0]
        self.assertEqual((e["title"], e["moved"], e["moved_note"]), ("Alt", False, ""))

    def test_moved_is_reported_once_and_not_after_cancel(self):
        store = Store(self.path)
        store.upsert([Event("v", "1", "A", D), Event("v", "2", "B", D, cancelled=True)])
        _, changed = store.upsert([Event("v", "1", "A", D, moved=True, moved_note="ins Dynamo"),
                                   Event("v", "2", "B", D, moved=True)])      # B war schon abgesagt gemeldet
        self.assertEqual([e.uid for e in changed], ["v:1"])
        _, changed = store.upsert([Event("v", "1", "A", D, moved=True, moved_note="ins Dynamo")])
        self.assertEqual(changed, [])
        e = {x["uid"]: x for x in store.events()}
        self.assertEqual((e["v:1"]["moved"], e["v:1"]["moved_note"], e["v:2"]["cancelled"]), (True, "ins Dynamo", False))


class NotifyTests(unittest.TestCase):
    def test_separate_section_with_note(self):
        n = TelegramNotifier(token="t", chat_id="c", venue_names={"v": "Komplex 457"})
        text = n.build_messages([], [Event("v", "1", "Betontod", D, moved=True, moved_note="neu im Dynamo"),
                                     Event("v", "2", "Murda", D, cancelled=True)])[0]
        self.assertIn("❌ <b>Abgesagt</b>", text)
        self.assertIn("↪️ <b>Verschoben</b>", text)
        self.assertIn("Komplex 457: Betontod → neu im Dynamo", text)
        self.assertLess(text.index("Murda"), text.index("Verschoben"))


class WebTests(MemberBase):
    def test_list_and_ical(self):
        self.agent.config.venues = [VenueConfig("kiff", "Kiff", "petzi", city="Aarau")]
        self.app = create_app(self.agent)
        self.store.upsert([Event("kiff", "9", "Betontod", D, moved=True, moved_note="neu im Dynamo")])
        e = next(e for e in json.loads(call(self.app, "GET", "/api/events")["text"]) if e["uid"] == "kiff:9")
        self.assertEqual((e["moved"], e["moved_note"], e["cancelled"]), (True, "neu im Dynamo", False))
        tok = self.store.user_by_id(self.anna)["ical_token"]
        self.store.set_mark(self.anna, "kiff:9", "going", "own")
        ical = call(self.app, "GET", f"/ical/{tok}.ics")["text"].replace("\r\n ", "")
        self.assertIn("SUMMARY:✓ Betontod (VERSCHOBEN)", ical)
        self.assertIn("STATUS:TENTATIVE", ical)
        self.assertNotIn("CANCELLED", ical)
        self.assertIn("Verschoben: neu im Dynamo", ical)


if __name__ == "__main__":
    unittest.main()
