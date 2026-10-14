# TODO

## Band-Infos & Login (Plan vom 2026-10-14)

- [x] 0. Versionsnummer in der Web-Oberfläche (v1.1.0)
- [x] 1. Bandnamen aus Event-Titeln erkennen + Testbefehl `artists <location>` (MusicBrainz + Deezer, speichert nichts)
- [x] 2. Artist-Infos speichern: Cache-Tabelle, Refresh alle ~30 Tage, Genres → grobe Genre-Gruppen,
         Fans → Popularität 0–100 (Headliner); Genres wirken in include/exclude (v1.2.0)
  - [ ] Last.fm als zusätzliche Genre-Quelle (API-Key folgt später)
  - [x] Ohne MusicBrainz-Genres auf die Tags der Location (PETZI/Schüür) zurückfallen
  - [x] Manuelle Korrektur falscher Zuordnungen (`artists.overrides` / `artists.titles` in config.yaml)
- [x] 3. Oberfläche: Genre-Filter, Popularitäts-Badge, Sortierung nach Popularität;
         Genre/Popularität auch im iCal-Abo (`?genre=…&pop=…`) (v1.3.0)
- [x] 4. Login (auch von ausserhalb des Heimnetzes) – Gäste sehen den Kalender nur lesend, alle
         Benutzer-Funktionen hinter Login; persönliche iCal-Links funktionieren ohne (geheimer Token)
  - [x] 4a. Login: Benutzer per Befehl anlegen, Login-Seite, Logout, Sperre nach Fehlversuchen,
            `/api/run` nur mit Login; iCal-Abo über persönlichen Token-Link (v1.5.0)
  - [x] Gäste dürfen den Kalender ansehen (nur lesen), «Anmelden»-Knopf schaltet Funktionen frei;
        `auth.guests: false` = alles hinter Login (v1.6.0)
  - [x] 4b. Konzerte markieren pro Benutzer: «Interessiert» / «Gehe hin» (v1.7.0)
    - [x] Ticket-Status: «Ja, selbst gekauft» / «Ja, jemand anderes hat sie» / «Noch nicht»
    - [x] Teilen per Opt-in, gegenseitig (nur wer teilt, sieht andere); andere sehen Name + Status,
          nicht den Ticket-Status. Filter «Meine Konzerte»: Markiert / Gehe hin / Ohne Ticket / Andere gehen
  - [x] 4c. Dashboard «Meine» (Tab, Klick auf den Namen oder /#meine): Ticket fehlt noch, Gehe hin,
            Interessiert, Vergangen – unabhängig von den Filtern (v1.8.0)
  - [x] 4d. Persönlicher iCal-Link mit den markierten Konzerten (☆/✓ im Titel, TENTATIVE/CONFIRMED,
            Ticket + wer sonst hingeht in der Beschreibung), `?status=going`, `?all=1` = alle mit Filtern;
            Link im Tab «Meine» erneuerbar (v1.9.0)
  - Zugang von aussen: eigene Domain über Cloudflare → nginx-Reverse-Proxy (noch nicht aktiviert)
  - Gegenseitig sehen, wer hingeht: pro Benutzer ein-/ausschaltbar (Opt-in)

## Userfunktionen
- [ ] 8. Optional: Bands folgen → Telegram-Meldung bei neuer Show
- [ ] 12. individulle Telegramconfiguration

## Weitere Locations

- [x] 6. Neue Scraper: Dynamo (Zürich), X-tra (Zürich), Nordportal (Baden),
         Old Capitol (Langenthal), Z7 (Pratteln) (v1.4.0)
  - Old Capitol: PETZI 268307 · Z7: `css` · X-tra/Dynamo/Nordportal: eigene Scraper
  - X-tra erlaubt Bots inzwischen (robots.txt «Allow: /»)
  - [ ] Dynamo zeigt nur ~6 Wochen; die Drupal-JSON:API (dynamo.nodehive.app) hätte alles, enthält aber
        private Kontaktdaten der Veranstalter → bewusst nicht verwendet
## Layout

- [ ] 7. Optimierungen am UX
  - [ ] Zusätzlicher Kalenderselector um individuelle Zeiträume (nicht nur wochenende, 7, 30 Tage etc) zu wählen
  - [ ] Locations als zusammenklappbar per Stadt
  - [ ] persönliche Einstellungen am Ende der Sidebar oder auf dem Userdashboard
- [ ] 9. Optimierungen am Layout
  - [ ] Option zur Wahl der Akzentfarbe
  - [ ] Option für Dark-/Lightmode

Reihenfolge (2026-10-14): zuerst 6 (erledigt), dann 4.
