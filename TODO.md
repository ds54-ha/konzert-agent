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

## Weitere Locations & Scraper

- [x] 6. Neue Scraper: Dynamo (Zürich), X-tra (Zürich), Nordportal (Baden),
         Old Capitol (Langenthal), Z7 (Pratteln) (v1.4.0)
  - Old Capitol: PETZI 268307 · Z7: `css` · X-tra/Dynamo/Nordportal: eigene Scraper
  - X-tra erlaubt Bots inzwischen (robots.txt «Allow: /»)
  - [x] Dynamo: alle Events über die Drupal-JSON:API (dynamo.nodehive.app) statt nur ~6 Wochen; nur die
        nötigen Felder abgefragt (`fields[...]`), Veranstalter-Kontaktdaten werden nicht geladen (v1.14.0)
- [ ] 13. statt nur locations auch Bandseiten direkt, um Touranouncement abzufangen und die Daten einzupflegen
## Layout & Bedienung

- [x] 7. Optimierungen am UX (v1.10.0)
  - [x] Zusätzlicher Kalenderselector um individuelle Zeiträume (nicht nur Wochenende, 7, 30 Tage etc.) zu wählen
  - [x] Locations als zusammenklappbar per Stadt (Haken pro Stadt, ⚠ bei Fehlern)
    - [x] Einfügen von "colapse all" («alle aufklappen / zuklappen») (v1.14.0)
    - [x] Hinter jeder Location eine "nur" Button (auch pro Stadt) (v1.14.0)
  - [x] Persönliche Einstellungen am Ende der Sidebar (Teilen zusätzlich im Dashboard)
  - [x] Filter nach Event-Typ: Konzert / Party / Andere – aus Tags der Location, sonst eindeutigen Titelwörtern
        (`konzert_agent/kinds.py`); auch im iCal-Abo (`?kind=…`)
- [x] 8. Optimierungen am Layout (v1.10.0)
  - [x] Option zur Wahl der Akzentfarbe (6 Farben, je hell/dunkel abgestimmt)
  - [x] Option für Dark-/Lightmode (System / Hell / Dunkel) – pro Gerät gespeichert, auch für Gäste
  - [x] add a disclaimer and copyright notice at the bottom (`settings.copyright`) (v1.14.0)

## Userfunktionen

- [x] 9. Individuelle Telegram-Konfiguration pro Benutzer (Voraussetzung für 10) (v1.11.0)
  - [x] Selbst verbinden über eigenen Bot: Einmal-Link `t.me/<bot>?start=<code>`, Long-Polling (kein Webhook)
  - [x] Pro Benutzer: neue Konzerte Aus / Alle / Nur passende (gespeicherter Filter), Absagen markierter Konzerte
  - [x] Trennen im Web, mit /stop oder `user telegram-off`; blockierter Bot trennt automatisch
- [x] 10. Bands folgen → Telegram-Meldung bei neuer Show (v1.12.0)
  - [x] Folgen per ＋ beim Konzert oder per Name im Tab «Meine»; ★ in der Liste, «★ Gefolgte Bands» im Dashboard
  - [x] Treffer über erkannte Bands oder Name als ganze Wörter im Titel (auch Support-Bands)
  - [x] Telegram: «⭐ Neue Show …» immer (auch bei «Aus»), abschaltbar; nicht doppelt in der allgemeinen Liste

## Später

- [x] 11. Support-Bands in der Liste anzeigen, unterhalb des Hauptacts (v1.13.0)
  - Line-up aus dem Titel (Locations liefern Support nicht separat): Hauptact, darunter «mit …» mit Stil/Fans, ＋ folgen
- [x] 12. Archiv: vergangene Events anschauen (Events werden nicht gelöscht, die DB füllt sich ab 2026-10-14) (v1.13.0)
  - Tab «Archiv» (neueste zuerst, Filter ohne Zeitraum, auch für Gäste); Monatsansicht blättert zurück
  - [ ] auch einen "Von-Bis"Filter im Archiv

Reihenfolge (2026-10-14): zuerst 6 (erledigt), dann 4 (erledigt).
Reihenfolge (2026-10-15): 7 + 8 zusammen, dann 9 → 10, danach 11 und 12.
