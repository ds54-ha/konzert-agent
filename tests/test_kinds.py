import unittest

from konzert_agent.kinds import event_kind


class KindTests(unittest.TestCase):
    def test_tags_first(self):
        self.assertEqual(event_kind("ETO - Sibcity Tour", ["Club", "Konzert", "Party"]), "Konzert")
        self.assertEqual(event_kind("Noche Cubana", ["Party"]), "Party")
        self.assertEqual(event_kind("PUB QUIZ - World-Special", ["Performance"]), "Andere")
        self.assertEqual(event_kind("Party Cannon", ["Konzert", "Metal"]), "Konzert")      # Bandname mit «Party»

    def test_title_fallback(self):
        self.assertEqual(event_kind("Die ultimative 2000er Party", []), "Party")
        self.assertEqual(event_kind("More Than Mode mit den DJs DZ & Kayce", []), "Party")
        self.assertEqual(event_kind("Comedy im KIFF: Lisa Christ", []), "Andere")
        self.assertEqual(event_kind("Goth Night – Volume 2", ["Konzert", "Alternative"]), "Konzert")
        self.assertEqual(event_kind("SLOPE (DE) – «SAME KIDS. JUST LOUDER.»", []), "Konzert")  # im Zweifel Konzert


if __name__ == "__main__":
    unittest.main()
